# AI 知识库 · 三 Agent PRD v1.0

## 总流程

每天 UTC 0:00 触发 · collector → analyzer → organizer · 串行。
前一阶段成功后才能触发下一阶段。

```
collector (采集) → analyzer (分析) → organizer (整理)
     ↓                 ↓                   ↓
knowledge/raw/    (stdout JSON)     knowledge/articles/*.json
```

## Agent 职责

### Collector（采集 Agent）
- 从 GitHub Trending 抓取 Top 50 热门仓库
- 过滤 AI/LLM/Agent/ML 相关内容
- 输出 JSON 到 `knowledge/raw/github-trending-YYYY-MM-DD.json`

### Analyzer（分析 Agent）
- 读取 `knowledge/raw/` 最新采集数据
- 对每条内容做深度分析：摘要、亮点、评分、标签
- 输出带标注的结构化 JSON（stdout，不自写文件）

### Organizer（整理 Agent）
- 读取分析结果
- 与已有知识条目做去重检查（URL hash 去重）
- 每条格式化为标准 JSON，存入 `knowledge/articles/`

## 依赖关系

| Agent | 依赖上游 | 产出给下游 |
|-------|---------|-----------|
| collector | 无 | analyzer |
| analyzer | collector 输出 | organizer |
| organizer | analyzer 输出 | — |

## 开放问题（需 Issue 细化）

1. 上游失败下游怎么办？（跳过 / 重试 / 全部失败？）
2. 数据怎么传？（文件 vs TCP 消息 vs stdout？）
3. 重跑策略？（全量重跑 vs 增量？）
4. 进度追踪？（日志级别？）
5. 采集 Agent 没有 Write 权限，JSON 由谁写入？
