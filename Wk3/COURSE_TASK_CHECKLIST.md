# Wk3 课内任务对照表

> 生成日期：2026-08-08
> 目的：把「课程要求做的」和「我们实际做了的」摆在一起，找出遗漏。

---

## 0. 先说清楚这份表的证据等级

课件本身**仍然没拿到**。这份表是三路信息合并的结果，每一路的可信度不同，
读的时候请对照下面的标记：

| 标记 | 含义 |
|:----:|------|
| **【实测】** | 从本仓库文件直接核实，可复现 |
| **【已核实】** | 外部来源，且与本地已有文件交叉验证一致 |
| **【推断】** | 从课程结构规律外推，**可能错**，拿到课件要改 |

### 获取课件的三次尝试与结果

| # | 方法 | 结果 |
|:-:|------|------|
| 1 | 检查本地 `Wk3/courseware/`、`Wk3-tasks/`、`Wk3/notes/` | **全部不存在**。Wk3 目录下只有 `README.md` + `.venv/` + `experiments/`【实测】 |
| 2 | `WebFetch https://u.geekbang.org/subject/lesson/100138101` | **失败**。未登录只返回站点外壳，正文仅「极客时间训练营-让优秀的人一起学习」一行【实测】 |
| 3 | WebSearch 第三方课程目录页 | **成功拿到课节标题**，见下节【已核实】 |

第 3 路之所以敢标【已核实】而不是【推断】：它给出的第 1-8 节标题与本地
`Wk1-tasks/0{1..4}资料包/课件 第N节：*.pdf` 和 `Wk2/courseware/0{5..8}-*/` 的目录名
**逐字对应**（AI编程范式转换 / Memory工程 / Sub-Agents角色分工 / Skills能力封装 /
Hooks事件驱动 / MCP外部数据连接 / CICD定时触发 / 成本控制实战）。
8/8 命中，因此它对 9-16 节的说法可信。

另有一处独立佐证：`scripts/extract_course_tasks.sh:54` 里硬编码的展开目标是
`'Week 3 多 Agent 协作'` 和 `'Week 4 产品上线'`，是上一轮从真实页面上抄下来的字符串【实测】。

**仍然缺失的是每节课的「实操任务」清单**——那部分在登录后的课程页里，三路都没拿到。
下面表格中的任务栏因此标【推断】，推断依据是 Wk1/Wk2 每节 2-4 个实操任务的固定体例。

---

## 1. Wk3 = 第 3 周「多 Agent 协作架构」，第 9-12 节【已核实】

| 节 | 标题 |
|:--:|------|
| 09 | 多 Agent 设计模式 |
| 10 | LangGraph 工作流 |
| 11 | 自主规划与质量控制 |
| 12 | 生产级工程实践 |

> ⚠️ **根 `README.md` 和 `Wk3/README.md` 都把 Wk3 写成「图编排（LangGraph StateGraph）」。
> 那只是第 10 节。** 我们用一整周的力气做了四分之一节课的内容，另外三节基本没碰。
> 这是这次对照最主要的发现。

---

## 2. 对照表

### 第 9 节 · 多 Agent 设计模式

| 课内任务【推断】 | 是否完成 | 产出文件 | 备注 |
|------------------|:--------:|---------|------|
| 定义多个角色 Agent（职责 / 权限 / 输出格式） | ✅ | `.opencode/agents/{collector,analyzer,organizer}.md`、`specs/issues/0{1,2,3}-*.md` | Wk1 第 3 节就写好了，Wk3 没有新增 |
| 跑通顺序管道模式（A→B→C） | ✅ | `Wk3/experiments/opencode-subagent-v1/` | **2026-08-08 今天才第一次真跑**，见下方 §3 |
| 对比其他协作模式（supervisor / 并行 / 辩论 / 群聊） | ❌ | 无 | **完全没做。这是最大的遗漏。** 一周的多 Agent 课，只验证了最简单的一种拓扑 |
| Agent 间通信与状态传递机制对比 | ⚠️ | `EXPERIMENT_REPORT.md` 实验 3 | 标题叫「多 Agent 协作中的状态共享机制」，实际比的是 **LangGraph 共享 state vs 文件传递**，是编排层对比，不是多 Agent 拓扑对比 |
| 权限矩阵与越权验证 | ⚠️ | `Wk2/experiments/v1-pipeline/sub-agent-test-log.md` | 该日志写「越权行为：无 / 全部符合预期」，**今天实测推翻了这个结论**，见 §3 |

