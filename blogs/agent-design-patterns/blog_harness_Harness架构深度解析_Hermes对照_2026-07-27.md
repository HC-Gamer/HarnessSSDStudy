
# Harness 架构深度解析：看完才发现，Hermes Agent 就是个 Harness

> 来源：极客时间《Claude Code 工程化实战》· 热点加餐｜Harness 架构深度解析（黄佳）

## 为什么这篇值得读

我之前一直没认真想过一个问题：**Claude Code 本身是什么？**

不是 Claude 模型——模型是 API，任何人都能调。也不是简单的命令行工具——同一个 Claude Sonnet，裸 API 调用和通过 Claude Code 调用，表现差距大到离谱。

答案藏在一个词里：**Harness（智能体编排框架）**。

Anthropic 官方定义：

> Claude Code serves as the **agentic harness** around Claude: it provides the tools, context management, and execution environment that turn a language model into a capable coding agent.

翻译：Claude Code 是一个包裹在模型外面的运行时基础设施。它提供工具、上下文管理、执行环境，把只会说的大脑变成能干活的手脚。

读完这篇我意识到——**我每天在用的 Hermes Agent，本质上也是个 Harness。**

## 核心框架：Model + 5 个组件

原文把 Harness 拆成了这张图：

```
        ┌─────────────────────────┐
        │        HARness           │
        │  ┌──────┐  ┌──────────┐ │
        │  │Tools │  │ Context  │ │
        │  └──────┘  └──────────┘ │
        │      ↘    MODEL    ↙     │
        │  ┌──────┐  ┌──────────┐ │
        │  │Memory│  │  Hooks   │ │
        │  └──────┘  └──────────┘ │
        │       Permissions        │
        └─────────────────────────┘
```

五个组件围着模型转，模型不直接接触外部世界——所有交互都通过 Harness 中转。

**Harness 是模型和现实之间的唯一接口。**

下面我把这五个组件逐个对照到 Hermes Agent，看看这个"自制的 Harness"做到了什么程度。

## 对照 Hermes Agent：一个活生生的 Harness

### 1. Tools（工具）—— 模型的手脚

**Claude Code 的设计哲学：少而精。** 只提供 5 类原子操作——Read、Write、Edit、Bash、Grep。复杂行为是原子操作的组合涌现。Bash 是"图灵完备的逃逸舱"——通过它，Agent 能做的事等于操作系统的上限。

**Hermes Agent 的工具集：**

| 原子操作 | Claude Code | Hermes Agent |
|---------|------------|-------------|
| 读 | Read | `read_file` |
| 写 | Write/Edit | `write_file`, `patch` |
| 搜索 | Grep/Glob | `search_files` |
| 执行 | Bash | `terminal` |

但 Hermes 不止这些。它还多了一层 Claude Code 没有的能力：

- **桌面控制** — `cua_driver` 系列（click、type_text、scroll、get_window_state），能操控 macOS GUI。Claude Code 只能在终端里干活。
- **浏览器控制** — `browser_navigate`、`browser_click`、`browser_type`，能直接操作网页。
- **MCP 工具集成** — 原生 MCP client，把外部 MCP server 的工具自动发现并注入。
- **技能系统** — `skill_view`、`skill_manage`，可复用的程序化知识。

Claude Code 的"少而精"够用但受限。Hermes 的工具面更广——从终端到桌面到浏览器，覆盖了三个交互面。

### 2. Context（上下文）—— 模型的记忆加载器

原文最精彩的部分是 **上下文压缩策略**：

```
对话历史（180K tokens）
    │
    ▼ 压缩触发（达到 92% 窗口）
┌────────────────────────────┐
│ 保留：最近的消息（完整）      │
│ 压缩：早期消息 → 摘要        │
│ 重注入：CLAUDE.md 内容       │
│ 重注入：系统提示词            │
│ 重注入：工具定义              │
└────────────────────────────┘
    │
    ▼
压缩后（~80K tokens）→ 继续工作
```

关键设计：**CLAUDE.md、系统提示词、工具定义在每次压缩后都重新注入。** 这就是为什么 CLAUDE.md 配置那么"持久"——不是模型记住了，是 Harness 每次都塞回去。

**Hermes Agent 的上下文管理：**

Hermes 没有自动压缩，但有**两段式持久上下文**：

```
┌──────────────────────────────────┐
│ MEMORY.md（95% capacity）         │
│  — 技术配置（UE5 路径、cron）      │
│  — 工作流规则（skills 触发条件）    │
│  — 踩坑记录（Pitfalls）           │
│  — 字符数追踪（2109/2200 chars）  │
├──────────────────────────────────┤
│ USER.md（97% capacity）           │
│  — 行为偏好（action-first）       │
│  — 语言偏好（中文回答）            │
│  — 命令速记（"用Opus辅助编译"）    │
└──────────────────────────────────┘
```

每次对话启动时，这两个文件作为 system prompt 的一部分注入——和 Claude Code 的 CLAUDE.md 重注入逻辑完全一样。

但 Hermes 缺了一个能力：**运行时压缩。** MEMORY.md 是静态的，对话过程中不会因为上下文膨胀而自动摘要压缩。这是 Claude Code 的 Harness 明显更强的地方。当 Hermes 跑长任务时（比如连续写 10 篇博客），对话历史会越来越大，没有自动压缩意味着模型迟早开始"遗忘"早期上下文。

