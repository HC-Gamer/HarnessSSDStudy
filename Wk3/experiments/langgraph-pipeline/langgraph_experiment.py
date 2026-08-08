#!/usr/bin/env python3
"""Wk3 实验：LangGraph 状态图编排 vs 线性 Harness 管线（修复版）

对比 V1 (collector→analyzer→organizer 线性管线) 与
LangGraph 状态图方案（共享状态 + 条件路由 + 质量反馈循环）。

实验维度：
1. 状态管理：文件传递 vs StateGraph shared state
2. 条件路由：线性 must-pass vs 图编排 conditional edge
3. 反馈循环：人工重跑 vs 自动 rewrite loop
4. 成本对比：Token 消耗统计

相对首版（2026-07-29）的修复，逐条对应 EXPERIMENT_REPORT.md 的「已知问题」表：

* #1 质量分公式无区分度 → 评分逻辑抽到 :mod:`quality`，新公式基线 40 分、
  空洞用语扣分、具体性信号加分，实测跨度 0-89（旧公式 62-100）
* #2 rewrite 结果被 analyze 覆盖 → 回边改成 ``rewrite → quality_check``，
  评分动作也从 ``analyze_node`` 移到 ``quality_check_node``，重写产出不再被冲掉
* #3 search_node 是模拟采集 → 新增 :mod:`rss_collector`，默认抓真实 RSS/Atom，
  抓不到才降级到 LLM 模拟，state 里用 ``collection_mode`` 记录实际走了哪条
* #4 MemorySaver 未被利用 → 新增 ``exp_checkpoint_recovery``（interrupt →
  get_state → update_state → resume）与 ``exp_sqlite_checkpointer``（跨进程恢复）
* #5 tokens_used 字段悬空 → 每个节点通过 :class:`TokenMeter` 写入真实 token 增量
* #6 CostTracker 全局累计 → 每次实验用 :class:`TokenMeter` 快照差值算单次成本
* #7 无权限隔离 → 未修复，属图编排的架构取舍，见报告「修复记录」

子命令::

    python langgraph_experiment.py all         # 全部
    python langgraph_experiment.py main        # 3 个主实验（真实采集）
    python langgraph_experiment.py lowq        # 低质量样本注入
    python langgraph_experiment.py breaker     # 3 次上限熔断
    python langgraph_experiment.py checkpoint  # MemorySaver 中断恢复
    python langgraph_experiment.py sqlite      # SQLite checkpointer 跨进程
    python langgraph_experiment.py v1v3        # V1/V3 同题对照
"""

from __future__ import annotations

import argparse
import json
import logging
import operator
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal

# ── 确保可以引用 model_client ────────────────────────────────────
HERE = Path(__file__).resolve().parent
V2_PIPELINE = HERE.parents[2] / "Wk2" / "experiments" / "v2-pipeline"
sys.path.insert(0, str(V2_PIPELINE))
sys.path.insert(0, str(HERE))

from dotenv import load_dotenv

# .env 优先级：本目录 → Wk3 → 项目根 → Wk2 v2-pipeline（密钥实际住在最后这个）
for candidate in (
    HERE / ".env",
    HERE.parents[1] / ".env",
    HERE.parents[2] / ".env",
    V2_PIPELINE / ".env",
):
    if candidate.exists():
        load_dotenv(candidate, override=False)

from pipeline.model_client import LLMError, quick_chat
import pipeline.model_client as mc

import rss_collector
from quality import QUALITY_THRESHOLD, QualityBreakdown, legacy_score, score_quality

# ── LangGraph ─────────────────────────────────────────────────────
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

try:
    from langgraph.checkpoint.sqlite import SqliteSaver

    SQLITE_AVAILABLE = True
except ImportError:  # pragma: no cover - 取决于是否装了 langgraph-checkpoint-sqlite
    SqliteSaver = None  # type: ignore[assignment]
    SQLITE_AVAILABLE = False

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("langgraph-experiment")

RESULTS_DIR = HERE / "results"
MAX_LLM_RETRIES = 2  # model_client 内部还有一层退避重试，这里是外层降级前的尝试次数


# ═══════════════════════════════════════════════════════════════════
# 1. 状态定义
# ═══════════════════════════════════════════════════════════════════


class PipelineState(TypedDict):
    """LangGraph 共享状态 —— 所有节点共享同一个 dict。

    对比 V1：V1 用文件系统传递（collector → knowledge/raw/xxx.json →
    analyzer → stdout → organizer → knowledge/articles/xxx.json）。
    LangGraph 所有节点直接读写同一份 state dict，不需要 I/O 中介。
    """

    # 输入
    topic: str  # 研究主题
    entry_mode: str  # "full" = 从 search 开始；"quality_only" = 直接进质量门禁
    analyze_style: str  # "normal" | "terse"（terse 用欠约束 prompt，制造低质产出）
    sabotage_rewrite: bool  # True 时 rewrite 故意不改好，用于验证 3 次上限熔断
    use_real_rss: bool  # True 时抓真实 RSS，失败降级为 LLM 模拟
    max_rewrites: int  # 重写次数上限（熔断阈值）

    # Collector 产出
    raw_content: str  # 原始采集内容
    sources: list[str]  # 来源列表
    collection_mode: str  # "real_rss" | "llm_mock" —— 记录实际走了哪条路

    # Analyzer 产出
    summary: str  # 摘要
    key_points: list[str]  # 关键要点

    # QualityCheck 产出（评分在门禁节点做，不在 analyze 做 —— Bug #2 的修复）
    quality_score: int  # 质量评分 0-100
    quality_breakdown: dict[str, Any]  # 评分分项，便于解释分数怎么来的
    legacy_quality_score: int  # 旧公式分数，用于「修复前 vs 修复后」对照

    # Organizer 产出
    article_title: str  # 最终文章标题
    article_body: str  # 最终文章正文

    # 路由控制
    rewrite_count: int  # 已重写次数
    should_rewrite: bool  # 是否需要重写
    circuit_broken: bool  # 是否因触顶 max_rewrites 而强制放行

    # 统计与轨迹
    tokens_used: int  # 累计 Token 消耗（Bug #5 修复：真的会被写）
    call_count: int  # LLM 调用次数
    degraded_calls: int  # LLM 失败后降级为规则处理的次数
    path: Annotated[list[str], operator.add]  # 走过的节点序列
    score_history: Annotated[list[int], operator.add]  # 每次门禁的评分


def make_initial_state(
    topic: str,
    *,
    entry_mode: str = "full",
    analyze_style: str = "normal",
    sabotage_rewrite: bool = False,
    use_real_rss: bool = True,
    max_rewrites: int = 3,
    summary: str = "",
    key_points: list[str] | None = None,
    raw_content: str = "",
) -> PipelineState:
    """构造初始 state。

    Args:
        topic: 研究主题。
        entry_mode: ``full`` 走完整图；``quality_only`` 跳过采集与分析，
            直接把预置的 summary/key_points 送进质量门禁（低质量注入用）。
        analyze_style: ``normal`` 或 ``terse``（欠约束 prompt）。
        sabotage_rewrite: True 时 rewrite 节点故意不改好，验证熔断。
        use_real_rss: 是否抓真实 RSS。
        max_rewrites: 重写次数上限。
        summary: 预置摘要（entry_mode=quality_only 时使用）。
        key_points: 预置要点。
        raw_content: 预置原始内容。

    Returns:
        初始化好的 PipelineState。
    """
    return PipelineState(
        topic=topic,
        entry_mode=entry_mode,
        analyze_style=analyze_style,
        sabotage_rewrite=sabotage_rewrite,
        use_real_rss=use_real_rss,
        max_rewrites=max_rewrites,
        raw_content=raw_content,
        sources=[],
        collection_mode="none",
        summary=summary,
        key_points=list(key_points or []),
        quality_score=0,
        quality_breakdown={},
        legacy_quality_score=0,
        article_title="",
        article_body="",
        rewrite_count=0,
        should_rewrite=False,
        circuit_broken=False,
        tokens_used=0,
        call_count=0,
        degraded_calls=0,
        path=[],
        score_history=[],
    )