### 第 10 节 · LangGraph 工作流

| 课内任务【推断】 | 是否完成 | 产出文件 | 备注 |
|------------------|:--------:|---------|------|
| 用 StateGraph 重写线性管线 | ✅ | `experiments/langgraph-pipeline/langgraph_experiment.py` | 5 节点 3 入口 |
| TypedDict 定义共享 state | ✅ | 同上 | 含 `Annotated[list, operator.add]` 累加字段 |
| 条件路由（conditional edges） | ✅ | 同上 `decide_route` | 返回类型标了 `Literal` |
| 反馈循环（回边） | ✅ | 同上 rewrite → quality_check | 首轮回边指错节点，修复轮已纠正 |
| checkpoint 中断恢复 | ✅ | `results/checkpoint_recovery.md`、`sqlite_checkpointer.md`、`verify_sqlite_resume.py` | MemorySaver + SQLite 跨进程都验了 |
| V1 线性 vs V3 图编排同题对照 | ✅ | `results/v1v3_*.md`、报告的 2×2 表 | |
| time-travel / 分叉重放 | ❌ | 无 | 报告残留问题 #4 已列，只数了 checkpoint 条数 |

**这一节做得最扎实，甚至超出课程要求（2×2 对照、成本核算、评分函数样本集都是自己加的）。**

### 第 11 节 · 自主规划与质量控制

| 课内任务【推断】 | 是否完成 | 产出文件 | 备注 |
|------------------|:--------:|---------|------|
| 质量评分函数 | ✅ | `quality.py` | 含 `SCORING_SAMPLES` 已知好/坏样本集 |
| 质量门禁 + 不合格重写 | ✅ | `langgraph_experiment.py` `quality_check_node` | 2×2 实测门禁在 prompt 欠约束时值 +36 分 |
| 重写次数上限与熔断 | ✅ | `results/breaker_circuit_breaker.md` | `MAX_REWRITES=3` + `circuit_broken` 标记 |
| **自主规划：Agent 自行分解任务、决定下一步** | ❌ | 无 | **完全没做。** Wk3 的图是**静态预定义**的，`decide_route` 是硬编码 if/else，没有任何一步是模型自己规划出来的 |
| Plan-and-Execute / ReAct 循环 | ❌ | 无 | 同上 |
| 动态生成子任务 | ❌ | 无 | 同上 |

> **这一节丢了一半。** 「质量控制」满分，「自主规划」零分。
> 名字里带「自主」的部分，我们一个都没实现——图的形状是人写死的。

### 第 12 节 · 生产级工程实践

| 课内任务【推断】 | 是否完成 | 产出文件 | 备注 |
|------------------|:--------:|---------|------|
| 成本计量与预算 | ✅ | 报告成本段，全套 ¥0.0372 | 复用 Wk2 `CostTracker` |
| 失败降级与重试 | ✅ | `rss_collector.py`、`model_client.py` | 指数退避 3 次 → 降级 |
| 持久化 checkpoint | ✅ | `checkpoints.sqlite` | |
| 可观测性（trace / 决策留痕） | ⚠️ | `results/run_all.log`、state 里的 `path`/`score_history` | 有日志和路径记录，**没有结构化 trace/span** |
| **提交 V3 完整项目** | ⚠️ | `experiments/langgraph-pipeline/` | 有实验脚本，**没有可交付产品**：没有 `v3-pipeline/` 目录、没有 `run.sh`、没接 CI（`.github/workflows/` 里仍只有 V2 的两个）。对比 Wk2 第 8 节任务 4「提交 V2 完整项目」的交付标准，V3 没达到 |
| 权限隔离 / 沙箱 | ❌ | 无 | 报告残留问题 #2 已列 |
| 容器化 / 部署 | ❌ | 无 | |
| 单元测试与 CI lint | ❌ | 无 | `specs/coding-standards.md` §10 自己列为未落地项 1-4 |

