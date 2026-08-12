#!/usr/bin/env python3
"""ReAct 循环 —— Wk3 第 11 节「自主规划」的补做（模式 B）。

标准 ReAct（Reasoning + Acting）：模型每一轮只想一步、做一步、看一眼结果，
再决定下一步。**没有计划这个东西**——与 :mod:`plan_execute` 的唯一结构差异就在这里。

    Thought → Action → Action Input → Observation → Thought → … → Final Answer

工具集、数据源、目标全部与 :mod:`plan_execute` 相同（都来自 :mod:`agent_tools`），
所以两边测出来的差异只可能来自「谁决定下一步、什么时候决定」。

实现上的两个取舍：

* **scratchpad 全量回填**。每轮把完整的 Thought/Action/Observation 历史重新塞进
  prompt。这是 ReAct 的标准做法，也是它 token 成本的来源——第 N 轮要为前 N-1 轮
  的观察重复付费。报告里的 token 对比主要就是在测这一条。
* **解析容错但不纠正**。模型写歪的 Action 名会被原样送进工具注册表并拿到
  `未知工具 'xxx'` 的报错，由它自己在下一轮 Thought 里读到并改。人不替它修。

用法::

    python react_loop.py                          # 用默认目标跑一次
    python react_loop.py --goal "..." --verbose
    python react_loop.py --max-iterations 12

产出：``results/react_run.json``（完整轨迹）+ 模型自己调 save_result 写的文章。
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

from agent_tools import (
    RESULTS_DIR,
    LLMError,
    ToolRegistry,
    TokenMeter,
    parse_json_reply,
    quick_chat,
)

logger = logging.getLogger("react-loop")

#: 与 plan_execute 共用的默认目标 —— 对照实验的前提是同题
from plan_execute import DEFAULT_GOAL  # noqa: E402

#: 循环轮数上限。ReAct 没有计划，也就没有天然的终点，上限是唯一的刹车。
DEFAULT_MAX_ITERATIONS = 12

#: 连续解析失败几次就中止（模型不按格式输出时的兜底）
MAX_PARSE_FAILURES = 3

REACT_SYSTEM = (
    "你是一个 ReAct Agent。你每次只想一步、做一步，看到结果后再想下一步。"
    "严格按给定格式输出，一次只输出一个 Action，不要一次列出多个动作，"
    "也不要自己编造 Observation。"
)

REACT_PROMPT = """目标：{goal}

可用工具（只能用这些，Action Input 必须是合法 JSON 且匹配签名）：
{tools}

严格按以下格式输出，**每次只输出到 Action Input 为止**，然后停下等我给你 Observation：

Thought: 我现在知道什么、还缺什么、因此下一步要做什么
Action: 工具名
Action Input: {{"参数": "值"}}

当你已经完成目标（文章写好并保存了）时，改成输出：

Thought: 收尾说明
Final Answer: 一段总结，说明你产出了什么、存在哪里、质量分是多少

注意：
- 你现在**不知道**快照里有哪些仓库，需要仓库名的工具必须先去查
- 如果 Observation 是 ERROR，读懂它然后换个做法，不要重复同样的错误调用
- 最多 {max_iterations} 轮，超了就强制结束，所以不要在探索上耗太多轮

