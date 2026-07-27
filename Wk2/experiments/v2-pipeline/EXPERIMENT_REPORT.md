# Week 2 实验报告：Harness 工程实战

## 实验环境

| 项目 | 值 |
|------|-----|
| 时间 | 2026-07-27 |
| Python | 3.13 |
| 虚拟环境 | v2-pipeline/.venv |
| DeepSeek 模型 | deepseek-chat (via API) |
| Qwen 模型 | qwen-plus（未测试，Key 不可用）|
| 工作目录 | /Volumes/M4_Workspace/AIHarness/OpenCode/OpenCodeStudy/Wk2/experiments/v2-pipeline/ |

## 代码架构

```
v2-pipeline/
├── pipeline/
│   ├── __init__.py
│   ├── pipeline.py          (835行) — 四步流水线：采集→采集→AI分析→入库
│   ├── model_client.py      (683行) — 统一 LLM 客户端 + CostTracker
│   └── rss_sources.yaml     — 7 个RSS数据源配置
├── hooks/
│   ├── validate_json.py     — JSON 格式校验 Hook
│   └── check_quality.py     — 5 维度质量评分 Hook (满分100)
├── mcp_knowledge_server.py   — MCP Server (stdio JSON-RPC 2.0, 零依赖)
├── .github/workflows/daily-collect.yml — CI/CD 每日定时采集
└── knowledge/
    ├── articles/            — 30 篇入库知识条目
    └── raw/                 — 原始采集数据
```

## 实验 1：免费采集

### 执行命令

```
python pipeline/pipeline.py --sources github,rss --limit 5 --verbose
```

### 结果

| 指标 | 值 |
|------|-----|
| 总采集数 | 30 条 |
| 数据源成功率 | 5/7 (71%) |

### 各源详情

| 源 | 状态 | 数量 |
|----|:----:|:----:|
| GitHub Trending | ✅ | 5 |
| Hacker News (hnrss) | ✅ | 5 |
| Lobsters | ✅ | 5 |
| arXiv CL | ✅ | 5 |
| OpenAI Blog | ✅ | 5 |
| Simon Willison's Blog | ✅ | 5 |
| arXiv AI (export.arxiv.org) | ❌ | 0 (连接超时) |
| Hugging Face Blog | ❌ | 0 (403 Forbidden) |

### 分析

- GitHub Search API 限制 10 req/min（未认证），limit=5 可以安全调用
- arXiv AI 的 `export.arxiv.org/rss/cs.AI` 经常超时——建议加 `timeout=30` 并重试
- Hugging Face Blog 返回 403，可能加了反爬——需要用 User-Agent 伪装或换 API
- RSS 源整体稳定，5/7 = 71% 成功率在免费采集范畴可接受

## 实验 2：DeepSeek 分析 + CostTracker

### 执行命令

```
LLM_PROVIDER=deepseek DEEPSEEK_API_KEY=sk-550...292d \
  python pipeline/pipeline.py --sources github --limit 5 --provider deepseek --verbose
```

### 结果

| 指标 | 值 |
|------|-----|
| 调用次数 | 3 |
| 输入 Tokens | 1,109 |
| 成本 (CNY) | ¥0.0014 |
| 成本 (USD) | $0.0019 |
| 平均每次 | ¥0.00047 |

### 分析质量（GitHub 5 条 DeepSeek 分析）

- 摘要长度：74~136 字，达到 >50 字门槛
- 标签精准度：全部满分 15/15
- 技术深度评分：6/10（规则降级为 5/10，LLM 分析略高）
- 无空洞词违规
- 平均质量分：83.9~84.9/100，全 A 级

### 成本评估

按每日 30 条算：
- 日成本：¥0.0014 × 6 = ¥0.0084
- 月成本：¥0.0084 × 30 ≈ **¥0.25**（两毛五）

DeepSeek 在批量分析场景下成本极低，适合做默认提供商。

## 实验 3：Qwen 对比

**状态：SKIPPED** — 原因：`DASHSCOPE_API_KEY` 环境变量未设置。

> 按实验说明：*"如果未设置则跳过 Qwen 实验"*

如需补充对比，设置 Key 后运行：
```
DASHSCOPE_API_KEY=xxx python pipeline/pipeline.py --sources github --limit 5 --provider qwen --verbose
```

