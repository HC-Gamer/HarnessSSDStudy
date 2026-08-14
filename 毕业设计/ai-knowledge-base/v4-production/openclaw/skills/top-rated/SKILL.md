---
name: top-rated
description: 用户问哪些文章分最高、推荐高分文章、top rated、最值得看的、评分最高的项目时使用。基于本地知识库，不需要联网。
allowed-tools:
  - Read
---

# 高分推荐

## 触发词

- 推荐 / 推荐几个 / 推荐几篇
- 最值得看的 / 最有价值的
- score 最高 / 评分最高 / 分最高
- top N / 前 N / top rated

## 做法

1. `Read knowledge/articles/index.json`（唯一入口，含 id / title / category /
   relevance_score / tags / collected_at 等精简字段）。
2. 在内存里按 `relevance_score` 降序排序。
3. 去重：同一个 `title` 只保留 `relevance_score` 最高的一条。
4. 默认取 Top 5，用户明确给了数字就用用户的数字。
5. 用项目的 `distribution/formatter.py::format_markdown` 逻辑作为格式参考
   （标题 + 来源 + 相关性 + 标签），输出简洁的 Markdown 列表：

   ```
   ⭐ 高分推荐 Top N：

   1. <title> · score <relevance_score> · <category>
      id: <id>
   ```

6. 把结果直接回复给用户。

## 禁止

- **禁止读取单篇全文** `knowledge/articles/<id>.json`：本技能只需要 `index.json` 一个文件就够，
  标题 / 分类 / 分数都在索引里，不要为了"更详细"多读文件。
- **禁止 Glob / Grep 目录**：不要尝试列目录或搜文件名，直接 `Read` 索引文件。
- **禁止猜测或编造分数**：`relevance_score` 必须来自 `index.json` 里的真实值，不允许估算、四舍五入到整数或凭印象排序。
- **禁止返回 relevance_score < 0.85 的条目**：低于此线不算"高分"，宁可少给条目也不能凑数。
- 找不到 `index.json`，如实告知用户"知识库索引缺失"，不要编造文章列表。
