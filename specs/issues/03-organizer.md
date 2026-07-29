# Issue: 03-organizer — 整理 Agent

## 职责
将分析结果整理为标准知识条目，做去重检查，格式化为 JSON 存入 `knowledge/articles/`。

## Depends On
- `02-analyzer` — 需要分析结果作为输入

## Acceptance Criteria

- [ ] 输入源：接收 Analyzer 的分析结果（stdout JSON）
- [ ] 与 `knowledge/articles/` 已有条目做去重检查（按 `source_url` 的 URL hash）
- [ ] 每条格式化为标准 JSON，包含 `id`, `title`, `source_url`, `summary`, `tags`, `status`, `analysis`
- [ ] 文件命名：`{date}-{source}-{slug}.json`
- [ ] 文件位置：`knowledge/articles/`
- [ ] `status` 可选值：`draft` / `reviewed` / `published`（初次均为 `draft`）
- [ ] `id` 格式：`YYYY-MM-DD-source-slug`
- [ ] 每个条目单独的 JSON 文件（不合并）

## Schema

```json
{
  "id": "2025-07-13-github-repo-name",
  "title": "项目全名",
  "source": "github-trending",
  "source_url": "https://github.com/owner/repo",
  "collected_at": "2025-07-13T00:00:00Z",
  "summary": "中文摘要（不超过 100 字）",
  "analysis": {
    "tech_highlights": ["亮点 1", "亮点 2"],
    "relevance_score": 8,
    "score_reason": "评分理由"
  },
  "tags": ["ai", "llm"],
  "status": "draft"
}
```

## 权限
- 允许：Read, Grep, Glob, Write, Edit
- 禁止：WebFetch, Bash
