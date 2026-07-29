#!/usr/bin/env python3
"""统一 LLM 客户端。

支持 DeepSeek / Qwen / OpenAI 三种提供商，全部走 OpenAI 兼容的
``/chat/completions`` 接口，直接用 httpx 发请求，不依赖任何厂商 SDK。

环境变量:
    LLM_PROVIDER: 提供商，可选 ``deepseek`` / ``qwen`` / ``openai``，默认 ``deepseek``。
    DEEPSEEK_API_KEY / DASHSCOPE_API_KEY / OPENAI_API_KEY: 对应提供商的密钥。
    LLM_MODEL: 可选，覆盖默认模型名。
    LLM_BASE_URL: 可选，覆盖默认接口地址。

示例::

    from pipeline.model_client import quick_chat
    print(quick_chat("用一句话解释 MCP"))
"""

from __future__ import annotations

import json
import logging
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import httpx

try:  # python-dotenv 是可选依赖
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover - 环境相关
    def load_dotenv(*args: Any, **kwargs: Any) -> bool:
        """python-dotenv 未安装时的空实现。"""
        return False


logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 60.0
DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_BASE = 2.0


# ---------------------------------------------------------------------------
# 提供商配置
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProviderConfig:
    """单个提供商的静态配置。

    Attributes:
        name: 提供商标识。
        base_url: OpenAI 兼容 API 的根地址。
        default_model: 默认模型名。
        api_key_env: 读取密钥的环境变量名。
        price_in_cny: 输入价格（元 / 百万 tokens）。
        price_out_cny: 输出价格（元 / 百万 tokens）。
        price_in_usd: 输入价格（USD / 千 tokens）。
        price_out_usd: 输出价格（USD / 千 tokens）。
    """

    name: str
    base_url: str
    default_model: str
    api_key_env: str
    price_in_cny: float
    price_out_cny: float
    price_in_usd: float
    price_out_usd: float


#: 各提供商配置表。价格单位见 ProviderConfig 文档。
PROVIDERS: dict[str, ProviderConfig] = {
    "deepseek": ProviderConfig(
        name="deepseek",
        base_url="https://api.deepseek.com/v1",
        default_model="deepseek-chat",
        api_key_env="DEEPSEEK_API_KEY",
        price_in_cny=1.0,
        price_out_cny=2.0,
        price_in_usd=0.00014,
        price_out_usd=0.00028,
    ),
    "qwen": ProviderConfig(
        name="qwen",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        default_model="qwen-plus",
        api_key_env="DASHSCOPE_API_KEY",
        price_in_cny=4.0,
        price_out_cny=12.0,
        price_in_usd=0.00056,
        price_out_usd=0.00168,
    ),
    "openai": ProviderConfig(
        name="openai",
        base_url="https://api.openai.com/v1",
        default_model="gpt-4o-mini",
        api_key_env="OPENAI_API_KEY",
        price_in_cny=0.15,
        price_out_cny=0.6,
        price_in_usd=0.00015,
        price_out_usd=0.0006,
    ),
}


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass
class Usage:
    """单次调用的 token 用量。

    Attributes:
        prompt_tokens: 输入 token 数。
        completion_tokens: 输出 token 数。
        total_tokens: 总 token 数。
    """

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> Usage:
        """从 API 响应的 usage 字段构造。

        Args:
            raw: API 返回的 usage 字典，可能为 None。

        Returns:
            解析后的 Usage 实例。
        """
        raw = raw or {}
        prompt = int(raw.get("prompt_tokens", 0) or 0)
        completion = int(raw.get("completion_tokens", 0) or 0)
        total = int(raw.get("total_tokens", 0) or 0) or prompt + completion
        return cls(prompt_tokens=prompt, completion_tokens=completion, total_tokens=total)


@dataclass
class LLMResponse:
    """统一的 LLM 返回结果。

    Attributes:
        content: 模型输出的文本内容。
        usage: token 用量。
        model: 实际使用的模型名。
        provider: 提供商标识。
        raw: 原始响应字典，便于调试。
    """

    content: str
    usage: Usage
    model: str = ""
    provider: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    def cost_usd(self) -> float:
        """按提供商单价估算本次调用成本（USD）。

        Returns:
            估算的美元成本。
        """
        config = PROVIDERS.get(self.provider)
        if config is None:
            return 0.0
        return (
            self.usage.prompt_tokens / 1000 * config.price_in_usd
            + self.usage.completion_tokens / 1000 * config.price_out_usd
        )


