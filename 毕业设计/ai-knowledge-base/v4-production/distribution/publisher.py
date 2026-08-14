"""distribution/publisher.py — 推送层。

把 `formatter.py` 产出的简报文本推送到各渠道。目前实现 Telegram（Bot API
`sendMessage`）；飞书 / 钉钉留空扩展点，不强制。

- 令牌只从环境变量 `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` 读取，绝不硬编码。
- 未配置令牌时自动降级为 dry-run：不发网络请求，返回 `success=True` 并打印预览，
  这样没有凭证也能本地跑通验收。
- 多渠道并发（`asyncio.gather`），单渠道失败不阻断其他渠道。
"""

import asyncio
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx

from distribution.formatter import format_markdown, format_telegram, load_articles

logger = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org"
TELEGRAM_TIMEOUT_SECONDS = 30.0
TELEGRAM_PREVIEW_CHARS = 500

DEFAULT_CHANNELS = ["telegram"]


@dataclass
class PublishResult:
    """单次推送结果。"""

    channel: str
    success: bool
    message_id: str | None = None
    error: str | None = None


class BasePublisher(ABC):
    """推送渠道抽象基类。"""

    channel_name: str

    @abstractmethod
    async def send_digest(
        self, markdown: str, telegram_html: str, dry_run: bool = False
    ) -> PublishResult:
        """发送一份简报，返回该渠道的推送结果。"""
        raise NotImplementedError


class TelegramPublisher(BasePublisher):
    """通过 Telegram Bot API 推送简报。"""

    channel_name = "telegram"

    def __init__(self, token: str | None = None, chat_id: str | None = None) -> None:
        """初始化 Telegram 推送器。

        Args:
            token: Bot Token，缺省从环境变量 `TELEGRAM_BOT_TOKEN` 读取。
            chat_id: 目标会话 ID，缺省从环境变量 `TELEGRAM_CHAT_ID` 读取。
        """
        self.token = token if token is not None else os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = chat_id if chat_id is not None else os.environ.get("TELEGRAM_CHAT_ID", "")

    async def send_digest(
        self, markdown: str, telegram_html: str, dry_run: bool = False
    ) -> PublishResult:
        """发送每日简报到 Telegram；无 token 或强制 dry_run 时只打印预览。"""
        if dry_run or not self.token:
            preview = telegram_html[:TELEGRAM_PREVIEW_CHARS]
            logger.info(
                "[dry-run] telegram 推送预览（前 %d 字）：%s", TELEGRAM_PREVIEW_CHARS, preview
            )
            print("=== [dry-run] Telegram 推送预览 ===")
            print(preview)
            return PublishResult(channel="telegram/dry-run", success=True)

        if not self.chat_id:
            return PublishResult(
                channel=self.channel_name, success=False, error="TELEGRAM_CHAT_ID 未设置"
            )

        payload = {
            "chat_id": self.chat_id,
            "text": telegram_html,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        url = f"{TELEGRAM_API_BASE}/bot{self.token}/sendMessage"
        try:
            async with httpx.AsyncClient(timeout=TELEGRAM_TIMEOUT_SECONDS) as client:
                response = await client.post(url, json=payload)
                data = response.json()
        except httpx.HTTPError as exc:
            logger.warning("telegram 推送网络异常：%s", exc)
            return PublishResult(channel=self.channel_name, success=False, error=str(exc))

        if data.get("ok"):
            return PublishResult(
                channel=self.channel_name,
                success=True,
                message_id=str(data["result"]["message_id"]),
            )
        return PublishResult(
            channel=self.channel_name,
            success=False,
            error=data.get("description", "telegram API 返回未知错误"),
        )


PUBLISHERS: dict[str, type[BasePublisher]] = {
    "telegram": TelegramPublisher,
}


async def _publish_to_channel(
    channel: str, markdown: str, telegram_html: str, dry_run: bool
) -> PublishResult:
    """把简报发到单个渠道，捕获异常防止阻断其他渠道。"""
    publisher_cls = PUBLISHERS.get(channel)
    if publisher_cls is None:
        return PublishResult(channel=channel, success=False, error=f"未实现的渠道：{channel}")
    try:
        publisher = publisher_cls()
        return await publisher.send_digest(markdown, telegram_html, dry_run=dry_run)
    except Exception as exc:  # noqa: BLE001 — 渠道异常必须隔离，不能拖垮其他渠道
        logger.exception("渠道 %s 推送异常", channel)
        return PublishResult(channel=channel, success=False, error=str(exc))


async def publish_daily_digest(
    articles: list[dict] | None = None,
    channels: list[str] | None = None,
    dry_run: bool = False,
) -> list[PublishResult]:
    """生成简报并并发推送到指定渠道。

    Args:
        articles: 待推送文章列表；为 `None` 时用 `formatter.load_articles()` 加载全库。
        channels: 目标渠道名列表；为 `None` 时使用 `DEFAULT_CHANNELS`。
        dry_run: 强制走 dry-run（即便配置了 token 也不真实发送）。

    Returns:
        每个渠道一条 `PublishResult`。
    """
    if articles is None:
        articles = load_articles()
    enabled_channels = channels or DEFAULT_CHANNELS

    markdown = format_markdown(articles)
    telegram_html = format_telegram(articles)

    tasks = [
        _publish_to_channel(channel, markdown, telegram_html, dry_run)
        for channel in enabled_channels
    ]
    results = await asyncio.gather(*tasks)
    logger.info(
        "[发布] 完成：%d/%d 个渠道成功",
        sum(1 for r in results if r.success),
        len(results),
    )
    return list(results)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    _results = asyncio.run(publish_daily_digest())
    for _r in _results:
        _status = "✅" if _r.success else "❌"
        print(f"{_status} {_r.channel}: {_r.message_id or _r.error or 'OK'}")
