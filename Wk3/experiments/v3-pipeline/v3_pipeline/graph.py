#!/usr/bin/env python3
"""V3 管线的图定义与运行封装。

**这里不重新实现图。** 节点、条件边、段间校验、质量门禁、反馈回路全部来自
`Wk3/experiments/langgraph-pipeline/langgraph_experiment.py`——那是图的唯一定义处，
经过了 12 组实验的验证。编码规范 §0.3 明确要求「不重复实现已有能力」，
把 700 行图定义抄一份到这里，只会得到两份会各自漂移的真相。

本模块负责的是**实验脚本不该操心、产品必须操心**的那部分：

* :class:`PipelineConfig` —— 一份显式的运行配置，取代实验脚本里散落的关键字参数
* :func:`run_pipeline` —— 跑一次图，返回结构化的 :class:`PipelineResult`
* :func:`to_knowledge_entry` —— 把图的最终 state 转成 `specs/issues/03-organizer.md`
  的知识条目 schema
* **落盘前必须过校验**——这是任务 2 那条原则在交付边界上的延伸：
  段间不许传坏数据，出口同样不许写坏数据

用法::

    from v3_pipeline.graph import PipelineConfig, run_pipeline
    result = run_pipeline(PipelineConfig(topic="AI agent", limit=5))
    print(result.quality_score, result.entry["id"])
"""

from __future__ import annotations

import logging
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
PACKAGE_ROOT = HERE.parent
REPO_ROOT = PACKAGE_ROOT.parents[2]
LANGGRAPH_DIR = REPO_ROOT / "Wk3" / "experiments" / "langgraph-pipeline"
V2_PIPELINE = REPO_ROOT / "Wk2" / "experiments" / "v2-pipeline"

