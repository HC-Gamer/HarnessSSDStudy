# 第 14 + 15 节验收证据

> V4 作业任务书 A 的本地验收记录。全部命令在项目根目录
> `/Volumes/M4_Workspace/AIHarness/OpenCode/OpenCodeStudy/毕业设计/ai-knowledge-base/v4-production`
> 下用项目 venv（`~/ai-knowledge-base/.venv/bin/python`，Python 3.12.10）执行。

## 环境准备

- `knowledge/` `pipeline/` `workflows/` `patterns/` `tests/` `AGENTS.md` `requirements.txt`
  `.env.example` `.gitignore` `pytest.ini` `run.sh` `scripts/` `.opencode/` 已从
  `v3-multi-agent` 用 `cp -R` 复制到 `v4-production`（`.env` 也复制并 `chmod 600`，已在
  `.gitignore` 里，不会被提交）。
- 系统 `python3` 是 3.9.6（PEP 604 语法会 SyntaxError），v3 没有现成 venv，于是用
  `/opt/homebrew/bin/python3.12` 在 `~/ai-knowledge-base/.venv` 新建了 venv（`run.sh` 默认就读这个路径）。
- 依赖安装：本机代理网络对 `files.pythonhosted.org` 连接非常不稳定（大量
  `ProxyError` / `SSLEOFError` / 超时），`pip install -r requirements.txt` 整体安装反复因某个包
  中途失败（`xxhash` / `pyyaml` 等）。改成逐个包安装后，`httpx` `python-dotenv` `pytest`
  `PyYAML` `feedparser`（第 14/15 节代码实际依赖的全部运行时依赖）安装成功；`langgraph` 系
  依赖链很长，多次重试仍受网络影响未必能完整装完，但**它只被 `workflows/graph.py` 用到，
  与本次验收的 `distribution/` `bot/` `daily_digest.py` 无关**，不影响下面 7 项验收。
- `black` 已装并用 `black --line-length 100` 格式化了 `distribution/` `bot/` `daily_digest.py`。
  `ruff` 因同样的网络问题未能在会话内完成安装，未跑 `ruff check`；代码手工核对了 PEP 8 /
  命名常量 / 类型注解 / docstring 等 AGENTS.md §6 要求。

```bash
$ python3 --version   # 系统 python，不可用
Python 3.9.6

$ /opt/homebrew/bin/python3.12 -m venv ~/ai-knowledge-base/.venv
$ ~/ai-knowledge-base/.venv/bin/python -V
Python 3.12.10

$ ~/ai-knowledge-base/.venv/bin/pip install httpx==0.28.1 python-dotenv==1.2.2 \
    pytest==9.1.1 PyYAML==6.0.3 feedparser==6.0.14
Successfully installed httpx-0.28.1 python-dotenv-1.2.2 pytest-9.1.1 PyYAML-6.0.3 feedparser-6.0.14 ...
```

---

## 验收 1：三模块可 import

```bash
$ cd v4-production
$ python3 -c "import distribution.formatter, distribution.publisher, bot.knowledge_bot; print('OK: import 成功，无报错')"
```

```
OK: import 成功，无报错
```

✅ 通过。

---

## 验收 2：formatter 自测（`python3 -m distribution.formatter`）

```
共加载 19 篇文章

==================== Markdown 预览（前 800 字） ====================
# 📚 AI 知识库简报（19 条）

---

### langgenius/dify

- **来源**：github
- **日期**：2026-08-12
- **相关性**：🟢 0.95
- **标签**：`llm`, `agent`, `rag`, `workflow`, `opensource`

Dify 将 LLM 应用开发从代码工程转变为可视化配置，是 Agent 和 RAG 技术走向生产实践的关键桥梁。

🔗 [原文链接](https://github.com/langgenius/dify)

---

### lobehub/lobehub

- **来源**：github
- **日期**：2026-08-12
- **相关性**：🟢 0.95
- **标签**：`ai-agent`, `orchestration`, `workflow`, `open-source`, `multi-agent`

LobeHub 将 AI 智能体从工具提升为可编排的"员工"，通过团队化调度和报告机制，重新定义了人机协作的生产力边界。

🔗 [原文链接](https://github.com/lobehub/lobehub)

---
（后略，共 19 条）

==================== Telegram 预览（前 800 字） ====================
📚 <b>AI 知识库每日简报</b>（19 条）

📌 <a href="https://github.com/langgenius/dify"><b>langgenius/dify</b></a>
Dify 将 LLM 应用开发从代码工程转变为可视化配置，是 Agent 和 RAG 技术走向生产实践的关键桥梁。
📊 相关性：🟢 0.95 | 来源：github
#llm #agent #rag #workflow #opensource

📌 <a href="https://github.com/lobehub/lobehub"><b>lobehub/lobehub</b></a>
LobeHub 将 AI 智能体从工具提升为可编排的"员工"，通过团队化调度和报告机制，重新定义了人机协作的生产力边界。
📊 相关性：🟢 0.95 | 来源：github
#ai-agent #orchestration #workflow #open-source #multi-agent
（后略）
```

