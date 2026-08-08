# AGENTS.md — AI Knowledge Base 项目定义

> 本文档定义 AI 知识库系统的项目愿景、架构和 Agent 行为规范，供 AI 开发者（人类或 Agent）阅读和执行。

---

## 1. 项目定义

**AI Knowledge Base** 是一个全自动的知识管理系统，每天从 GitHub Trending、Hacker News、arXiv 抓取 AI 相关内容，通过多 Agent 管线协作完成采集→清洗→摘要→入库，输出结构化知识条目。

### 核心原则
- **全自动**：每天定时运行，无需人工介入
- **管线化**：Collect → Clean → Summarize 三步分离，各自独立优化
- **可验证**：每步输出结构化，端到端验收指标明确

---

## 2. Agent 角色与分工

### 2.1 Collect Agent（采集）
- **职责**：从各来源抓取原始数据
- **输入**：来源配置（URL、API key、频率）
- **输出**：原始 JSON `{title, url, source, content, meta}`
- **失败处理**：指数退避 3 次 → dead-letter queue → 标记 failed

### 2.2 Clean Agent（清洗）
- **职责**：去噪、标准化、去重
- **输入**：Collect Agent 的原始输出
- **输出**：清洗后的结构化数据
- **去重**：URL hash 严格去重 + 同来源 SimHash（0.85 阈值）

### 2.3 Summarize Agent（摘要）
- **职责**：生成结构化摘要
- **输入**：Clean Agent 的清洗后数据
- **输出**：`{id, title, url, source, summary, tags[], quality_score, fetched_at}`
- **要求**：JSON 元数据 + Markdown 正文并存

---

## 3. 技术约束

- **模型**：全部通过 API 调用（DeepSeek / 国产模型），不微调
- **存储**：文件系统，元数据 JSON 索引 + Markdown 条目
- **运行环境**：CLI/终端，单用户模式
- **部署**：cron 定时触发或手动 `run.sh`

---

## 4. 验收指标

| 指标 | 标准 |
|------|------|
| 准确率 | 人工核验好评率 >= 80% |
| 稳定性 | 连续 7 天无中断 |
| 规模 | 30 天累计 >= 1500 条 |
| 去重 | 零 URL 重复，同源误杀率 < 5% |

---

## 5. 编码规范

**规范来源（唯一）**：[`specs/coding-standards.md`](specs/coding-standards.md)

所有代码与数据改动以该文件为准，人类和 Agent 同等适用。本节只给索引和最常踩的几条，
细则、验证命令、未落地项清单都在规范正文里。

### 5.1 索引

| 章节 | 内容 |
|------|------|
| §1 Python | 3.11+（实际 3.13）、black `--line-length 100`、ruff、全量类型标注、Google 风格 docstring |
| §2 JSON / 数据 | 知识条目 schema、`id` 格式 `<source>-<YYYYMMDD>-<NNN>`、`status` 枚举、标签词表 |
| §3 Shell | `#!/bin/bash` + `set -euo pipefail`、shellcheck、变量加引号 |
| §4 Git | Conventional Commits（`<type>(<scope>): <subject>`）、禁止 force push 到 `main` |
| §5 测试 | 模块内 `_self_test()` 为最低要求、doctest、pytest、纯函数覆盖率 ≥ 80% |
| §6 日志 | `logging.getLogger(__name__)`、lazy `%` 格式化、决策必须留痕 |
| §7 安全 | 密钥只存 `.env` / 环境变量、日志脱敏、不落网页全文、成本熔断 |
| §8 文档 | 实验报告固定结构、历史结论不覆盖、区分实测与推断 |
| §9 检查清单 | 提交前必跑的 5 条命令 |
| §10 未落地项 | 规范里写了但仓库还没做到的 6 项，避免被误读为现状 |

### 5.2 Agent 写代码时最容易违反的几条

1. **不重复实现已有能力**。LLM 调用走 `Wk2/experiments/v2-pipeline/pipeline/model_client.py`，
   RSS 采集走 `Wk3/experiments/langgraph-pipeline/rss_collector.py`，
   质量评分走 `Wk3/experiments/langgraph-pipeline/quality.py`。要另写一份先说明为什么不能复用。
2. **禁止魔法数字与魔法字符串**。阈值、价格、超时、黑名单一律提为模块级命名常量。
3. **日志用 lazy `%` 格式化**，不要在 `logger.info()` 里拼 f-string。
4. **密钥不进代码、注释、日志、产出、commit message**。示例只写 `sk-xxxxxxxx`。
5. **没跑过的结论不许写进报告**。每条「✅ 已验证」都要能追溯到一条断言或一段实测数字。
6. **带循环的编排必须有次数上限和熔断标记**，成本按安全项管理（规范 §7.4）。

---

## 6. 不做什么（边界明确）

- 不做用户认证和权限
- 不做实时通知
- 不存储原始网页全文
- 不训练/微调模型
