"""Analyzer Agent —— 分析节点（V3 流水线节点 ③，课件 10-2）。

对 ``state["sources"]`` 逐条调用 LLM，产出结构化分析：摘要、标签、相关度、
分类、一句话洞察。**只产出内容，不打质量分** —— 评分是 Reviewer 的唯一职责
（Wk3 实验 Bug #2 的教训：分析节点顺手算分，会在 revise 回流后被重算覆盖）。

``relevance_score`` 统一用 **0–1 浮点**（见 PLANNING §8.2 / D4 决策），
下游 organizer 用 ``plan.relevance_threshold`` 过滤。
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests.cost_guard import BudgetExceededError  # noqa: E402
from workflows.model_client import accumulate_usage, chat_json  # noqa: E402
from workflows.state import KBState  # noqa: E402

logger = logging.getLogger(__name__)

#: 本节点在成本报告里的名字（12-4 步骤 1.2：节点透传 node_name）
NODE_NAME = "analyze"

#: 允许的分类取值，与 AGENTS.md 的知识条目 schema 一致
VALID_CATEGORIES = ("llm", "agent", "rag", "multimodal", "tools", "industry")

#: 分析用的 system prompt 与温度
ANALYZER_SYSTEM = "你是一个技术内容分析 Agent。输出信息密度高的中文，严格只返回 JSON。"
ANALYZER_TEMPERATURE = 0.3

#: 单条分析的 prompt 模板
ANALYZE_PROMPT = """请分析以下技术项目，只返回 JSON。

项目名: {title}
链接: {url}
描述: {description}
Star 数: {stars}

返回格式：
{{
  "summary": "150 字以上中文摘要，说清它是什么、解决什么问题、和同类的差别",
  "key_insight": "一句话洞察（为什么值得关注）",
  "tags": ["3-5 个小写英文标签"],
  "category": "从 {categories} 里选一个",
  "relevance_score": 0.85
}}

要求：
- relevance_score 是 0-1 之间的浮点数，表示与「AI/LLM/Agent 技术动态」的相关度
- 严禁空洞用语：赋能、抓手、闭环、打通、对齐、颗粒度、生态、顶层设计
- 只返回 JSON，不要额外说明"""


def _normalize_score(raw: Any) -> float:
    """把模型给的相关度归一到 0–1。

    模型有时会返回 0–10 甚至 0–100，这里统一收口，避免下游阈值失效。

    Args:
        raw: 模型返回的 relevance_score。

    Returns:
        0–1 之间的浮点数；无法解析时返回 0.0。

    Examples:
        >>> _normalize_score(0.8)
        0.8
        >>> _normalize_score(8)
        0.8
        >>> _normalize_score(85)
        0.85
        >>> _normalize_score("bad")
        0.0
    """
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 0.0
    if value > 10:
        value /= 100
    elif value > 1:
        value /= 10
    return round(max(0.0, min(1.0, value)), 4)


def _normalize_category(raw: Any) -> str:
    """把模型给的分类收敛到白名单。

    Args:
        raw: 模型返回的 category。

    Returns:
        白名单内的分类；无法匹配时返回 ``"industry"``。

    Examples:
        >>> _normalize_category("Agent")
        'agent'
        >>> _normalize_category("不知道")
        'industry'
    """
    text = str(raw or "").strip().lower()
    if text in VALID_CATEGORIES:
        return text
    for candidate in VALID_CATEGORIES:
        if candidate in text:
            return candidate
    return "industry"


def analyze_node(state: KBState) -> dict:
    """LangGraph 节点 ③：逐条 LLM 分析。

    Args:
        state: 当前 KBState，读 ``sources`` 与 ``cost_tracker``。

    Returns:
        ``{"analyses": [...], "cost_tracker": {...}}`` 部分状态更新。

    Raises:
        BudgetExceededError: 预算熔断时**向上抛**，中断整条流水线 ——
            这正是 12-4 步骤 4.1 要看到的「中途被打断」。
    """
    sources = state.get("sources", []) or []
    tracker = state.get("cost_tracker", {})
    analyses: list[dict[str, Any]] = []

    for item in sources:
        prompt = ANALYZE_PROMPT.format(
            title=item.get("title", ""),
            url=item.get("url", ""),
            description=item.get("description", "") or "（无描述）",
            stars=item.get("stars", 0),
            categories="/".join(VALID_CATEGORIES),
        )
        try:
            result, usage = chat_json(
                prompt,
                system=ANALYZER_SYSTEM,
                temperature=ANALYZER_TEMPERATURE,
                node_name=NODE_NAME,
            )
            tracker = accumulate_usage(tracker, usage)
        except BudgetExceededError:
            logger.error("[Analyzer] 预算熔断，已完成 %d 条，中断分析", len(analyses))
            raise
        except Exception as exc:  # noqa: BLE001 - 单条失败不该拖垮整批
            logger.warning("[Analyzer] 分析失败: %s - %s", item.get("title", "?"), exc)
            analyses.append(
                {
                    **item,
                    "summary": f"分析失败：{exc}",
                    "key_insight": "",
                    "tags": [],
                    "category": "industry",
                    "relevance_score": 0.0,
                    "analysis_failed": True,
                }
            )
            continue

        if not isinstance(result, dict):
            result = {}

        analyses.append(
            {
                **item,
                "summary": str(result.get("summary", "")).strip(),
                "key_insight": str(result.get("key_insight", "")).strip(),
                "tags": [str(tag).lower() for tag in (result.get("tags") or [])][:5],
                "category": _normalize_category(result.get("category")),
                "relevance_score": _normalize_score(result.get("relevance_score")),
            }
        )

    logger.info("[Analyzer] 完成 %d 条分析", len(analyses))
    return {"analyses": analyses, "cost_tracker": tracker}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    from workflows.collector import collect_node
    from workflows.state import make_initial_state

    demo = make_initial_state(plan={"per_source_limit": 2})
    demo.update(collect_node(demo))  # type: ignore[typeddict-item]
    out = analyze_node(demo)
    print(json.dumps(out["analyses"], ensure_ascii=False, indent=2)[:1500])
