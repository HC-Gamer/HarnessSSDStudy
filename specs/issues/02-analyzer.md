# Issue: 02-analyzer — 分析 Agent

## 职责
读取 `knowledge/raw/` 最新采集数据，对每条内容进行深度分析：写摘要、提亮点、打评分、建议标签。

## Depends On
- `01-collector` — 需要采集数据作为输入

## Acceptance Criteria

- [ ] 输入源：读取 `knowledge/raw/` 最新的 `github-trending-*.json` 文件
- [ ] 每条分析包含：中文摘要（<= 50 字）
- [ ] 每条包含 2-3 个技术亮点（用事实说话，不空洞）
- [ ] 评分 1-10，附理由
- [ ] 评分有区分度：15 条中 9-10 分不超过 2 个
- [ ] 评分标准：9-10 改变格局, 7-8 直接有帮助, 5-6 值得了解, 1-4 可略过
- [ ] 每条建议 1-3 个标签
- [ ] 有趋势发现（共同主题、新概念）
- [ ] 不自写文件（stdout JSON），由主 Agent 或下游 Organizer 负责写入

## Schema

```json
{
  "source": "github-trending",
  "analyzed_at": "2025-07-13T00:05:00Z",
  "trends": ["共同主题 1", "趋势发现 2"],
  "items": [
    {
      "name": "repo-name",
      "summary": "中文摘要（<= 50 字）",
      "highlights": ["亮点 1", "亮点 2"],
      "relevance_score": 8,
      "score_reason": ".....的原因",
      "tags": ["tag1", "tag2"]
    }
  ]
}
```

## 权限
- 允许：Read, Grep, Glob, WebFetch
- 禁止：Write, Edit, Bash