class LLMError(RuntimeError):
    """LLM 调用失败时抛出的异常。"""


# ---------------------------------------------------------------------------
# 成本追踪
# ---------------------------------------------------------------------------


@dataclass
class _ProviderStat:
    """单个提供商的累计统计。"""

    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0


class CostTracker:
    """累计记录 token 消耗与成本。

    典型用法::

        tracker = CostTracker()
        tracker.record(response.usage, "deepseek")
        tracker.report()
    """

    def __init__(self) -> None:
        """初始化空的追踪器。"""
        self._stats: dict[str, _ProviderStat] = {}

    def record(self, usage: Usage, provider: str) -> None:
        """记录一次调用的用量。

        Args:
            usage: 本次调用的 token 用量。
            provider: 提供商标识。
        """
        stat = self._stats.setdefault(provider, _ProviderStat())
        stat.calls += 1
        stat.prompt_tokens += usage.prompt_tokens
        stat.completion_tokens += usage.completion_tokens
        logger.debug(
            "记录用量 provider=%s prompt=%d completion=%d",
            provider,
            usage.prompt_tokens,
            usage.completion_tokens,
        )

    def estimated_cost(self, provider: str | None = None) -> float:
        """估算累计成本（人民币元）。

        Args:
            provider: 只统计指定提供商；为 None 时统计全部。

        Returns:
            估算成本，单位元。
        """
        total = 0.0
        for name, stat in self._stats.items():
            if provider is not None and name != provider:
                continue
            config = PROVIDERS.get(name)
            if config is None:
                continue
            total += (
                stat.prompt_tokens / 1_000_000 * config.price_in_cny
                + stat.completion_tokens / 1_000_000 * config.price_out_cny
            )
        return total

    def estimated_cost_usd(self, provider: str | None = None) -> float:
        """估算累计成本（美元）。

        Args:
            provider: 只统计指定提供商；为 None 时统计全部。

        Returns:
            估算成本，单位 USD。
        """
        total = 0.0
        for name, stat in self._stats.items():
            if provider is not None and name != provider:
                continue
            config = PROVIDERS.get(name)
            if config is None:
                continue
            total += (
                stat.prompt_tokens / 1000 * config.price_in_usd
                + stat.completion_tokens / 1000 * config.price_out_usd
            )
        return total

    @property
    def total_calls(self) -> int:
        """累计调用次数。"""
        return sum(stat.calls for stat in self._stats.values())

    @property
    def total_tokens(self) -> int:
        """累计 token 总数。"""
        return sum(stat.prompt_tokens + stat.completion_tokens for stat in self._stats.values())

    def reset(self) -> None:
        """清空所有统计。"""
        self._stats.clear()

    def report(self) -> str:
        """生成并输出成本报告。

        Returns:
            报告文本（同时通过 logger 输出）。
        """
        lines = ["=" * 52, "LLM 成本报告", "=" * 52]

        if not self._stats:
            lines.append("暂无调用记录")
        else:
            for name, stat in sorted(self._stats.items()):
                cny = self.estimated_cost(name)
                usd = self.estimated_cost_usd(name)
                lines.append(f"[{name}]")
                lines.append(f"  调用次数: {stat.calls}")
                lines.append(f"  输入 tokens: {stat.prompt_tokens:,}")
                lines.append(f"  输出 tokens: {stat.completion_tokens:,}")
                lines.append(f"  合计 tokens: {stat.prompt_tokens + stat.completion_tokens:,}")
                lines.append(f"  估算成本: ¥{cny:.4f} / ${usd:.4f}")
            lines.append("-" * 52)
            lines.append(
                f"总计: {self.total_calls} 次调用, {self.total_tokens:,} tokens, "
                f"¥{self.estimated_cost():.4f} / ${self.estimated_cost_usd():.4f}"
            )

        lines.append("=" * 52)
        text = "\n".join(lines)
        logger.info("成本报告\n%s", text)
        return text


#: 全局成本追踪器，chat() 内部自动记录
tracker = CostTracker()


# ---------------------------------------------------------------------------
# 提供商实现
# ---------------------------------------------------------------------------


