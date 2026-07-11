# AI 知识库 · 项目愿景 v1.0

> Agent 协作完成「采集 → 分析 → 整理 → 发布」全自动知识管理

---

## 要做什么

### 1. 多源内容采集
- **范围**：聚焦 AI 领域，覆盖 GitHub Trending（AI 相关 repo）、Hacker News（AI 相关）、arXiv（AI/ML 论文）
- **数量**：每次运行抓取 top 20 条/来源，总计约 60 条/天
- **频率**：每日 1 次全量运行，可手动触发增量

### 2. Agent 管线化处理（三步分工）

| 阶段 | Agent | 职责 | 输出 |
|------|-------|------|------|
| **Collect** | 采集 Agent | 从各来源抓取原始数据 + meta 信息 | 原始 JSON 含 url/title/source/content |
| **Clean** | 清洗 Agent | 去噪、标准化、去重 | 清洗后的结构化数据 |
| **Summarize** | 摘要 Agent | 生成结构化摘要+标签+质量评分 | 最终知识条目 |

### 3. 输出知识条目
- **存储格式**：元数据 JSON + 正文 Markdown 并存
  - JSON 索引层：`id, title, url, source, summary, tags[], quality_score, fetched_at`
  - Markdown 内容层：正文全文，LLM 原生理解且人类可读
- **去重策略**：两级去重
  1. URL hash 严格去重（O(1) 零误报）
  2. 同来源内 SimHash 内容相似度去重（阈值 0.85）

### 4. 检索方式
- **v0.1**：文件系统浏览 + 关键词搜索（grep/fd），CLI 查询
- **后续**：可升级为 RAG 语义检索或 Web 界面

---

## 不做什么

- ❌ 不做用户注册和权限系统（单用户模式，存储层预留 user_id 字段）
- ❌ 不做实时推送和通知
- ❌ 不训练/微调模型，全部靠 API 调用
- ❌ 不存储原始网页全文，只存储结构化摘要（含原始 URL 引用）

---

## 边界 & 验收条件

| # | 条件 | 指标 |
|---|------|------|
| 1 | 全自动运行 | 每天定时执行，无需人工介入 |
| 2 | 失败重试 | 指数退避（1s → 60s，最多 3 次），3 次失败入 dead-letter queue |
| 3 | 单次全流程 | 采集 → 清洗 → 摘要 → 入库 <= 10 分钟 |
| 4 | 数据完整性 | 每条文摘必须含 title/url/source/summary/tags/quality_score |
| 5 | 去重准确率 | 无 URL 级重复，同来源内容去重误杀率 < 5% |

---

## 怎么验证

1. **准确率验收**：人工核验连续 3 天的输出，分析质量好评率 >= 80%
2. **稳定性验收**：连续运行 7 天无中断（网络超时触发重试不算中断）
3. **规模验收**：运行 30 天后知识库累计条目 >= 1500 条（约 50 条/天）
4. **可复现验收**：清空后重新运行，同一天数据产出结果一致

---

## 项目结构（建议）

```
ai-knowledge-base/
├── specs/               # 需求文档
│   └── project-vision.md
├── AGENTS.md            # Agent 行为定义（供 AI 读取）
├── agents/              # Agent 管线代码
│   ├── collector.py     # 采集 Agent
│   ├── cleaner.py       # 清洗 Agent
│   └── summarizer.py    # 摘要 Agent
├── data/                # 知识条目存储
│   ├── index.json       # JSON 索引
│   └── entries/         # Markdown 条目
├── config.yaml          # 抓取来源/频率等配置
└── run.sh               # 每日全量运行脚本
```

---

*Spec v1.0 · 经过 Specify → Clarify → Implement 闭环 · 2025-07-12*
