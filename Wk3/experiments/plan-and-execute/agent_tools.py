#!/usr/bin/env python3
"""自主规划实验的共享工具层 —— Plan-and-Execute 与 ReAct 用的是同一套工具。

两种模式要对比的是**谁来决定下一步**，不是**能用什么工具**。所以工具集必须
完全相同，否则测出来的差异分不清是规划策略造成的还是能力差造成的。

工具设计的三条约束：

* **确定性优先**。``load_trending`` / ``filter_repos`` / ``rank_repos`` 完全不调 LLM，
  同样的参数必然给同样的结果。只有 ``analyze_repos`` 和 ``draft_article`` 调 LLM，
  因为那两件事本来就没有确定性答案。这样两种模式拿到的**事实**是同一份，
  差异只可能来自「选了哪些事实、按什么顺序用」。
* **每个工具都会失败**。参数错、仓库名不存在、超出条数上限都返回结构化的错误
  而不是抛异常——自主规划的价值有一半体现在「工具报错之后怎么办」，
  抛异常会让循环直接死掉，看不到这一半。
* **调用可计量**。每次调用记一条 :class:`ToolCall`，供报告统计「几步、花了多少」。

用法::

    from agent_tools import TOOLS, ToolRegistry
    registry = ToolRegistry()
    print(registry.call("load_trending", {"limit": 10}))
    print(registry.describe())
"""

from __future__ import annotations

import json
import logging
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
LANGGRAPH_DIR = REPO_ROOT / "Wk3" / "experiments" / "langgraph-pipeline"
V2_PIPELINE = REPO_ROOT / "Wk2" / "experiments" / "v2-pipeline"

