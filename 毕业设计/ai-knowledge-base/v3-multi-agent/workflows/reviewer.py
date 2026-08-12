"""Reviewer Agent —— 质量审核节点（V3 流水线节点 ④，课件 11-1）。

核心原则：**只评估不修改（Evaluate, don't modify）**。
Reviewer 看到的是 Analyzer 输出的 ``analyses``，一个字都不改，只给分 + 反馈。
改内容是 Reviser 的事 —— 两个独立 Agent，避免「自己给自己打高分」。

评分口径（5 维加权，总权重 1.00）：

===================  ======  ========================================
维度                  权重     看什么
===================  ======  ========================================
summary_quality       25%     摘要是否说清「是什么 + 解决什么问题」
technical_depth       25%     有没有超出 README 复述的技术判断
relevance             20%     与「AI/LLM/Agent 技术动态」的相关度
originality           15%     有没有原创洞察，还是只是搬运
formatting            15%     字段完整、标签规范、无空洞用语
===================  ======  ========================================

**加权总分由 Python 重算，不采信模型算术**：模型算加权和的错误率远高于它
打分本身的噪声；把算术交给代码，模型只负责给 5 个维度分。

与 ``quality.py``（V1/V2 遗留的规则评分）的关系：规则评分看的是「摘要字数、
要点条数、空洞词命中」等**可数的形式特征**，稳定但打不出「有没有洞察」；
LLM 5 维加权能评价内容，代价是有采样噪声。两者保留做对照，
差异分析写在实验报告里。
"""

from __future__ import annotations

import json
import logging
import os
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

#: 本节点在成本报告里的名字
NODE_NAME = "review"

#: 5 维权重。写在代码里而不是 prompt 里 —— 调权重不用动 prompt，也不用重跑评测。
REVIEWER_WEIGHTS: dict[str, float] = {
    "summary_quality": 0.25,
    "technical_depth": 0.25,
    "relevance": 0.20,
    "originality": 0.15,
    "formatting": 0.15,
}

#: 通过线（0–10 量纲）。课件让你「临时改常量」来验证 revise / human_flag 分支，
#: 这里改成读环境变量 —— 验证分支不必动代码，也就不会忘了改回来：
#:     REVIEWER_PASS_THRESHOLD=9.0 python3 -m workflows.graph
REVIEWER_PASS_THRESHOLD = float(os.getenv("REVIEWER_PASS_THRESHOLD", "7.0"))

#: 只审前 N 条，控 token 消耗 —— 长上下文本身也会拉低审核质量
REVIEW_SAMPLE_SIZE = 5

#: 审核温度：低温保证同一份内容多次审核得到相近分数
REVIEWER_TEMPERATURE = 0.1

REVIEWER_SYSTEM = "你是严格但公正的知识库质量审核员。给出具体、可操作的反馈。只返回 JSON。"

REVIEW_PROMPT = """你是知识库质量审核员。请审核以下分析结果：

{sample}

请按以下维度评分（每项 1-10 分整数）：
1. summary_quality  - 摘要质量：是否说清「是什么 + 解决什么问题 + 与同类的差别」
2. technical_depth  - 技术深度：是否超出 README 复述，有具体技术判断
3. relevance        - 相关性：与「AI/LLM/Agent 技术动态」的贴合度
4. originality      - 原创性：是否有独立洞察，而非搬运描述
5. formatting       - 格式规范：字段完整、标签规范、无空洞用语

只返回 JSON：
{{
  "scores": {{
    "summary_quality": 8,
    "technical_depth": 6,
    "relevance": 9,
    "originality": 5,
    "formatting": 8
  }},
  "feedback": "具体的改进建议，点名最弱的维度该怎么改",
  "weak_dimensions": ["technical_depth", "originality"]
}}

当前是第 {round_no} 次审核（上限 {max_iterations} 次）。"""


def compute_weighted_score(scores: dict[str, Any]) -> float:
    """用 Python 重算 5 维加权总分（不采信模型算术）。

    缺失维度按 0 计入，这样「模型漏给一维」会体现为扣分而不是被忽略。

    Args:
        scores: 模型给的 ``{维度: 分数}``。

    Returns:
        0–10 量纲的加权总分，保留两位小数。

    Examples:
        >>> compute_weighted_score({"summary_quality": 8, "technical_depth": 8,
        ...                         "relevance": 8, "originality": 8, "formatting": 8})
        8.0
        >>> compute_weighted_score({"summary_quality": 10, "technical_depth": 10,
        ...                         "relevance": 10, "originality": 0, "formatting": 0})
        7.0
        >>> compute_weighted_score({})
        0.0
    """
    total = 0.0
    for dimension, weight in REVIEWER_WEIGHTS.items():
        try:
            value = float(scores.get(dimension, 0) or 0)
        except (TypeError, ValueError):
            value = 0.0
        total += max(0.0, min(10.0, value)) * weight
    return round(total, 2)


