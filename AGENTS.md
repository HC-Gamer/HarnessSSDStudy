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

## 5. 不做什么（边界明确）

- 不做用户认证和权限
- 不做实时通知
- 不存储原始网页全文
- 不训练/微调模型
