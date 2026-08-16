# HarnessSSDStudy

> OpenCode 学习与实践系列 — 将 AI Agent 框架的实操经验整理为可读的技术博客。

---

## 博客索引

### 📚 系列一：《Agent 设计模式之美》专栏消化（19/23 已完成，4 篇待写）

把极客时间黄佳专栏《Agent 设计模式之美》的 28 个设计模式，逐篇对照 Hermes Agent / 游戏项目 / Harness 工程实践消化成原创博客（目录 `blogs/agent-design-patterns/`）。

| # | 标题 | 日期 |
|:--:|------|:----:|
| 1 | [读完开篇词：我一直在用上一代语言描述下一代系统](<blogs/agent-design-patterns/blog1_开篇词范式转移_2025-07-17.md>) | 2025-07-17 |
| 2 | [双轴框架审视 Agent 系统：从概念到配置项](<blogs/agent-design-patterns/blog2_双轴框架审视Agent系统_2025-07-17.md>) | 2025-07-17 |
| 3 | [双轴为什么必须正交：当矩阵变成坐标系，模式才真正可用](<blogs/agent-design-patterns/blog3_双轴正交矩阵实战_2025-07-19.md>) | 2025-07-19 |
| 4 | [拿逆向五步法拆自己项目的源码：把 Hermes Agent 当标本解剖了](<blogs/agent-design-patterns/blog4_逆向五步法拆源码_2025-07-19.md>) | 2025-07-19 |
| 5 | [把 8 个 Agent 框架切开摆在一起看：5 个地基和 3 种工程性格](<blogs/agent-design-patterns/blog5_8框架横切3种工程性格_2025-07-19.md>) | 2025-07-19 |
| 6 | [Agent 设计模式的价值在哪里？——从一场企业案例拆解，回顾我踩过的坑](<blogs/agent-design-patterns/blog6_直播回放：企业案例拆解，Agent 设计_2026-07-24.md>) | 2026-07-24 |
| 7 | [Loop Engineering — 如何把 Agent 的循环工程化](<blogs/agent-design-patterns/blog7_Loop Engineering：如何把_2026-07-25.md>) | 2026-07-25 |
| 8 | [感知模块导论——从"喂什么"到"怎么喂"的工程哲学](<blogs/agent-design-patterns/blog8_感知模块导论：如何优雅设计 Agent 感知层_2026-07-26.md>) | 2026-07-26 |
| 9 | [上下文分诊——给 Agent 装一个急诊室分诊台](<blogs/agent-design-patterns/blog9_上下文分诊_2026-07-27.md>) | 2026-07-27 |
| 10 | [语义压缩——别让 Agent 在同一个坑里摔两次](<blogs/agent-design-patterns/blog10_语义压缩_2026-07-27.md>) | 2026-07-27 |
| 11 | [渐进发现——信息的觅食循环](<blogs/agent-design-patterns/blog11_渐进发现：信息的觅食循环_2026-07-28.md>) | 2026-07-28 |
| 12 | [多模态融合——数据在进模型之前，先决定它该长什么样](<blogs/agent-design-patterns/blog12_多模态融合：日志、SQL 和 PDF 一起进 Agent_2026-07-31.md>) | 2026-07-31 |
| 13 | [记忆模块导论——从草稿纸到长期记忆，建立 Agent 的经验沉淀秩序](<blogs/agent-design-patterns/blog13_记忆模块导论：从草稿纸到长期记忆，建立_2026-08-01.md>) | 2026-08-01 |
| 14 | [分层保留——给 Agent 的记忆建一套货架](<blogs/agent-design-patterns/blog14_分层保留：给 Agent 的记忆建一套货_2026-08-02.md>) | 2026-08-02 |
| 15 | [检索增强——Agent 的知识库和证据链](<blogs/agent-design-patterns/blog15_检索增强：Agent 的知识库和证据链_2026-08-03.md>) | 2026-08-03 |
| 16 | [长任务中别让 Agent 走丢——进度追踪的五个工程支架](<blogs/agent-design-patterns/blog16_进度追踪：长任务中别让 Agent 走丢_2026-08-04.md>) | 2026-08-04 |
| 17 | [失败日记：让 Agent 把摔过的跤变成本事](<blogs/agent-design-patterns/blog17_失败日记：让 Agent 把摔过的跤变成_2026-08-05.md>) | 2026-08-05 |
| 18 | [推理模块导论：让 Agent 想得清楚，也想得起来](<blogs/agent-design-patterns/blog18_推理模块导论：让 Agent 想得清楚_2026-08-06.md>) | 2026-08-06 |
| 19 | [思维链：给 Agent 的判断留下一条可检查的路径](<blogs/agent-design-patterns/blog19_思维链：给 Agent 的判断留下一条可_2026-08-07.md>) | 2026-08-07 |
| 番外 | [Harness 架构深度解析——看完才发现，Hermes Agent 就是个 Harness](blogs/agent-design-patterns/blog_harness_Harness架构深度解析_Hermes对照_2026-07-27.md) | 2026-07-27 |
| 20 | 复杂度路由 — 给 Agent 装上导航系统 | — |
| 21 | 并行探索 — 让多个假设同时跑 | — |
| 22 | 迭代假设验证 — 步步收紧答案 | — |
| 23 | 行动模块导论 — 从"想"到"做"的最后一步 | — |