for path in (str(V2_PIPELINE), str(LANGGRAPH_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)

from dotenv import load_dotenv

# .env 优先级与 langgraph_experiment.py 保持一致（密钥实际住在 v2-pipeline）
for candidate in (HERE / ".env", HERE.parents[1] / ".env", REPO_ROOT / ".env", V2_PIPELINE / ".env"):
    if candidate.exists():
        load_dotenv(candidate, override=False)

import pipeline.model_client as mc  # noqa: E402
from pipeline.model_client import LLMError, quick_chat  # noqa: E402

from quality import score_quality  # noqa: E402

logger = logging.getLogger("agent-tools")

#: model_client 的模块级全局 tracker —— 全实验共用这一个，不新建
tracker = mc.tracker

#: 采集数据目录，复用仓库里已有的 GitHub Trending 快照
RAW_DIR = REPO_ROOT / "knowledge" / "raw"

#: 实验产出目录
RESULTS_DIR = HERE / "results"

#: 单次运行允许的最大工具调用数（防止 ReAct 转不出来）
MAX_TOOL_CALLS = 40

#: analyze_repos 一次最多分析几个仓库
MAX_ANALYZE_BATCH = 8


# ---------------------------------------------------------------------------
# 计量
# ---------------------------------------------------------------------------


@dataclass
class ToolCall:
    """一次工具调用的记录。

    Attributes:
        index: 第几次调用（从 1 开始）。
        name: 工具名。
        args: 调用参数。
        ok: 是否成功。
        summary: 结果摘要（不存全文，避免记录膨胀）。
        tokens: 该次调用产生的 token 增量（不调 LLM 的工具为 0）。
        elapsed: 耗时秒。
    """

    index: int
    name: str
    args: dict[str, Any]
    ok: bool
    summary: str
    tokens: int
    elapsed: float

    def as_dict(self) -> dict[str, Any]:
        """转成可 JSON 序列化的 dict。"""
        return {
            "index": self.index,
            "name": self.name,
            "args": self.args,
            "ok": self.ok,
            "summary": self.summary[:300],
            "tokens": self.tokens,
            "elapsed": round(self.elapsed, 2),
        }


class TokenMeter:
    """对全局 tracker 做快照差值，得到「本次运行」而非「进程累计」的开销。

    与 ``langgraph_experiment.TokenMeter`` 同形；这里重新实现是因为那个模块
    绑了 LangGraph，本实验不引入图依赖。
    """

    def __init__(self) -> None:
        """记录当前快照。"""
        self.reset()

    def reset(self) -> None:
        """把基准线挪到当前值。"""
        self._tokens0 = tracker.total_tokens
        self._calls0 = tracker.total_calls
        self._cny0 = tracker.estimated_cost()
        self._usd0 = tracker.estimated_cost_usd()

    @property
    def tokens(self) -> int:
        """自基准线以来消耗的 token。"""
        return tracker.total_tokens - self._tokens0

    @property
    def calls(self) -> int:
        """自基准线以来的 LLM 调用次数。"""
        return tracker.total_calls - self._calls0

    @property
    def cny(self) -> float:
        """自基准线以来的成本（元）。"""
        return tracker.estimated_cost() - self._cny0

    @property
    def usd(self) -> float:
        """自基准线以来的成本（美元）。"""
        return tracker.estimated_cost_usd() - self._usd0

    def as_dict(self) -> dict[str, Any]:
        """导出为结果 JSON 用的 dict。"""
        return {
            "tokens": self.tokens,
            "llm_calls": self.calls,
            "cost_cny": round(self.cny, 6),
            "cost_usd": round(self.usd, 6),
        }


class ToolError(Exception):
    """工具执行失败。注册表会把它转成结构化错误结果，不向外抛。"""


# ---------------------------------------------------------------------------
# 工具实现
# ---------------------------------------------------------------------------


def _latest_trending_file() -> Path:
    """找 ``knowledge/raw/`` 下最新的 GitHub Trending 快照。

    Returns:
        文件路径。

    Raises:
        ToolError: 目录不存在或没有快照文件。
    """
    if not RAW_DIR.exists():
        raise ToolError(f"采集目录不存在: {RAW_DIR}")
    files = sorted(RAW_DIR.glob("github-trending-*.json"))
    if not files:
        raise ToolError(f"{RAW_DIR} 下没有 github-trending-*.json")
    return files[-1]


def load_trending(limit: int = 15) -> dict[str, Any]:
    """载入最新的 GitHub Trending 采集快照。

    两种模式的**唯一数据入口**。用磁盘上已有的快照而不是现抓，是为了让
    Plan-and-Execute 与 ReAct 面对完全相同的事实——现抓的话两次运行拿到的
    star 数会漂移，最终产出的差异就无法归因到规划策略上。

    Args:
        limit: 最多返回几条，按 star 降序。

    Returns:
        含 ``source`` / ``collected_at`` / ``count`` / ``items`` 的 dict。

    Raises:
        ToolError: 快照缺失或格式非法。
    """
    path = _latest_trending_file()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ToolError(f"读取 {path.name} 失败: {exc}") from exc

    items = data.get("items")
    if not isinstance(items, list):
        raise ToolError(f"{path.name} 缺少 items 数组")

    limit = max(1, min(int(limit), len(items)))
    picked = sorted(items, key=lambda x: x.get("stars", 0), reverse=True)[:limit]

    return {
        "source": data.get("source", "github-trending"),
        "collected_at": data.get("collected_at", ""),
        "file": path.name,
        "total_available": len(items),
        "count": len(picked),
        "items": picked,
    }


def filter_repos(keyword: str, limit: int = 20) -> dict[str, Any]:
    """按关键词过滤快照里的仓库（匹配 name / summary / topics / language）。

    Args:
        keyword: 关键词，大小写不敏感。空串会被拒绝——这是最常见的调用错误，
            返回错误比返回全集更有信息量。
        limit: 最多返回几条。

    Returns:
        含 ``keyword`` / ``count`` / ``items`` 的 dict。

    Raises:
        ToolError: 关键词为空。
    """
    keyword = (keyword or "").strip()
    if not keyword:
        raise ToolError("keyword 不能为空；如果想要全部条目请用 load_trending")

    needle = keyword.lower()
    all_items = load_trending(limit=999)["items"]

    matched = [
        item
        for item in all_items
        if needle in str(item.get("name", "")).lower()
        or needle in str(item.get("summary", "")).lower()
        or needle in str(item.get("language", "")).lower()
        or any(needle in str(t).lower() for t in item.get("topics", []))
    ]

    return {
        "keyword": keyword,
        "searched": len(all_items),
        "count": len(matched),
        "items": matched[: max(1, int(limit))],
    }


def rank_repos(names: list[str] | None = None, by: str = "stars",
               limit: int = 10) -> dict[str, Any]:
    """按指定字段给仓库排序。

    Args:
        names: 只对这些仓库排序；为空则对全部快照条目排序。
        by: 排序字段，支持 ``stars`` 与 ``name``。
        limit: 最多返回几条。

    Returns:
        含 ``by`` / ``count`` / ``items``（只保留 name/stars/language）的 dict。

    Raises:
        ToolError: 排序字段不支持，或指定的仓库名全部找不到。
    """
    if by not in ("stars", "name"):
        raise ToolError(f"不支持的排序字段: {by!r}，可选 stars / name")

    pool = load_trending(limit=999)["items"]
    if names:
        wanted = {str(n).strip().lower() for n in names}
        pool = [i for i in pool if str(i.get("name", "")).lower() in wanted]
        if not pool:
            raise ToolError(f"给的 {len(names)} 个仓库名一个都没匹配上，请先用 load_trending 看真实名字")

    reverse = by == "stars"
    ordered = sorted(pool, key=lambda x: x.get(by, 0 if by == "stars" else ""), reverse=reverse)[
        : max(1, int(limit))
    ]

    return {
        "by": by,
        "count": len(ordered),
        "items": [
            {"name": i.get("name"), "stars": i.get("stars"), "language": i.get("language")}
            for i in ordered
        ],
    }


def analyze_repos(names: list[str], question: str = "") -> dict[str, Any]:
    """用 LLM 分析指定的几个仓库，回答一个具体问题。

    这是两个调 LLM 的工具之一。刻意要求显式传 ``names``——不接受「分析全部」，
    逼规划方自己先做筛选决策，那个决策正是本实验要观察的东西。

    Args:
        names: 要分析的仓库全名列表，1 到 ``MAX_ANALYZE_BATCH`` 个。
        question: 要回答的具体问题；留空则做通用趋势分析。

    Returns:
        含 ``analyzed`` / ``question`` / ``analysis`` 的 dict。

    Raises:
        ToolError: 名单为空、超出批量上限、仓库名匹配不上，或 LLM 调用失败。
    """
    if not names:
        raise ToolError("names 不能为空，请先用 load_trending / filter_repos 选出要分析的仓库")
    if len(names) > MAX_ANALYZE_BATCH:
        raise ToolError(f"一次最多分析 {MAX_ANALYZE_BATCH} 个仓库，收到 {len(names)} 个；请分批")

    pool = {str(i.get("name", "")).lower(): i for i in load_trending(limit=999)["items"]}
    picked = [pool[str(n).strip().lower()] for n in names if str(n).strip().lower() in pool]
    missing = [n for n in names if str(n).strip().lower() not in pool]
    if not picked:
        raise ToolError(f"这些仓库名都不在快照里: {names}；请先用 load_trending 看真实名字")

    listing = "\n\n".join(
        f"- {i['name']}（{i.get('stars', 0)} stars, {i.get('language', '?')}, "
        f"topics={i.get('topics', [])}）\n  {i.get('summary', '')}"
        for i in picked
    )
    ask = question.strip() or "这几个项目共同反映了什么技术趋势？"

    prompt = f"""以下是 GitHub Trending 上的几个项目：

{listing}

请回答：{ask}

要求：
- 只基于上面给出的事实作答，不要引入列表之外的项目
- 结论要具体，出现数字、对比或举例
- 不超过 300 字
- 严禁空洞用语：赋能、抓手、闭环、打通、对齐、颗粒度、生态、顶层设计、全面提升"""

    try:
        text = quick_chat(prompt, system="你是技术趋势分析师，只讲有证据支撑的判断。")
    except LLMError as exc:
        raise ToolError(f"LLM 调用失败: {exc}") from exc

    return {
        "analyzed": [i["name"] for i in picked],
        "not_found": missing,
        "question": ask,
        "analysis": text,
    }


def draft_article(title: str, points: list[str], evidence: str = "") -> dict[str, Any]:
    """根据要点写一篇短文，并当场用 :func:`quality.score_quality` 打分。

    返回值里带质量分是刻意的：让规划方**看得见**自己产出的分数，
    从而有机会自主决定要不要再改一轮。Plan-and-Execute 与 ReAct 会不会
    利用这个信号，本身就是实验要观察的行为差异。

    Args:
        title: 文章标题。
        points: 要展开的要点，至少 2 条。
        evidence: 可选的事实素材（通常是 ``analyze_repos`` 的产出）。

    Returns:
        含 ``title`` / ``body`` / ``quality_score`` / ``quality_explain`` 的 dict。

    Raises:
        ToolError: 标题为空、要点不足 2 条，或 LLM 调用失败。
    """
    title = (title or "").strip()
    if not title:
        raise ToolError("title 不能为空")
    points = [str(p).strip() for p in (points or []) if str(p).strip()]
    if len(points) < 2:
        raise ToolError(f"points 至少 2 条，收到 {len(points)} 条")

    bullets = "\n".join(f"- {p}" for p in points)
    prompt = f"""写一篇 300-500 字的技术短文。

标题：{title}

必须展开的要点：
{bullets}

{('可引用的事实素材：' + chr(10) + evidence) if evidence.strip() else ''}

要求：
- 面向 AI 开发者，有观点、有具体事实
- 至少出现两处具体数字或对比
- 严禁空洞用语：赋能、抓手、闭环、打通、对齐、颗粒度、生态、顶层设计、全面提升
- 只写正文，不要重复标题"""

    try:
        body = quick_chat(prompt, system="你是技术专栏写手，输出 Markdown 正文。")
    except LLMError as exc:
        raise ToolError(f"LLM 调用失败: {exc}") from exc

    breakdown = score_quality(body, points)

    return {
        "title": title,
        "body": body,
        "chars": len(body),
        "quality_score": breakdown.score,
        "quality_explain": breakdown.explain(),
    }


def save_result(slug: str, content: str) -> dict[str, Any]:
    """把最终产出写进 ``results/``。

    Args:
        slug: 文件名片段（不含扩展名），非法字符会被替换成 ``-``。
        content: Markdown 正文。

    Returns:
        含 ``path`` / ``chars`` 的 dict。

    Raises:
        ToolError: slug 为空或内容为空。
    """
    slug = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in (slug or "").strip())
    if not slug:
        raise ToolError("slug 不能为空")
    if not (content or "").strip():
        raise ToolError("content 不能为空")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / f"{slug}.md"
    path.write_text(content, encoding="utf-8")
    return {"path": str(path.relative_to(REPO_ROOT)), "chars": len(content)}


