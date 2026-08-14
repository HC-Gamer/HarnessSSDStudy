"""钉钉 → 知识库 Bot 渠道接入（v4 待办 2，替代原 Telegram 方案）。

群聊 @ 机器人 → 收到消息 → 交给 `bot/knowledge_bot.py` 的 `KnowledgeBot`
本地检索 → markdown 回复钉钉群。纯本地规则匹配，不调 LLM、不花 token。

与 `openclaw/dingtalk_bridge.py` 的关系：
    同一套 Stream 凭证与连接模式，但 handler 里把「调 OpenClaw agent」换成
    「调 KnowledgeBot 检索」。两者是**互斥**的两个进程 ——
    同一 app_key 钉钉只允许一个 Stream 连接实例，起本脚本前先停掉旧桥。

独立启动：
    cd v4-production && ~/ai-knowledge-base/.venv/bin/python3 -u \
        openclaw/dingtalk_knowledge_bot.py > /tmp/dingtalk_knowledge_bot.log 2>&1 &

凭证：
    .env 中 DINGTALK_APP_KEY / DINGTALK_APP_SECRET（钉钉开发者平台应用凭证，
    消息接收模式需为 Stream 模式）。本脚本不需要任何模型 API key。

注意：
    - 钉钉国内直连，必须清代理环境变量（Clash 会卡死 Stream 连接）
    - 钉钉 Stream 机器人只推被 @ 的消息（群聊普通消息、文件、语音收不到）
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

# 钉钉国内直连，必须绕过 Clash 代理。必须在 import dingtalk_stream 之前执行。
for _k in (
    "http_proxy",
    "https_proxy",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "all_proxy",
    "ALL_PROXY",
    "ftp_proxy",
    "FTP_PROXY",
):
    os.environ.pop(_k, None)

import dingtalk_stream  # noqa: E402
from dingtalk_stream import AckMessage, ChatbotHandler, Credential  # noqa: E402

# 项目根目录（本文件位于 <root>/openclaw/），加进 sys.path 才能 import bot 包
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bot.knowledge_bot import HELP_TEXT, KnowledgeBot  # noqa: E402

ENV_FILE = ROOT / ".env"
ARTICLES_DIR = ROOT / "knowledge" / "articles"
SUBSCRIPTIONS_PATH = ROOT / "data" / "subscriptions.json"

MARKDOWN_TITLE = "AI 知识库"
# 钉钉 markdown 把单个换行折叠成空格，用行尾两空格强制换行
MARKDOWN_LINE_BREAK = "  \n"
LOG_PREVIEW_CHARS = 120
ANONYMOUS_USER = "dingtalk-anonymous"

logger = logging.getLogger("dingtalk_knowledge_bot")


def load_env() -> dict[str, str]:
    """加载 .env（KEY=VALUE 格式，忽略 # 注释与空行）。"""
    env: dict[str, str] = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def strip_at_mentions(text: str) -> str:
    """去掉消息里的 @机器人 前缀，只留真正的指令内容。

    Args:
        text: 钉钉推来的原始文本，形如 `"@小哨 /search agent"`。

    Returns:
        剥掉 @xxx 之后的净文本；只 @ 不带内容时返回空串。
    """
    cleaned = text
    for part in text.split():
        if part.startswith("@"):
            cleaned = cleaned.replace(part, "", 1)
    return cleaned.strip()


def to_markdown(reply: str) -> str:
    """把 Bot 的纯文本回复转成钉钉 markdown（保留换行与缩进）。"""
    return MARKDOWN_LINE_BREAK.join(line.rstrip() for line in reply.splitlines())


class KnowledgeBotHandler(ChatbotHandler):
    """收到群 @ 消息 → KnowledgeBot 本地检索 → markdown 回复。"""

    def __init__(self, bot: KnowledgeBot) -> None:
        """注入已初始化的 `KnowledgeBot`（索引路径在 main 里配好）。"""
        super().__init__()
        self.bot = bot

    async def process(self, callback: dingtalk_stream.frames.CallbackMessage):
        """处理一条钉钉回调消息，返回 Stream ACK。"""
        raw = callback.data
        text = (raw.get("text") or {}).get("content", "").strip()
        nick = raw.get("senderNick") or "?"
        user_id = raw.get("senderStaffId") or raw.get("senderId") or ANONYMOUS_USER
        cid = raw.get("conversationId") or raw.get("openConversationId") or "?"
        logger.info("收到群消息 from=%s cid=%s text=%r", nick, cid, text)

        # SDK 的 reply_markdown 需要 ChatbotMessage 对象（session_webhook / sender_staff_id），
        # 不能直接传 dict —— 用 SDK 自带的 from_dict 转换。
        msg = dingtalk_stream.ChatbotMessage.from_dict(raw)

        if not text:
            return AckMessage.STATUS_OK, "OK"

        query = strip_at_mentions(text)
        try:
            # 只 @ 机器人不带内容时直接给帮助，避免命中 UNKNOWN 兜底话术
            reply = self.bot.handle_message(user_id, query) if query else HELP_TEXT

            logger.info("回复 %s: %r", nick, reply[:LOG_PREVIEW_CHARS])
            self.reply_markdown(
                MARKDOWN_TITLE,
                f"> {nick} 问：{query or text}\n\n---\n\n{to_markdown(reply)}",
                msg,
            )
        except Exception as e:  # noqa: BLE001
            logger.exception("处理失败: %s", e)
            try:
                self.reply_markdown(
                    MARKDOWN_TITLE, f"> {nick} 问：{query or text}\n\n（处理失败：{e}）", msg
                )
            except Exception:  # noqa: BLE001
                logger.exception("兜底回复也失败")
        return AckMessage.STATUS_OK, "OK"


def main() -> int:
    """装配 KnowledgeBot 与钉钉 Stream 客户端并常驻运行。"""
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    env = load_env()
    app_key = env.get("DINGTALK_APP_KEY", "").strip()
    app_secret = env.get("DINGTALK_APP_SECRET", "").strip()
    if not app_key or not app_secret:
        logger.error("错误: .env 中缺少 DINGTALK_APP_KEY / DINGTALK_APP_SECRET")
        return 2
    if not (ARTICLES_DIR / "index.json").exists():
        logger.error("错误: 知识库索引不存在 %s", ARTICLES_DIR / "index.json")
        return 3

    bot = KnowledgeBot(articles_dir=ARTICLES_DIR, subscriptions_path=SUBSCRIPTIONS_PATH)
    client = dingtalk_stream.DingTalkStreamClient(Credential(app_key, app_secret))
    client.register_callback_handler(
        dingtalk_stream.chatbot.ChatbotMessage.TOPIC, KnowledgeBotHandler(bot)
    )
    logger.info("知识库索引: %s", ARTICLES_DIR)
    logger.info("正在连接钉钉 Stream（Ctrl+C 退出）...")
    client.start_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
