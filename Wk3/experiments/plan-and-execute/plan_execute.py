#!/usr/bin/env python3
"""Plan-and-Execute 自主规划 —— Wk3 第 11 节「自主规划」的补做（模式 A）。

与 `langgraph-pipeline` 的根本差别：那边的图是**人写死的**，`decide_route` 是
硬编码 if/else，节点序列在编码期就固定了；这里**没有图**，执行序列由模型在
运行时产出，人只提供目标和工具清单。

三阶段循环::

    Plan      ── LLM 看目标 + 工具清单，产出 JSON 执行计划（每步：用哪个工具、
                 什么参数、为什么）
    Execute   ── 逐步执行。工具返回结构化结果或结构化错误，都写进观察记录
    Replan    ── 每步之后把「原计划 + 已发生的观察」交回 LLM，问它要不要改计划。
                 三种动作：continue（照原样走）/ revise（改剩余步骤）/ finish（提前收尾）

Replan 是这个模式的关键，也是最容易做成摆设的地方。为了让它真的有事可做，
本实现刻意**不做参数预校验**——模型写错的仓库名会真的打到工具上并拿到报错，
它得自己看懂 `ERROR: 给的 3 个仓库名一个都没匹配上` 然后决定补一步 `load_trending`。
这一步是不是发生了，在结果 JSON 的 ``replans`` 里可查。

用法::

    python plan_execute.py                       # 用默认目标跑一次
    python plan_execute.py --goal "..." --verbose
    python plan_execute.py --max-steps 8

产出：``results/plan_execute_run.json``（完整轨迹）+ 模型自己调 save_result 写的文章。
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent_tools import (
    RESULTS_DIR,
    LLMError,
    ToolRegistry,
    TokenMeter,
    parse_json_reply,
    quick_chat,
)

logger = logging.getLogger("plan-execute")

#: 本实验的默认目标。两种模式共用，写死在这里保证可对照。
DEFAULT_GOAL = (
    "帮我整理今日 GitHub Trending 中关于 AI Agent 的最重要趋势，"
    "最终产出一篇 300-500 字、面向 AI 开发者的技术短文，并存进 results/。"
)

#: 计划步数上限。超过就强制收尾——无上限的自主规划是账单事故。
DEFAULT_MAX_STEPS = 10

#: 连续失败几步就中止（避免在同一个错误上原地打转）
MAX_CONSECUTIVE_FAILURES = 3


@dataclass
class Step:
    """计划里的一步。

    Attributes:
        tool: 工具名。
        args: 调用参数。
        why: 模型给出的理由——这是「自主」留下的可审计痕迹，不是装饰。
        origin: 这一步是哪来的，``plan`` 表示初始计划，``replan#N`` 表示第 N 次重规划加的。
    """

    tool: str
    args: dict[str, Any]
    why: str = ""
    origin: str = "plan"

    def as_dict(self) -> dict[str, Any]:
        """转成可 JSON 序列化的 dict。"""
        return {"tool": self.tool, "args": self.args, "why": self.why, "origin": self.origin}


@dataclass
class Observation:
    """一步执行后的观察。

    Attributes:
        step: 执行的那一步。
        ok: 是否成功。
        text: 观察文本（成功是结果 JSON，失败是错误信息）。
    """

    step: Step
    ok: bool
    text: str

    def render(self, limit: int = 2000) -> str:
        """渲染进 replan prompt 的紧凑形式。

        限长给到 2000 是有原因的：``draft_article`` 的观察里带着完整正文，
        重规划要把这段正文原样填进 ``save_result`` 的 content。截短到几百字
        它就只能看见开头，只好自己编一句「文章内容」交差——首轮实测就是这么坏的。
        """
        body = self.text if len(self.text) <= limit else self.text[:limit] + "…"
        return f"[{'ok' if self.ok else 'FAIL'}] {self.step.tool}({json.dumps(self.step.args, ensure_ascii=False)[:150]})\n  → {body}"


@dataclass
class RunRecord:
    """一次完整运行的记录。

    Attributes:
        mode: 模式名，固定 ``plan-and-execute``。
        goal: 目标。
        initial_plan: 初始计划。
        executed: 实际执行序列。
        observations: 每步观察。
        replans: 每次重规划的决策记录。
        finished_reason: 结束原因。
    """

    mode: str = "plan-and-execute"
    goal: str = ""
    initial_plan: list[dict[str, Any]] = field(default_factory=list)
    executed: list[dict[str, Any]] = field(default_factory=list)
    observations: list[dict[str, Any]] = field(default_factory=list)
    replans: list[dict[str, Any]] = field(default_factory=list)
    finished_reason: str = ""


# ---------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------

PLANNER_SYSTEM = (
    "你是一个任务规划器。你不执行任何动作，只负责把一个高层目标拆成可执行的工具调用序列。"
    "你只能使用给定的工具，参数必须严格符合签名。只返回 JSON。"
)

PLANNER_PROMPT = """目标：{goal}

