# 钉钉渠道接入（知识库 Bot）

群里 @ 机器人 → 本地检索知识库 → markdown 回复。**替代原 Telegram 方案**（不再需要 BotFather token）。

## 两个 Stream 脚本（互斥，二选一）

| 脚本 | 用途 | 是否调模型 |
|---|---|---|
| `openclaw/dingtalk_knowledge_bot.py` | @ 机器人 → `bot/knowledge_bot.py` 本地检索 → 回群 | 否，零 token |
| `openclaw/dingtalk_bridge.py` | @ 机器人 → OpenClaw agent（DeepSeek）→ 回群 | 是 |

> ⚠️ 同一个 `DINGTALK_APP_KEY` 钉钉只允许**一个** Stream 连接实例。
> 换脚本前先 `pgrep -fl dingtalk` 确认并停掉在跑的那个，不要并行启动两个。

## 前置条件

1. `.env`（`chmod 600`，已 gitignore）中填好钉钉开发者平台的应用凭证：
   ```
   DINGTALK_APP_KEY=dingxxxxxxxx
   DINGTALK_APP_SECRET=xxxxxxxx
   ```
2. 在 [open-dev.dingtalk.com](https://open-dev.dingtalk.com) 把应用的**消息接收模式设为 Stream 模式**，
   并把机器人加进目标群（这步在钉钉后台手动完成，脚本不做自动化）。
3. `knowledge/articles/index.json` 存在（跑过一次 `run.sh` 即有）。

## 启动 / 停止

```bash
cd v4-production
pgrep -fl dingtalk                      # 先确认没有在跑的实例
../.venv/bin/python3 -u openclaw/dingtalk_knowledge_bot.py \
    > /tmp/dingtalk_knowledge_bot.log 2>&1 &

tail -f /tmp/dingtalk_knowledge_bot.log # 看到 endpoint is wss://... 即连接成功
pkill -f dingtalk_knowledge_bot         # 停止
```

- 必须用项目根 `.venv`（Python 3.12，已装 `dingtalk_stream` + `websockets`）；brew 的 python3 没装 SDK。
- 必须加 `-u` 防日志缓冲。
- 脚本开头已内置清代理逻辑（`http_proxy` / `https_proxy` / `all_proxy` 等），
  钉钉走国内直连，挂着 Clash 会卡死 Stream 握手。连不上时先探针：
  `curl -m 5 -o /dev/null -w "%{http_code}" https://api.dingtalk.com` 应返回 200。

## 群内可用指令

@ 机器人后跟指令，指令集与 `bot/knowledge_bot.py` 完全一致：

| 指令 | 作用 |
|---|---|
| `/search <关键词>` | 加权检索（标题 +10 / 标签 +5 / 摘要 +3，再乘 relevance_score） |
| `/today` | 今日入库文章（当天无数据回退到最近一次入库日） |
| `/top [N]` | 全库相关性最高的 N 篇（默认 5） |
| `/subscribe <关键词>` / `/unsubscribe <关键词>` | 订阅管理，按钉钉 `senderStaffId` 分用户，落盘 `data/subscriptions.json` |
| `/help` | 帮助；只 @ 机器人不带内容时也返回帮助 |

也支持自然语言触发（"搜索 RAG" / "今天" / "排行榜" / "订阅 agent"）。

## 已知限制

- 钉钉 Stream 机器人只能收到**被 @ 的群消息**，普通群消息、文件、语音、视频收不到（官方限制）。
- 回复走 `reply_markdown`；钉钉会把单换行折叠成空格，脚本用行尾双空格强制换行。
