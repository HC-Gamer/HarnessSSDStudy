# HarnessSSDStudy

> OpenCode 学习与实践系列 — 将 AI Agent 框架的实操经验整理为可读的技术博客。

---

## 学习进度

课程《Agent 设计模式之美》Harness 工程实战，一周四节。

| 周 | 节 | 主题 | 课件 | 实验 | 博客 | 状态 |
|:--:|:--:|------|:----:|:----:|:----:|------|
| [Wk1](Wk1/) | 1-4 | AI 编程范式转换 / Memory 工程 / Sub-Agents 角色分工 / Skills 能力封装 | ✅ | ✅ | ✅ 1-3 | 完成 |
| [Wk2](Wk2/) | 5-8 | Hooks 事件驱动 / MCP 外部数据 / CI-CD 定时触发 / 成本控制 | ✅ | ✅ V2 管线 | ✅ 4-6 | 完成 |
| [Wk3](Wk3/README.md) | 9-12 | 图编排（LangGraph StateGraph） | ❌ 未下载 | ✅ V3 StateGraph | ✅ 7 | 完成（含修复轮） |
| [Wk4](Wk4/README.md) | 13-16 | 推断：Agent 评估 / 可观测性 / 生产化 | ❌ 未下载 | ❌ | ❌ | **未开始** |

### 各周产出

| 周 | 主要产出 |
|:--:|---------|
| Wk1 | `AGENTS.md` 项目定义、`specs/` SDD 初稿、裸 API vs 框架对比、源码编排循环解析 |
| Wk2 | `Wk2/experiments/v2-pipeline/` —— 全自动知识管线（Hooks 校验 + 质量评分 + MCP Server + GitHub Actions 定时 + `CostTracker` 计量） |
| Wk3 | `Wk3/experiments/langgraph-pipeline/` —— StateGraph 图编排（条件路由 + 反馈循环 + 熔断 + SQLite checkpointer + 2×2 同题对照）。全套 12 次图执行 ¥0.0372 |
| Wk4 | 待开始，框架已建（`Wk4/README.md` 含主题推断与行动清单） |

### 规范与配置

| 文件 | 内容 |
|------|------|
| [`AGENTS.md`](AGENTS.md) | 项目定义、Agent 角色分工、技术约束、验收指标、编码规范索引 |
| [`specs/coding-standards.md`](specs/coding-standards.md) | 编码规范 v1.0 —— Python / JSON / Shell / Git / 测试 / 日志 / 安全 |
| [`specs/project-vision.md`](specs/project-vision.md) · [`specs/agents-prd.md`](specs/agents-prd.md) | SDD 愿景与 PRD |
| [`.opencode/opencode.jsonc`](.opencode/opencode.jsonc) | 项目级 OpenCode 配置（DeepSeek provider） |
| [`HarnessSSDStudyRules.md`](HarnessSSDStudyRules.md) | 仓库工作流规章 |

---

## 博客索引

1. [OpenCode 安装与配置实战指南：给 Agent 开发者的一把趁手工具](blogs/blog1_安装配置实战指南_2025-07-12.md) *(2025-07-12)*

   从零开始搭建 OpenCode + 国产 DeepSeek 模型，理解配置与密钥分离的工程卫生，以及 Agent 编排框架的核心运行逻辑。

2. [写信 vs 对话：从一次裸 API 与 OpenCode 的对比实验，看懂 Agent 的核心抽象](blogs/blog2_无状态vs有状态_对比实验报告_2025-07-12.md) *(2025-07-12)*

   通过裸 API 调用与 OpenCode CLI 编排的对比实验，揭示有状态对话与无状态调用的本质差异。

3. [读 OpenCode 源码：一个「没有步数限制的循环」如何撑起 Agent 的全部智能](blogs/blog3_源码深度解析_编排循环_2025-07-12.md) *(2025-07-12)*

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

## 关于

- **作者**: HC-Gamer (patrick.huangchengai@gmail.com)
- **本文**: 由 AI 辅助生成
