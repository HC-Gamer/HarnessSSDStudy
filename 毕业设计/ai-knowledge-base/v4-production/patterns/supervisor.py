"""Supervisor 模式 —— Worker 执行 + Supervisor 审核 + 反馈修正循环（课件 9-2）。

设计要点：

* **职责隔离** —— Worker 只执行，Supervisor 只审核。同一个 Agent 既写又评，
  等于让它给自己的作业打分；
* **结构化反馈** —— 审核输出 ``{passed, score, feedback}``，Worker 拿到的是
  「哪里不行、该怎么改」，而不是笼统的「重做一遍」。带反馈重做 ≠ 盲目重试；
* **审核低温**（``temperature=0.2``）—— 审核要的是一致性，不是创造力；
* **强制出口** —— 最多 3 轮，到顶就带 ``warning`` 返回，绝不无限循环。

这个模式和 V3 工作流里的 Reviewer/Reviser 是同一个思想的两种形态：
这里是**函数内的循环**，那里是**图上的条件边闭环**。

运行::

    python3 -m patterns.supervisor
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

from workflows.model_client import chat  # noqa: E402
from workflows.model_client import parse_json_reply  # noqa: E402

logger = logging.getLogger(__name__)

#: 成本报告里的节点名
WORKER_NODE = "supervisor:worker"
SUPERVISOR_NODE = "supervisor:reviewer"

#: 默认最大轮次 —— 3 轮之内改不好，多半是任务本身有问题，再改是浪费
DEFAULT_MAX_RETRIES = 3

#: 通过线（1-10 总分）
PASS_SCORE = 7

#: 审核温度：低温保证同一份内容多次审核得分接近
SUPERVISOR_TEMPERATURE = 0.2

WORKER_SYSTEM = """你是 AI 技术分析师。请按要求完成分析任务。
只返回 JSON，包含三个字段：summary（中文摘要）、key_points（要点数组）、
recommendation（一句话建议）。"""

SUPERVISOR_SYSTEM = """你是质量审核专家。请审核以下分析报告。

评分维度（每维度 1-10）：
1. 准确性：信息是否准确无误
2. 深度：分析是否有洞察力，而非泛泛而谈
3. 格式：是否符合 JSON 规范，字段齐全、结构清晰

只返回 JSON（score 是 1-10 的**总体评价**，不是三个维度相加）：
{"passed": true/false, "score": 8, "feedback": "具体改进建议",
 "dimension_scores": {"accuracy": 8, "depth": 6, "format": 9}}"""

REVISION_PROMPT = """原始任务: {task}

上次产出:
{previous}

审核反馈:
{feedback}