输出非空，Markdown 含标题/来源/日期/相关性徽标/标签/摘要/原文链接，Telegram 含 HTML `<a>` `<b>`
标记与 `#tag`。✅ 通过。

---

## 验收 3：publisher dry-run（无 `TELEGRAM_BOT_TOKEN`）

```bash
$ unset TELEGRAM_BOT_TOKEN TELEGRAM_CHAT_ID
$ python3 -c "
import asyncio
from distribution.publisher import publish_daily_digest
print(asyncio.run(publish_daily_digest()))
"
```

```
=== [dry-run] Telegram 推送预览 ===
📚 <b>AI 知识库每日简报</b>（19 条）

📌 <a href="https://github.com/langgenius/dify"><b>langgenius/dify</b></a>
Dify 将 LLM 应用开发从代码工程转变为可视化配置，是 Agent 和 RAG 技术走向生产实践的关键桥梁。
📊 相关性：🟢 0.95 | 来源：github
#llm #agent #rag #workflow #opensource
（预览截断，前 500 字）

[PublishResult(channel='telegram/dry-run', success=True, message_id=None, error=None)]
```

无 token 自动降级为 dry-run，`success=True`，`channel='telegram/dry-run'`，打印了推送预览。
✅ 通过。

---

## 验收 4：`daily_digest.py --dry-run`

```bash
$ unset TELEGRAM_BOT_TOKEN TELEGRAM_CHAT_ID
$ python3 daily_digest.py --dry-run
```

```
==================================================
  AI 知识库 — 每日摘要推送
==================================================
本次简报文章数：10
2026-08-14 21:08:50,691 [INFO] [dry-run] telegram 推送预览（前 500 字）：📚 <b>AI 知识库每日简报</b>（10 条）
...
=== [dry-run] Telegram 推送预览 ===
📚 <b>AI 知识库每日简报</b>（10 条）
...
2026-08-14 21:08:50,691 [INFO] [发布] 完成：1/1 个渠道成功

推送结果: 1/1 个渠道成功
  ✅ telegram/dry-run: OK
```

`RELEVANCE_THRESHOLD = 0.6` 过滤后从 19 篇里选出 10 篇最近入库的高质量文章（本地知识库全部
`relevance_score >= 0.75`，19 篇均达标，取 `DIGEST_ARTICLE_COUNT = 10` 篇上限），推送汇总
`1/1 个渠道成功`。✅ 通过。

---

## 验收 5：`knowledge_bot` 自测

```bash
$ python3 -m bot.knowledge_bot
```

