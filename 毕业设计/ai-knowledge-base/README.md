# AI 知识库 — 多智能体内容采集与分发流水线

> 毕业设计（基于 Harness 多智能体框架的 AI 知识库系统）
> V1 → V4 全版本演进，覆盖 规划 → 多智能体 → 生产级流水线 → 渠道分发

---

## ① 项目简介

一套**自运行的 AI 知识库流水线**：每日定时从多个信息源采集 AI/技术文章，经
**多智能体编排**（路由器 → 规划器 → 执行 Worker → 审核器 → 分发器）完成
抓取、清洗、筛选、去重、人工复核标记、格式化、多渠道发布，并内建
**成本守卫 / 安全三防线 / 评测与门禁**，做到低成本、可观测、可验收。

```
┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐
│  信息源   │→ │ 路由器    │→ │ 规划器    │→ │ Worker   │→ │ 审核器    │
│ RSS/API  │  │ Router   │  │ Planner  │  │ Extract  │  │ Reviewer │
└──────────┘  └──────────┘  └──────────┘  └──────────┘  └──────────┘
                                                        │
┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ▼
│  分发器    │← │ 格式化器  │← │ 人工复核  │← │ 校验门禁  │──┤
│ Publisher│  │Formatter │  │ HumanFlag│  │ Validate │  │
└──────────┘  └──────────┘  └──────────┘  └──────────┘  │
   │  │                                                   │
   ▼  ▼                ┌──────────────┐                   │
 钉钉 本地              │ 成本守卫 Cost │◄──────────────────┘
                       │ 安全三防线     │
                       │ 评测与门禁     │
                       └──────────────┘
```

## ② 快速开始

```bash
# 1. 克隆
git clone git@github.com:HC-Gamer/HarnessSSDStudy.git
cd HarnessSSDStudy/ai-knowledge-base   # 若仓库内路径不同，以实际为准

# 2. 配置
cp .env.example .env
# 编辑 .env，填 DEEPSEEK_API_KEY（必填），GITHUB_TOKEN / 钉钉 按需

# 3. 安装依赖（Python 3.12）
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r v4-production/requirements.txt

# 4. 跑一条（采集 5 条精简模式，成本优先）
cd v4-production
TARGET_COUNT=5 ./run.sh
# 或直接: python run.sh

# 5. 看结果
#   知识库: knowledge/articles/index.json + 各文章 md
#   日志:   logs/
```

### 钉钉群里查知识库

在钉钉群 @ 机器人即可检索（`/search <关键词>` / `/today` / `/top N` / `/subscribe` / `/help`）：

```bash
cd v4-production
pgrep -fl dingtalk    # 同一 app_key 只允许一个 Stream 实例，先确认没在跑
../.venv/bin/python3 -u openclaw/dingtalk_knowledge_bot.py \
    > /tmp/dingtalk_knowledge_bot.log 2>&1 &
```

日志出现 `endpoint is wss://...` 即连接成功。凭证放 `.env`（`DINGTALK_APP_KEY` / `DINGTALK_APP_SECRET`），
钉钉后台需把消息接收模式设为 Stream 模式。完整说明见
[`v4-production/docs/dingtalk-channel.md`](v4-production/docs/dingtalk-channel.md)。

## ③ 目录结构

```
ai-knowledge-base/
├── v3-multi-agent/        # V3 多智能体毕业设计 M1（13 项硬验收全过）
│   ├── patterns/          #   路由器/规划器/执行/审核 等模式实现
│   ├── pipeline/          #   工作流管线
│   ├── workflows/         #   LangGraph 工作流编排
│   ├── tests/             #   单元/集成测试
│   ├── validate.py        #   硬验收脚本（13 项）
│   └── M1_COMPLETION.md   #   M1 完成报告
├── v4-production/         # V4 生产级流水线（当前主版本）
│   ├── pipeline/          #   模型客户端、成本守卫、安全防线
│   ├── patterns/          #   router/supervisor/planner 等核心模式
│   ├── workflows/         #   LangGraph 工作流（含 human-in-the-loop 人工复核）
│   ├── distribution/      #   格式化器 + 分发器
│   ├── bot/               #   知识库检索 Bot（本地规则，不调 LLM）
│   ├── docs/              #   验收证据 + 钉钉渠道接入说明
│   ├── knowledge/         #   知识库存储（articles / raw / pending_review）
│   ├── openclaw/          #   OpenClaw 模型网关集成 + 钉钉 Stream 机器人
│   ├── scripts/           #   运维脚本
│   ├── tests/             #   测试（pytest 全绿）
│   ├── validate.py        #   验收门禁
│   ├── daily_digest.py    #   每日摘要
│   ├── requirements.txt
│   └── run.sh
├── docs/
│   └── evidence/          # 验收证据（23 项检查点 txt）
├── screenshots/           # 运行截图（39 张 PNG，终端风格渲染）
├── plans/                 # 任务书 / 规划
├── .env.example           # 环境变量模板（复制为 .env 填写）
└── README.md
```

## ④ 技术栈