def review_node(state: KBState) -> dict:
    """LangGraph 节点 ④：对 analyses 做 5 维加权审核。

    审的是 ``analyses`` 而不是 ``articles`` —— articles 要等 organize 之后才存在，
    而审核的目的正是决定「要不要让它走到 organize」。

    Args:
        state: 当前 KBState，读 ``analyses`` / ``iteration`` / ``plan``。

    Returns:
        ``{"review_passed", "review_feedback", "iteration", "cost_tracker"}``。

    Raises:
        BudgetExceededError: 预算熔断时向上抛，中断流水线。
    """
    analyses = state.get("analyses", []) or []
    iteration = state.get("iteration", 0)
    tracker = state.get("cost_tracker", {})
    plan = state.get("plan", {}) or {}
    max_iterations = int(plan.get("max_iterations", 3))

    if not analyses:
        logger.info("[Reviewer] 没有条目需要审核，直接通过")
        return {
            "review_passed": True,
            "review_feedback": "没有条目需要审核",
            "iteration": iteration + 1,
            "cost_tracker": tracker,
        }

    sample = analyses[:REVIEW_SAMPLE_SIZE]
    prompt = REVIEW_PROMPT.format(
        sample=json.dumps(sample, ensure_ascii=False, indent=2),
        round_no=iteration + 1,
        max_iterations=max_iterations,
    )

    try:
        result, usage = chat_json(
            prompt,
            system=REVIEWER_SYSTEM,
            temperature=REVIEWER_TEMPERATURE,
            node_name=NODE_NAME,
        )
        tracker = accumulate_usage(tracker, usage)
    except BudgetExceededError:
        logger.error("[Reviewer] 预算熔断，审核中断")
        raise
    except Exception as exc:  # noqa: BLE001 - 审核是锦上添花，不能因它阻塞流水线
        logger.warning("[Reviewer] 审核 LLM 调用失败，自动通过：%s", exc)
        return {
            "review_passed": True,
            "review_feedback": f"审核 LLM 调用失败：{exc}，自动通过",
            "iteration": iteration + 1,
            "cost_tracker": tracker,
        }

    scores = result.get("scores", {}) if isinstance(result, dict) else {}
    weighted_total = compute_weighted_score(scores)
    passed = weighted_total >= REVIEWER_PASS_THRESHOLD

    feedback = str(result.get("feedback", "")).strip() if isinstance(result, dict) else ""
    weak_dims = result.get("weak_dimensions", []) if isinstance(result, dict) else []
    if weak_dims:
        feedback = f"[弱项: {', '.join(str(d) for d in weak_dims)}] {feedback}"
    feedback = (
        f"[加权总分 {weighted_total}/10 · 阈值 {REVIEWER_PASS_THRESHOLD}] "
        f"{feedback or '（模型未给出文字反馈）'}"
    )

    logger.info(
        "[Reviewer] 加权总分: %s/10, 通过: %s (第 %d 次审核 · 明细 %s)",
        weighted_total, passed, iteration + 1, scores,
    )

    return {
        "review_passed": passed,
        "review_feedback": feedback,
        "iteration": iteration + 1,
        "cost_tracker": tracker,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    print("=== 加权总分自测（纯 Python，不调 LLM）===")
    cases = [
        ({"summary_quality": 8, "technical_depth": 8, "relevance": 8,
          "originality": 8, "formatting": 8}, 8.0),
        ({"summary_quality": 10, "technical_depth": 10, "relevance": 10,
          "originality": 0, "formatting": 0}, 7.0),
        ({"summary_quality": 6, "technical_depth": 5, "relevance": 7,
          "originality": 4, "formatting": 6}, 5.65),
    ]
    for scores_in, expected in cases:
        got = compute_weighted_score(scores_in)
        status = "OK" if abs(got - expected) < 1e-9 else "FAIL"
        print(f"  [{status}] {scores_in} → {got}（期望 {expected}）")
        assert status == "OK"
    print(f"\n权重合计 = {sum(REVIEWER_WEIGHTS.values()):.2f}（应为 1.00）")
