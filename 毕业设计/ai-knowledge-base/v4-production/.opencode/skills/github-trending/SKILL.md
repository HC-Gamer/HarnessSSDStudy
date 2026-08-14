---
name: github-trending
description: 当需要采集 GitHub 热门开源项目、获取 GitHub Trending 数据、搜索 AI 仓库时使用此技能。适用于知识库采集阶段。
allowed-tools:
  - Read
  - Grep
  - Glob
  - WebFetch
---

# GitHub 热门项目采集技能

## 使用场景
在知识库采集阶段，从 GitHub 搜索并采集 AI 领域热门开源项目。当用户要求"抓取热门项目"、"获取趋势仓库"、"采集开源项目"时自动触发。

## 执行步骤

### 第 1 步：搜索热门仓库
使用 GitHub Search API 搜索近 7 天创建、star > 100 的仓库：
```
GET https://api.github.com/search/repositories?q=created:>{7天前日期}+stars:>100&sort=stars&order=desc&per_page=30
```

### 第 2 步：提取仓库信息
提取以下字段：`name`, `full_name`, `html_url`, `description`, `stargazers_count`, `language`, `topics`

### 第 3 步：过滤
- **纳入**：AI/ML/LLM/Agent 相关、开发者工具、框架重大更新
- **排除**：Awesome 列表、纯教程、Star 刷量、无 README

### 第 4 步：去重
按 `full_name` 严格去重，只保留一条。

### 第 5 步：撰写中文摘要
公式：「项目名 + 做什么 + 为什么值得关注」
示例：「Llama Cookbook：Meta 官方 Llama 模型使用指南，涵盖微调到部署的最佳实践」

### 第 6 步：排序取 Top 15
按 star 数降序排列，取前 15 条。

### 第 7 步：输出 JSON
路径：`knowledge/raw/github-trending-{YYYY-MM-DD}.json`

```json
{
  "source": "github-trending",
  "skill": "github-trending",
  "collected_at": "2025-07-13T00:00:00Z",
  "items": [
    {
      "name": "owner/repo",
      "url": "https://github.com/owner/repo",
      "summary": "中文摘要",
      "stars": 1234,
      "language": "Python",
      "topics": ["ai", "llm"]
    }
  ]
}
```

## 注意事项
- GitHub API 未认证限频 10 次/分钟（认证据 30 次/分钟）
- 摘要必须是中文
- 不编造不存在的仓库
- 失败时返回空数组，不抛异常
