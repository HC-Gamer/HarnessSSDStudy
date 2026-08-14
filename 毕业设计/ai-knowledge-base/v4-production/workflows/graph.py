"""LangGraph 工作流图 —— V3 最终版 7 节点（课件 11-3 + 12-4 收尾接入）。

拓扑::

    ① plan → ② collect ─[闸门]→ ③ analyze ─[闸门]→ ④ review ┬─[pass]────→ ⑥ organize → END
                   │                    │                     │
                   └────────────────────┴─────────────────────┼─[fail<max]→ ⑤ revise → ④ review
                            （段间校验不过）                    │
                                   ↓                          └─[>=max]───→ ⑦ human_flag → END
                            ⑦ human_flag → END

七个节点，一个 Agent 一个文件：

=====  ============  ==========================  ===========================
节点    文件           职责                        终点类型
=====  ============  ==========================  ===========================
①      planner.py    动态规划三档策略              —
②      collector.py  采集 + 入口 sanitize_input    —
③      analyzer.py   逐条 LLM 分析                 —
④      reviewer.py   5 维加权审核（只评不改）       —
⑤      reviser.py    读反馈定向修改（只改不评）      —
⑥      organizer.py  整理 + PII 掩码 + 落盘        正常终点
⑦      human_flag.py 兜底落盘 pending_review/      异常终点
=====  ============  ==========================  ===========================

**加分项 —— 段间 schema 校验闸门**：``collect`` 与 ``analyze`` 之后各加一道
结构校验（复用项目根的 ``validate.py``）。坏数据在这里就被拦下走 human_flag，
而不是带着缺字段一路往下，让 Analyzer / Organizer 自己「编一个填上去」。
校验只管结构合法性，内容质量仍归 Reviewer —— 两者职责不重叠。
校验是**路由判断**不是节点，所以拓扑仍是 7 节点。

**12-4 收尾接入（接入点 ③）**：``__main__`` 里捕获
:class:`~tests.cost_guard.BudgetExceededError`，无论正常结束还是熔断，
都打印按节点分组的成本并写 ``knowledge/cost-report.json``。
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from langgraph.graph import END, StateGraph  # noqa: E402

import validate  # noqa: E402
from workflows.analyzer import analyze_node  # noqa: E402
from workflows.collector import collect_node  # noqa: E402
from workflows.human_flag import human_flag_node  # noqa: E402
from workflows.organizer import organize_node  # noqa: E402
from workflows.planner import planner_node  # noqa: E402
from workflows.reviewer import review_node  # noqa: E402
from workflows.reviser import revise_node  # noqa: E402
from workflows.state import KBState, make_initial_state  # noqa: E402

logger = logging.getLogger(__name__)

#: route_after_review 在 plan 缺失时的兜底迭代上限
DEFAULT_MAX_ITERATIONS = 3

#: 段间校验开关（``VALIDATE_SEGMENTS=0`` 可关掉，用于对照实验）
VALIDATE_SEGMENTS_ENV = "VALIDATE_SEGMENTS"


def segment_gate_enabled() -> bool:
    """段间校验闸门是否开启。

    Returns:
        True 表示开启（默认）。
    """
    return os.getenv(VALIDATE_SEGMENTS_ENV, "1").strip().lower() not in {"0", "false", "no"}


def _segment_passed(segment: str, state: KBState) -> bool:
    """跑一次段间校验并打日志。

    Args:
        segment: ``sources`` 或 ``analyses``。
        state: 当前 state。

    Returns:
        True 表示结构合法（或闸门被关闭）。
    """
    if not segment_gate_enabled():
        return True

    checker = validate.V3_SEGMENT_VALIDATORS[segment]
    passed, errors, warnings = checker(dict(state))

    for message in warnings:
        logger.warning("[Validate:%s] ⚠ %s", segment, message)

    if passed:
        logger.info("[Validate:%s] ✅ 结构校验通过（%d 条警告）", segment, len(warnings))
    else:
        logger.error("[Validate:%s] ❌ 结构校验未通过，%d 条硬错误：", segment, len(errors))
        for message in errors:
            logger.error("[Validate:%s]    ✗ %s", segment, message)

    return passed


# ---------------------------------------------------------------------------
# 路由函数
# ---------------------------------------------------------------------------


def route_after_collect(state: KBState) -> str:
    """采集后的闸门：结构不合法直接转人工，不浪费 analyze 的 token。

    Args:
        state: 当前 state。

    Returns:
        ``"analyze"`` 或 ``"human_flag"``。
    """
    return "analyze" if _segment_passed("sources", state) else "human_flag"


def route_after_analyze(state: KBState) -> str:
    """分析后的闸门：结构不合法直接转人工，不让坏数据进审核循环。

    Args:
        state: 当前 state。

    Returns:
        ``"review"`` 或 ``"human_flag"``。
    """
    return "review" if _segment_passed("analyses", state) else "human_flag"


def route_after_review(state: KBState) -> str:
    """审核后的 3 路条件路由。

    迭代上限读 ``plan.max_iterations``，不再硬编码 3 —— 这正是 Planner
    存在的意义：策略参数集中在一个地方，节点和路由都只是消费者。

    Args:
        state: 当前 state。

    Returns:
        ``"organize"``（通过）/ ``"revise"``（打回重改）/
        ``"human_flag"``（超轮次兜底）。

    Examples:
        >>> route_after_review({"review_passed": True})
        'organize'
        >>> route_after_review({"review_passed": False, "iteration": 1,
        ...                     "plan": {"max_iterations": 2}})
        'revise'
        >>> route_after_review({"review_passed": False, "iteration": 2,
        ...                     "plan": {"max_iterations": 2}})
        'human_flag'
    """
    plan = state.get("plan", {}) or {}
    max_iterations = int(plan.get("max_iterations", DEFAULT_MAX_ITERATIONS))
    iteration = state.get("iteration", 0)

    if state.get("review_passed", False):
        return "organize"
    if iteration >= max_iterations:
        return "human_flag"
    return "revise"


# ---------------------------------------------------------------------------
# 图组装
# ---------------------------------------------------------------------------


def build_graph() -> StateGraph:
    """组装 V3 的 7 节点工作流。

    Returns:
        未编译的 :class:`StateGraph`。
    """
    graph = StateGraph(KBState)

    graph.add_node("plan", planner_node)
    graph.add_node("collect", collect_node)
    graph.add_node("analyze", analyze_node)
    graph.add_node("review", review_node)
    graph.add_node("revise", revise_node)
    graph.add_node("organize", organize_node)
    graph.add_node("human_flag", human_flag_node)

    graph.add_edge("plan", "collect")

    # 加分项：两道段间校验闸门（不新增节点，只是条件边）
    graph.add_conditional_edges(
        "collect",
        route_after_collect,
        {"analyze": "analyze", "human_flag": "human_flag"},
    )
    graph.add_conditional_edges(
        "analyze",
        route_after_analyze,
        {"review": "review", "human_flag": "human_flag"},
    )

    # 课件核心：审核后的 3 路条件边
    graph.add_conditional_edges(
        "review",
        route_after_review,
        {
            "organize": "organize",
            "revise": "revise",
            "human_flag": "human_flag",
        },
    )

    # revise 回到 review 形成闭环
    graph.add_edge("revise", "review")

    # 两个终点
    graph.add_edge("organize", END)
    graph.add_edge("human_flag", END)

    graph.set_entry_point("plan")
    return graph


#: 编译后的应用，供 ``from workflows.graph import app`` 直接使用
app = build_graph().compile()


def run(initial_state: KBState | None = None) -> dict[str, Any]:
    """跑一次完整工作流。

    Args:
        initial_state: 初始状态；None 时用 :func:`make_initial_state`。

    Returns:
        最终状态字典。

    Raises:
        BudgetExceededError: 预算熔断（调用方负责捕获并打报告）。
    """
    return app.invoke(initial_state or make_initial_state())


def _finish(guard: Any) -> None:
    """★ 12-4 接入点 ③ —— 收尾打成本报告并落盘。

    Args:
        guard: 全局 CostGuard 实例。
    """
    report = guard.get_report()
    print(
        f"\n[CostGuard] 总调用 {report['total_calls']} 次 · "
        f"总成本 ¥{report['total_cost_yuan']} / 预算 ¥{report['budget_yuan']}"
    )
    print(f"[CostGuard] 按节点：{report['cost_by_node']}")
    guard.save_report()


def main() -> int:
    """CLI 入口：跑一次工作流并打成本报告。

    Returns:
        退出码：正常 0，熔断 2。
    """
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    # 传输层日志压到 WARNING —— 节点日志才是这条流水线要看的东西
    for noisy in ("httpx", "httpcore", "pipeline.model_client"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    from workflows.model_client import BudgetExceededError, get_cost_guard

    print("=" * 60)
    print("AI 知识库 V3 —— LangGraph 7 节点工作流启动")
    print("=" * 60)

    exit_code = 0
    try:
        final_state = run()
        print("\n=== 工作流完成 ===")
        print(
            f"  采集 {len(final_state.get('sources', []))} 条 · "
            f"分析 {len(final_state.get('analyses', []))} 条 · "
            f"入库 {len(final_state.get('articles', []))} 条 · "
            f"审核轮次 {final_state.get('iteration', 0)} · "
            f"待人工 {final_state.get('needs_human_review', False)}"
        )
    except BudgetExceededError as exc:
        print(f"\n[FATAL] 预算熔断触发：{exc}")
        print("[FATAL] 流水线已中断，未产出 organize / 落盘结果")
        exit_code = 2

    _finish(get_cost_guard())
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
