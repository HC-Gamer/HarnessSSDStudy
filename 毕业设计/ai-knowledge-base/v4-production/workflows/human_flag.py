"""HumanFlag Agent —— 人工介入节点（V3 流水线节点 ⑦，课件 11-2）。

审核循环必须有出口。跑满 ``plan.max_iterations`` 还没通过，说明问题
多半不在「写得不好」而在「数据本身有问题」，再改也是浪费 token ——
这时把整批条目**落盘到 ``knowledge/pending_review/``** 交人工判断，
而不是静默丢弃，也不污染主知识库 ``knowledge/articles/``。

段间校验（``validate.py``）拦下的坏数据也走这里 —— 同一个异常终点，
落盘文件里用 ``reason`` 区分是「审核不过」还是「结构不合法」。
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import validate  # noqa: E402
from workflows.state import KBState  # noqa: E402

logger = logging.getLogger(__name__)

#: 待人工复核的落盘目录
PENDING_DIR = PROJECT_ROOT / "knowledge" / "pending_review"

#: 反馈在日志里截断的长度
FEEDBACK_PREVIEW_CHARS = 200


def _diagnose(state: KBState) -> tuple[str, list[str]]:
    """判定这批数据为什么走到人工兜底。

    两条来路：段间校验拦下的**结构问题**，和审核循环跑满的**质量问题**。
    校验闸门是路由函数、不写 state，所以这里重跑一次校验来取错误明细 ——
    校验是纯函数，重跑零成本且结果一致。

    Args:
        state: 当前 KBState。

    Returns:
        ``(reason, errors)``，reason 取
        ``validation_failed`` / ``review_not_passed``。
    """
    errors: list[str] = []
    for segment, checker in validate.V3_SEGMENT_VALIDATORS.items():
        passed, segment_errors, _ = checker(dict(state))
        if not passed:
            errors.extend(f"{segment}: {message}" for message in segment_errors)

    return ("validation_failed" if errors else "review_not_passed"), errors


def human_flag_node(state: KBState) -> dict:
    """LangGraph 节点 ⑦：兜底退出，把问题批次写进 pending_review/。

    Args:
        state: 当前 KBState，读 ``analyses`` / ``iteration`` / ``review_feedback``。

    Returns:
        ``{"needs_human_review": True}`` 部分状态更新。
    """
    analyses = state.get("analyses", []) or []
    iteration = state.get("iteration", 0)
    feedback = state.get("review_feedback", "")
    plan = state.get("plan", {}) or {}

    reason, validation_errors = _diagnose(state)

    if reason == "validation_failed":
        logger.warning("[HumanFlag] ⚠️ 段间校验未通过，%d 条硬错误，转人工", len(validation_errors))
    else:
        logger.warning("[HumanFlag] ⚠️ 达到 %d 次审核仍未通过，转人工", iteration)
    logger.warning("[HumanFlag] 最后反馈: %s", feedback[:FEEDBACK_PREVIEW_CHARS] or "（无）")

    PENDING_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M%S")
    filepath = PENDING_DIR / f"pending-{stamp}.json"

    payload: dict[str, Any] = {
        "timestamp": stamp,
        "reason": reason,
        "iterations_used": iteration,
        "max_iterations": plan.get("max_iterations"),
        "strategy": plan.get("strategy"),
        "last_feedback": feedback,
        "validation_errors": validation_errors,
        "item_count": len(analyses),
        "analyses": analyses,
    }
    with open(filepath, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)

    logger.warning("[HumanFlag] 已保存 %d 条到 %s", len(analyses), filepath)
    return {"needs_human_review": True}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    from workflows.state import make_initial_state

    demo = make_initial_state(
        analyses=[{"title": "demo", "summary": "自测条目"}],
        iteration=3,
        review_feedback="[加权总分 5.2/10] 摘要过于空洞",
        plan={"max_iterations": 3, "strategy": "standard"},
    )
    print(human_flag_node(demo))