# ---------------------------------------------------------------------------
# 工具注册表
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolSpec:
    """一个工具的元信息，用于生成给模型看的工具清单。

    Attributes:
        name: 工具名。
        func: 实现函数。
        signature: 参数签名，写进 prompt。
        description: 一句话说明工具做什么、什么时候用。
    """

    name: str
    func: Callable[..., dict[str, Any]]
    signature: str
    description: str


#: 全部可用工具。两种规划模式看到的是**同一份**清单。
TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec(
        "load_trending",
        load_trending,
        '{"limit": int}',
        "载入最新 GitHub Trending 快照，按 star 降序返回 limit 条。所有事实的唯一来源。",
    ),
    ToolSpec(
        "filter_repos",
        filter_repos,
        '{"keyword": str, "limit": int}',
        "按关键词过滤仓库（匹配名称/摘要/语言/topics）。keyword 不能为空。",
    ),
    ToolSpec(
        "rank_repos",
        rank_repos,
        '{"names": list[str], "by": "stars"|"name", "limit": int}',
        "给仓库排序。names 为空表示对全部快照排序。",
    ),
    ToolSpec(
        "analyze_repos",
        analyze_repos,
        '{"names": list[str], "question": str}',
        f"用 LLM 分析指定的 1-{MAX_ANALYZE_BATCH} 个仓库并回答一个具体问题。names 必须是真实仓库全名。",
    ),
    ToolSpec(
        "draft_article",
        draft_article,
        '{"title": str, "points": list[str], "evidence": str}',
        "根据要点写 300-500 字短文，返回正文与质量分（0-100，门槛 60）。points 至少 2 条。",
    ),
    ToolSpec(
        "save_result",
        save_result,
        '{"slug": str, "content": str}',
        "把最终 Markdown 产出写进 results/。这通常是最后一步。",
    ),
)