class LLMProvider(ABC):
    """LLM 提供商抽象基类。"""

    def __init__(self, config: ProviderConfig, api_key: str, model: str | None = None) -> None:
        """初始化提供商。

        Args:
            config: 提供商静态配置。
            api_key: API 密钥。
            model: 可选的模型名覆盖。
        """
        self.config = config
        self.api_key = api_key
        self.model = model or config.default_model

    @property
    def name(self) -> str:
        """提供商标识。"""
        return self.config.name

    @abstractmethod
    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        **kwargs: Any,
    ) -> LLMResponse:
        """执行一次对话补全。

        Args:
            messages: OpenAI 格式的消息列表。
            temperature: 采样温度。
            max_tokens: 最大输出 token 数。
            timeout: 请求超时秒数。
            **kwargs: 透传给 API 的其他参数。

        Returns:
            统一的 LLMResponse。

        Raises:
            LLMError: 请求失败或响应格式异常。
        """

    def chat_with_retry(
        self,
        messages: list[dict[str, str]],
        *,
        max_retries: int = DEFAULT_MAX_RETRIES,
        backoff_base: float = DEFAULT_BACKOFF_BASE,
        **kwargs: Any,
    ) -> LLMResponse:
        """带指数退避重试的对话补全。

        Args:
            messages: OpenAI 格式的消息列表。
            max_retries: 最大尝试次数（含首次）。
            backoff_base: 退避基数，第 n 次失败后等待 ``backoff_base ** n`` 秒。
            **kwargs: 透传给 :meth:`chat`。

        Returns:
            统一的 LLMResponse。

        Raises:
            LLMError: 所有重试均失败。
        """
        last_error: Exception | None = None

        for attempt in range(1, max_retries + 1):
            try:
                return self.chat(messages, **kwargs)
            except LLMError as exc:
                last_error = exc
                if attempt >= max_retries:
                    break
                delay = backoff_base ** attempt
                logger.warning(
                    "第 %d/%d 次调用失败: %s，%.1fs 后重试", attempt, max_retries, exc, delay
                )
                time.sleep(delay)

        logger.error("重试 %d 次后仍然失败: %s", max_retries, last_error)
        raise LLMError(f"调用 {self.name} 失败（已重试 {max_retries} 次）: {last_error}")


class OpenAICompatibleProvider(LLMProvider):
    """基于 OpenAI 兼容 ``/chat/completions`` 接口的通用实现。

    DeepSeek、Qwen（DashScope 兼容模式）、OpenAI 均可复用本实现。
    """

    def __init__(
        self,
        config: ProviderConfig,
        api_key: str,
        model: str | None = None,
        base_url: str | None = None,
    ) -> None:
        """初始化。

        Args:
            config: 提供商静态配置。
            api_key: API 密钥。
            model: 可选的模型名覆盖。
            base_url: 可选的接口地址覆盖。
        """
        super().__init__(config, api_key, model)
        self.base_url = (base_url or config.base_url).rstrip("/")

    def _headers(self) -> dict[str, str]:
        """构造请求头。"""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        **kwargs: Any,
    ) -> LLMResponse:
        """执行一次对话补全并自动记录成本。

        Args:
            messages: OpenAI 格式的消息列表。
            temperature: 采样温度。
            max_tokens: 最大输出 token 数。
            timeout: 请求超时秒数。
            **kwargs: 透传给 API 的其他参数（如 ``response_format``）。

        Returns:
            统一的 LLMResponse。

        Raises:
            LLMError: HTTP 错误、网络异常或响应格式异常。
        """
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        payload.update(kwargs)

        url = f"{self.base_url}/chat/completions"
        logger.debug("请求 %s model=%s messages=%d", url, self.model, len(messages))

        try:
            response = httpx.post(url, headers=self._headers(), json=payload, timeout=timeout)
        except httpx.TimeoutException as exc:
            raise LLMError(f"请求超时（{timeout}s）: {exc}") from exc
        except httpx.HTTPError as exc:
            raise LLMError(f"网络错误: {exc}") from exc

        if response.status_code != 200:
            snippet = response.text[:500]
            raise LLMError(f"HTTP {response.status_code}: {snippet}")

        try:
            data = response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise LLMError(f"响应不是合法 JSON: {response.text[:200]}") from exc

        try:
            content = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"响应结构异常: {json.dumps(data, ensure_ascii=False)[:300]}") from exc

        usage = Usage.from_dict(data.get("usage"))
        tracker.record(usage, self.name)

        logger.info(
            "调用成功 provider=%s model=%s tokens=%d(输入 %d/输出 %d)",
            self.name,
            self.model,
            usage.total_tokens,
            usage.prompt_tokens,
            usage.completion_tokens,
        )

        return LLMResponse(
            content=content,
            usage=usage,
            model=data.get("model", self.model),
            provider=self.name,
            raw=data,
        )