| 领域 | 选型 |
|---|---|
| 语言 | Python 3.12 |
| 工作流编排 | LangGraph + langgraph-checkpoint-sqlite |
| 数据源 | RSS (feedparser) / HTTP (httpx) / YAML 配置 |
| 模型 | DeepSeek（默认）/ DashScope / OpenAI（可切换） |
| 网关 | OpenClaw（模型路由 + 成本治理） |
| 渠道 | 钉钉群机器人（Stream 模式，已接通知识库检索） |
| 测试 | pytest（全部钉死版本） |
| 工程 | .env 配置、pytest.ini、AGENTS.md、validate.py 门禁 |

## ⑤ 版本历史

| 版本 | 内容 | 状态 |
|---|---|---|
| V1 | 单机采集 → 清洗 → 入库的朴素流水线 | 完成 |
| V2 | 引入 LLM 清洗/筛选、成本估算雏形 | 完成 |
| V3 | 多智能体架构（路由器/规划器/执行/审核/分发），LangGraph 工作流，M1 13 项硬验收全过 | 完成 |
| V4 | 生产级：OpenClaw 网关、成本守卫、安全三防线、人工复核 HITL、格式化双格式、多渠道分发（钉钉已通/Telegram 预留）、验收 24 项检查点 | 完成（当前） |

## ⑥ 月度成本估算

> 以 DeepSeek 为例，按每日 1 次、TARGET_COUNT=15（标准模式）估算。

| 项 | 说明 | 月成本 |
|---|---|---|
| 采集+清洗 | 15 条/日，每条 ~2K tokens 入 + 1K 出 | ~¥3-6 |
| 多智能体审核 | 每轮 3 次模型调用（worker+reviewer+supervisor） | ~¥5-10 |
| 全量月成本 | 含 30 天运行 + 容错重试 | **¥10-20 / 月** |

> 成本守卫：`BUDGET_YUAN` 超预算自动熔断；TARGET_COUNT 5/15/30 三档调节成本与质量。

## ⑦ License

MIT License — 详见 [LICENSE](LICENSE)（若仓库未含 LICENSE 文件，默认 MIT）。

---

## 运行截图

以下截图由真实运行输出渲染（终端风格 PNG，见 `screenshots/`）：

| 检查点 | 截图 |
|---|---|
| 01 全流水线运行 | 01a-pipeline-run.png ~ 01i-pipeline-run.png |
| 02 LangGraph 工作流 | 02a-langgraph-workflow-run.png ~ 02c |
| 04 pytest 全绿 | 04-pytest-all-green.png |
| 05 成本守卫自测 | 05-cost-guard-selftest.png |
| 06 安全三防线 | 06-security-three-defenses.png |
| 07 评测报告 | 07-eval-test-report.png |
| 08 路由器模式 | 08-pattern-router.png |
| 09 路由器单测 | 09-router-unit-tests.png |
| 10 规划器模式 | 10-pattern-planner.png |
| 11 审核器五维 | 11-reviewer-5dim.png |
| 12 人工复核标记 | 12-human-flag.png |
| 13 校验门禁 | 13a-validate-schema-gate.png ~ 13b |
| 14 格式化双格式 | 14a-formatter-two-formats.png ~ 14b |
| 15 分发器试运行 | 15-publisher-dryrun.png |
| 16 每日摘要试运行 | 16-daily-digest-dryrun.png |
| 17 知识库机器人意图 | 17a-knowledge-bot-intent.png ~ 17b |
| 18 成本守卫熔断 | 18a-costguard-breaker.png ~ 18c |
| 19 环境变量权限 | 19-env-keys-permissions.png |
| 20 最小权限技能 | 20-skills-least-privilege.png |
| 21 依赖钉死 | 21-requirements-pinned.png |
| 22 知识库统计 | 22a-knowledge-store-stats.png ~ 22b |
| 23 OpenClaw 模型在线 | 23-openclaw-model-live.png |
| 24 钉钉桥在线 | 24-dingtalk-bridge-live.png |

---

## 验收 Checklist（16-1）

见 `docs/evidence/`（23 项检查点 txt 原文留证）：

- [x] 01 全流水线运行成功
- [x] 02 LangGraph 工作流可运行
- [x] 04 pytest 全绿
- [x] 05 成本守卫自测通过
- [x] 06 安全三防线
- [x] 07 评测报告
- [x] 08 路由器模式
- [x] 09 路由器单元测试
- [x] 10 规划器模式
- [x] 11 审核器五维评审
- [x] 12 人工复核标记
- [x] 13 校验 Schema 门禁
- [x] 14 格式化双格式输出
- [x] 15 分发器试运行
- [x] 16 每日摘要试运行
- [x] 17 知识库机器人意图识别
- [x] 18 成本守卫熔断
- [x] 19 环境变量权限收紧
- [x] 20 最小权限技能
- [x] 21 依赖版本钉死
- [x] 22 知识库存储统计
- [x] 23 OpenClaw 模型网关在线
- [x] 24 钉钉桥在线

> 说明：检查点 03 未单独成证（并入 01/02）；09/10 曾因 DeepSeek API 抖动 exit=1，
> 重试后通过，见 evidence/09-router-unit-tests.txt 与 10-pattern-planner.txt 实况。
