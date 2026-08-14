# AGENTS.md — AI 知识库助手 · 项目定义

> 本文档定义 AI 知识库系统的愿景、数据契约、Agent 分工与红线，供人类开发者和 AI Coding Agent 同等阅读执行。
> V1（Wk1）编写 → V2（Wk2）继承 → **V3（Wk3）当前版本** → V4（Wk4）继承。

---

## 1. 项目定义

**AI Knowledge Base** 是一个自动化的技术情报系统：每天从 GitHub Trending / Hacker News / RSS
采集 AI、LLM、Agent 领域的技术动态，经大模型分析结构化后存入本地 JSON 知识库，
再通过 Telegram / 飞书分发给使用者。

### 核心原则

- **自动化**：定时运行，正常路径无需人工介入
- **管线化**：规划 → 采集 → 分析 → 审核 → 修订 → 整理，每步职责单一、可单独优化
- **可验证**：每步输出结构化，段间有 schema 校验，端到端验收指标明确
- **有闸门**：质量不达标不入库，超预算立刻熔断，超轮次转人工

---

## 2. Agent 角色与分工

V3 是七节点多 Agent 工作流（`workflows/graph.py`），**一个 Agent 一个文件**：

| 节点 | 文件 | 职责 | 关键约束 |
|:--|:--|:--|:--|
| ① Planner | `workflows/planner.py` | 按目标量选三档策略 | 只规划不执行，不调 LLM |
| ② Collector | `workflows/collector.py` | GitHub / RSS 采集 | 入口必须 `sanitize_input` |
| ③ Analyzer | `workflows/analyzer.py` | 逐条 LLM 分析 | 只产出内容，不打质量分 |
| ④ Reviewer | `workflows/reviewer.py` | 5 维加权审核 | 只评估不修改；加权分由代码重算 |
| ⑤ Reviser | `workflows/reviser.py` | 按反馈定向修改 | 只修改不评估；改完必须回 Reviewer |
| ⑥ Organizer | `workflows/organizer.py` | 过滤去重 + 落盘（正常终点） | 出口必须 `filter_output` |
| ⑦ HumanFlag | `workflows/human_flag.py` | 兜底落盘（异常终点） | 不静默丢弃任何数据 |

另有两个通用设计模式演示（`patterns/`）：Router（意图路由）与 Supervisor（主管审核循环）。

三个生产防护模块（`tests/`）：CostGuard（预算熔断）、Security（注入 + PII + 限流 + 审计）、
Eval（范围断言 + LLM-as-Judge）。**它们必须挂在生产路径上** —— 写了不接入等于摆设。

### 三个 OpenCode 子 Agent（`.opencode/agents/`）

`collector.md` / `analyzer.md` / `organizer.md` —— V1 的手动流程版本，
与上面的工作流节点一一对应，保留用于交互式操作与对照。

---

## 3. 数据契约

### 3.1 知识条目 schema（`knowledge/articles/<id>.json`）

| 字段 | 类型 | 说明 |
|:--|:--|:--|
| `id` | str | `<source>-<YYYYMMDD>-<NNN>`，全局唯一 |
| `title` | str | 条目标题 |
| `source` | str | 来源标识（github / hackernews / rss 源名） |
| `source_url` | str | 原文链接，必须 http(s) |
| `summary` | str | 中文摘要 |
| `key_insight` | str | 一句话洞察 |
| `tags` | list[str] | 小写英文标签，3–5 个 |
| `keywords` | list[str] | 检索关键词，取 tags 前 3 |
| `category` | enum | `llm` \| `agent` \| `rag` \| `multimodal` \| `tools` \| `industry` |
| `relevance_score` | float | **0–1 浮点**（量纲见 §3.2） |
| `status` | enum | `draft` \| `published` \| `archived` |
| `fetched_at` / `analyzed_at` / `published_at` | str \| null | ISO 8601 时间戳 |
| `metadata` | dict | `{stars, language, author, upvotes, comments, collection_mode}` |

`knowledge/articles/index.json` 是全库索引，Wk4 的 Bot / Skill / formatter 以它为唯一入口。

### 3.2 `relevance_score` 量纲：统一 0–1

课件里这个字段在不同章节出现过 0–1、0–10、0–100 三种写法。本项目**一律用 0–1 浮点**：
`workflows/analyzer.py: _normalize_score()` 负责把模型的任意量纲归一，
`validate.py: validate_analyses_segment()` 把越界值判为硬错误。

注意与 Reviewer 的 5 维评分区分开：那是 **0–10** 的质量分，通过线 7.0，两者不是一回事。

### 3.3 工作流共享状态

`workflows/state.py: KBState`，恰好 9 个字段。改字段数会连带影响 V4 的继承检查，
改之前先读该文件顶部的演进表。

---

## 4. 技术约束

- **模型**：统一走 OpenAI 兼容 API（默认 DeepSeek），不微调；所有调用必须经
  `workflows/model_client.py`，不允许节点自己发 HTTP —— 那样会绕过记账与熔断
- **存储**：文件系统，JSON 元数据 + 索引，无数据库
- **运行**：Python 3.12 venv（系统 3.9 会因 PEP 604 语法直接 SyntaxError）
- **部署**：`run.sh` 手动触发 / cron 定时 / GitHub Actions

---

## 5. 红线（不可协商）

1. **密钥不硬编码、不入库、不进日志与产出**。只存 `.env`（已 gitignore）或环境变量，
   示例一律写 `sk-xxxxxxxx`
2. **不绕过 robots.txt**，不做高频抓取，采集失败按降级路径处理而不是重试打穿
3. **`published` 状态前必须经过审核**。工作流写盘一律 `status="draft"`
4. **不用 `print` 做日志**，用 `logging`（CLI 的用户界面输出除外）
5. **带循环的编排必须有次数上限和熔断标记**，成本按安全项管理
6. **不存储网页全文**，只存结构化摘要（报告式通信）

---

## 6. 编码规范

- PEP 8，`black --line-length 100`，`ruff` 通过
- `snake_case` 函数与变量，`UPPER_SNAKE` 常量，Google 风格 docstring，全量类型注解
- **禁止魔法数字与魔法字符串**：阈值、价格、超时、白名单一律提为模块级命名常量
- **不重复实现已有能力**：LLM 调用走 `pipeline/model_client.py`，RSS 采集走
  `pipeline/rss_collector.py`，段间校验走 `validate.py`。要另写一份先说明为什么不能复用
- 日志用 lazy `%` 格式化，不在 `logger.info()` 里拼 f-string
- 每个模块至少有 `__main__` 自测或对应 pytest 用例
- 没跑过的结论不写进报告；每条「已验证」都要能追溯到一条断言或一段实测输出

---

## 7. 不做什么（边界）

- 不做用户认证与权限系统
- 不做实时通知（只有定时推送与被动查询）
- 不存储原始网页全文
- 不训练 / 微调模型
