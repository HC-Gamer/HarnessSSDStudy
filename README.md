# HarnessSSDStudy

> OpenCode 学习与实践系列 + Agent 设计模式之美系列 — 将 AI Agent 框架的实操经验整理为可读的技术博客。

---

## 博客索引

1. [OpenCode 安装与配置实战指南：给 Agent 开发者的一把趁手工具](blogs/harness-study/blog1_安装配置实战指南_2025-07-12.md) *(2025-07-12)*

   从零开始搭建 OpenCode + 国产 DeepSeek 模型，理解配置与密钥分离的工程卫生，以及 Agent 编排框架的核心运行逻辑。

2. [写信 vs 对话：从一次裸 API 与 OpenCode 的对比实验，看懂 Agent 的核心抽象](blogs/harness-study/blog2_无状态vs有状态_对比实验报告_2025-07-12.md) *(2025-07-12)*

   通过裸 API 调用与 OpenCode CLI 编排的对比实验，揭示有状态对话与无状态调用的本质差异。

3. [读 OpenCode 源码：一个「没有步数限制的循环」如何撑起 Agent 的全部智能](blogs/harness-study/blog3_源码深度解析_编排循环_2025-07-12.md) *(2025-07-12)*

   逐层解析 processGeneration 主循环、流式事件、子 Agent 与上下文压缩，理解生产级 Agent 框架的心脏。

4. [给 AI 一本「员工手册」：AGENTS.md 如何驯服代码生成的随机性](blogs/harness-study/blog4_memory_vs_no_memory_2025-07-13.md) *(2025-07-13)*

   深入探讨为什么 AI 编程工具需要一个项目级「员工手册」——AGENTS.md 从常见陷阱（环境变量污染、错误的绝对路径）中吸取教训，定义出边界清晰、可复现的项目上下文。

5. [三个 Agent 一个管线：从 PRD 到 Issue 到角色文件的 SDD 实践](blogs/harness-study/blog5_subagents_角色分工_2025-07-13.md) *(2025-07-13)*

   实践 Subagent-Driven Development（SDD）：将 AI 知识库系统拆分为采集、分析、归档三个独立 Agent，各自拥有专属角色文件，实现「专人专事」的流水线协作。

6. [Skill 封装 + V1 全流程：从零到知识条目的 3 步管线](blogs/harness-study/blog6_skill_封装与V1全流程_2025-07-13.md) *(2025-07-13)*

   将 V1 管线的核心经验封装为可复用的 Skill——解决 AI 行为不稳定的问题，让每次执行都是可预测的三步走：采集→清洗→摘要。

7. [AGENTS.md 不只是代码规范：用一份文件定义 AI 项目的全貌](blogs/harness-study/blog_agents_md_项目定义编写指南_2025-07-13.md) *(2025-07-13)*

   一份好的 AGENTS.md 应该像产品 PRD 一样定义项目愿景、Agent 角色分工、验收指标和不做什么的边界——而不只是风格指南。

---

## Agent 设计模式之美系列

> 黄佳《Agent 设计模式之美》专栏读后感 — 用真实项目对号入座，把 28 个模式变成自己能用的架构语言。

1. [读完开篇词，我发现自己一直在用上一代语言描述下一代系统](blogs/agent-design-patterns/blog1_开篇词范式转移_2025-07-17.md) *(2025-07-17)*

   范式转移不是选择题——你不选择进入新范式，就会被旧范式卡住。读完开篇词才意识到，我一直在用确定性系统的语言描述概率性系统。

2. [用双轴框架审视我的 Agent 系统：从概念到配置项](blogs/agent-design-patterns/blog2_双轴框架审视Agent系统_2025-07-17.md) *(2025-07-17)*

   把双轴框架的七个认知功能和六种执行拓扑，逐个对号入座到我的 Hermes Agent 配置里——感知在补课，治理刚起步，协作还没真正开始。

3. [双轴为什么必须正交：当矩阵变成坐标系，模式才真正可用](blogs/agent-design-patterns/blog3_双轴正交矩阵实战_2025-07-19.md) *(2025-07-19)*

   双轴不是分类表而是坐标系——42 格矩阵、Pattern Selection Card 选型三步法、双轴评审五问、Compound Error 公理，以及为什么空格比填满更有信息量。

4. [拿逆向五步法拆自己项目的源码：我把 Hermes Agent 当标本解剖了](blogs/agent-design-patterns/blog4_逆向五步法拆源码_2025-07-19.md) *(2025-07-19)*

   用 Detect → Classify → Filter → Map → Verify 五步法解剖 Hermes Agent 源码——从 tool_call 开始找主循环、三组 grep 交叉定位、七个组件归入七脉、三个深度 Matrix Map 到双轴格，以及为什么从 main() 开始读源码是错的。

5. [把 8 个 Agent 框架切开摆在一起看：5 个地基和 3 种工程性格](blogs/agent-design-patterns/blog5_8框架横切3种工程性格_2025-07-19.md) *(2025-07-19)*

   用同一把刀横切 Claude Code / Codex CLI / Aider / OpenCode / OpenClaw / Hermes / DeerFlow / OpenHands——提炼 5 个共同地基（主循环、上下文、工具、账本、治理）和 3 种工程性格（开发者工具、个人助手、重执行），以及如何用分类表做选型决策。

---

## 关于

- **作者**: HC-Gamer (patrick.huangchengai@gmail.com)
- **本文**: 由 AI 辅助生成