可用工具（只能用这些，参数必须匹配签名）：
{tools}

请产出一个执行计划，最多 {max_steps} 步。规划时注意：

- 第一步通常需要先把事实拿到手（你现在**并不知道**快照里有哪些仓库）
- analyze_repos / rank_repos 的 names 必须是**真实存在**的仓库全名，
  你还没看过数据，所以不要在计划里瞎猜仓库名——需要名字的步骤把 names 留成空数组，
  执行时会给你机会根据前面的观察补上
- 最后应当产出文章并保存

返回 JSON：
{{"reasoning": "整体思路，不超过 100 字",
  "steps": [{{"tool": "工具名", "args": {{...}}, "why": "这一步为什么必要，不超过 30 字"}}]}}

只返回 JSON。"""


def make_plan(goal: str, registry: ToolRegistry, max_steps: int) -> tuple[list[Step], str]:
    """让 LLM 产出初始执行计划。

    Args:
        goal: 高层目标。
        registry: 工具注册表（用于生成工具清单）。
        max_steps: 计划步数上限。

    Returns:
        ``(计划步骤列表, 模型给的整体思路)``。计划为空表示规划失败。
    """
    prompt = PLANNER_PROMPT.format(goal=goal, tools=registry.describe(), max_steps=max_steps)

    try:
        text = quick_chat(prompt, system=PLANNER_SYSTEM, temperature=0.3)
    except LLMError as exc:
        logger.error("[plan] 规划调用失败: %s", exc)
        return ([], f"规划失败: {exc}")

    data = parse_json_reply(text)
    raw_steps = data.get("steps") or []
    steps = [
        Step(
            tool=str(s.get("tool", "")),
            args=s.get("args") if isinstance(s.get("args"), dict) else {},
            why=str(s.get("why", "")),
            origin="plan",
        )
        for s in raw_steps
        if isinstance(s, dict)
    ][:max_steps]

    reasoning = str(data.get("reasoning", ""))
    logger.info("[plan] 产出 %d 步计划｜思路: %s", len(steps), reasoning)
    for i, step in enumerate(steps, 1):
        logger.info("[plan]   %d. %s(%s) — %s", i, step.tool,
                    json.dumps(step.args, ensure_ascii=False)[:100], step.why)
    return (steps, reasoning)


# ---------------------------------------------------------------------------
# Replan
# ---------------------------------------------------------------------------

REPLANNER_SYSTEM = (
    "你是一个计划修订器。给你原计划和已经发生的观察，你判断剩余步骤还合不合适。"
    "保守一点：没有明确理由就不要改计划。只返回 JSON。"
)

REPLANNER_PROMPT = """目标：{goal}

可用工具：
{tools}

已执行 {done} 步，观察如下：
{observations}

剩余计划：
{remaining}

请判断剩余计划还合不合适。三选一：

- "continue"：剩余计划没问题，照原样执行
- "revise"：剩余计划需要改（上一步报错要补救、需要插入新步骤、参数要用观察到的真实值填）
- "finish"：目标已经达成，剩下的步骤没必要跑了

**必须选 revise 的三种情况**（这三条是从实测失败里总结的，逐条对照）：

1. 上一步的 Observation 是 ERROR —— 给出修好的步骤
2. 剩余步骤里还有**空数组占位**（如 `"names": []`），而观察里已经有真实值了
3. 剩余步骤里还有**字面占位文本** —— 比如 `"content": "文章内容"`、
   `"points": ["趋势要点1", "趋势要点2"]`、`"evidence": "基于分析结果"`。
   计划是在你看到数据**之前**写的，这类占位符必然存在，必须用观察里的真实内容替换。
   `save_result` 的 `content` 尤其要注意：它必须是 draft_article 观察里那段完整正文，
   不是对正文的描述。

返回 JSON：
{{"action": "continue|revise|finish",
  "reason": "为什么，不超过 50 字",
  "steps": [{{"tool": "...", "args": {{...}}, "why": "..."}}]}}