#: 名称 → ToolSpec
TOOL_INDEX: dict[str, ToolSpec] = {spec.name: spec for spec in TOOLS}


@dataclass
class ToolResult:
    """一次工具调用的返回，统一成 ok/data/error 三段。

    Attributes:
        ok: 是否成功。
        data: 成功时的结果 dict。
        error: 失败时的错误信息。
        tokens: 本次调用的 token 增量。
    """

    ok: bool
    data: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    tokens: int = 0

    def to_observation(self, limit: int = 1800) -> str:
        """渲染成塞进 prompt 的 Observation 文本。

        Args:
            limit: 截断长度，防止长结果把上下文撑爆。

        Returns:
            观察文本。
        """
        if not self.ok:
            return f"ERROR: {self.error}"
        text = json.dumps(self.data, ensure_ascii=False)
        return text if len(text) <= limit else text[:limit] + f"…（已截断，原长 {len(text)}）"


class ToolRegistry:
    """工具调度器 —— 负责参数校验、异常转错误、调用计量。

    典型用法::

        registry = ToolRegistry()
        result = registry.call("load_trending", {"limit": 10})
        print(registry.total_calls, registry.total_tokens)
    """

    def __init__(self, max_calls: int = MAX_TOOL_CALLS) -> None:
        """初始化。

        Args:
            max_calls: 单次运行允许的最大调用数。
        """
        self.max_calls = max_calls
        self.calls: list[ToolCall] = []

    @property
    def total_calls(self) -> int:
        """已发生的工具调用次数。"""
        return len(self.calls)

    @property
    def total_tokens(self) -> int:
        """工具内部 LLM 调用消耗的 token 总数。"""
        return sum(c.tokens for c in self.calls)

    @property
    def failed_calls(self) -> int:
        """失败的调用次数。"""
        return sum(1 for c in self.calls if not c.ok)

    def describe(self) -> str:
        """生成给模型看的工具清单文本。

        Returns:
            多行文本，每个工具一行签名 + 一行说明。
        """
        lines = []
        for spec in TOOLS:
            lines.append(f"- {spec.name}{spec.signature}")
            lines.append(f"    {spec.description}")
        return "\n".join(lines)

    def call(self, name: str, args: dict[str, Any] | None = None) -> ToolResult:
        """调用一个工具，任何失败都转成 ``ToolResult(ok=False)``。

        Args:
            name: 工具名。
            args: 参数 dict。

        Returns:
            统一的 ToolResult。
        """
        args = args if isinstance(args, dict) else {}
        index = len(self.calls) + 1
        before = tracker.total_tokens
        start = time.time()

        if index > self.max_calls:
            result = ToolResult(ok=False, error=f"已达工具调用上限 {self.max_calls} 次，必须立刻收尾")
        else:
            spec = TOOL_INDEX.get(name)
            if spec is None:
                result = ToolResult(
                    ok=False,
                    error=f"未知工具 {name!r}，可选: {', '.join(TOOL_INDEX)}",
                )
            else:
                try:
                    result = ToolResult(ok=True, data=spec.func(**args))
                except ToolError as exc:
                    result = ToolResult(ok=False, error=str(exc))
                except TypeError as exc:
                    result = ToolResult(ok=False, error=f"参数不匹配 {spec.name}{spec.signature}: {exc}")
                except Exception as exc:  # noqa: BLE001 - 工具层任何异常都不该打断循环
                    result = ToolResult(ok=False, error=f"{type(exc).__name__}: {exc}")

        elapsed = time.time() - start
        result.tokens = tracker.total_tokens - before

        self.calls.append(
            ToolCall(
                index=index,
                name=name,
                args=args,
                ok=result.ok,
                summary=result.to_observation(200),
                tokens=result.tokens,
                elapsed=elapsed,
            )
        )
        logger.info(
            "[tool #%d] %s(%s) → %s (%d tokens, %.1fs)",
            index,
            name,
            json.dumps(args, ensure_ascii=False)[:120],
            "ok" if result.ok else f"ERROR: {result.error[:80]}",
            result.tokens,
            elapsed,
        )
        return result

    def as_dict(self) -> dict[str, Any]:
        """导出调用轨迹与统计。"""
        return {
            "total_calls": self.total_calls,
            "failed_calls": self.failed_calls,
            "tool_tokens": self.total_tokens,
            "trace": [c.as_dict() for c in self.calls],
        }


