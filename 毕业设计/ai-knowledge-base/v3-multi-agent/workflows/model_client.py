"""统一模型客户端 —— V3 工作流的唯一 LLM 出口（课件 10-2 + 12-4 接入点 ①②）。

本模块**不重复实现** HTTP 调用与重试退避，而是复用 V2 已经跑了一个月的
``pipeline/model_client.py``（AGENTS.md §5.2 第 1 条：不重复实现已有能力）。
在它之上补两件 V3 才需要的事：

1. 把返回值统一成课件约定的 ``(text, usage_dict)`` 二元组，并提供
   :func:`chat_json` 与 :func:`accumulate_usage`；
2. **接入 CostGuard**（12-4 接入点 ①②）—— 每次 LLM 调用后自动
   ``record()`` 记账、``check()`` 检查预算，超预算抛
   :class:`~tests.cost_guard.BudgetExceededError` 熔断整条调用链。

为什么记账埋在这里而不是每个节点里：这是 **AOP（面向切面）**。节点是业务代码，
写节点的人不该关心记账；所有 LLM 调用强制走同一个出口，一行不漏。
副作用是节点看不见 cost_guard，但换模型 / 换计费时不用动任何节点。
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

#: 项目根目录（workflows/ 的上一级），保证 ``pipeline`` / ``tests`` 可导入
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

from pipeline.model_client import (  # noqa: E402
    LLMError,
    Usage,
    get_provider,
    tracker as v2_tracker,
)
from tests.cost_guard import BudgetExceededError, CostGuard  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")

logger = logging.getLogger(__name__)

__all__ = [
    "BudgetExceededError",
    "LLMError",
    "accumulate_usage",
    "chat",
    "chat_json",
    "get_cost_guard",
    "parse_json_reply",
    "reset_cost_guard",
]

#: 默认 system prompt
DEFAULT_SYSTEM = "你是一个专业的 AI 技术分析师。"

#: 默认采样温度与输出上限（节点可覆盖）
DEFAULT_TEMPERATURE = 0.3
DEFAULT_MAX_TOKENS = 2000


# ---------------------------------------------------------------------------
# CostGuard 全局实例（12-4 接入点 ①）
# ---------------------------------------------------------------------------

_cost_guard: CostGuard | None = None


def get_cost_guard() -> CostGuard:
    """返回进程级 CostGuard 单例（懒加载，一次运行共享一个）。

    预算与预警阈值从环境变量读取，便于 ``BUDGET_YUAN=0.001 python3 -m
    workflows.graph`` 这类熔断验证。

    Returns:
        全局唯一的 :class:`~tests.cost_guard.CostGuard`。
    """
    global _cost_guard
    if _cost_guard is None:
        _cost_guard = CostGuard(
            budget_yuan=float(os.getenv("BUDGET_YUAN", "1.0")),
            alert_threshold=float(os.getenv("BUDGET_ALERT", "0.8")),
        )
        logger.info(
            "[CostGuard] 初始化：预算 ¥%.4f · 预警阈值 %.0f%%",
            _cost_guard.budget_yuan,
            _cost_guard.alert_threshold * 100,
        )
    return _cost_guard


def reset_cost_guard() -> None:
    """丢弃全局 CostGuard（单测用，避免用例之间互相污染）。"""
    global _cost_guard
    _cost_guard = None


# ---------------------------------------------------------------------------
# 供应商实例缓存
# ---------------------------------------------------------------------------

_provider = None


def _get_cached_provider(model: str | None):
    """复用同一个 provider 实例，避免每次调用都重建配置。

    Args:
        model: 模型名覆盖；传入不同模型时会重建。

    Returns:
        ``pipeline.model_client.LLMProvider`` 实例。
    """
    global _provider
    if _provider is None or (model and _provider.model != model):
        _provider = get_provider(model=model)
    return _provider


# ---------------------------------------------------------------------------
# 核心调用
# ---------------------------------------------------------------------------


def chat(
    prompt: str,
    system: str = DEFAULT_SYSTEM,
    model: str | None = None,
    temperature: float = DEFAULT_TEMPERATURE,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    node_name: str = "unknown",
) -> tuple[str, dict[str, int]]:
    """调用 LLM，并自动记账 + 预算检查。

    Args:
        prompt: 用户 prompt。
        system: system prompt。
        model: 模型名覆盖，None 时用 ``LLM_MODEL`` 或提供商默认模型。
        temperature: 采样温度。
        max_tokens: 最大输出 token 数。
        node_name: 调用所在节点名，用于按节点分组的成本报告。

    Returns:
        ``(text, usage)``，usage 形如
        ``{"prompt_tokens": int, "completion_tokens": int, "total_tokens": int}``。

    Raises:
        BudgetExceededError: 累计成本超过 ``BUDGET_YUAN``（熔断）。
        LLMError: 调用失败且重试用尽。
    """
    client = _get_cached_provider(model)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
    ]

    response = client.chat_with_retry(
        messages, temperature=temperature, max_tokens=max_tokens
    )

    usage_obj: Usage = response.usage
    usage: dict[str, int] = {
        "prompt_tokens": usage_obj.prompt_tokens,
        "completion_tokens": usage_obj.completion_tokens,
        "total_tokens": usage_obj.total_tokens,
    }

    # ★ 接入点 ① —— 每次 LLM 调用自动 record
    guard = get_cost_guard()
    guard.record(node_name, usage, model=response.model or client.model)
    # ★ 接入点 ② —— check()，超预算抛 BudgetExceededError 熔断
    guard.check()

    return response.content, usage


def parse_json_reply(text: str) -> Any:
    """从模型回复里抠出 JSON（容忍 ```json 围栏与前后废话）。

    Args:
        text: 模型原始回复。

    Returns:
        解析出的 dict 或 list；解析失败返回空 dict。

    Examples:
        >>> parse_json_reply('```json\\n{"a": 1}\\n```')
        {'a': 1}
        >>> parse_json_reply("胡说八道")
        {}
    """
    if not text:
        return {}

    candidate = text.strip()
    if candidate.startswith("```"):
        lines = [ln for ln in candidate.splitlines() if not ln.strip().startswith("```")]
        candidate = "\n".join(lines).strip()

    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass

    # 退而求其次：截取第一个 { 或 [ 到最后一个 } 或 ]
    for opener, closer in (("{", "}"), ("[", "]")):
        start, end = candidate.find(opener), candidate.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(candidate[start : end + 1])
            except json.JSONDecodeError:
                continue
    return {}


