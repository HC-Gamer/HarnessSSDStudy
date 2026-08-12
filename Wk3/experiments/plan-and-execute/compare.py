#!/usr/bin/env python3
"""Plan-and-Execute vs ReAct 对照实验 —— Wk3 任务 1 的数据来源。

三个实验臂，同题、同工具、同数据源，唯一差异是「谁在什么时候决定下一步」：

============================  ==========================================
臂                            决策方式
============================  ==========================================
``plan-execute``              先出完整计划，每步后可重规划
``plan-execute-norep``        先出完整计划，**不许改**（消融组）
``react``                     不出计划，每轮只想一步
============================  ==========================================

第二个臂是关键。只跑前两个臂的话，看到的差异分不清是「有没有计划」造成的
还是「能不能改」造成的——Wk3 的 2×2 对照已经吃过一次这个亏，
只跑一格得出了误导性结论。

每个臂重复 ``--repeats`` 次。Wk3 EXPERIMENT_REPORT 残留问题 #5 明确写着
「单次运行，方差未量化」，这次不重蹈覆辙：报告里给区间，不给单点。

用法::

    python compare.py                      # 每臂 3 次
    python compare.py --repeats 1 --verbose
    python compare.py --arms react         # 只跑某一臂

产出：``results/comparison.json``（全部原始数据）+ 终端对照表。
"""

from __future__ import annotations

import argparse
import json
import logging
import statistics
import time
from typing import Any, Callable

import plan_execute
import react_loop
from agent_tools import RESULTS_DIR, tracker
from plan_execute import DEFAULT_GOAL

logger = logging.getLogger("compare")

#: 实验臂定义：名称 → (说明, 跑一次的函数)
ARMS: dict[str, tuple[str, Callable[[str], dict[str, Any]]]] = {
    "plan-execute": (
        "Plan-and-Execute（计划 + 重规划）",
        lambda goal: plan_execute.run(goal, replan_enabled=True),
    ),
    "plan-execute-norep": (
        "Plan-and-Execute（静态计划，消融组）",
        lambda goal: plan_execute.run(goal, replan_enabled=False),
    ),
    "react": (
        "ReAct（无计划，逐轮决策）",
        lambda goal: react_loop.run(goal),
    ),
}

#: 从单次运行结果里抽出来用于对照的指标
METRICS: tuple[tuple[str, str], ...] = (
    ("steps", "推理步数"),
    ("llm_calls", "LLM 调用"),
    ("tokens", "Token"),
    ("cost_cny", "成本 ¥"),
    ("quality_score", "质量分"),
    ("elapsed_seconds", "耗时 s"),
    ("failed_tool_calls", "工具报错"),
    ("saved", "落盘成功"),
)


def extract_metrics(payload: dict[str, Any]) -> dict[str, Any]:
    """把一次运行的结果压成统一口径的指标 dict。

    两种模式的「一步」定义必须对齐，否则步数没法比：
    Plan-and-Execute 的一步 = 执行了一个工具；ReAct 的一步 = 一轮 Thought/Action。
    ReAct 的最后一轮只给 Final Answer 不调工具，所以两边都按**工具调用次数**
    再记一列，避免口径争议。

    Args:
        payload: :func:`plan_execute.run` 或 :func:`react_loop.run` 的返回值。

    Returns:
        指标 dict。
    """
    article = payload.get("article") or {}
    return {
        "mode": payload.get("mode", ""),
        "steps": payload.get("executed_steps") or payload.get("iterations") or 0,
        "tool_calls": (payload.get("tools") or {}).get("total_calls", 0),
        "llm_calls": payload.get("llm_calls", 0),
        "tokens": payload.get("tokens", 0),
        "cost_cny": round(payload.get("cost_cny", 0.0), 6),
        "quality_score": article.get("quality_score"),
        "elapsed_seconds": payload.get("elapsed_seconds", 0.0),
        "failed_tool_calls": payload.get("failed_tool_calls", 0),
        "saved": bool(article.get("saved_to")),
        "saved_to": article.get("saved_to", ""),
        "article_chars": len(article.get("body") or ""),
        "finished_reason": payload.get("finished_reason", ""),
        "replan_rounds": payload.get("replan_rounds", 0),
        "replan_revised": payload.get("replan_revised", 0),
    }