---

## 3. 今天补做的：第一次真跑 OpenCode sub-agent 管线

**这条单独拎出来，因为它推翻了一份既有记录。**

`Wk2/experiments/v1-pipeline/run_v1_pipeline.py` 的模块 docstring 写着
「**模拟** Collector → Analyzer → Organizer 三步流程，**不依赖 OpenCode TUI**」，
`step1_collect()` 返回的是**函数体里硬编码的 15 条仓库字面量**（`openai/codex` stars=45200 等）【实测】。
也就是说：**V1 三 Agent 管线此前从未真正经过 OpenCode 执行**，
而 `sub-agent-test-log.md` 却以此写下了「权限验证 ⋯ 全部符合预期」。

2026-08-08 用 `opencode run --agent <name>` 真跑了一次三段管线，产出与日志在
`Wk3/experiments/opencode-subagent-v1/`。结果见该目录的 `RUN_REPORT.md`。
一句话结论：**管线跑通了，但那份「权限全部符合预期」的旧结论不成立**——
`.opencode/agents/*.md` 里的「权限」段是散文，OpenCode 不读它，实测越权 7 次。

---

## 4. 汇总

| 节 | 完成度 | 一句话 |
|:--:|:------:|--------|
| 09 多 Agent 设计模式 | 🟡 约 40% | 只验了顺序管道一种拓扑，且今天才第一次真跑 |
| 10 LangGraph 工作流 | 🟢 约 90% | 唯一做透的一节，缺 time-travel |
| 11 自主规划与质量控制 | 🟡 约 50% | 质量控制满分，**自主规划零分** |
| 12 生产级工程实践 | 🟡 约 45% | 成本/降级/checkpoint 有了，**V3 没有可交付形态**，无隔离无部署无测试 |

### 按优先级排的补做清单

| 优先级 | 待办 | 理由 |
|:------:|------|------|
| P0 | **补「自主规划」实验**：让模型自己产出执行计划并驱动图 | 第 11 节丢了一半，且这是「多 Agent」区别于「多函数」的核心 |
| P0 | **补多 Agent 拓扑对比**：supervisor / 并行 / 顺序 三选二做对照 | 第 9 节的正题 |
| P1 | **把 V3 做成可交付**：`Wk3/experiments/v3-pipeline/` + `run.sh` + 接 CI | 对齐 Wk2 第 8 节任务 4 的交付标准 |
| P1 | **给 `.opencode/agents/*.md` 补 frontmatter 让权限真生效** | 见 `opencode-subagent-v1/RUN_REPORT.md` |
| P2 | 修正 `Wk3/README.md` 与根 `README.md` 的主题描述 | 现在写的是第 10 节的标题，不是本周的标题 |
| P2 | time-travel 分叉重放 | 残留问题 #4 |
| P2 | 下载真实课件核对本表 | 本表的任务栏全是【推断】 |

---

## 5. 怎么拿到真课件

按可行性排序：

1. **手动下载**（最可靠）。登录 `u.geekbang.org/subject/lesson/100138101` →
   第 3 周 → 每节的「资料包」→ 按 Wk2 的约定放进 `Wk3/courseware/09-多Agent设计模式/` 等目录，
   每个目录放 `课件.pdf` + `课件.txt` + `实操任务/任务N-<名称>/任务说明.md`。
2. `scripts/extract_course_tasks.sh`——osascript 驱动 Safari 抓已登录页面。
   **未验证能否跑通**，且需要桌面会话，非交互环境下跑不了。
3. WebFetch —— **已排除**，未登录拿不到正文。

拿到之后，把本文件第 2 节表格里所有【推断】的任务栏替换成真任务，并更新完成度。