# ---------------------------------------------------------------------------
# 工厂与便捷函数
# ---------------------------------------------------------------------------


def get_provider(name: str | None = None, model: str | None = None) -> LLMProvider:
    """根据名称或环境变量创建提供商实例。

    Args:
        name: 提供商标识；为 None 时读取 ``LLM_PROVIDER``，默认 ``deepseek``。
        model: 可选的模型名覆盖；为 None 时读取 ``LLM_MODEL``。

    Returns:
        已配置好的 LLMProvider 实例。

    Raises:
        LLMError: 提供商不支持或缺少 API Key。
    """
    provider_name = (name or os.getenv("LLM_PROVIDER") or "deepseek").strip().lower()

    config = PROVIDERS.get(provider_name)
    if config is None:
        raise LLMError(f"不支持的提供商: {provider_name}，可选 {sorted(PROVIDERS)}")

    api_key = os.getenv(config.api_key_env, "").strip()
    if not api_key:
        raise LLMError(f"缺少环境变量 {config.api_key_env}，请在 .env 中配置 {provider_name} 的 API Key")

    return OpenAICompatibleProvider(
        config=config,
        api_key=api_key,
        model=model or os.getenv("LLM_MODEL") or None,
        base_url=os.getenv("LLM_BASE_URL") or None,
    )


def quick_chat(
    prompt: str,
    *,
    system: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    temperature: float = 0.7,
    max_tokens: int | None = None,
) -> str:
    """一句话调用 LLM，返回纯文本。

    Args:
        prompt: 用户输入。
        system: 可选的 system prompt。
        provider: 可选的提供商覆盖。
        model: 可选的模型名覆盖。
        temperature: 采样温度。
        max_tokens: 最大输出 token 数。

    Returns:
        模型输出的文本内容。

    Raises:
        LLMError: 调用失败。
    """
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    client = get_provider(provider, model)
    response = client.chat_with_retry(
        messages, temperature=temperature, max_tokens=max_tokens
    )
    return response.content


def estimate_cost(usage: Usage, provider: str, *, currency: str = "cny") -> float:
    """估算单次调用成本。

    Args:
        usage: token 用量。
        provider: 提供商标识。
        currency: ``cny`` 返回人民币元，``usd`` 返回美元。

    Returns:
        估算成本。

    Raises:
        LLMError: 提供商未知或币种不支持。
    """
    config = PROVIDERS.get(provider)
    if config is None:
        raise LLMError(f"未知提供商: {provider}")

    if currency.lower() == "cny":
        return (
            usage.prompt_tokens / 1_000_000 * config.price_in_cny
            + usage.completion_tokens / 1_000_000 * config.price_out_cny
        )
    if currency.lower() == "usd":
        return (
            usage.prompt_tokens / 1000 * config.price_in_usd
            + usage.completion_tokens / 1000 * config.price_out_usd
        )
    raise LLMError(f"不支持的币种: {currency}")


# ---------------------------------------------------------------------------
# 自测
# ---------------------------------------------------------------------------


def _self_test() -> int:
    """本地自测：打印配置、离线校验价格计算，可用时发起一次真实调用。

    Returns:
        退出码。
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    logger.info("已注册提供商: %s", sorted(PROVIDERS))
    logger.info("当前 LLM_PROVIDER=%s", os.getenv("LLM_PROVIDER", "deepseek（默认）"))

    # 离线校验：1000 输入 + 500 输出 tokens 的成本估算
    sample = Usage(prompt_tokens=1000, completion_tokens=500, total_tokens=1500)
    for name in PROVIDERS:
        logger.info(
            "价格自测 %s: ¥%.6f / $%.6f (1000 in / 500 out)",
            name,
            estimate_cost(sample, name, currency="cny"),
            estimate_cost(sample, name, currency="usd"),
        )

    try:
        client = get_provider()
    except LLMError as exc:
        logger.warning("跳过真实调用: %s", exc)
        return 0

    logger.info("使用 %s / %s 发起测试调用", client.name, client.model)
    try:
        reply = quick_chat(
            "用一句话解释什么是 Model Context Protocol（MCP）。",
            system="你是简洁准确的技术助手，回答不超过 50 字。",
            max_tokens=200,
        )
    except LLMError as exc:
        logger.error("测试调用失败: %s", exc)
        return 1

    logger.info("模型回复: %s", reply)
    tracker.report()
    return 0


if __name__ == "__main__":
    raise SystemExit(_self_test())
