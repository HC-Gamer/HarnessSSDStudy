"""Planner Agent —— 动态规划节点（V3 流水线节点 ①，课件 11-3）。

核心原则：**只规划不执行（Plan, don't execute）**。

Planner 挂在图的最前面，输出一个 ``plan`` dict 写进 ``state["plan"]``，
下游 Collector / Organizer / Reviewer / 路由函数共同消费：

============  ========================  =================================
plan 字段      消费方                     作用
============  ========================  =================================
per_source_limit    collector.py         每个来源采集几条
relevance_threshold organizer.py         低分条目过滤线
max_iterations      graph.route_after_review  审核循环上限（不再硬编码 3）
============  ========================  =================================

三档策略由环境变量 ``PLANNER_TARGET_COUNT`` 切换（默认 10 → standard）。
Planner **不调 LLM** —— 规划规则是确定性的业务策略，用 LLM 既贵又不稳定；
这也是「只规划不执行」的另一层含义：规划本身要可预测、可复现。
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

#: 环境变量名：目标采集量，决定走哪一档策略
TARGET_COUNT_ENV = "PLANNER_TARGET_COUNT"

#: 默认目标采集量（对应 standard 档）
DEFAULT_TARGET_COUNT = 10

#: 档位切换阈值
FULL_THRESHOLD = 20
STANDARD_THRESHOLD = 10

#: 三档策略表（写成常量而不是散落的魔法数字，便于单测与调参）
STRATEGY_TABLE: dict[str, dict[str, Any]] = {
    "full": {
        "per_source_limit": 20,
        "relevance_threshold": 0.4,
        "max_iterations": 3,
        "rationale_tpl": "目标 {n} 条，启用深度模式（质量优先）",
    },
    "standard": {
        "per_source_limit": 10,
        "relevance_threshold": 0.5,
        "max_iterations": 2,
        "rationale_tpl": "目标 {n} 条，启用标准模式（平衡）",
    },
    "lite": {
        "per_source_limit": 5,
        "relevance_threshold": 0.7,
        "max_iterations": 1,
        "rationale_tpl": "目标 {n} 条，启用精简模式（成本优先）",
    },
}


def _read_target_count() -> int:
    """从环境变量读目标采集量，兼容 ``lite`` / ``standard`` / ``full`` 三个别名。

    课件写的是数字（``PLANNER_TARGET_COUNT=5``），但档位名更好记，
    两种写法都支持。

    Returns:
        目标采集量；无法解析时返回 :data:`DEFAULT_TARGET_COUNT`。
    """
    raw = os.getenv(TARGET_COUNT_ENV, str(DEFAULT_TARGET_COUNT)).strip().lower()

    alias = {"lite": 5, "standard": 10, "full": 30}
    if raw in alias:
        return alias[raw]

    try:
        return int(raw)
    except ValueError:
        logger.warning(
            "[Planner] %s=%r 无法解析为整数，回退到默认 %d", TARGET_COUNT_ENV, raw, DEFAULT_TARGET_COUNT
        )
        return DEFAULT_TARGET_COUNT


def plan_strategy(target_count: int | None = None) -> dict[str, Any]:
    """根据目标采集量选择策略档位。

    Args:
        target_count: 目标采集量；None 时读环境变量 ``PLANNER_TARGET_COUNT``。

    Returns:
        策略字典，含 strategy / per_source_limit / relevance_threshold /
        max_iterations / target_count / rationale。

    Examples:
        >>> plan_strategy(5)["strategy"]
        'lite'
        >>> plan_strategy(15)["strategy"]
        'standard'
        >>> plan_strategy(30)["strategy"]
        'full'
        >>> plan_strategy(30)["max_iterations"]
        3
    """
    if target_count is None:
        target_count = _read_target_count()

    if target_count >= FULL_THRESHOLD:
        name = "full"
    elif target_count >= STANDARD_THRESHOLD:
        name = "standard"
    else:
        name = "lite"

    spec = STRATEGY_TABLE[name]
    return {
        "strategy": name,
        "per_source_limit": spec["per_source_limit"],
        "relevance_threshold": spec["relevance_threshold"],
        "max_iterations": spec["max_iterations"],
        "target_count": target_count,
        "rationale": spec["rationale_tpl"].format(n=target_count),
    }


def planner_node(state: dict) -> dict:
    """LangGraph 节点 ①：把策略写入 ``state["plan"]``。

    Args:
        state: 当前 KBState（这里只读环境变量，不依赖上游字段）。

    Returns:
        ``{"plan": plan}`` 部分状态更新。
    """
    plan = plan_strategy()
    logger.info(
        "[Planner] 策略：%s · 每源限 %d 条 · 阈值 %.1f · 最大迭代 %d · %s",
        plan["strategy"],
        plan["per_source_limit"],
        plan["relevance_threshold"],
        plan["max_iterations"],
        plan["rationale"],
    )
    return {"plan": plan}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    print("=== Planner 三档策略 ===")
    for count in (5, 10, 15, 20, 30):
        plan = plan_strategy(count)
        print(
            f"  target={count:>2} → {plan['strategy']:<8} "
            f"per_source={plan['per_source_limit']:>2} "
            f"threshold={plan['relevance_threshold']} "
            f"max_iter={plan['max_iterations']}"
        )
    print(f"\n=== 当前环境（{TARGET_COUNT_ENV}={os.getenv(TARGET_COUNT_ENV, '未设置')}）===")
    planner_node({})
