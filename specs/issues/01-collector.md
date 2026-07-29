# Issue: 01-collector — 采集 Agent

## 职责
从 GitHub Trending 采集 AI 领域热门开源项目，输出结构化 JSON 到 `knowledge/raw/`。

## Depends On
无（首个 Agent）

## Acceptance Criteria

- [ ] 采集来源：GitHub Trending（https://github.com/trending）或 GitHub Search API
- [ ] 过滤条件：仅保留 topics 或 description 含 ai/llm/agent/ml 的项目
- [ ] 排除条件：排除 Awesome 列表、纯教程仓库、star 刷量仓库
- [ ] 条目数量：>= 15 条
- [ ] 去重规则：按 `full_name` 去重
- [ ] 排序规则：按 star 数降序
- [ ] 输出路径：`knowledge/raw/github-trending-YYYY-MM-DD.json`
- [ ] 输出格式：JSON 数组，每条含 `name`, `url`, `stars`, `description`, `language`, `topics`
- [ ] 摘要格式：中文，公式「项目名 + 做什么 + 为什么值得关注」
- [ ] 失败处理：失败时输出空数组，不抛异常

## Schema

```json
{
  "source": "github-trending",
  "skill": "github-trending",
  "collected_at": "2025-07-13T00:00:00Z",
  "items": [
    {
      "name": "repo-name",
      "url": "https://github.com/owner/repo",
      "summary": "项目名：做了什么，为什么值得关注（中文）",
      "stars": 1234,
      "language": "Python",
      "topics": ["ai", "llm"]
    }
  ]
}
```

## 权限
- 允许：Read, Grep, Glob, WebFetch
- 禁止：Write, Edit, Bash
- 注意：采集 Agent 不自写文件，由主 Agent 负责写入