{scratchpad}"""


@dataclass
class Turn:
    """ReAct 的一轮。

    Attributes:
        index: 第几轮。
        thought: 模型的推理。
        action: 工具名（Final Answer 轮为空）。
        action_input: 工具参数。
        observation: 工具返回。
        final_answer: 非空表示这一轮给出了最终答案。
        parse_ok: 模型输出是否符合格式。
        both_action_and_final: 同一轮里既写了 Action 又写了 Final Answer。
            这是判断「模型有没有真的想执行」与「解析器有没有吃掉动作」的关键证据，
            必须留痕，否则事后分不清是谁的问题。
        raw: 模型原始输出。
    """

    index: int
    thought: str = ""
    action: str = ""
    action_input: dict[str, Any] = field(default_factory=dict)
    observation: str = ""
    final_answer: str = ""
    parse_ok: bool = True
    both_action_and_final: bool = False
    raw: str = ""

    def as_dict(self) -> dict[str, Any]:
        """转成可 JSON 序列化的 dict。"""
        return {
            "index": self.index,
            "thought": self.thought,
            "action": self.action,
            "action_input": self.action_input,
            "observation": self.observation[:1500],
            "final_answer": self.final_answer,
            "parse_ok": self.parse_ok,
            "both_action_and_final": self.both_action_and_final,
            "raw": self.raw[:2500],
        }

    def render(self) -> str:
        """渲染进 scratchpad 的形式。

        既有 Action 又有 Final Answer 的那种轮次必须渲染成 **Action 分支**。
        早先的写法一见 ``final_answer`` 就走总结分支，把这一轮的 Action 和
        Observation 整个丢出了 scratchpad——模型下一轮看不到自己刚保存成功，
        于是反复重存了三次。那不是模型转不出来，是我把它的记忆删了。
        """
        if self.final_answer and not self.action:
            return f"Thought: {self.thought}\nFinal Answer: {self.final_answer}"

        rendered = (
            f"Thought: {self.thought}\n"
            f"Action: {self.action}\n"
            f"Action Input: {json.dumps(self.action_input, ensure_ascii=False)}\n"
            f"Observation: {self.observation}"
        )
        if self.final_answer:
            rendered += (
                "\n（注意：你上一轮在写 Action 的同时还写了 Final Answer，"
                "但那时动作尚未执行。以上 Observation 才是动作的真实结果。）"
            )
        return rendered


#: 解析 Thought/Action/Action Input/Final Answer 的正则
_THOUGHT_RE = re.compile(r"Thought\s*[:：]\s*(.+?)(?=\n\s*(?:Action|Final Answer)\s*[:：]|\Z)",
                         re.DOTALL)
_ACTION_RE = re.compile(r"Action\s*[:：]\s*([A-Za-z_][A-Za-z0-9_]*)")
_INPUT_RE = re.compile(r"Action\s*Input\s*[:：]\s*(.+?)(?=\n\s*(?:Observation|Thought)\s*[:：]|\Z)",
                       re.DOTALL)
_FINAL_RE = re.compile(r"Final\s*Answer\s*[:：]\s*(.+)", re.DOTALL)


def parse_react_output(text: str, index: int) -> Turn:
    """解析模型一轮的输出。

    刻意做成「能读多少读多少」：Action 名读出来就照原样送进工具注册表，
    哪怕它明显是编的。让模型自己在下一轮从 Observation 里看到 `未知工具`，
    是 ReAct 纠错能力的一部分，替它修掉就测不出来了。

    Args:
        text: 模型原始输出。
        index: 轮次序号。

    Returns:
        解析后的 Turn；``parse_ok=False`` 表示既没有 Action 也没有 Final Answer。
    """
    turn = Turn(index=index, raw=text or "")

    thought_match = _THOUGHT_RE.search(text or "")
    if thought_match:
        turn.thought = thought_match.group(1).strip()

    final_match = _FINAL_RE.search(text or "")
    action_match = _ACTION_RE.search(text or "")
    turn.both_action_and_final = bool(final_match and action_match)

    if final_match:
        # Action 优先于 Final Answer：一轮里两者都写了，说明模型还想执行动作，
        # 只是顺手把总结也写了。此时若认 Final Answer，就等于替它把动作吃掉，
        # 测出来的「宣称完成但没做」会是解析器造成的假象。
        if not action_match:
            turn.final_answer = final_match.group(1).strip()
            if not turn.thought:
                turn.thought = "（未给出 Thought）"
            return turn
        logger.warning(
            "[react #%d] 同一轮既有 Action 又有 Final Answer，按 Action 处理（证据留在 raw 里）",
            index,
        )
        turn.final_answer = final_match.group(1).strip()

    if not action_match:
        turn.parse_ok = False
        return turn
    turn.action = action_match.group(1).strip()

    input_match = _INPUT_RE.search(text or "")
    if input_match:
        turn.action_input = parse_json_reply(input_match.group(1))

    if not turn.thought:
        turn.thought = "（未给出 Thought）"
    return turn


def run(
    goal: str = DEFAULT_GOAL,
    *,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
) -> dict[str, Any]:
    """跑一次完整的 ReAct 循环。

    Args:
        goal: 高层目标。
        max_iterations: 循环轮数上限。

    Returns:
        完整结果 dict（可直接 JSON 序列化）。
    """
    registry = ToolRegistry()
    meter = TokenMeter()
    turns: list[Turn] = []
    scratchpad = ""
    parse_failures = 0
    finished_reason = ""
    start = time.time()

    logger.info("=" * 70)
    logger.info("ReAct | max_iterations=%d", max_iterations)
    logger.info("目标: %s", goal)
    logger.info("=" * 70)

    for index in range(1, max_iterations + 1):
        prompt = REACT_PROMPT.format(
            goal=goal,
            tools=registry.describe(),
            max_iterations=max_iterations,
            scratchpad=scratchpad,
        )

        try:
            text = quick_chat(prompt, system=REACT_SYSTEM, temperature=0.3, max_tokens=900)
        except LLMError as exc:
            finished_reason = f"第 {index} 轮 LLM 调用失败: {exc}"
            logger.error("[react] %s", finished_reason)
            break

        turn = parse_react_output(text, index)

        if not turn.parse_ok:
            parse_failures += 1
            logger.warning("[react #%d] 输出不符合格式（第 %d 次）: %s",
                           index, parse_failures, (text or "")[:150])
            turns.append(turn)
            if parse_failures >= MAX_PARSE_FAILURES:
                finished_reason = f"连续 {parse_failures} 轮输出不符合格式，中止"
                break
            scratchpad += (
                "\n\n（你上一轮的输出不符合格式，必须严格按 "
                "Thought / Action / Action Input 或 Thought / Final Answer 输出）"
            )
            continue

        parse_failures = 0
        logger.info("[react #%d] Thought: %s", index, turn.thought[:160])

        if turn.final_answer and not turn.action:
            logger.info("[react #%d] Final Answer: %s", index, turn.final_answer[:200])
            turns.append(turn)
            finished_reason = "模型给出 Final Answer"
            break

        logger.info("[react #%d] Action: %s(%s)", index, turn.action,
                    json.dumps(turn.action_input, ensure_ascii=False)[:140])
        result = registry.call(turn.action, turn.action_input)
        turn.observation = result.to_observation()
        turns.append(turn)

        scratchpad += ("\n\n" if scratchpad else "") + turn.render()

    if not finished_reason:
        finished_reason = f"触达轮数上限 {max_iterations}，未给出 Final Answer"
        logger.warning("[react] %s", finished_reason)

    elapsed = time.time() - start
    article = _extract_article(turns)

    payload: dict[str, Any] = {
        "mode": "react",
        "goal": goal,
        "iterations": len(turns),
        "action_turns": sum(1 for t in turns if t.action),
        "parse_failures": sum(1 for t in turns if not t.parse_ok),
        "finished_reason": finished_reason,
        "final_answer": next((t.final_answer for t in reversed(turns) if t.final_answer), ""),
        "failed_tool_calls": registry.failed_calls,
        "elapsed_seconds": round(elapsed, 2),
        "turns": [t.as_dict() for t in turns],
        "article": article,
        "tools": registry.as_dict(),
        **meter.as_dict(),
    }

    logger.info("=" * 70)
    logger.info(
        "完成 | %d 轮 | %d 次工具调用(%d 失败) | %d 次 LLM | %d tokens | ¥%.4f | %.1fs",
        payload["iterations"],
        registry.total_calls,
        registry.failed_calls,
        payload["llm_calls"],
        payload["tokens"],
        payload["cost_cny"],
        elapsed,
    )
    logger.info("结束原因: %s", finished_reason)
    logger.info("最终产出: %s（质量 %s）", article.get("title") or "（无）",
                article.get("quality_score", "—"))
    logger.info("=" * 70)
    return payload


def _extract_article(turns: list[Turn]) -> dict[str, Any]:
    """从轮次轨迹里回捞最终文章。

    与 :func:`plan_execute._extract_article` 同规则：取最后一次成功的
    ``draft_article`` 的正文与质量分，取最后一次成功的 ``save_result`` 的路径。
    两边必须用同一套口径，否则「产出质量」这一列没法比。

    Args:
        turns: 全部轮次。

    Returns:
        含 ``title`` / ``body`` / ``quality_score`` / ``saved_to`` 的 dict。
    """
    article: dict[str, Any] = {"title": "", "body": "", "quality_score": None, "saved_to": ""}

    for turn in turns:
        if not turn.observation or turn.observation.startswith("ERROR"):
            continue
        data = parse_json_reply(turn.observation) or {}
        if turn.action == "draft_article" and data.get("body"):
            article["title"] = data.get("title", "")
            article["body"] = data.get("body", "")
            article["quality_score"] = data.get("quality_score")
            article["quality_explain"] = data.get("quality_explain", "")
        elif turn.action == "save_result" and data.get("path"):
            article["saved_to"] = data["path"]

    return article


def main(argv: list[str] | None = None) -> int:
    """CLI 入口。

    Args:
        argv: 命令行参数，默认取 ``sys.argv[1:]``。

    Returns:
        退出码。
    """
    parser = argparse.ArgumentParser(description="ReAct 循环（Wk3 任务 1 模式 B）")
    parser.add_argument("--goal", default=DEFAULT_GOAL, help="高层目标")
    parser.add_argument("--max-iterations", type=int, default=DEFAULT_MAX_ITERATIONS,
                        help="循环轮数上限")
    parser.add_argument("--out", default="react_run.json", help="结果 JSON 文件名")
    parser.add_argument("--verbose", action="store_true", help="打印 DEBUG 日志")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)

    payload = run(args.goal, max_iterations=args.max_iterations)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS_DIR / args.out
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("结果已保存: %s", out_path)

    return 0 if payload["iterations"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