# ---------------------------------------------------------------------------
# 共用的 JSON 解析
# ---------------------------------------------------------------------------


def parse_json_reply(text: str) -> dict[str, Any]:
    """从模型回复里抠出 JSON 对象（容忍 ``` 围栏与前后废话）。

    与 ``langgraph_experiment.parse_json_reply`` 同形。这里独立一份是因为本实验
    不引入 LangGraph 依赖；行为必须保持一致，改一处要同步另一处。

    Args:
        text: 模型原始回复。

    Returns:
        解析出的 dict；失败时返回空 dict。
    """
    if not text:
        return {}

    candidate = text.strip()
    if candidate.startswith("```"):
        lines = [ln for ln in candidate.splitlines() if not ln.strip().startswith("```")]
        candidate = "\n".join(lines).strip()

    start, end = candidate.find("{"), candidate.rfind("}")
    if start != -1 and end > start:
        candidate = candidate[start : end + 1]

    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _self_test() -> int:
    """离线自测：跑一遍不调 LLM 的工具，确认数据源可用、错误路径正常。

    Returns:
        退出码。
    """
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    registry = ToolRegistry()

    cases: list[tuple[str, dict[str, Any], bool]] = [
        ("load_trending", {"limit": 5}, True),
        ("filter_repos", {"keyword": "agent", "limit": 5}, True),
        ("filter_repos", {"keyword": ""}, False),
        ("rank_repos", {"by": "stars", "limit": 3}, True),
        ("rank_repos", {"by": "forks"}, False),
        ("rank_repos", {"names": ["不存在/仓库"]}, False),
        ("analyze_repos", {"names": []}, False),
        ("no_such_tool", {}, False),
        ("save_result", {"slug": "", "content": "x"}, False),
    ]

    failures = 0
    for name, args, expect_ok in cases:
        result = registry.call(name, args)
        if result.ok != expect_ok:
            failures += 1
            print(f"❗ {name}{args} 期望 ok={expect_ok}，实际 ok={result.ok}")

    print("-" * 70)
    print(registry.describe())
    print("-" * 70)
    print(f"{len(cases)} 个用例，{len(cases) - failures} 个符合预期，工具层 token 消耗 "
          f"{registry.total_tokens}（应为 0，离线用例不调 LLM）")
    return 1 if failures or registry.total_tokens else 0


if __name__ == "__main__":
    raise SystemExit(_self_test())