```
=== 意图识别自测 ===
  '/search agent'      -> SEARCH       payload='agent'
  '/today'             -> TODAY        payload=''
  '/top 3'             -> TOP          payload='3'
  '/help'              -> HELP         payload=''
  '搜一下 RAG'            -> SEARCH       payload='RAG'
  '随便聊聊'               -> UNKNOWN      payload='随便聊聊'

=== Bot 消息处理自测 ===
输入: /search agent
回复: 🔍 找到 5 条与「agent」相关的内容：

📌 1. e2b-dev/awesome-ai-agents
   📊 0.95 | github | 2026-08-12 | ai-agents, awesome-list, autonomous-agents, frameworks, resources
📌 2. alibaba/page-agent
   📊 0.95 | github | 2026-08-12 | llm, browser-automation, gui-agent, natural-language, dom
📌 3. reworkd/AgentGPT
   📊 0.90 | github | 2026-08-12 | autonomous-agent, browser-based, task-planning, gpt, open-source
📌 4. langgenius/dify
   📊 0.95 | github | 2026-08-12 | llm, agent, rag, workflow, opensource
📌 5. bytedance/deer-flow
   📊 0.95 | github | 2026-08-12 | agent, long-horizon, sandbox, workflow, open-source

输入: /today
回复: 🔍 找到 5 条与「今日入库」相关的内容：
（本地知识库最近一次入库是 2026-08-12，当前系统日期 2026-08-14，/today 按设计回退到
全库最近一次入库日期，返回真实数据而不是空列表）

输入: /top 3
回复: 🔍 找到 3 条与「Top 3」相关的内容：
1. langgenius/dify · 2. lobehub/lobehub · 3. bytedance/deer-flow（均 0.95 分）

输入: /subscribe rag
回复: ✅ 已订阅关键词「rag」
```

`/search` `/today` `/top` 均返回真实检索结果（非空、非硬编码），`/subscribe` 落盘到
`data/subscriptions.json`：

```bash
$ cat data/subscriptions.json
{
  "cli-user": [
    "rag"
  ]
}
```

✅ 通过。

---

## 验收 6：crontab 已配置

```bash
$ crontab -l | grep -A1 "v4-daily-digest"
```

```
# v4-daily-digest
0 8 * * * cd "/Volumes/M4_Workspace/AIHarness/OpenCode/OpenCodeStudy/毕业设计/ai-knowledge-base/v4-production" && "/Users/huangcheng/ai-knowledge-base/.venv/bin/python" daily_digest.py >> "/Volumes/M4_Workspace/AIHarness/OpenCode/OpenCodeStudy/毕业设计/ai-knowledge-base/v4-production/logs/cron.log" 2>&1
```

每天 08:00 用项目 venv 的绝对路径 Python 运行 `daily_digest.py`，日志追加到 `logs/cron.log`。
写入前先 `grep -v "v4-daily-digest"` 清理了同名旧行（本次是首次配置，未发现旧行），保证幂等。
✅ 通过。

---

## 验收 7：本文档

本文件即验收 7 的交付物，记录了以上 6 项的命令与真实输出。

---

## 交付文件清单

| 文件 | 说明 |
|:--|:--|
| `distribution/formatter.py` | 格式化层：`load_articles` / `format_markdown` / `format_telegram`（纯函数） |
| `distribution/publisher.py` | 推送层：`PublishResult` / `BasePublisher` / `TelegramPublisher` / `publish_daily_digest`（异步并发，无 token 自动 dry-run） |
| `daily_digest.py` | 每日推送入口：过滤 `relevance_score >= 0.6` → 取最近 10 篇 → 推送 → 打印汇总，支持 `--dry-run` |
| `bot/knowledge_bot.py` | `KnowledgeSearchEngine`（加权检索）/ `SubscriptionManager`（订阅持久化）/ `KnowledgeBot`（意图识别 + 指令分发） |
| `openclaw/skills/daily-digest/SKILL.md` | 每日简报 Skill：触发词 + `--dry-run` 执行步骤 |
| `openclaw/skills/top-rated/SKILL.md` | 高分推荐 Skill：读 `index.json` → 排序去重取 Top 5 |
| crontab `# v4-daily-digest` | 每天 08:00 定时运行 `daily_digest.py` |

## 已知限制

- 飞书 / 钉钉推送渠道未实现（课件标注"自行开发，不强制"，且没有可用的 webhook 凭证做本地验证，
  超出本次任务范围）。
- `ruff check` 未能在本机网络条件下完成安装验证；代码已用 `black --line-length 100` 格式化，
  并手工核对了 AGENTS.md §6 的命名常量 / 类型注解 / docstring / 不用 `print` 做日志等要求。
- `requirements.txt` 里 `langgraph` 系依赖因网络问题未确认完整装好，但与本次交付的
  `distribution/` `bot/` `daily_digest.py` 无 import 关系，不影响上述 7 项验收。