这是 Hermes 的下一个明显改进点。

### 3. Memory（记忆）—— 模型的长期存储

Claude Code 的 Memory 分两层：`CLAUDE.md`（显式记忆）+ `~/.claude/memory/`（隐式记忆，自动记录偏好）。

**Hermes 的记忆系统：**

- **MEMORY.md** = CLAUDE.md 等价物。存储技术配置、工作流规则、Pitfalls。有显式的字符数追踪（95% 容量提醒），逼迫定期整理。
- **Skills** = 程序化记忆。把成功的工作流保存为可复用的 SKILL.md，比 CLAUDE.md 的纯文本规则更进一步——skill 带有触发条件、步骤指令、Pitfalls，可以自动加载执行。
- **没有隐式记忆。** Hermes 不会自动从对话中提取偏好和规则写入 MEMORY。必须我手动让它更新。

技能系统是 Hermes 的一个独特优势——Claude Code 的 CLAUDE.md 是"声明式知识"，Hermes 的 Skills 是"程序式知识"。但不自动积累隐式记忆也是个明显的差距。

### 4. Hooks（钩子）—— 模型的神经反射

Claude Code 的 Hooks 是事件驱动的自动化：工具执行前后触发自定义逻辑。比如保存文件前自动格式化。

**Hermes 没有显式的 Hooks 系统。** 但它有一个近似的机制：**Skills 的自动加载规则。**

Persona 里写的规则——比如"如果用户提到 codex CLI，加载 codex skill 而不是 claude-code skill"——就是 Hook 的雏形。只不过它是基于关键词匹配而非事件驱动。

如果要给 Hermes 加真正的 Hooks，最自然的做法是：工具调用前后触发 skill。比如每次 `terminal` 返回非零 exit code 时自动加载 `systematic-debugging` skill。这个设计空间很大。

### 5. Permissions（权限）—— 模型的安全围栏

Claude Code 分三档：自由使用、需要审批、完全禁止。

**Hermes 的权限模型：** 工具级别的访问控制。`cua_driver` 的桌面操控工具需要显式授权。MCP 工具可以通过配置开关。但没有 Claude Code 那种细粒度的"允许 Bash 但只允许 `npm test`"的命令白名单。

## Agentic Loop —— 一模一样的心跳

原文说 Agentic Loop 是 Harness 的发动机：

```
用户指令 → 模型推理 → 工具调用 → 结果回注 → 继续推理 → ...
```

Hermes 的行为模式完全一致：

```
用户输入 → 模型 think → tool_call → 工具执行 → 结果注入 → 下一轮 think → ...
```

这不是巧合。这是所有 Harness 的共性——Harness 本质上就是一个循环泵，不断地把工具执行结果泵回模型的上下文。

## 我补充的：Hermes 比 Claude Code 多了什么

用原文的框架审视下来，Hermes 在两个维度上超越了 Claude Code：

**1. 桌面操控（CUA Driver）**

Claude Code 只能活在终端里。Hermes 能操控 macOS 桌面——打开 App、点击按钮、输入文字、滚动窗口。这意味着它能把任何 GUI 应用变成"可编程的"。

这个能力在真实工作流里价值巨大——比如用 Safari 从极客时间获取文章、用终端执行脚本、用 Finder 管理文件，全在一个 Agent 里串起来。

**2. 技能系统（Skills）**

Claude Code 的 CLAUDE.md 是被动的知识库。Hermes 的 Skills 是主动的程序化记忆——带触发条件、步骤指令、Pitfalls 和版本管理。每次解决一个复杂问题后保存为 skill，下次遇到同类任务自动加载。

这是 Agent"从经验中学习"的基础设施。

## Hermes 缺了什么

反过来，跟 Claude Code 比，Hermes 有两个明显的短板：

**1. 运行时上下文压缩**

MEMORY.md 是静态快照。长对话会膨胀。没有自动摘要压缩，长任务的质量会随着 token 用尽而下降。这是 Hermes 最需要补的课。

**2. 隐式记忆**

Claude Code 会自动从对话中提取偏好存入 `~/.claude/memory/`。Hermes 只能靠我手动要求它更新 MEMORY.md。自动化程度不够。

## 总结

这篇文章让我看清了一件事：**我每天在"调教"的不是一个聊天机器人，而是一个 Harness。**

`hermes config`、写 persona、维护 MEMORY.md、保存 skill——这些操作的本质上和配置 Claude Code 的 CLAUDE.md、Hooks、Permissions 是一回事。都是在调 Harness 的参数，让同一个模型在同一套工具和上下文的加持下表现出更好的工程能力。

2026 年 Harness 比 Model 更重要——这个判断我深有体会。换了几个模型（Claude、DeepSeek、GPT），真正决定产出质量的不是模型本身，是 Harness 的配置——MEMORY.md 里存了多少规则、Skills 覆盖了多少场景、工具集够不够用。

**写代码的时代过去了，写规范的时代来临了。** 这不是口号，是我过去两个月每天在做的事。

---

*参考：[极客时间《Claude Code 工程化实战》· 热点加餐｜Harness 架构深度解析](https://time.geekbang.org/column/intro/1398)（黄佳）*
