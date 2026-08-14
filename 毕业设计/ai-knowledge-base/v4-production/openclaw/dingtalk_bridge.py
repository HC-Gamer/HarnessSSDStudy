"""钉钉 → OpenClaw 桥接机器人（v4 第 13 节交付物）。

群聊 @ 机器人 → 收到消息 → 调用 OpenClaw agent（DeepSeek 模型）→ 回复钉钉群。

独立启动：
    cd v4-production && ~/ai-knowledge-base/.venv/bin/python3 -u openclaw/dingtalk_bridge.py

凭证：
    .env 中 DINGTALK_APP_KEY / DINGTALK_APP_SECRET（钉钉开发者平台应用凭证，
    消息接收模式需为 Stream 模式）；模型走 OpenClaw 已 onboard 的 DeepSeek。

注意：
    - 钉钉国内直连，必须清代理环境变量（Clash 会卡死 Stream 连接）
    - 钉钉 Stream 机器人只推被 @ 的消息（群聊普通消息收不到）
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

# 钉钉国内直连，必须绕过 Clash 代理
for _k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY",
           "all_proxy", "ALL_PROXY", "ftp_proxy", "FTP_PROXY"):
    os.environ.pop(_k, None)

import dingtalk_stream
from dingtalk_stream import ChatbotHandler, AckMessage, Credential

# 项目根目录（本文件位于 <root>/openclaw/）
ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"


def load_env() -> dict:
    """加载 .env（KEY=VALUE 格式，忽略 # 注释与空行）。"""
    env: dict = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


ENV = load_env()


def call_openclaw(text: str) -> str:
    """调用 OpenClaw agent（embedded 模式），返回回复文本。"""
    msg_file = ROOT / ".openclaw_msg.json"
    msg_file.write_text(json.dumps({"message": text}, ensure_ascii=False),
                        encoding="utf-8")
    env = os.environ.copy()
    # OpenClaw 需要新版 Node（≥22.22.3/24.15/25.9，内嵌 SQLite 安全版本）
    node25 = "/Users/huangcheng/.local/node25/bin"
    env["PATH"] = node25 + ":" + env.get("PATH", "")
    env["HOME"] = "/Users/huangcheng"
    if ENV.get("DEEPSEEK_API_KEY"):
        env["DEEPSEEK_API_KEY"] = ENV["DEEPSEEK_API_KEY"]
    cmd = [
        "openclaw", "agent", "--local", "--agent", "main",
        "--message-file", str(msg_file),
    ]
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True,
                          timeout=180)
    out = proc.stdout.strip()
    if not out and proc.stderr:
        return f"（OpenClaw 调用失败）{proc.stderr.strip()[-200:]}"
    # 非 JSON 输出直接返回；JSON 则取 result/out 字段
    try:
        data = json.loads(out)
        reply = (data.get("result") or data.get("out") or data.get("text")
                 or json.dumps(data, ensure_ascii=False))
        return reply
    except json.JSONDecodeError:
        return out


class OpenClawBridgeHandler(ChatbotHandler):
    """收到群 @ 消息 → OpenClaw → 回复。"""

    async def process(self, callback: dingtalk_stream.frames.CallbackMessage):
        msg = callback.data
        text = (msg.get("text") or {}).get("content", "").strip()
        nick = msg.get("senderNick") or msg.get("senderStaffId") or "?"
        cid = (msg.get("conversationId") or msg.get("openConversationId")
               or msg.get("chatId") or "?")
        print(f"[bridge] 收到群消息 from={nick} cid={cid} text={text!r}",
              flush=True)
        if not text:
            return AckMessage.STATUS_OK, "OK"
        # 去掉 @机器人 前缀（形如 " @小哨 "），避免模型困惑
        cleaned = text
        for part in text.split():
            if part.startswith("@"):
                cleaned = cleaned.replace(part, "", 1)
        cleaned = cleaned.strip()
        if not cleaned:
            cleaned = text
        try:
            print(f"[bridge] 调用 OpenClaw: {cleaned!r}", flush=True)
            reply = call_openclaw(cleaned)
            print(f"[bridge] OpenClaw 回复: {reply[:120]!r}", flush=True)
            await self.reply_markdown("OpenClaw", f"> {nick} 问：\n\n> {text}\n\n---\n\n{reply}", msg)
        except Exception as e:  # noqa: BLE001
            print(f"[bridge] 调用/应答失败: {e}", flush=True)
            try:
                await self.reply_markdown("OpenClaw",
                                          f"> {nick} 问：{text}\n\n（处理失败：{e}）",
                                          msg)
            except Exception:  # noqa: BLE001
                pass
        return AckMessage.STATUS_OK, "OK"


def main() -> int:
    app_key = ENV.get("DINGTALK_APP_KEY", "").strip()
    app_secret = ENV.get("DINGTALK_APP_SECRET", "").strip()
    if not app_key or not app_secret:
        print("错误: .env 中缺少 DINGTALK_APP_KEY / DINGTALK_APP_SECRET",
              file=sys.stderr)
        return 2

    client = dingtalk_stream.DingTalkStreamClient(
        Credential(app_key, app_secret)
    )
    client.register_callback_handler(
        dingtalk_stream.chatbot.ChatbotMessage.TOPIC,
        OpenClawBridgeHandler(),
    )
    print("[bridge] 正在连接钉钉 Stream（Ctrl+C 退出）...", flush=True)
    client.start_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