action 为 revise 时 steps 是**替换后的完整剩余计划**；其他情况 steps 可以是空数组。
只返回 JSON。"""


def replan(
    goal: str,
    registry: ToolRegistry,
    observations: list[Observation],
    remaining: list[Step],
    round_no: int,
    max_steps: int,
) -> tuple[str, list[Step], str]:
    """让 LLM 决定是否调整剩余计划。

    Args:
        goal: 高层目标。
        registry: 工具注册表。
        observations: 迄今为止的观察。
        remaining: 剩余计划。
        round_no: 第几次重规划。
        max_steps: 步数上限，用于截断修订后的计划。

    Returns:
        ``(action, 新的剩余计划, 理由)``。action 取值 continue / revise / finish。
    """
    remaining_text = (
        "\n".join(
            f"{i}. {s.tool}({json.dumps(s.args, ensure_ascii=False)[:120]}) — {s.why}"
            for i, s in enumerate(remaining, 1)
        )
        or "（没有剩余步骤了）"
    )
    obs_text = "\n".join(o.render() for o in observations[-4:]) or "（还没有观察）"

    prompt = REPLANNER_PROMPT.format(
        goal=goal,
        tools=registry.describe(),
        done=len(observations),
        observations=obs_text,
        remaining=remaining_text,
    )

    try:
        text = quick_chat(prompt, system=REPLANNER_SYSTEM, temperature=0.2)
    except LLMError as exc:
        logger.warning("[replan#%d] 调用失败，按 continue 处理: %s", round_no, exc)
        return ("continue", remaining, f"重规划调用失败: {exc}")

    data = parse_json_reply(text)
    action = str(data.get("action", "continue")).strip().lower()
    reason = str(data.get("reason", ""))

    if action not in ("continue", "revise", "finish"):
        logger.warning("[replan#%d] 非法 action %r，按 continue 处理", round_no, action)
        return ("continue", remaining, f"非法 action {action!r}")

    if action != "revise":
        logger.info("[replan#%d] %s — %s", round_no, action, reason)
        return (action, remaining if action == "continue" else [], reason)

    new_steps = [
        Step(
            tool=str(s.get("tool", "")),
            args=s.get("args") if isinstance(s.get("args"), dict) else {},
            why=str(s.get("why", "")),
            origin=f"replan#{round_no}",
        )
        for s in (data.get("steps") or [])
        if isinstance(s, dict)
    ][:max_steps]

    logger.info("[replan#%d] revise：剩余 %d 步 → %d 步 — %s",
                round_no, len(remaining), len(new_steps), reason)
    for i, step in enumerate(new_steps, 1):
        logger.info("[replan#%d]   %d. %s(%s)", round_no, i, step.tool,
                    json.dumps(step.args, ensure_ascii=False)[:100])
    return ("revise", new_steps, reason)


# ---------------------------------------------------------------------------
# 主循环
# ---------------------------------------------------------------------------


def run(
    goal: str = DEFAULT_GOAL,
    *,
    max_steps: int = DEFAULT_MAX_STEPS,
    replan_enabled: bool = True,
) -> dict[str, Any]:
    """跑一次完整的 Plan-and-Execute。

    Args:
        goal: 高层目标。
        max_steps: 执行步数上限。
        replan_enabled: 关掉可以得到「纯静态计划」的对照组——这是判断
            重规划到底有没有价值的唯一办法。

    Returns:
        完整结果 dict（可直接 JSON 序列化）。
    """
    registry = ToolRegistry()
    meter = TokenMeter()
    record = RunRecord(goal=goal)
    start = time.time()

    logger.info("=" * 70)
    logger.info("Plan-and-Execute | replan=%s | max_steps=%d", replan_enabled, max_steps)
    logger.info("目标: %s", goal)
    logger.info("=" * 70)

    plan, reasoning = make_plan(goal, registry, max_steps)
    record.initial_plan = [s.as_dict() for s in plan]

    if not plan:
        record.finished_reason = "规划阶段没产出任何步骤"
        return _finalize(record, registry, meter, start, reasoning, 0)

    observations: list[Observation] = []
    remaining = list(plan)
    replan_rounds = 0
    consecutive_failures = 0

    while remaining and len(observations) < max_steps:
        step = remaining.pop(0)
        logger.info("[exec %d/%d] %s(%s)", len(observations) + 1, max_steps, step.tool,
                    json.dumps(step.args, ensure_ascii=False)[:140])

        result = registry.call(step.tool, step.args)
        obs = Observation(step=step, ok=result.ok, text=result.to_observation())
        observations.append(obs)
        record.executed.append(step.as_dict())
        record.observations.append({"step": step.as_dict(), "ok": obs.ok, "text": obs.text[:1500]})

        consecutive_failures = 0 if result.ok else consecutive_failures + 1
        if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
            record.finished_reason = f"连续 {consecutive_failures} 步失败，中止"
            logger.error("[exec] %s", record.finished_reason)
            break

        if not replan_enabled:
            continue
        if not remaining and result.ok:
            # 计划跑完且没出错，不必再问一次模型——省一次调用
            break

        replan_rounds += 1
        action, remaining, reason = replan(
            goal, registry, observations, remaining, replan_rounds, max_steps
        )
        record.replans.append(
            {
                "round": replan_rounds,
                "after_step": len(observations),
                "action": action,
                "reason": reason,
                "new_remaining": [s.as_dict() for s in remaining],
            }
        )
        if action == "finish":
            record.finished_reason = f"模型判定目标已达成：{reason}"
            break

    if not record.finished_reason:
        record.finished_reason = (
            "计划执行完毕" if not remaining else f"触达步数上限 {max_steps}"
        )

    return _finalize(record, registry, meter, start, reasoning, replan_rounds)


def _finalize(
    record: RunRecord,
    registry: ToolRegistry,
    meter: TokenMeter,
    start: float,
    reasoning: str,
    replan_rounds: int,
) -> dict[str, Any]:
    """把运行记录压成结果 dict。

    Args:
        record: 运行记录。
        registry: 工具注册表。
        meter: 计量器。
        start: 起始时刻。
        reasoning: 规划阶段的整体思路。
        replan_rounds: 重规划轮数。

    Returns:
        结果 dict。
    """
    elapsed = time.time() - start

    # 从工具轨迹里回捞最终产出——模型自己决定叫什么、存哪儿，这里只负责找到它
    article = _extract_article(record)

    payload: dict[str, Any] = {
        "mode": record.mode,
        "goal": record.goal,
        "planner_reasoning": reasoning,
        "initial_plan": record.initial_plan,
        "initial_plan_steps": len(record.initial_plan),
        "executed_steps": len(record.executed),
        "executed": record.executed,
        "observations": record.observations,
        "replan_rounds": replan_rounds,
        "replans": record.replans,
        "replan_revised": sum(1 for r in record.replans if r["action"] == "revise"),
        "finished_reason": record.finished_reason,
        "failed_tool_calls": registry.failed_calls,
        "elapsed_seconds": round(elapsed, 2),
        "article": article,
        "tools": registry.as_dict(),
        **meter.as_dict(),
    }

    logger.info("=" * 70)
    logger.info(
        "完成 | %d 步 | 重规划 %d 轮(改 %d 次) | %d 次 LLM | %d tokens | ¥%.4f | %.1fs",
        payload["executed_steps"],
        replan_rounds,
        payload["replan_revised"],
        payload["llm_calls"],
        payload["tokens"],
        payload["cost_cny"],
        elapsed,
    )
    logger.info("结束原因: %s", record.finished_reason)
    logger.info("最终产出: %s（质量 %s）", article.get("title") or "（无）",
                article.get("quality_score", "—"))
    logger.info("=" * 70)
    return payload


def _extract_article(record: RunRecord) -> dict[str, Any]:
    """从观察轨迹里回捞最终文章。

    Plan-and-Execute 不规定产出必须叫什么，所以这里按「最后一次成功的
    draft_article」取正文与质量分，按「最后一次成功的 save_result」取落盘路径。

    Args:
        record: 运行记录。

    Returns:
        含 ``title`` / ``body`` / ``quality_score`` / ``saved_to`` 的 dict。
    """
    article: dict[str, Any] = {"title": "", "body": "", "quality_score": None, "saved_to": ""}

    for entry in record.observations:
        if not entry["ok"]:
            continue
        tool = entry["step"]["tool"]
        data = parse_json_reply(entry["text"]) or {}
        if tool == "draft_article" and data.get("body"):
            article["title"] = data.get("title", "")
            article["body"] = data.get("body", "")
            article["quality_score"] = data.get("quality_score")
            article["quality_explain"] = data.get("quality_explain", "")
        elif tool == "save_result" and data.get("path"):
            article["saved_to"] = data["path"]

    return article


def main(argv: list[str] | None = None) -> int:
    """CLI 入口。

    Args:
        argv: 命令行参数，默认取 ``sys.argv[1:]``。

    Returns:
        退出码。
    """
    parser = argparse.ArgumentParser(description="Plan-and-Execute 自主规划（Wk3 任务 1 模式 A）")
    parser.add_argument("--goal", default=DEFAULT_GOAL, help="高层目标")
    parser.add_argument("--max-steps", type=int, default=DEFAULT_MAX_STEPS, help="执行步数上限")
    parser.add_argument("--no-replan", action="store_true",
                        help="关掉重规划，得到纯静态计划的对照组")
    parser.add_argument("--out", default="plan_execute_run.json", help="结果 JSON 文件名")
    parser.add_argument("--verbose", action="store_true", help="打印 DEBUG 日志")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)

    payload = run(args.goal, max_steps=args.max_steps, replan_enabled=not args.no_replan)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS_DIR / args.out
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("结果已保存: %s", out_path)

    return 0 if payload["executed_steps"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