请针对反馈定向改进，保持相同的 JSON 字段结构。"""


def _run_worker(task: str, previous: str | None, feedback: str) -> str:
    """跑一轮 Worker。

    Args:
        task: 原始任务描述。
        previous: 上一轮产出；None 表示第一轮。
        feedback: 上一轮的审核反馈。

    Returns:
        Worker 的输出文本。
    """
    if previous is None:
        prompt = task
    else:
        prompt = REVISION_PROMPT.format(task=task, previous=previous, feedback=feedback)
    text, _ = chat(prompt, system=WORKER_SYSTEM, node_name=WORKER_NODE)
    return text


#: 三个评分维度，用于在 Python 侧重算总分
SCORE_DIMENSIONS = ("accuracy", "depth", "format")


def normalize_score(review: dict[str, Any]) -> int:
    """把审核结果的总分收敛到 1-10。

    实测坑：让模型「给一个 1-10 的总分」时，它经常把三个维度**加起来**
    返回 26/10。和 Reviewer 一样的教训 —— **算术交给代码**，模型只负责
    给维度分。有维度分就按维度分取平均，没有才退回它自报的总分。

    Args:
        review: 审核返回的 JSON。

    Returns:
        1-10 之间的整数。

    Examples:
        >>> normalize_score({"score": 26, "dimension_scores":
        ...                  {"accuracy": 9, "depth": 7, "format": 10}})
        9
        >>> normalize_score({"score": 8})
        8
        >>> normalize_score({"score": 26})
        10
    """
    dimensions = review.get("dimension_scores") or {}
    values = [
        float(dimensions[name])
        for name in SCORE_DIMENSIONS
        if isinstance(dimensions.get(name), (int, float))
    ]
    raw = sum(values) / len(values) if values else float(review.get("score", 0) or 0)
    return int(round(max(0.0, min(10.0, raw))))


def _run_supervisor(worker_output: str) -> dict[str, Any]:
    """跑一轮 Supervisor 审核。

    Args:
        worker_output: Worker 的产出。

    Returns:
        ``{"passed": bool, "score": int, "feedback": str, ...}``；
        解析失败时返回一个「不通过」的兜底结果。
    """
    text, _ = chat(
        f"请审核以下分析报告：\n{worker_output}",
        system=SUPERVISOR_SYSTEM,
        temperature=SUPERVISOR_TEMPERATURE,
        node_name=SUPERVISOR_NODE,
    )
    review = parse_json_reply(text)
    if not isinstance(review, dict) or "score" not in review:
        return {"passed": False, "score": 0, "feedback": "审核输出格式错误，无法解析评分"}

    review["score"] = normalize_score(review)
    # passed 也由代码判定 —— 不让模型的自我感觉盖过分数线
    review["passed"] = review["score"] >= PASS_SCORE
    return review


def supervisor(task: str, max_retries: int = DEFAULT_MAX_RETRIES) -> dict[str, Any]:
    """监督模式：Worker 产出 → Supervisor 评分 → 带反馈重做，最多 N 轮。

    Args:
        task: 分析任务描述。
        max_retries: 最大轮次，默认 3。

    Returns:
        ``{"output": str, "attempts": int, "final_score": int,
        "history": [...], "warning": str|None}``。

    Examples:
        >>> DEFAULT_MAX_RETRIES
        3
    """
    worker_output = ""
    feedback = ""
    score = 0
    history: list[dict[str, Any]] = []

    for attempt in range(1, max_retries + 1):
        worker_output = _run_worker(task, None if attempt == 1 else worker_output, feedback)

        try:
            review = _run_supervisor(worker_output)
        except Exception as exc:  # noqa: BLE001 - 审核挂了不该丢掉 Worker 的产出
            logger.warning("[Supervisor] 第 %d 轮审核调用失败：%s", attempt, exc)
            review = {"passed": False, "score": 0, "feedback": f"审核调用失败: {exc}"}

        score = int(review.get("score", 0) or 0)
        feedback = str(review.get("feedback", "请提高分析深度与准确性"))
        history.append({"attempt": attempt, "score": score, "feedback": feedback})

        logger.info(
            "  第 %d 轮审核: 得分 %d/10 · 明细 %s",
            attempt, score, review.get("dimension_scores", {}),
        )

        if review.get("passed", False) or score >= PASS_SCORE:
            return {
                "output": worker_output,
                "attempts": attempt,
                "final_score": score,
                "history": history,
                "warning": None,
            }

    return {
        "output": worker_output,
        "attempts": max_retries,
        "final_score": score,
        "history": history,
        "warning": f"达到最大重试次数({max_retries})，可能质量不达标",
    }


def _demo() -> int:
    """跑一次监督循环演示。

    Returns:
        0 表示循环在 max_retries 之内正常退出。
    """
    print("=" * 60)
    print("Supervisor 监督模式演示（最多 3 轮）")
    print("=" * 60)

    result = supervisor("请分析 LangGraph 框架的优缺点和适用场景")

    print("\n最终结果:")
    print(f"  审核轮次: {result['attempts']}（上限 {DEFAULT_MAX_RETRIES}）")
    print(f"  最终得分: {result['final_score']}/10")
    if result.get("warning"):
        print(f"  警告: {result['warning']}")
    print(f"  评分轨迹: {[h['score'] for h in result['history']]}")
    print(f"  输出预览: {result['output'][:200]}...")

    assert result["attempts"] <= DEFAULT_MAX_RETRIES, "循环必须在 3 轮内退出"
    print(f"\n[OK] 循环在 {result['attempts']} 轮内退出，未超过上限")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    raise SystemExit(_demo())