for path in (str(V2_PIPELINE), str(LANGGRAPH_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)

import validate  # noqa: E402  —— 任务 2 的校验模块
from langgraph.checkpoint.memory import MemorySaver  # noqa: E402

import langgraph_experiment as lg  # noqa: E402
from quality import QUALITY_THRESHOLD  # noqa: E402

logger = logging.getLogger("v3-pipeline.graph")

#: 复用 model_client 的模块级 tracker —— 不新建实例，否则成本统计对不上
tracker = lg.tracker

#: 质量分 0-100 映射到 relevance_score 1-10 的分档边界
_SCORE_BUCKETS: tuple[tuple[int, int], ...] = (
    (95, 10), (85, 9), (75, 8), (65, 7), (60, 6), (45, 5), (30, 4), (15, 3), (1, 2),
)


@dataclass
class PipelineConfig:
    """一次 V3 运行的完整配置。

    Attributes:
        topic: 研究主题，同时决定文章方向与标签。
        limit: 每个 RSS 源采集几条。
        provider: LLM 提供商（deepseek / qwen / openai），None 表示按环境变量。
        model: 模型名覆盖，None 表示用提供商默认值。
        max_rewrites: 质量不达标时的重写次数上限（熔断阈值）。
        use_real_rss: 是否抓真实 RSS；False 时走 LLM 模拟，仅供离线冒烟。
        output_dir: 知识库根目录，产出写进它的 ``raw/`` 与 ``articles/``。
        dry_run: 只跑图不落盘，用于验证配置。
        strict: 出口校验失败时是否判运行失败（CI 用 True）。
    """

    topic: str = "AI agent"
    limit: int = 3
    provider: str | None = None
    model: str | None = None
    max_rewrites: int = 3
    use_real_rss: bool = True
    output_dir: Path = field(default_factory=lambda: REPO_ROOT / "knowledge")
    dry_run: bool = False
    strict: bool = True

    def slug(self) -> str:
        """把主题压成适合做文件名的 slug。

        Returns:
            只含小写字母、数字与连字符的短标识。
        """
        cleaned = "".join(
            ch.lower() if (ch.isalnum() and ch.isascii()) else "-" for ch in self.topic
        )
        parts = [p for p in cleaned.split("-") if p]
        return "-".join(parts)[:48] or "topic"


@dataclass
class PipelineResult:
    """一次 V3 运行的结果。

    Attributes:
        ok: 整体是否成功（图跑完 + 出口校验通过）。
        state: 图的最终 state。
        entry: 知识条目（组织成 organizer schema）；未产出时为空 dict。
        validation: 出口校验的 ``(passed, errors, warnings)``。
        written: 实际写出的文件路径。
        elapsed_seconds: 耗时。
        tokens: 本次运行消耗的 token。
        llm_calls: 本次运行的 LLM 调用次数。
        cost_cny: 本次运行的成本（元）。
        failure_reason: 失败原因；成功时为空串。
    """

    ok: bool
    state: dict[str, Any]
    entry: dict[str, Any]
    validation: tuple[bool, list[str], list[str]]
    written: list[str] = field(default_factory=list)
    elapsed_seconds: float = 0.0
    tokens: int = 0
    llm_calls: int = 0
    cost_cny: float = 0.0
    failure_reason: str = ""

    @property
    def quality_score(self) -> int:
        """最终质量分。"""
        return int(self.state.get("quality_score", 0))

    def as_dict(self) -> dict[str, Any]:
        """导出为可 JSON 序列化的 dict。"""
        passed, errors, warnings = self.validation
        return {
            "ok": self.ok,
            "failure_reason": self.failure_reason,
            "topic": self.state.get("topic", ""),
            "quality_score": self.quality_score,
            "quality_threshold": QUALITY_THRESHOLD,
            "score_history": self.state.get("score_history", []),
            "rewrite_count": self.state.get("rewrite_count", 0),
            "circuit_broken": self.state.get("circuit_broken", False),
            "collection_mode": self.state.get("collection_mode", ""),
            "sources": self.state.get("sources", []),
            "path": self.state.get("path", []),
            "segment_validation": self.state.get("validation_log", []),
            "exit_validation": {"passed": passed, "errors": errors, "warnings": warnings},
            "written": self.written,
            "elapsed_seconds": round(self.elapsed_seconds, 2),
            "tokens": self.tokens,
            "llm_calls": self.llm_calls,
            "cost_cny": round(self.cost_cny, 6),
            "entry": self.entry,
        }


def quality_to_relevance(score: int) -> int:
    """把 0-100 的质量分映射到 organizer schema 的 1-10 relevance_score。

    Args:
        score: 质量分。

    Returns:
        1-10 的整数。

    Examples:
        >>> quality_to_relevance(100)
        10
        >>> quality_to_relevance(0)
        1
    """
    for threshold, value in _SCORE_BUCKETS:
        if score >= threshold:
            return value
    return 1


def derive_tags(topic: str) -> list[str]:
    """从主题里挑出 1-3 个标签。

    组织条目的 ``tags`` 按 spec 03 是 1-3 个。这里用一张关键词表而不是再调一次
    LLM——标签是索引用的，不值得为它多花一次调用。

    Args:
        topic: 研究主题。

    Returns:
        1 到 3 个标签。
    """
    lowered = topic.lower()
    table = (
        ("agent", "agent"),
        ("langgraph", "langgraph"),
        ("rag", "rag"),
        ("llm", "llm"),
        ("mcp", "mcp"),
        ("多 agent", "multi-agent"),
        ("编排", "orchestration"),
        ("评估", "evaluation"),
        ("成本", "cost"),
    )
    tags = [tag for needle, tag in table if needle in lowered]
    if not tags:
        tags = ["ai"]
    return tags[:3]


def to_knowledge_entry(state: dict[str, Any], config: PipelineConfig) -> dict[str, Any]:
    """把图的最终 state 转成 `specs/issues/03-organizer.md` 的知识条目。

    ``summary`` 会截到 100 字——spec 03 的上限。截断而不是让它超标，是因为
    这个字段进的是知识库索引，长度失控会污染下游所有引用它的地方；
    完整摘要仍然完整保留在 ``analysis.full_summary`` 里，没有信息损失。

    Args:
        state: 图的最终 state。
        config: 运行配置。

    Returns:
        organizer schema 的条目 dict。
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    sources = [s for s in state.get("sources", []) if str(s).startswith("http")]
    summary = str(state.get("summary", "")).strip()
    key_points = [str(k) for k in state.get("key_points", []) if str(k).strip()]
    breakdown = state.get("quality_breakdown", {})

    return {
        "id": f"{today}-v3-{config.slug()}",
        "title": state.get("article_title") or f"V3 管线产出：{config.topic}",
        "source": "v3-pipeline",
        "source_url": sources[0] if sources else "https://github.com/trending",
        "collected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "summary": summary[:100],
        "analysis": {
            "tech_highlights": key_points[:3],
            "relevance_score": quality_to_relevance(int(state.get("quality_score", 0))),
            "score_reason": (
                f"质量分 {state.get('quality_score', 0)}/100（门槛 {QUALITY_THRESHOLD}），"
                f"重写 {state.get('rewrite_count', 0)} 次"
                f"{'，熔断放行' if state.get('circuit_broken') else ''}。"
                f"分项：{breakdown.get('avg_len', 0)} 字/条，空洞用语 "
                f"{breakdown.get('bad_hits', 0)} 次，具体性信号 {breakdown.get('good_hits', 0)} 个。"
            ),
            "full_summary": summary,
            "all_key_points": key_points,
            "article_body": state.get("article_body", ""),
        },
        "tags": derive_tags(config.topic),
        "status": "draft",
    }


def run_pipeline(config: PipelineConfig) -> PipelineResult:
    """跑一次完整的 V3 管线。

    流程：编译图 → invoke → 检查段间校验有没有中途终止 → 转知识条目 →
    出口校验 → 落盘。任一环节判失败都不写文件。

    Args:
        config: 运行配置。

    Returns:
        结构化的运行结果。
    """
    if config.provider:
        import os

        os.environ["LLM_PROVIDER"] = config.provider
    if config.model:
        import os

        os.environ["LLM_MODEL"] = config.model

    initial = lg.make_initial_state(
        config.topic,
        entry_mode="full",
        analyze_style="normal",
        use_real_rss=config.use_real_rss,
        max_rewrites=config.max_rewrites,
        rss_limit=config.limit,
    )

    graph = lg.build_pipeline_graph()
    app = graph.compile(checkpointer=MemorySaver())
    thread_id = f"v3-{config.slug()}-{int(time.time() * 1000)}"

    logger.info("=" * 70)
    logger.info("V3 管线 | topic=%s | limit=%d | provider=%s",
                config.topic, config.limit, config.provider or "（环境变量）")
    logger.info("thread_id=%s | 输出目录=%s | dry_run=%s",
                thread_id, config.output_dir, config.dry_run)
    logger.info("=" * 70)

    tokens0, calls0, cost0 = tracker.total_tokens, tracker.total_calls, tracker.estimated_cost()
    start = time.time()
    state = app.invoke(initial, config={"configurable": {"thread_id": thread_id}})
    elapsed = time.time() - start

    usage = {
        "elapsed_seconds": elapsed,
        "tokens": tracker.total_tokens - tokens0,
        "llm_calls": tracker.total_calls - calls0,
        "cost_cny": tracker.estimated_cost() - cost0,
    }

    # 段间校验中途终止：图走到了 abort，没有文章
    if state.get("validation_failed"):
        failures = [
            f"[{r['segment']}] {msg}"
            for r in state.get("validation_log", [])
            if not r["passed"]
            for msg in r["errors"]
        ]
        logger.error("段间校验未通过，不落盘。共 %d 条硬错误", len(failures))
        return PipelineResult(
            ok=False,
            state=state,
            entry={},
            validation=(False, failures, []),
            failure_reason="段间 schema 校验未通过",
            **usage,
        )

    entry = to_knowledge_entry(state, config)
    result = validate.validate_organizer(entry, validate.RELAXED_CONFIG)
    passed, errors, warnings = result

    for message in warnings:
        logger.warning("[出口校验] ⚠ %s", message)
    for message in errors:
        logger.error("[出口校验] ✗ %s", message)

    if not passed and config.strict:
        logger.error("出口校验未通过且 strict=True，不落盘")
        return PipelineResult(
            ok=False,
            state=state,
            entry=entry,
            validation=result,
            failure_reason="出口 schema 校验未通过",
            **usage,
        )

    written: list[str] = []
    if not config.dry_run:
        written = write_outputs(state, entry, config)

    logger.info("=" * 70)
    logger.info("完成 | 质量 %d/100 | 重写 %d 次 | %d 次调用 | %d tokens | ¥%.4f | %.1fs",
                state.get("quality_score", 0), state.get("rewrite_count", 0),
                usage["llm_calls"], usage["tokens"], usage["cost_cny"], elapsed)
    logger.info("路径: %s", " → ".join(state.get("path", [])))
    if written:
        logger.info("产出: %s", "、".join(written))
    logger.info("=" * 70)

    return PipelineResult(
        ok=True, state=state, entry=entry, validation=result, written=written, **usage
    )


def write_outputs(
    state: dict[str, Any], entry: dict[str, Any], config: PipelineConfig
) -> list[str]:
    """把采集快照、知识条目、文章正文写进知识库目录。

    Args:
        state: 图的最终 state。
        entry: 知识条目。
        config: 运行配置。

    Returns:
        写出的文件路径（相对仓库根）。
    """
    import json

    raw_dir = config.output_dir / "raw"
    articles_dir = config.output_dir / "articles"
    raw_dir.mkdir(parents=True, exist_ok=True)
    articles_dir.mkdir(parents=True, exist_ok=True)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    slug = config.slug()
    written: list[str] = []

    raw_path = raw_dir / f"v3-{today}-{slug}.json"
    raw_path.write_text(
        json.dumps(
            {
                "source": "v3-pipeline",
                "collected_at": entry["collected_at"],
                "topic": config.topic,
                "collection_mode": state.get("collection_mode", ""),
                "sources": state.get("sources", []),
                "raw_content": state.get("raw_content", ""),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    written.append(str(raw_path.relative_to(REPO_ROOT)))

    entry_path = articles_dir / f"{entry['id']}.json"
    entry_path.write_text(json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8")
    written.append(str(entry_path.relative_to(REPO_ROOT)))

    article_path = articles_dir / f"{entry['id']}.md"
    article_path.write_text(
        f"# {entry['title']}\n\n"
        f"> 主题: {config.topic}\n"
        f"> 质量评分: {state.get('quality_score', 0)}/100（门槛 {QUALITY_THRESHOLD}）"
        f"{' ⚡熔断放行' if state.get('circuit_broken') else ''}\n"
        f"> 评分轨迹: {state.get('score_history', [])} | 重写 {state.get('rewrite_count', 0)} 次\n"
        f"> 采集方式: {state.get('collection_mode', '')}\n"
        f"> 路径: {' → '.join(state.get('path', []))}\n\n"
        f"## 摘要\n\n{state.get('summary', '')}\n\n"
        f"## 关键要点\n\n"
        + ("\n".join(f"- {k}" for k in state.get("key_points", [])) or "- （无）")
        + f"\n\n## 正文\n\n{state.get('article_body', '')}\n\n"
        f"## 数据来源\n\n"
        + ("\n".join(f"- {s}" for s in state.get("sources", [])) or "- （无）")
        + "\n",
        encoding="utf-8",
    )
    written.append(str(article_path.relative_to(REPO_ROOT)))

    return written