# ═══════════════════════════════════════════════════════════════════
# 2. LLM 调用包装（带 Token 统计 + 失败降级）
# ═══════════════════════════════════════════════════════════════════

tracker = mc.tracker  # model_client 的全局 tracker，quick_chat 内部自动记录


class TokenMeter:
    """对全局 tracker 做快照差值，得到「本次实验」而非「进程累计」的开销。

    首版报告的已知问题 #6：三次实验共用一个全局 tracker，写进结果里的
    ``cost_total_cny`` 是累计值，实验 3 的成本看起来是实验 1 的三倍。
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
        """自基准线以来的调用次数。"""
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


@dataclass
class LLMResult:
    """一次 LLM 调用的结果，含降级标记与 token 增量。

    Attributes:
        text: 模型输出（降级时为空串）。
        tokens: 本次调用消耗的 token（降级时为 0）。
        degraded: 是否因调用失败而降级。
    """

    text: str
    tokens: int
    degraded: bool


def call_llm(prompt: str, system: str = "") -> LLMResult:
    """调用 LLM，最多重试 MAX_LLM_RETRIES 次，失败则降级返回空结果。

    Args:
        prompt: 用户 prompt。
        system: 可选 system prompt。

    Returns:
        LLMResult；``degraded=True`` 时调用方需走规则分支。
    """
    before = tracker.total_tokens
    last_error: Exception | None = None

    for attempt in range(1, MAX_LLM_RETRIES + 1):
        try:
            text = quick_chat(prompt, system=system or None)
            return LLMResult(text=text, tokens=tracker.total_tokens - before, degraded=False)
        except (LLMError, OSError) as exc:
            last_error = exc
            logger.warning("LLM 调用失败 (%d/%d): %s", attempt, MAX_LLM_RETRIES, exc)
            if attempt < MAX_LLM_RETRIES:
                time.sleep(2.0 * attempt)

    logger.error("LLM 连续失败，降级为规则处理: %s", last_error)
    return LLMResult(text="", tokens=tracker.total_tokens - before, degraded=True)


def parse_json_reply(text: str) -> dict[str, Any]:
    """从模型回复里抠出 JSON（容忍 ```json 围栏和前后废话）。

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


# ═══════════════════════════════════════════════════════════════════
# 3. 节点函数
# ═══════════════════════════════════════════════════════════════════

#: analyze_node 的两套 prompt。terse 是「欠约束 prompt」的真实写法 ——
#: 不是刻意写坏，而是把要求写少了，这在实际项目里非常常见。
ANALYZE_PROMPTS: dict[str, str] = {
    "normal": """分析以下真实采集到的技术内容，提取核心信息。

{content}

要求（每一条都会被质量门禁检查）：
- summary：150 字以上中文摘要，必须包含至少一个具体数字、版本号或百分比
- key_points：恰好 5 条，每条一句话，要说清「是什么 + 为什么/怎么做」
- 至少 2 条要点里出现具体对比、实测数据或举例（用「例如」「对比」等词引出）
- 严禁空洞用语：赋能、抓手、闭环、打通、对齐、颗粒度、生态、顶层设计、全面提升

返回 JSON：{{"summary": "...", "key_points": ["...", "...", "...", "...", "..."]}}
只返回 JSON。""",
    "terse": """总结下面的内容。

{content}

返回 JSON：{{"summary": "一句话摘要", "key_points": ["要点1", "要点2"]}}
只返回 JSON。""",
}


def search_node(state: PipelineState) -> dict[str, Any]:
    """Node 1: 采集。

    Bug #3 修复：默认走 :mod:`rss_collector` 抓真实 RSS/Atom feed；
    只有在网络或解析全部失败时才降级为 LLM 模拟，并在
    ``collection_mode`` 里如实记录走了哪条路。

    Args:
        state: 当前 state。

    Returns:
        partial state 更新。
    """
    topic = state["topic"]
    logger.info("[search_node] 采集主题: %s (real_rss=%s)", topic, state["use_real_rss"])

    if state.get("use_real_rss", True):
        try:
            entries = rss_collector.collect(max_sources=3, per_source=3)
        except Exception as exc:  # noqa: BLE001 - 采集层任何异常都应降级而非中断实验
            logger.warning("[search_node] 真实采集异常，降级: %s", exc)
            entries = []

        if entries:
            raw_content, sources = rss_collector.entries_to_raw_content(entries, topic)
            logger.info("[search_node] ✅ 真实采集 %d 条，%d 字", len(entries), len(raw_content))
            return {
                "raw_content": raw_content,
                "sources": sources,
                "collection_mode": "real_rss",
                "path": ["search(real_rss)"],
            }
        logger.warning("[search_node] 真实采集 0 条，降级为 LLM 模拟")

    prompt = f"""你是一个信息采集 Agent。用户关注的主题是：「{topic}」

请模拟一次 GitHub Trending + RSS 采集的结果。返回 JSON 格式：
{{"sources": ["source1", "source2"], "raw_content": "模拟采集到的原始文本，至少 300 字"}}

只返回 JSON，不要额外说明。"""

    result = call_llm(prompt)
    data = parse_json_reply(result.text)

    if result.degraded:
        # 规则降级：没有 LLM 也要让图跑完，用主题本身合成一段最小可用内容
        raw_content = (
            f"# 研究主题: {topic}\n"
            "# 采集方式: 规则降级（真实 RSS 与 LLM 模拟均不可用）\n\n"
            f"{topic} 相关内容采集失败，本次仅验证图编排流转，不产出可引用内容。"
        )
        return {
            "raw_content": raw_content,
            "sources": ["degraded://no-network"],
            "collection_mode": "degraded",
            "call_count": state.get("call_count", 0) + 1,
            "degraded_calls": state.get("degraded_calls", 0) + 1,
            "tokens_used": state.get("tokens_used", 0) + result.tokens,
            "path": ["search(degraded)"],
        }

    return {
        "raw_content": data.get("raw_content") or result.text,
        "sources": data.get("sources") or ["llm-mock"],
        "collection_mode": "llm_mock",
        "call_count": state.get("call_count", 0) + 1,
        "tokens_used": state.get("tokens_used", 0) + result.tokens,
        "path": ["search(llm_mock)"],
    }


def analyze_node(state: PipelineState) -> dict[str, Any]:
    """Node 2: 分析 —— 对标 V1 Analyzer。

    注意：本节点**不再计算质量分**。首版把评分写在这里，导致 rewrite 回到
    analyze 后分数被重算覆盖（Bug #2）。现在评分是 ``quality_check_node``
    的唯一职责，analyze 只负责产出内容。

    Args:
        state: 当前 state。

    Returns:
        partial state 更新。
    """
    style = state.get("analyze_style", "normal")
    logger.info(
        "[analyze_node] 分析原始内容 (%d chars, style=%s)",
        len(state.get("raw_content", "")),
        style,
    )

    prompt = ANALYZE_PROMPTS.get(style, ANALYZE_PROMPTS["normal"]).format(
        content=state.get("raw_content", "")[:2500]
    )
    system = "你是一个技术内容分析 Agent。输出简洁、信息密度高，严格只返回 JSON。"

    result = call_llm(prompt, system)
    data = parse_json_reply(result.text)

    if result.degraded:
        # 规则降级：从 raw_content 里切句子当要点，保证图能走完并被门禁判为低质
        lines = [ln.strip() for ln in state.get("raw_content", "").splitlines() if ln.strip()]
        return {
            "summary": " ".join(lines[:2])[:120],
            "key_points": lines[2:5],
            "call_count": state.get("call_count", 0) + 1,
            "degraded_calls": state.get("degraded_calls", 0) + 1,
            "tokens_used": state.get("tokens_used", 0) + result.tokens,
            "path": [f"analyze({style},degraded)"],
        }

    return {
        "summary": data.get("summary") or result.text[:200],
        "key_points": [str(kp) for kp in (data.get("key_points") or [])],
        "call_count": state.get("call_count", 0) + 1,
        "tokens_used": state.get("tokens_used", 0) + result.tokens,
        "path": [f"analyze({style})"],
    }


def quality_check_node(state: PipelineState) -> dict[str, Any]:
    """Node 3: 质量门禁 —— 评分 + 条件路由决策。

    这是 LangGraph 独有的能力，V1/V2 没有运行时条件路由。

    两处修复：

    * Bug #1：评分改用 :func:`quality.score_quality`，基线 40 分、
      空洞用语扣分、具体性信号加分，分数真的有分布
    * Bug #2：评分动作从 ``analyze_node`` 挪到这里。回边是
      ``rewrite → quality_check``，所以 rewrite 的产出会被**重新评分**，
      而不是被 analyze 重算覆盖

    Args:
        state: 当前 state。

    Returns:
        partial state 更新（含 should_rewrite 路由信号）。
    """
    breakdown: QualityBreakdown = score_quality(
        state.get("summary", ""), state.get("key_points", [])
    )
    legacy = legacy_score(state.get("summary", ""), state.get("key_points", []))
    rewrites = state.get("rewrite_count", 0)
    cap = state.get("max_rewrites", 3)

    passed = breakdown.score >= QUALITY_THRESHOLD
    should_rewrite = (not passed) and rewrites < cap
    circuit_broken = (not passed) and rewrites >= cap

    logger.info(
        "[quality_check_node] 评分 %d/100 (门槛 %d, 旧公式会给 %d) | 已重写 %d/%d",
        breakdown.score,
        QUALITY_THRESHOLD,
        legacy,
        rewrites,
        cap,
    )
    logger.info("[quality_check_node] 分项: %s", breakdown.explain())
    if breakdown.bad_words:
        logger.info("[quality_check_node] 命中空洞用语: %s", "、".join(breakdown.bad_words))
    if circuit_broken:
        logger.warning(
            "[quality_check_node] ⚡ 熔断：重写已达上限 %d 次，分数仍 %d，强制放行",
            cap,
            breakdown.score,
        )

    return {
        "quality_score": breakdown.score,
        "quality_breakdown": breakdown.as_dict(),
        "legacy_quality_score": legacy,
        "should_rewrite": should_rewrite,
        "circuit_broken": circuit_broken,
        "path": [f"quality_check({breakdown.score})"],
        "score_history": [breakdown.score],
    }


def rewrite_node(state: PipelineState) -> dict[str, Any]:
    """Node 4: 修正节点 —— 质量反馈循环。

    Bug #2 修复：本节点的出边是 ``rewrite → quality_check``（不再回 analyze），
    所以改进后的 summary / key_points 会直接被重新评分，不会被覆盖。
    也不再用 ``quality_score + 20`` 的假加分 —— 分数完全由门禁按新内容重算。

    ``sabotage_rewrite=True`` 时故意产出仍然低质的内容（不调 LLM），
    专门用来验证 ``rewrite_count < max_rewrites`` 的熔断。

    Args:
        state: 当前 state。

    Returns:
        partial state 更新。
    """
    attempt = state.get("rewrite_count", 0) + 1
    breakdown = state.get("quality_breakdown", {})
    logger.info(
        "[rewrite_node] 第 %d 次重写（上一轮 %d 分）",
        attempt,
        state.get("quality_score", 0),
    )

    if state.get("sabotage_rewrite", False):
        # 破坏性重写：模拟「模型改了但没改好」，验证熔断而不是验证质量提升
        logger.warning("[rewrite_node] ⚠️ sabotage 模式：本次故意产出低质内容（不调 LLM）")
        return {
            "summary": f"第{attempt}次修订：仍然通过赋能实现闭环。",
            "key_points": ["打通生态", "对齐颗粒度"],
            "rewrite_count": attempt,
            "path": [f"rewrite#{attempt}(sabotage)"],
        }

    bad_words = breakdown.get("bad_words") or []
    feedback_lines = [
        f"- 平均字数只有 {breakdown.get('avg_len', 0)} 字，信息量不足",
        f"- 要点缺 {breakdown.get('shortfall', 0)} 条（需要 5 条）",
        f"- 具体性信号只命中 {breakdown.get('good_hits', 0)} 个（数字/对比/举例）",
    ]
    if bad_words:
        feedback_lines.append(f"- 命中空洞用语 {breakdown.get('bad_hits', 0)} 次：{'、'.join(bad_words)}")

    prompt = f"""上一轮分析没通过质量门禁：得分 {state.get('quality_score', 0)}/100，门槛 {QUALITY_THRESHOLD}。

评分器给出的具体扣分原因：
{chr(10).join(feedback_lines)}

上一轮的产出：
摘要：「{state.get('summary', '')}」
要点：{json.dumps(state.get('key_points', []), ensure_ascii=False)}

请针对上面每一条扣分原因重做分析。硬性要求：
- summary 至少 150 字，含至少一个具体数字、版本号或百分比
- key_points 恰好 5 条，每条一句话说清「是什么 + 为什么/怎么做」
- 至少 2 条要点用「例如」「对比」「实测」引出具体事实
- 一个空洞用语都不许出现（赋能、抓手、闭环、打通、对齐、颗粒度、生态、顶层设计、全面提升）

原始采集内容：
{state.get('raw_content', '')[:2500]}

返回 JSON：{{"summary": "...", "key_points": ["...", "...", "...", "...", "..."]}}
只返回 JSON。"""

    result = call_llm(prompt, "你是一个技术内容分析 Agent，正在按评分反馈修订上一版产出。")
    data = parse_json_reply(result.text)

    if result.degraded:
        return {
            "rewrite_count": attempt,
            "call_count": state.get("call_count", 0) + 1,
            "degraded_calls": state.get("degraded_calls", 0) + 1,
            "tokens_used": state.get("tokens_used", 0) + result.tokens,
            "path": [f"rewrite#{attempt}(degraded)"],
        }

    return {
        "summary": data.get("summary") or state.get("summary", ""),
        "key_points": [str(kp) for kp in (data.get("key_points") or state.get("key_points", []))],
        "rewrite_count": attempt,
        "call_count": state.get("call_count", 0) + 1,
        "tokens_used": state.get("tokens_used", 0) + result.tokens,
        "path": [f"rewrite#{attempt}"],
    }


def organize_node(state: PipelineState) -> dict[str, Any]:
    """Node 5: 组织输出 —— 对标 V1 Organizer。

    Args:
        state: 当前 state。

    Returns:
        partial state 更新。
    """
    logger.info("[organize_node] 生成最终文章（质量 %d）", state.get("quality_score", 0))

    kp_bullets = "\n".join(f"- {kp}" for kp in state.get("key_points", []))
    gate_note = (
        "注意：本次内容是在重写达到上限后被熔断放行的，质量仍不达标，"
        "请在文章开头如实说明这一点。"
        if state.get("circuit_broken")
        else ""
    )

    prompt = f"""基于以下分析，写一篇 300-500 字的技术文章。

主题：{state['topic']}
摘要：{state.get('summary', '')}
关键要点：
{kp_bullets}
质量评分：{state.get('quality_score', 0)}/100（门槛 {QUALITY_THRESHOLD}）
采集方式：{state.get('collection_mode', 'unknown')}
{gate_note}

风格：技术专栏风格，面向 AI 开发者。
要求：有观点、有深度、有人味儿。只写文章正文，不要写标题。"""

    result = call_llm(prompt, "你是一个技术文章写手。输出工整的 Markdown。")

    if result.degraded:
        body = (
            f"> LLM 调用降级，本节内容由规则生成。\n\n"
            f"**摘要**：{state.get('summary', '')}\n\n{kp_bullets}\n"
        )
        return {
            "article_title": f"LangGraph 实验报告：{state['topic']}",
            "article_body": body,
            "call_count": state.get("call_count", 0) + 1,
            "degraded_calls": state.get("degraded_calls", 0) + 1,
            "tokens_used": state.get("tokens_used", 0) + result.tokens,
            "path": ["organize(degraded)"],
        }

    return {
        "article_title": f"LangGraph 实验报告：{state['topic']}",
        "article_body": result.text,
        "call_count": state.get("call_count", 0) + 1,
        "tokens_used": state.get("tokens_used", 0) + result.tokens,
        "path": ["organize"],
    }


# ═══════════════════════════════════════════════════════════════════
# 4. 路由函数
# ═══════════════════════════════════════════════════════════════════


def entry_route(state: PipelineState) -> Literal["search", "analyze", "quality_check"]:
    """入口条件边 —— 决定从哪个节点开始。

    三个入口：

    * ``full``         —— 从 search 开始，走完整图（主实验）
    * ``analyze_only`` —— 跳过采集，用预置的 raw_content 从 analyze 开始
      （V1/V3 同题对照用：两边喂同一份素材，避免采集差异污染对比）
    * ``quality_only`` —— 跳过采集与分析，把预置的 summary/key_points 直接送进
      质量门禁（低质量样本注入用）

    Args:
        state: 当前 state。

    Returns:
        下一个节点名。
    """
    mode = state.get("entry_mode", "full")
    if mode == "quality_only":
        logger.info("→ 入口路由：quality_only（注入预置样本，跳过采集与分析）")
        return "quality_check"
    if mode == "analyze_only":
        logger.info("→ 入口路由：analyze_only（用预置素材，跳过采集）")
        return "analyze"
    logger.info("→ 入口路由：full（从 search 开始）")
    return "search"


def decide_route(state: PipelineState) -> Literal["rewrite", "organize"]:
    """条件边 —— 根据 quality_check 的结果选择路径。

    这是 LangGraph 的 Conditional Edge，V1 线性管线做不到。

    Args:
        state: 当前 state。

    Returns:
        下一个节点名。
    """
    if state.get("should_rewrite", False):
        logger.info("→ 路由到 rewrite 节点（质量修正循环）")
        return "rewrite"
    if state.get("circuit_broken", False):
        logger.info("→ 路由到 organize 节点（熔断放行，质量未达标）")
    else:
        logger.info("→ 路由到 organize 节点（通过质量门禁）")
    return "organize"


# ═══════════════════════════════════════════════════════════════════
# 5. 图构建
# ═══════════════════════════════════════════════════════════════════


def build_pipeline_graph() -> StateGraph:
    """构建 LangGraph StateGraph。

    图结构（修复后）::

        START ─┬─ (full) ────────► search → analyze ─┐
               └─ (quality_only) ───────────────────►┴► quality_check
                                                         │
                            ┌────────────────────────────┤ decide_route
                            │                            │
                            ▼ (score < 60 且未触顶)       ▼ (通过 / 熔断)
                        rewrite ─────► quality_check   organize → END
                                (回边指向门禁，不再回 analyze)

    与首版的差异：回边从 ``rewrite → analyze`` 改为 ``rewrite → quality_check``。
    首版回边会让 analyze 从 raw_content 从头重算，把 rewrite 的改进产出覆盖掉，
    真正生效的只有 rewrite_count 计数器（EXPERIMENT_REPORT.md 已知问题 #2）。

    Returns:
        未 compile 的 StateGraph builder。
    """
    builder = StateGraph(PipelineState)

    builder.add_node("search", search_node)
    builder.add_node("analyze", analyze_node)
    builder.add_node("quality_check", quality_check_node)
    builder.add_node("rewrite", rewrite_node)
    builder.add_node("organize", organize_node)

    # 入口条件边 —— 支持「注入预置低质样本」的旁路入口
    builder.add_conditional_edges(
        START,
        entry_route,
        {"search": "search", "analyze": "analyze", "quality_check": "quality_check"},
    )

    builder.add_edge("search", "analyze")
    builder.add_edge("analyze", "quality_check")

    # 质量门禁的条件边 —— LangGraph 独有
    builder.add_conditional_edges(
        "quality_check",
        decide_route,
        {"rewrite": "rewrite", "organize": "organize"},
    )

    # 反馈循环回边：rewrite → quality_check（Bug #2 修复的核心一行）
    builder.add_edge("rewrite", "quality_check")

    builder.add_edge("organize", END)

    return builder


# ═══════════════════════════════════════════════════════════════════
# 6. 单次实验执行
# ═══════════════════════════════════════════════════════════════════


def run_graph(
    initial: PipelineState,
    *,
    label: str,
    checkpointer: Any = None,
    thread_id: str | None = None,
) -> tuple[dict[str, Any], float, TokenMeter]:
    """编译并跑一次图。

    Args:
        initial: 初始 state。
        label: 日志标签。
        checkpointer: checkpointer 实例，默认新建 MemorySaver。
        thread_id: checkpointer 的 thread_id，默认按时间戳生成。

    Returns:
        (最终 state, 耗时秒, 本次实验的 TokenMeter)。
    """
    graph = build_pipeline_graph()
    app = graph.compile(checkpointer=checkpointer or MemorySaver())

    thread_id = thread_id or f"{label}-{int(time.time() * 1000)}"
    config = {"configurable": {"thread_id": thread_id}}

    logger.info("=" * 66)
    logger.info("实验: %s | topic=%s", label, initial["topic"])
    logger.info(
        "entry=%s style=%s sabotage=%s real_rss=%s cap=%d",
        initial["entry_mode"],
        initial["analyze_style"],
        initial["sabotage_rewrite"],
        initial["use_real_rss"],
        initial["max_rewrites"],
    )
    logger.info("thread_id=%s", thread_id)
    logger.info("=" * 66)

    meter = TokenMeter()
    start = time.time()
    final_state = app.invoke(initial, config=config)
    elapsed = time.time() - start

    logger.info("=" * 66)
    logger.info("完成 %s | 耗时 %.1fs", label, elapsed)
    logger.info("路径: %s", " → ".join(final_state.get("path", [])))
    logger.info("评分轨迹: %s", final_state.get("score_history", []))
    logger.info(
        "LLM 调用 %d 次 | token %d | 成本 ¥%.4f | 降级 %d 次",
        final_state.get("call_count", 0),
        meter.tokens,
        meter.cny,
        final_state.get("degraded_calls", 0),
    )
    logger.info("=" * 66)

    return final_state, elapsed, meter


def summarize_result(
    name: str,
    state: dict[str, Any],
    elapsed: float,
    meter: TokenMeter,
) -> dict[str, Any]:
    """把一次运行压成结果 dict。

    Args:
        name: 实验名。
        state: 最终 state。
        elapsed: 耗时。
        meter: 该次实验的计量器。

    Returns:
        结果 dict。
    """
    return {
        "name": name,
        "topic": state.get("topic", ""),
        "elapsed_seconds": round(elapsed, 2),
        "collection_mode": state.get("collection_mode"),
        "sources": state.get("sources", []),
        "quality_score": state.get("quality_score", 0),
        "legacy_quality_score": state.get("legacy_quality_score", 0),
        "quality_breakdown": state.get("quality_breakdown", {}),
        "score_history": state.get("score_history", []),
        "rewrite_count": state.get("rewrite_count", 0),
        "circuit_broken": state.get("circuit_broken", False),
        "path": state.get("path", []),
        "llm_calls": state.get("call_count", 0),
        "degraded_calls": state.get("degraded_calls", 0),
        "tokens_used_state": state.get("tokens_used", 0),
        "summary": state.get("summary", ""),
        "key_points": state.get("key_points", []),
        "article_title": state.get("article_title", ""),
        **meter.as_dict(),
    }


def write_article(slug: str, state: dict[str, Any]) -> Path:
    """把一次运行的产出写成 Markdown。

    Args:
        slug: 文件名片段。
        state: 最终 state。

    Returns:
        写入的文件路径。
    """
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / f"{slug}.md"

    breakdown = state.get("quality_breakdown", {})
    content = f"""# {state.get('article_title', '')}

> 主题: {state.get('topic', '')}
> 质量评分: {state.get('quality_score', 0)}/100（门槛 {QUALITY_THRESHOLD}，旧公式会给 {state.get('legacy_quality_score', 0)}）
> 评分轨迹: {state.get('score_history', [])} | 重写次数: {state.get('rewrite_count', 0)}{' ⚡熔断放行' if state.get('circuit_broken') else ''}
> 采集方式: {state.get('collection_mode', 'unknown')} | LLM 调用: {state.get('call_count', 0)} 次
> 走过的路径: {' → '.join(state.get('path', []))}

## 评分分项

| 分项 | 值 |
|------|-----|
| 平均字数 | {breakdown.get('avg_len', 0)} |
| 空洞用语命中 | {breakdown.get('bad_hits', 0)} 次 {('（' + '、'.join(breakdown.get('bad_words', [])) + '）') if breakdown.get('bad_words') else ''} |
| 具体性信号 | {breakdown.get('good_hits', 0)} 个 |
| 要点缺口 | {breakdown.get('shortfall', 0)} 条 |
| 原始分 → 最终分 | {breakdown.get('raw_score', 0)} → {breakdown.get('score', 0)} |

## 数据来源

{chr(10).join(f'- {s}' for s in state.get('sources', [])) or '- （无）'}

## 摘要

{state.get('summary', '')}

## 关键要点

{chr(10).join(f'- {kp}' for kp in state.get('key_points', [])) or '- （无）'}

## 正文

{state.get('article_body', '')}
"""
    path.write_text(content, encoding="utf-8")
    logger.info("产出已保存: %s", path)
    return path


# ═══════════════════════════════════════════════════════════════════
# 7. 实验组
# ═══════════════════════════════════════════════════════════════════

MAIN_TOPICS: tuple[tuple[str, str], ...] = (
    ("LangGraph StateGraph vs 线性 Harness 管线架构对比", "normal"),
    # 实验 2 故意用欠约束 prompt —— 这不是人为造假，而是真实项目里最常见的
    # 低质量来源：prompt 把要求写少了。用来验证门禁能识别并触发 rewrite 分支。
    ("AI Agent 中的条件路由与反馈循环设计模式", "terse"),
    ("多 Agent 协作中的状态共享机制", "normal"),
)


def exp_main() -> list[dict[str, Any]]:
    """3 个主实验：真实 RSS 采集 + 完整图。实验 2 用欠约束 prompt 触发 rewrite。

    Returns:
        结果列表。
    """
    results = []
    for i, (topic, style) in enumerate(MAIN_TOPICS, 1):
        initial = make_initial_state(topic, analyze_style=style, use_real_rss=True)
        state, elapsed, meter = run_graph(initial, label=f"main-{i}")
        write_article(f"experiment_{i}_article", state)
        results.append(summarize_result(f"main-{i}({style})", state, elapsed, meter))
    return results


#: 故意低质的注入样本（对应下一步 #3）。两种典型低质形态：
#: 空洞用语堆砌，以及摘要极短 + 要点条数不足。
LOW_QUALITY_SAMPLES: tuple[tuple[str, str, str, list[str]], ...] = (
    (
        "lowq-1-空洞用语",
        "AI Agent 编排框架对比",
        "本方案通过赋能业务实现闭环，打通生态，对齐颗粒度，形成合力。",
        ["顶层设计先行", "全面提升效率", "深度融合场景"],
    ),
    (
        "lowq-2-摘要极短",
        "AI Agent 编排框架对比",
        "介绍了一些情况。",
        ["有进展", "后续观察"],
    ),
)


def exp_low_quality() -> list[dict[str, Any]]:
    """注入低质量样本，验证 rewrite 分支真的被触发并能把分数救回来。

    先抓一次真实 RSS 作为 raw_content（rewrite 需要真实素材才能改好），
    然后从 quality_check 入口进图，预置的低质 summary/key_points 必然不及格。

    Returns:
        结果列表。
    """
    entries = rss_collector.collect(max_sources=2, per_source=3)
    if entries:
        raw_content, _ = rss_collector.entries_to_raw_content(entries, "AI Agent 编排框架对比")
    else:
        logger.warning("[exp_low_quality] 真实采集失败，rewrite 将缺少素材")
        raw_content = "（采集失败，无真实素材）"

    results = []
    for slug, topic, summary, key_points in LOW_QUALITY_SAMPLES:
        initial = make_initial_state(
            topic,
            entry_mode="quality_only",
            summary=summary,
            key_points=key_points,
            raw_content=raw_content,
            use_real_rss=False,
        )
        state, elapsed, meter = run_graph(initial, label=slug)
        write_article(slug, state)
        results.append(summarize_result(slug, state, elapsed, meter))
    return results


def exp_circuit_breaker() -> list[dict[str, Any]]:
    """验证 ``rewrite_count < max_rewrites`` 的熔断。

    用 ``sabotage_rewrite=True`` 模拟「模型改了但改不好」：rewrite 每次都产出
    同样低质的内容，门禁每次都判不及格。图应当在第 3 次重写后停止循环、
    置 ``circuit_broken=True``、放行到 organize，而不是无限打转。

    sabotage 分支不调 LLM，所以这个实验只花 organize 一次调用的钱。

    Returns:
        结果列表。
    """
    initial = make_initial_state(
        "熔断验证：重写达到上限后强制放行",
        entry_mode="quality_only",
        summary="通过赋能实现闭环。",
        key_points=["打通生态"],
        raw_content="（熔断验证不需要真实素材）",
        sabotage_rewrite=True,
        use_real_rss=False,
        max_rewrites=3,
    )
    state, elapsed, meter = run_graph(initial, label="breaker")
    write_article("breaker_circuit_breaker", state)

    result = summarize_result("breaker", state, elapsed, meter)
    result["assertions"] = {
        "rewrite_count_equals_cap": state.get("rewrite_count") == 3,
        "circuit_broken": bool(state.get("circuit_broken")),
        "reached_organize": "organize" in state.get("path", []),
        "quality_checks_run": sum(
            1 for p in state.get("path", []) if p.startswith("quality_check")
        ),
    }
    logger.info("[breaker] 断言: %s", json.dumps(result["assertions"], ensure_ascii=False))
    return [result]


def exp_checkpoint_recovery() -> list[dict[str, Any]]:
    """MemorySaver 中断恢复验证（Bug #4）。

    流程：
    1. ``interrupt_before=["organize"]`` 编译，invoke 到 organize 前挂起
    2. ``get_state`` 读出 checkpoint，确认 ``next == ("organize",)``
    3. ``update_state`` 改写 state（把 topic 改掉，作为「恢复后确实读的是
       改过的 checkpoint」的可观测证据）
    4. ``invoke(None, config)`` 从 checkpoint 续跑，验证走完 organize
    5. ``get_state_history`` 数一数存了几个 checkpoint

    Returns:
        结果列表（含断言）。
    """
    logger.info("=" * 66)
    logger.info("实验: checkpoint-recovery (MemorySaver 中断 → 改写 → 恢复)")
    logger.info("=" * 66)

    saver = MemorySaver()
    graph = build_pipeline_graph()
    app = graph.compile(checkpointer=saver, interrupt_before=["organize"])

    thread_id = f"ckpt-{int(time.time() * 1000)}"
    config = {"configurable": {"thread_id": thread_id}}

    meter = TokenMeter()
    start = time.time()

    initial = make_initial_state(
        "checkpoint 中断恢复验证", analyze_style="normal", use_real_rss=True
    )
    paused = app.invoke(initial, config=config)
    logger.info("① 已在 organize 前中断，路径: %s", " → ".join(paused.get("path", [])))

    snapshot = app.get_state(config)
    next_nodes = list(snapshot.next)
    logger.info("② checkpoint 读出: next=%s, quality=%s", next_nodes, snapshot.values.get("quality_score"))
    assert_paused_before_organize = next_nodes == ["organize"]
    article_empty_at_pause = not snapshot.values.get("article_body")

    marker = "checkpoint 中断恢复验证【已被 update_state 改写】"
    app.update_state(config, {"topic": marker})
    after_update = app.get_state(config)
    logger.info("③ update_state 后 topic = %s", after_update.values.get("topic"))
    update_took_effect = after_update.values.get("topic") == marker

    resumed = app.invoke(None, config=config)
    elapsed = time.time() - start
    logger.info("④ 从 checkpoint 续跑完成，路径: %s", " → ".join(resumed.get("path", [])))

    history = list(app.get_state_history(config))
    logger.info("⑤ checkpoint 历史条数: %d", len(history))

    write_article("checkpoint_recovery", resumed)

    result = summarize_result("checkpoint-recovery", resumed, elapsed, meter)
    result["assertions"] = {
        "paused_before_organize": assert_paused_before_organize,
        "article_empty_at_pause": article_empty_at_pause,
        "update_state_took_effect": update_took_effect,
        "resumed_reached_organize": "organize" in resumed.get("path", []),
        "article_filled_after_resume": bool(resumed.get("article_body")),
        "topic_carried_marker": marker in resumed.get("article_title", ""),
        "checkpoint_history_count": len(history),
    }
    logger.info("[checkpoint] 断言: %s", json.dumps(result["assertions"], ensure_ascii=False))
    return [result]


def _verify_cross_process(db_path: Path, thread_id: str) -> dict[str, Any]:
    """拉起一个独立 Python 进程读同一个 SQLite checkpoint。

    这是「跨进程恢复」最硬的证据：子进程除了 ``(db_path, thread_id)`` 之外
    什么都不知道，读得出 next 节点就说明 checkpoint 真的在磁盘上。

    Args:
        db_path: SQLite 文件路径。
        thread_id: 要读的 thread。

    Returns:
        子进程返回的 JSON（失败时含 ``error`` 键）。
    """
    script = HERE / "verify_sqlite_resume.py"
    try:
        proc = subprocess.run(
            [sys.executable, str(script), str(db_path), thread_id],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(HERE),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"error": f"子进程启动失败: {exc}"}

    if proc.returncode not in (0, 1):
        return {"error": f"子进程退出码 {proc.returncode}", "stderr": proc.stderr[-400:]}

    try:
        return json.loads(proc.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        return {"error": "子进程输出不是 JSON", "stdout": proc.stdout[-400:]}


def exp_sqlite_checkpointer() -> list[dict[str, Any]]:
    """SQLite checkpointer 对比 MemorySaver（下一步 #4）。

    MemorySaver 的 checkpoint 活在进程内存里，进程一退就没了。SqliteSaver
    落盘，所以可以**换一个 checkpointer 实例**（等价于换一个进程）再从同一个
    thread_id 续跑 —— 这是 MemorySaver 做不到的。

    本实验用两段独立的 ``with SqliteSaver.from_conn_string(db)`` 上下文来模拟
    「进程 A 跑到一半崩了，进程 B 接着跑」。同时用一个新的 MemorySaver 实例做
    对照，验证它确实拿不到之前的 checkpoint。

    Returns:
        结果列表（含断言）；未安装 langgraph-checkpoint-sqlite 时返回跳过说明。
    """
    if not SQLITE_AVAILABLE:
        logger.warning("未安装 langgraph-checkpoint-sqlite，跳过 SQLite checkpointer 实验")
        return [
            {
                "name": "sqlite-checkpointer",
                "skipped": True,
                "reason": (
                    "当前环境 langgraph 1.2.9 的 langgraph.checkpoint.sqlite 需要额外安装 "
                    "langgraph-checkpoint-sqlite；未安装时跳过。"
                ),
            }
        ]

    logger.info("=" * 66)
    logger.info("实验: sqlite-checkpointer (跨 checkpointer 实例恢复)")
    logger.info("=" * 66)

    db_path = RESULTS_DIR / "checkpoints.sqlite"
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    thread_id = f"sqlite-{int(time.time() * 1000)}"
    config = {"configurable": {"thread_id": thread_id}}
    graph = build_pipeline_graph()

    meter = TokenMeter()
    start = time.time()

    # ── 进程 A：跑到 organize 前中断，checkpoint 落盘 ────────────────
    with SqliteSaver.from_conn_string(str(db_path)) as saver_a:
        app_a = graph.compile(checkpointer=saver_a, interrupt_before=["organize"])
        initial = make_initial_state(
            "SQLite checkpointer 跨进程恢复验证", use_real_rss=True
        )
        paused = app_a.invoke(initial, config=config)
        snap_a = app_a.get_state(config)
        logger.info(
            "① 进程A 中断于 %s，quality=%s，路径 %s",
            list(snap_a.next),
            snap_a.values.get("quality_score"),
            " → ".join(paused.get("path", [])),
        )
        paused_next_a = list(snap_a.next)

    db_size = db_path.stat().st_size
    logger.info("② checkpointer 上下文已退出，DB 落盘 %d 字节", db_size)

    # ── 对照：全新 MemorySaver 拿不到这个 thread 的 checkpoint ────────
    fresh_mem = graph.compile(checkpointer=MemorySaver())
    mem_snapshot = fresh_mem.get_state(config)
    mem_sees_nothing = not mem_snapshot.values
    logger.info(
        "③ 对照组：全新 MemorySaver 看到的 state = %s（应为空）",
        mem_snapshot.values or "{}",
    )

    # ── 真·跨进程验证：拉起一个独立 Python 进程读同一个 DB ────────────
    cross_process = _verify_cross_process(db_path, thread_id)
    logger.info("③b 独立进程 (pid=%s) 读到: %s", cross_process.get("pid"), cross_process)

    # ── 进程 B：新建 SqliteSaver 实例，从磁盘续跑 ────────────────────
    with SqliteSaver.from_conn_string(str(db_path)) as saver_b:
        app_b = graph.compile(checkpointer=saver_b)
        snap_b = app_b.get_state(config)
        sqlite_sees_state = bool(snap_b.values)
        logger.info(
            "④ 进程B 新实例读到 checkpoint: next=%s, quality=%s",
            list(snap_b.next),
            snap_b.values.get("quality_score"),
        )
        resumed = app_b.invoke(None, config=config)
        history_len = len(list(app_b.get_state_history(config)))

    elapsed = time.time() - start
    logger.info("⑤ 进程B 续跑完成，路径 %s", " → ".join(resumed.get("path", [])))

    write_article("sqlite_checkpointer", resumed)

    result = summarize_result("sqlite-checkpointer", resumed, elapsed, meter)
    result["assertions"] = {
        "process_a_paused_before_organize": paused_next_a == ["organize"],
        "db_file_written_bytes": db_size,
        "fresh_memorysaver_sees_nothing": mem_sees_nothing,
        "new_sqlite_instance_sees_state": sqlite_sees_state,
        "separate_os_process_sees_state": bool(cross_process.get("saw_state")),
        "separate_os_process_detail": cross_process,
        "process_b_completed_organize": "organize" in resumed.get("path", []),
        "article_filled_by_process_b": bool(resumed.get("article_body")),
        "checkpoint_history_count": history_len,
    }
    logger.info("[sqlite] 断言: %s", json.dumps(result["assertions"], ensure_ascii=False))
    return [result]


# ── V1 线性管线（对照组）────────────────────────────────────────────


def run_v1_linear(
    topic: str,
    raw_content: str,
    sources: list[str],
    analyze_style: str = "normal",
) -> dict[str, Any]:
    """V1 线性管线复刻：collector → analyzer → organizer，靠文件系统传递。

    刻意保留 V1 的三个特征，用来和 V3 做同题对照：

    * 中间产物必须落盘（``v1_workdir/`` 下的 raw / analysis / article）
    * 没有质量门禁，也没有回头路 —— 跑到底就算完
    * 每一步只能看到上一步写下的文件，不存在全局 state

    为了让对照只隔离「编排」这一个变量，analyzer 用的 prompt 与 V3 的
    ``analyze_node`` **完全相同**（同一份 :data:`ANALYZE_PROMPTS`）。
    这样 V1 与 V3 的唯一差别就是：V3 后面挂了质量门禁和 rewrite 回路。

    Args:
        topic: 研究主题。
        raw_content: 采集内容（与 V3 用同一份，保证同题同料）。
        sources: 来源列表。
        analyze_style: 与 V3 对齐的 prompt 风格（``normal`` / ``terse``）。

    Returns:
        V1 运行结果 dict。
    """
    workdir = RESULTS_DIR / "v1_workdir"
    workdir.mkdir(parents=True, exist_ok=True)
    stamp = f"{int(time.time())}-{analyze_style}"

    meter = TokenMeter()
    start = time.time()
    calls = 0
    files: list[str] = []

    # ── Step 1: collector → 落盘 raw JSON ─────────────────────────
    raw_path = workdir / f"raw-{stamp}.json"
    raw_path.write_text(
        json.dumps(
            {"topic": topic, "sources": sources, "raw_content": raw_content},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    files.append(str(raw_path.relative_to(RESULTS_DIR)))
    logger.info("[V1/collector] 已写 %s", raw_path.name)

    # ── Step 2: analyzer → 读 raw JSON，写 analysis JSON ──────────
    loaded = json.loads(raw_path.read_text(encoding="utf-8"))
    prompt = ANALYZE_PROMPTS.get(analyze_style, ANALYZE_PROMPTS["normal"]).format(
        content=loaded["raw_content"][:2500]
    )
    result = call_llm(prompt, "你是一个技术内容分析 Agent。输出简洁、信息密度高，严格只返回 JSON。")
    calls += 1
    data = parse_json_reply(result.text)
    summary = data.get("summary") or result.text[:200]
    key_points = [str(kp) for kp in (data.get("key_points") or [])]

    analysis_path = workdir / f"analysis-{stamp}.json"
    analysis_path.write_text(
        json.dumps({"summary": summary, "key_points": key_points}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    files.append(str(analysis_path.relative_to(RESULTS_DIR)))
    logger.info("[V1/analyzer] 已写 %s", analysis_path.name)

    # V1 没有门禁 —— 这里只是「事后」用同一把尺子量一下，管线本身不看这个分数
    breakdown = score_quality(summary, key_points)
    logger.info("[V1] 事后评分 %d/100（管线本身不做门禁）: %s", breakdown.score, breakdown.explain())

    # ── Step 3: organizer → 读 analysis JSON，写 article ──────────
    analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
    kp_bullets = "\n".join(f"- {kp}" for kp in analysis["key_points"])
    prompt = f"""基于以下分析，写一篇 300-500 字的技术文章。

主题：{topic}
摘要：{analysis['summary']}
关键要点：
{kp_bullets}

风格：技术专栏风格，面向 AI 开发者。
要求：有观点、有深度、有人味儿。只写文章正文，不要写标题。"""
    result = call_llm(prompt, "你是一个技术文章写手。输出工整的 Markdown。")
    calls += 1
    body = result.text

    article_path = workdir / f"article-{stamp}.md"
    article_path.write_text(f"# V1 线性管线：{topic}\n\n{body}\n", encoding="utf-8")
    files.append(str(article_path.relative_to(RESULTS_DIR)))
    logger.info("[V1/organizer] 已写 %s", article_path.name)

    elapsed = time.time() - start

    return {
        "name": f"v1-linear({analyze_style})",
        "topic": topic,
        "analyze_style": analyze_style,
        "elapsed_seconds": round(elapsed, 2),
        "quality_score": breakdown.score,
        "legacy_quality_score": legacy_score(summary, key_points),
        "quality_breakdown": breakdown.as_dict(),
        "quality_gate": "无（事后评分，管线不据此分支）",
        "rewrite_count": 0,
        "path": ["collector", "→file→", "analyzer", "→file→", "organizer"],
        "intermediate_files": files,
        "llm_calls": calls,
        "summary": summary,
        "key_points": key_points,
        "article_title": f"V1 线性管线：{topic}",
        "article_body": body,
        **meter.as_dict(),
    }


V1V3_TOPIC = "AI Agent 编排框架对比"


def exp_v1_vs_v3() -> dict[str, Any]:
    """V1/V3 同题对照（下一步 #6），2×2 设计。

    实验设计要点 —— 只隔离「编排」一个变量：

    * 同一个 topic
    * 同一份真实采集素材（抓一次，两边共用同一个 ``raw_content`` 字符串）
    * **同一个 analyzer prompt**（V1 与 V3 都用 :data:`ANALYZE_PROMPTS`）
    * 唯一差别：V3 的 analyze 后面挂了质量门禁 + rewrite 回路，V1 没有

    2×2 的第二个因子是 prompt 质量，因为「有门禁」的价值完全取决于
    analyzer 会不会失手：

    * ``normal`` 严格 prompt → analyzer 一次到位 → 门禁应当是 no-op，V1≈V3
    * ``terse`` 欠约束 prompt → analyzer 交出低质产出 → 门禁应当拦下并 rewrite

    只跑 normal 一格会得出「门禁没用」的结论，只跑 terse 一格会得出「门禁
    大幅提升质量」的结论。两格都跑才说得清门禁到底在什么条件下值钱。

    Returns:
        含四格结果与对比表的 dict。
    """
    logger.info("=" * 66)
    logger.info("实验: V1/V3 同题对照 (2×2) | topic=%s", V1V3_TOPIC)
    logger.info("=" * 66)

    entries = rss_collector.collect(max_sources=3, per_source=3)
    if entries:
        raw_content, sources = rss_collector.entries_to_raw_content(entries, V1V3_TOPIC)
        collection_mode = "real_rss"
    else:
        logger.warning("[v1v3] 真实采集失败，四格都用降级素材（对照仍公平）")
        raw_content, sources = f"# 研究主题: {V1V3_TOPIC}\n（采集失败）", []
        collection_mode = "degraded"

    cells: dict[str, dict[str, Any]] = {}

    for style in ("normal", "terse"):
        # ── V1：线性、文件传递、无门禁 ──────────────────────────────
        v1 = run_v1_linear(V1V3_TOPIC, raw_content, sources, analyze_style=style)
        v1["collection_mode"] = collection_mode
        v1["quality_gate"] = "无（事后评分，管线不据此分支）"
        write_article(
            f"v1v3_v1_linear_{style}",
            {
                **v1,
                "score_history": [v1["quality_score"]],
                "sources": sources,
                "circuit_broken": False,
                "call_count": v1["llm_calls"],
            },
        )
        cells[f"v1_{style}"] = v1

        # ── V3：同素材、同 prompt，但 analyze 后挂门禁 + rewrite 回路 ──
        initial = make_initial_state(
            V1V3_TOPIC,
            entry_mode="analyze_only",
            analyze_style=style,
            raw_content=raw_content,
            use_real_rss=False,
        )
        state, elapsed, meter = run_graph(initial, label=f"v1v3-v3-{style}")
        v3 = summarize_result(f"v3-stategraph({style})", state, elapsed, meter)
        v3["analyze_style"] = style
        v3["quality_gate"] = f"有（门槛 {QUALITY_THRESHOLD}，不达标自动 rewrite，上限 3 次）"
        write_article(f"v1v3_v3_stategraph_{style}", state)
        cells[f"v3_{style}"] = v3

        logger.info(
            "[v1v3/%s] V1 质量 %d (轨迹单次) vs V3 质量 %d (轨迹 %s, 重写 %d)",
            style,
            v1["quality_score"],
            v3["quality_score"],
            v3["score_history"],
            v3["rewrite_count"],
        )

    def cell(key: str, field: str, default: Any = "") -> Any:
        return cells[key].get(field, default)

    table = [
        {
            "维度": "拓扑",
            "V1/normal": "线性链 3 节点",
            "V3/normal": "有向图 5 节点 +2 条件边 +1 回边",
            "V1/terse": "线性链 3 节点",
            "V3/terse": "有向图 5 节点 +2 条件边 +1 回边",
        },
        {
            "维度": "中间产物",
            "V1/normal": f"{len(cell('v1_normal','intermediate_files',[]))} 个文件落盘",
            "V3/normal": "共享 state，0 文件",
            "V1/terse": f"{len(cell('v1_terse','intermediate_files',[]))} 个文件落盘",
            "V3/terse": "共享 state，0 文件",
        },
    ]
    for label, field in (
        ("质量分", "quality_score"),
        ("旧公式分", "legacy_quality_score"),
        ("评分轨迹", "score_history"),
        ("重写次数", "rewrite_count"),
        ("LLM 调用", "llm_calls"),
        ("Token", "tokens"),
        ("成本 CNY", "cost_cny"),
        ("耗时 s", "elapsed_seconds"),
    ):
        table.append(
            {
                "维度": label,
                "V1/normal": cell("v1_normal", field, "—（单次）" if field == "score_history" else 0),
                "V3/normal": cell("v3_normal", field, 0),
                "V1/terse": cell("v1_terse", field, "—（单次）" if field == "score_history" else 0),
                "V3/terse": cell("v3_terse", field, 0),
            }
        )
    table.append(
        {
            "维度": "摘要字数",
            "V1/normal": len(cell("v1_normal", "summary", "")),
            "V3/normal": len(cell("v3_normal", "summary", "")),
            "V1/terse": len(cell("v1_terse", "summary", "")),
            "V3/terse": len(cell("v3_terse", "summary", "")),
        }
    )
    table.append(
        {
            "维度": "要点条数",
            "V1/normal": len(cell("v1_normal", "key_points", [])),
            "V3/normal": len(cell("v3_normal", "key_points", [])),
            "V1/terse": len(cell("v1_terse", "key_points", [])),
            "V3/terse": len(cell("v3_terse", "key_points", [])),
        }
    )

    return {
        "topic": V1V3_TOPIC,
        "design": "2×2：{V1 线性, V3 StateGraph} × {normal 严格 prompt, terse 欠约束 prompt}；同素材同 prompt，唯一差异是门禁+回路",
        "collection_mode": collection_mode,
        "same_raw_content_chars": len(raw_content),
        "cells": cells,
        "table": table,
        "gate_delta": {
            "normal": cell("v3_normal", "quality_score", 0) - cell("v1_normal", "quality_score", 0),
            "terse": cell("v3_terse", "quality_score", 0) - cell("v1_terse", "quality_score", 0),
        },
    }


# ═══════════════════════════════════════════════════════════════════
# 8. 入口
# ═══════════════════════════════════════════════════════════════════


def print_summary(payload: dict[str, Any]) -> None:
    """打印总汇总。

    Args:
        payload: 全部实验结果。
    """
    print("\n")
    print("=" * 78)
    print("  Wk3 LangGraph 实验汇总（修复版）")
    print("=" * 78)

    rows: list[dict[str, Any]] = []
    for group in ("main", "low_quality", "circuit_breaker", "checkpoint", "sqlite"):
        rows.extend(payload.get(group, []) or [])

    print(f"  {'实验':<22}{'质量':>6}{'旧公式':>7}{'重写':>5}{'调用':>5}{'Token':>8}{'成本¥':>9}{'耗时s':>7}")
    print("-" * 78)
    for row in rows:
        if row.get("skipped"):
            print(f"  {row['name']:<22}  SKIPPED — {row.get('reason', '')[:40]}")
            continue
        print(
            f"  {row['name']:<22}{row.get('quality_score', 0):>6}"
            f"{row.get('legacy_quality_score', 0):>7}"
            f"{row.get('rewrite_count', 0):>5}{row.get('llm_calls', 0):>5}"
            f"{row.get('tokens', 0):>8}{row.get('cost_cny', 0):>9.4f}"
            f"{row.get('elapsed_seconds', 0):>7.1f}"
        )

    if payload.get("v1_vs_v3"):
        cmp_ = payload["v1_vs_v3"]
        print("-" * 78)
        print(f"  V1/V3 同题对照 (2×2) | topic={cmp_['topic']}")
        print(f"  {'维度':<12}{'V1/normal':>22}{'V3/normal':>22}")
        for item in cmp_["table"]:
            print(f"    {item['维度']:<10} {str(item['V1/normal'])[:20]:>20} | {str(item['V3/normal'])[:20]:>20}"
                  f"   ‖ terse: {str(item['V1/terse'])[:16]:>16} | {str(item['V3/terse'])[:16]:>16}")
        print(f"  门禁带来的质量分增量: normal {cmp_['gate_delta']['normal']:+d} | "
              f"terse {cmp_['gate_delta']['terse']:+d}")

    print("-" * 78)
    print(f"  进程累计: {tracker.total_calls} 次调用, {tracker.total_tokens:,} tokens, "
          f"¥{tracker.estimated_cost():.4f} / ${tracker.estimated_cost_usd():.4f}")
    print("=" * 78)


def main(argv: list[str] | None = None) -> int:
    """CLI 入口。

    Args:
        argv: 命令行参数，默认取 sys.argv[1:]。

    Returns:
        退出码。
    """
    parser = argparse.ArgumentParser(description="Wk3 LangGraph 实验（修复版）")
    parser.add_argument(
        "suite",
        nargs="?",
        default="all",
        choices=["all", "main", "lowq", "breaker", "checkpoint", "sqlite", "v1v3"],
        help="要跑哪一组实验",
    )
    args = parser.parse_args(argv)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "suite": args.suite,
        "quality_threshold": QUALITY_THRESHOLD,
        "sqlite_available": SQLITE_AVAILABLE,
    }

    if args.suite in ("all", "main"):
        payload["main"] = exp_main()
    if args.suite in ("all", "lowq"):
        payload["low_quality"] = exp_low_quality()
    if args.suite in ("all", "breaker"):
        payload["circuit_breaker"] = exp_circuit_breaker()
    if args.suite in ("all", "checkpoint"):
        payload["checkpoint"] = exp_checkpoint_recovery()
    if args.suite in ("all", "sqlite"):
        payload["sqlite"] = exp_sqlite_checkpointer()
    if args.suite in ("all", "v1v3"):
        payload["v1_vs_v3"] = exp_v1_vs_v3()

    payload["process_total"] = {
        "llm_calls": tracker.total_calls,
        "tokens": tracker.total_tokens,
        "cost_cny": round(tracker.estimated_cost(), 6),
        "cost_usd": round(tracker.estimated_cost_usd(), 6),
    }

    out_path = RESULTS_DIR / f"results_{args.suite}.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("结果 JSON 已保存: %s", out_path)

    print_summary(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