### 🔧 系列二：OpenCode / Harness 学习系列（8 篇）

1. [OpenCode 安装与配置实战指南：给 Agent 开发者的一把趁手工具](blogs/harness-study/blog1_安装配置实战指南_2026-07-12.md) *(2026-07-12)*

   从零开始搭建 OpenCode + 国产 DeepSeek 模型，理解配置与密钥分离的工程卫生，以及 Agent 编排框架的核心运行逻辑。

2. [写信 vs 对话：从一次裸 API 与 OpenCode 的对比实验，看懂 Agent 的核心抽象](blogs/harness-study/blog2_无状态vs有状态_对比实验报告_2026-07-12.md) *(2026-07-12)*

   通过裸 API 调用与 OpenCode CLI 编排的对比实验，揭示有状态对话与无状态调用的本质差异。

3. [读 OpenCode 源码：一个「没有步数限制的循环」如何撑起 Agent 的全部智能](blogs/harness-study/blog3_源码深度解析_编排循环_2026-07-12.md) *(2026-07-12)*

   逐层解析 processGeneration 主循环、流式事件、子 Agent 与上下文压缩，理解生产级 Agent 框架的心脏。

4. [AGENTS.md 不只是代码规范：用一份文件定义 AI 项目的全貌](blogs/harness-study/blog_agents_md_项目定义编写指南_2026-07-13.md) *(2026-07-13)*

   从零写一份 AGENTS.md 的五层结构——项目概述、角色分工、技术约束、验收指标、边界声明——让 AI 从「帮我写代码」进化到「帮我做项目」。

5. [给 AI 一本「员工手册」：AGENTS.md 如何驯服代码生成的随机性](blogs/harness-study/blog4_memory_vs_no_memory_2026-07-13.md) *(2026-07-13)*

   通过有 Memory 与无 Memory 的对比实验，验证 AGENTS.md 对 AI 代码质量的显著影响——9 个维度的差异证明了声明式配置不是锦上添花，而是工程级 AI 协作的必需品。

6. [三个 Agent 一个管线：从 PRD 到 Issue 到角色文件的 SDD 实践](blogs/harness-study/blog5_subagents_角色分工_2026-07-13.md) *(2026-07-13)*

   三 Agent 架构的分工设计——从高阶 PRD 展开为带依赖关系、验收标准和数据契约的 Issue 任务票，再到 Agent 配置文件的最小权限约束。

7. [Skill 封装 + V1 全流程：从零到知识条目的 3 步管线](blogs/harness-study/blog6_skill_封装与V1全流程_2026-07-13.md) *(2026-07-13)*

   两个 Skill 文件（github-trending + tech-summary）从设计到验证，以及 V1 全流程（采集→分析→归档）的完整输出——15 条 GitHub Trending 数据、15 份深度分析、15 个知识条目 JSON。

8. [从线性管线到状态图：LangGraph StateGraph 实验报告](blogs/harness-study/blog7_langgraph_stategraph_实验报告_2026-07-29.md) *(2026-07-29)*

   把「采集→分析→组织」用 StateGraph 重写，验证共享状态、条件路由、反馈循环与成本四个维度；也记录了一个反面教材——评分函数基线正好等于门槛，导致三次实验全部报告满分。

---


1. [复杂度路由：一件事该消耗多少推理](blogs/agent-design-patterns/blog20_复杂度路由：一件事该消耗多少推理_2026-08-13.md) (2026-08-13)

   我家 Mac mini 上的 Hermes 有个挺有意思的调度规则：用户的问题默认路由给 Codex CLI，但只要�

1. [并行探索：一题多解，择优录取](blogs/agent-design-patterns/blog21_并行探索：一题多解，择优录取_2026-08-14.md) (2026-08-14)

   上周我的 UE5 项目遇到一个编译错误，我同时让 Codex 和 Claude Code 各诊断了一次。两个模型�

1. [迭代假设验证：用科学方法猜至证据的收敛](blogs/agent-design-patterns/blog22_迭代假设验证：用科学方法猜至证据的收敛_2026-08-15.md) (2026-08-15)

   昨晚 UE5 项目又编译失败了。按照我的老习惯，我立刻让模型"再试一次"——结果它在同一�

1. [行动模块导论：把任务安全地做好](blogs/agent-design-patterns/blog23_行动模块导论：把任务安全地做好_2026-08-16.md) (2026-08-16)

   今天下午 5 点，每日写博管线照常触发。第一步拉文章，API 返回 HTTP 200、`code: -1`、`column_ha
## 关于

- **作者**: HC-Gamer (patrick.huangchengai@gmail.com)
- **本文**: 由 AI 辅助生成
