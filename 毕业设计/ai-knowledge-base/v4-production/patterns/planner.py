"""Planner 模式 —— re-export，主体实现在 :mod:`workflows.planner`。

**为什么有这个文件**：课件自身有一处不一致 ——

* 11-3 实操、12-4 步骤 7 目录树、12-4 步骤 9 自查清单都写 ``workflows/planner.py``
* 16-2（毕业项目完整性检查）唯独写 ``patterns/planner.py``

处理办法：主体放 ``workflows/planner.py``（它是图上的真实节点），
这里放三行 re-export。两处检查都能过，而且符合 ``patterns/`` 的定位 ——
装的是「可以脱离本项目单独讲的通用设计模式」。

Planner 模式的要点：**只规划不执行（Plan, don't execute）**。
它和 Plan-and-Execute 型 Agent 的区别是，后者自己拿着计划去跑工具；
这里的 Planner 只把策略写进共享状态，执行完全交给下游节点。
"""

from __future__ import annotations

from workflows.planner import (  # noqa: F401
    STRATEGY_TABLE,
    TARGET_COUNT_ENV,
    plan_strategy,
    planner_node,
)

__all__ = ["STRATEGY_TABLE", "TARGET_COUNT_ENV", "plan_strategy", "planner_node"]


if __name__ == "__main__":
    for count in (5, 15, 30):
        strategy = plan_strategy(count)
        print(f"target={count:>2} → {strategy['strategy']:<8} {strategy['rationale']}")