def _aggregate(values: list[Any]) -> dict[str, Any]:
    """把一个指标的多次取值汇总成 min/median/max。

    Args:
        values: 多次运行的取值，可能含 None（如某次没产出文章）。

    Returns:
        含 ``n`` / ``min`` / ``median`` / ``max`` / ``values`` 的 dict。
    """
    numeric = [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
    if not numeric:
        # bool 指标（如 saved）按「成功几次」汇总
        bools = [v for v in values if isinstance(v, bool)]
        if bools:
            return {"n": len(bools), "ok": sum(bools), "values": bools}
        return {"n": 0, "values": values}

    return {
        "n": len(numeric),
        "min": min(numeric),
        "median": round(statistics.median(numeric), 4),
        "max": max(numeric),
        "values": numeric,
    }


def _fmt(agg: dict[str, Any]) -> str:
    """把汇总结果渲染成表格单元格。"""
    if "ok" in agg:
        return f"{agg['ok']}/{agg['n']}"
    if agg.get("n", 0) == 0:
        return "—"
    if agg["min"] == agg["max"]:
        value = agg["min"]
        return f"{value:.4f}" if isinstance(value, float) and value < 1 else f"{value:g}"
    lo, mid, hi = agg["min"], agg["median"], agg["max"]
    if isinstance(mid, float) and mid < 1:
        return f"{mid:.4f} ({lo:.4f}–{hi:.4f})"
    return f"{mid:g} ({lo:g}–{hi:g})"


def run_comparison(
    goal: str = DEFAULT_GOAL,
    *,
    arms: list[str] | None = None,
    repeats: int = 3,
) -> dict[str, Any]:
    """跑完整对照实验。

    Args:
        goal: 三个臂共用的目标。
        arms: 要跑哪些臂，默认全部。
        repeats: 每臂重复次数。

    Returns:
        含每次运行原始数据与汇总的 dict。
    """
    arms = arms or list(ARMS)
    started = time.time()
    tokens0, calls0, cost0 = tracker.total_tokens, tracker.total_calls, tracker.estimated_cost()

    runs: dict[str, list[dict[str, Any]]] = {}
    raw: dict[str, list[dict[str, Any]]] = {}

    for arm in arms:
        label, runner = ARMS[arm]
        runs[arm] = []
        raw[arm] = []
        for attempt in range(1, repeats + 1):
            logger.info("#" * 74)
            logger.info("# 臂 %s（%s）第 %d/%d 次", arm, label, attempt, repeats)
            logger.info("#" * 74)
            try:
                payload = runner(goal)
            except Exception as exc:  # noqa: BLE001 - 一次运行崩了不该毁掉整组对照
                logger.error("[%s#%d] 运行异常: %s", arm, attempt, exc)
                runs[arm].append({"mode": arm, "error": str(exc)})
                continue
            raw[arm].append(payload)
            runs[arm].append(extract_metrics(payload))

    summary: dict[str, dict[str, Any]] = {}
    for arm in arms:
        ok_runs = [r for r in runs[arm] if "error" not in r]
        summary[arm] = {
            key: _aggregate([r.get(key) for r in ok_runs]) for key, _ in METRICS
        }
        summary[arm]["tool_calls"] = _aggregate([r.get("tool_calls") for r in ok_runs])
        summary[arm]["article_chars"] = _aggregate([r.get("article_chars") for r in ok_runs])
        summary[arm]["successful_runs"] = len(ok_runs)

    return {
        "goal": goal,
        "repeats": repeats,
        "arms": arms,
        "arm_labels": {a: ARMS[a][0] for a in arms},
        "runs": runs,
        "summary": summary,
        "raw": raw,
        "total_elapsed_seconds": round(time.time() - started, 2),
        "total_tokens": tracker.total_tokens - tokens0,
        "total_llm_calls": tracker.total_calls - calls0,
        "total_cost_cny": round(tracker.estimated_cost() - cost0, 6),
    }


def print_table(payload: dict[str, Any]) -> None:
    """打印对照表。

    Args:
        payload: :func:`run_comparison` 的返回值。
    """
    arms = payload["arms"]
    summary = payload["summary"]

    print()
    print("=" * 92)
    print(f"  Plan-and-Execute vs ReAct 对照（每臂 {payload['repeats']} 次，中位数与区间）")
    print("=" * 92)
    print(f"  目标: {payload['goal']}")
    print("-" * 92)

    header = f"  {'指标':<12}" + "".join(f"{a:>26}" for a in arms)
    print(header)
    print("-" * 92)

    rows = list(METRICS) + [("tool_calls", "工具调用"), ("article_chars", "正文字数")]
    for key, label in rows:
        cells = "".join(f"{_fmt(summary[a].get(key, {})):>26}" for a in arms)
        print(f"  {label:<12}{cells}")

    print("-" * 92)
    for arm in arms:
        print(f"  {arm}: {payload['arm_labels'][arm]} | 成功 "
              f"{summary[arm]['successful_runs']}/{payload['repeats']} 次")
    print("-" * 92)
    print(f"  本次对照共 {payload['total_llm_calls']} 次 LLM 调用, "
          f"{payload['total_tokens']:,} tokens, ¥{payload['total_cost_cny']:.4f}, "
          f"{payload['total_elapsed_seconds']:.0f}s")
    print("=" * 92)


def main(argv: list[str] | None = None) -> int:
    """CLI 入口。

    Args:
        argv: 命令行参数，默认取 ``sys.argv[1:]``。

    Returns:
        退出码。
    """
    parser = argparse.ArgumentParser(description="Plan-and-Execute vs ReAct 对照（Wk3 任务 1）")
    parser.add_argument("--goal", default=DEFAULT_GOAL, help="三臂共用的目标")
    parser.add_argument("--arms", nargs="*", choices=sorted(ARMS), default=None,
                        help="只跑指定的臂，默认全部")
    parser.add_argument("--repeats", type=int, default=3, help="每臂重复次数")
    parser.add_argument("--out", default="comparison.json", help="结果 JSON 文件名")
    parser.add_argument("--verbose", action="store_true", help="打印 DEBUG 日志")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)

    payload = run_comparison(args.goal, arms=args.arms, repeats=args.repeats)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS_DIR / args.out
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("对照结果已保存: %s", out_path)

    print_table(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
