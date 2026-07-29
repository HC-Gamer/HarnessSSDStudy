# HarnessSSDStudy

> OpenCode 学习与实践系列 — 将 AI Agent 框架的实操经验整理为可读的技术博客。

---

## 博客索引

1. [OpenCode 安装与配置实战指南：给 Agent 开发者的一把趁手工具](blogs/blog1_安装配置实战指南_2025-07-12.md) *(2025-07-12)*

   从零开始搭建 OpenCode + 国产 DeepSeek 模型，理解配置与密钥分离的工程卫生，以及 Agent 编排框架的核心运行逻辑。

2. [写信 vs 对话：从一次裸 API 与 OpenCode 的对比实验，看懂 Agent 的核心抽象](blogs/blog2_无状态vs有状态_对比实验报告_2025-07-12.md) *(2025-07-12)*

   通过裸 API 调用与 OpenCode CLI 编排的对比实验，揭示有状态对话与无状态调用的本质差异。

3. [读 OpenCode 源码：一个「没有步数限制的循环」如何撑起 Agent 的全部智能](blogs/blog3_源码深度解析_编排循环_2025-07-12.md) *(2025-07-12)*

   逐层解析 processGeneration 主循环、流式事件、子 Agent 与上下文压缩，理解生产级 Agent 框架的心脏。

4. [AGENTS.md 不只是代码规范：用一份文件定义 AI 项目的全貌](Wk2/blogs/blog_agents_md_项目定义编写指南_2025-07-13.md) *(2025-07-13)*

   从零写一份 AGENTS.md 的五层结构——项目概述、角色分工、技术约束、验收指标、边界声明——让 AI 从「帮我写代码」进化到「帮我做项目」。

5. [给 AI 一本「员工手册」：AGENTS.md 如何驯服代码生成的随机性](Wk2/blogs/blog4_memory_vs_no_memory_2025-07-13.md) *(2025-07-13)*

   通过有 Memory 与无 Memory 的对比实验，验证 AGENTS.md 对 AI 代码质量的显著影响——9 个维度的差异证明了声明式配置不是锦上添花，而是工程级 AI 协作的必需品。

6. [三个 Agent 一个管线：从 PRD 到 Issue 到角色文件的 SDD 实践](Wk2/blogs/blog5_subagents_角色分工_2025-07-13.md) *(2025-07-13)*

   三 Agent 架构的分工设计——从高阶 PRD 展开为带依赖关系、验收标准和数据契约的 Issue 任务票，再到 Agent 配置文件的最小权限约束。

7. [Skill 封装 + V1 全流程：从零到知识条目的 3 步管线](Wk2/blogs/blog6_skill_封装与V1全流程_2025-07-13.md) *(2025-07-13)*

   两个 Skill 文件（github-trending + tech-summary）从设计到验证，以及 V1 全流程（采集→分析→归档）的完整输出——15 条 GitHub Trending 数据、15 份深度分析、15 个知识条目 JSON。

---

## 关于

- **作者**: HC-Gamer (patrick.huangchengai@gmail.com)
- **本文**: 由 AI 辅助生成