## 实验 4：Hook 校验

### JSON 格式校验

```
python hooks/validate_json.py knowledge/articles/*.json
```

| 指标 | 值 |
|------|:----:|
| 总文件 | 30 |
| 通过 | 30 |
| 失败 | 0 |
| 错误 | 0 |
| 通过率 | **100%** ✅ |

### 品质评分

```
python hooks/check_quality.py knowledge/articles/*.json
```

| 等级 | 数量 | 占比 |
|:----:|:----:|:----:|
| A (≥80) | 25 | 83% |
| B (60-79) | 5 | 17% |
| C (<60) | 0 | 0% |
| 平均分 | **80.4/100** | |

### 各源质量分布

| 源 | 平均分 | 等级 | 薄弱点 |
|----|:----:|:----:|--------|
| GitHub | 84.1 | A 级 | 摘要偏短(74-136字) |
| arXiv CL | 81.7 | A 级 | 技术深度全 5/10 |
| Hacker News | 81.1 | A 级 | 标签单一(all=llm) |
| OpenAI Blog | 81.3 | A 级 | 摘要机械(180字截断) |
| Simon Willison | 81.3 | A 级 | 同上 |
| Lobsters | 73.1 | B 级 | **摘要太短(28-46字)** |

### 发现的问题

1. **Lobsters 摘要过短**：5 篇全 B 级，摘要仅 28-46 字——RSS 源只给标题，没给正文，规则降级只能截标题
2. **技术深度全部偏低**：LLM 分析给 6/10，规则降级固定 5/10——缺乏代码样本或正文来支撑更高分
3. **标签同质化**：Hacker News 和 OpenAI Blog 全部被标为 "llm" 单一标签——Prompt 可能没有鼓励多样性

## 成本分析与路由策略建议

### 月估算

| 方案 | 月成本(CNY) | 说明 |
|------|:----------:|------|
| 全 DeepSeek | ¥0.25 | 30条/天，每次 5 条批量 |
| DeepSeek 每日 + Qwen 周末对比 | ¥0.30 | 少量 Qwen 调用做质量基准 |
| 全免费（规则降级） | ¥0 | 无 LLM 成本，但摘要质量下降 |

### 三档路由策略建议

```
if article.price == "free" and article.length < 200:
    → 规则降级 (keyword → tags)
elif article.source == "github":
    → DeepSeek (高性价比)
elif article.source == "arxiv":
    → Qwen (中文论文理解好)
else:
    → DeepSeek (default)
```

## 总结

### 已完成

- [x] pipeline.py 四步流水线（GitHub + RSS 采集 → AI 分析 → 入库）
- [x] rss_sources.yaml 7 源配置
- [x] mcp_knowledge_server.py MCP Server（3 tools: search/query/stats）
- [x] .github/workflows/daily-collect.yml CI/CD 定时任务
- [x] 实验 1: 30 条免费采集，5/7 源成功
- [x] 实验 2: DeepSeek 3 次调用，¥0.0014，成本极低
- [x] 实验 3: Qwen 对比 (skipped — 无 Key)
- [x] 实验 4: Hook 校验 — 100% JSON 通过，均分 80.4，83% A 级

### 待优化

1. arXiv AI 和 Hugging Face Blog 源修复（超时/403）
2. Lobsters 摘要质量问题——增加正文抓取或更换源
3. 标签多样性——优化 LLM Prompt，避免全部标记为 "llm"
4. Qwen 对比——配置 DASHSCOPE_API_KEY 后补充实验 3
5. CI/CD 验证——GitHub Actions 首次运行需要确认 workflow 权限

### 文件清单

| 文件 | 大小 | 功能 |
|------|:----:|------|
| pipeline/pipeline.py | 28KB | 四步流水线主脚本 |
| pipeline/model_client.py | 21KB | LLM 客户端 + CostTracker |
| pipeline/rss_sources.yaml | 1.3KB | 7 个 RSS 源 |
| hooks/validate_json.py | 9.5KB | JSON 格式校验 |
| hooks/check_quality.py | 16KB | 5 维质量评分 |
| mcp_knowledge_server.py | — | MCP stdio Server |
| .github/workflows/daily-collect.yml | — | CI/CD |
| EXPERIMENT_REPORT.md | — | 本报告 |
