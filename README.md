# OpenCode Study — 系列技术博客

本仓库是 OpenCode 学习与实践的系列技术博客。基于 Wk1（第一周）的实际操作日志、对比实验和源码分析整理而成。

## 博客列表

| # | 文章 | 日期 | 核心主题 |
|---|------|------|----------|
| 1 | [安装配置实战指南](./Wk1/blogs/blog1_安装配置实战指南_2025-07-12.md) | 2025-07-12 | OpenCode 安装、国产模型配置、编排框架基础概念 |
| 2 | [无状态 vs 有状态——Agent 的核心抽象](./Wk1/blogs/blog2_无状态vs有状态_对比实验报告_2025-07-12.md) | 2025-07-12 | 裸 API 调用 vs OpenCode 编排的对比实验报告 |
| 3 | [读 OpenCode 源码：没有步数限制的循环](./Wk1/blogs/blog3_源码深度解析_编排循环_2025-07-12.md) | 2025-07-12 | processGeneration 主循环、流式事件、子 Agent、上下文压缩源码分析 |

## 背后的方法论

每篇博客的生成，都基于以下工作流：
1. 实际操作 → 2. 记录实验日志 → 3. 用约定的"vibe prompt"由 Claude/AI 扩写为技术专栏风格文章

文章的 prompt 模板（tech-blog-from-research）也记录在 Hermes Agent 的 skill 中，可复用。