def chat_json(
    prompt: str,
    system: str = DEFAULT_SYSTEM,
    model: str | None = None,
    temperature: float = DEFAULT_TEMPERATURE,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    node_name: str = "unknown",
) -> tuple[Any, dict[str, int]]:
    """调用 LLM 并把回复解析成 JSON。

    Args:
        prompt: 用户 prompt。
        system: system prompt。
        model: 模型名覆盖。
        temperature: 采样温度。
        max_tokens: 最大输出 token 数。
        node_name: 调用所在节点名（透传给 :func:`chat`）。

    Returns:
        ``(parsed, usage)``；parsed 可能是 dict 或 list，解析失败为空 dict。

    Raises:
        BudgetExceededError: 累计成本超过预算。
        LLMError: 调用失败且重试用尽。
    """
    text, usage = chat(
        prompt,
        system=system,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        node_name=node_name,
    )
    parsed = parse_json_reply(text)
    if parsed == {} and text.strip():
        logger.warning("[model_client] JSON 解析失败，原文前 120 字：%s", text[:120])
    return parsed, usage


def accumulate_usage(tracker: dict | None, usage: dict) -> dict[str, int]:
    """把一次调用的用量累加进 state 里的 ``cost_tracker``。

    Args:
        tracker: 现有累计值，可为 None 或空 dict。
        usage: 本次调用的用量。

    Returns:
        新的累计字典（不原地修改入参）。

    Examples:
        >>> accumulate_usage({}, {"prompt_tokens": 10, "completion_tokens": 5})
        {'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15, 'calls': 1}
    """
    base = dict(tracker or {})
    prompt_tokens = int(base.get("prompt_tokens", 0)) + int(usage.get("prompt_tokens", 0))
    completion_tokens = int(base.get("completion_tokens", 0)) + int(
        usage.get("completion_tokens", 0)
    )
    total = int(usage.get("total_tokens", 0)) or (
        int(usage.get("prompt_tokens", 0)) + int(usage.get("completion_tokens", 0))
    )
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": int(base.get("total_tokens", 0)) + total,
        "calls": int(base.get("calls", 0)) + 1,
    }


def cost_summary() -> str:
    """返回一行成本摘要（V2 tracker + V3 CostGuard 两个口径）。

    Returns:
        可直接打日志的摘要文本。
    """
    guard = get_cost_guard()
    return (
        f"CostGuard: {len(guard.records)} 次调用 · ¥{guard.total_cost_yuan:.6f} / "
        f"¥{guard.budget_yuan:.4f}；V2 tracker: {v2_tracker.total_tokens} tokens"
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    print("=== workflows/model_client 自测（不调网络）===")
    print("parse_json_reply:", parse_json_reply('```json\n{"ok": true}\n```'))
    print("accumulate_usage:", accumulate_usage({}, {"prompt_tokens": 3, "completion_tokens": 4}))
    print("CostGuard 预算:", get_cost_guard().budget_yuan)
    print("OK")
