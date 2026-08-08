# Week 3 实验报告：LangGraph StateGraph vs 线性 Harness 管线

> 首轮日期：2026-07-29
> 修复轮日期：2026-08-08（见文末[修复记录](#修复记录2026-08-08)）
> 对照组：Wk2 V1 线性 sub-agent 管线（collector → analyzer → organizer）

> **阅读提示**：本报告的「实验 1/2/3」「汇总」「四维对比」记录的是 **2026-07-29 首轮**
> 的结果，作为历史记录原样保留。首轮暴露的 7 个问题已在 2026-08-08 修复并重跑，
> 新数据、新实验组和残留问题都在文末[修复记录](#修复记录2026-08-08)里。
> 两轮结论的差异本身就是这次实验最有价值的部分——尤其是「质量分 100/100」
> 在首轮是**评分函数失效**的症状，不是质量好的证据。

## 实验目标

V1/V2 的管线是**线性**的：三个 sub-agent 依次触发，靠文件系统传递中间产物，跑到底就结束，没有运行时分支，也没有质量不合格时的回头路。

本次实验把同一条「采集 → 分析 → 组织」流水线用 LangGraph 的 StateGraph 重写，验证四件事：

| # | 维度 | 要回答的问题 |
|:-:|------|------------|
| 1 | 状态管理 | 共享 state dict 能否替代文件系统传递？ |
| 2 | 条件路由 | 运行时能否根据中间结果选择下一个节点？ |
| 3 | 反馈循环 | 质量不达标时能否自动回炉重做，而不是人工重跑？ |
| 4 | 成本 | 引入图编排后，Token 和钱的开销是多少？ |

## 实验环境

| 项目 | 值 |
|------|-----|
| 时间 | 2026-07-29 |
| Python | 3.13 |
| LLM | DeepSeek `deepseek-chat`（via API） |
| 编排框架 | LangGraph `StateGraph` + `MemorySaver` checkpointer |
| 复用组件 | Wk2 `pipeline/model_client.py`（`quick_chat` + 全局 `CostTracker`） |
| 工作目录 | `Wk3/experiments/langgraph-pipeline/` |

### Tech Stack

| 层 | 技术 | 说明 |
|----|------|------|
| 运行时 | Python 3.13 | venv 隔离，`.venv/` 已 gitignore |
| 模型 | DeepSeek `deepseek-chat` (via API) | OpenAI 兼容接口，无第三方 SDK |
| 编排 | LangGraph `StateGraph` | 节点 + 条件边 + 循环边 |
| 状态 | `TypedDict` (`PipelineState`) | 13 个字段，全节点共享 |
| 持久化 | `langgraph.checkpoint.memory.MemorySaver` | 内存 checkpoint，按 `thread_id` 隔离 |
| 计量 | `CostTracker`（复用 Wk2） | CNY / USD 双币种 + token 累计 |
| 配置 | `python-dotenv` | `DEEPSEEK_API_KEY` 从 `.env` 读 |

## 代码架构

```
Wk3/experiments/langgraph-pipeline/
├── langgraph_experiment.py       (500行) — StateGraph 定义 + 5 个节点 + 实验入口
├── results/
│   ├── experiment_1_article.md   — LangGraph vs 线性管线架构对比
│   ├── experiment_2_article.md   — 条件路由与反馈循环设计模式
│   └── experiment_3_article.md   — 多 Agent 状态共享机制
├── EXPERIMENT_REPORT.md          — 本报告
└── EXPERIMENT_REFLECTION.md      — 深度心得
```

## 架构对比

### V1：线性 sub-agent 管线（Wk2 对照组）

```
  ┌───────────┐   knowledge/raw/    ┌──────────┐    stdout     ┌───────────┐
  │ collector │ ──── *.json ──────► │ analyzer │ ─── JSON ───► │ organizer │
  └───────────┘                     └──────────┘               └───────────┘
       │                                 │                          │
   WebFetch ✅                       WebFetch ✅                 Write ✅
   Write   ❌                        Write   ❌                 WebFetch ❌
       │                                 │                          │
       └──────── 文件系统 = 唯一通信通道 ──┴──────────────────────────┘
                                                                    │
                                                                    ▼
                                                        knowledge/articles/*.json

  特征：单向、无分支、无回路。
  失败处理：人工发现 → 人工重跑整条管线。
  状态：不存在「全局状态」，只有磁盘上的中间文件。
```

### V3：LangGraph StateGraph（本次实验）

```
                    ┌──────────────────────────────────────────┐
                    │        PipelineState (TypedDict)         │
                    │  topic / raw_content / sources           │
                    │  summary / key_points / quality_score    │
                    │  article_title / article_body            │
                    │  rewrite_count / should_rewrite          │
                    │  tokens_used / call_count                │
                    └──────────────────────────────────────────┘
                       ▲        ▲        ▲        ▲        ▲
                       │        │        │        │        │   ← 所有节点读写同一份 dict
                       │        │        │        │        │
   START               │        │        │        │        │
     │                 │        │        │        │        │
     ▼                 │        │        │        │        │
  ┌────────┐           │        │        │        │        │
  │ search │───────────┘        │        │        │        │
  └────────┘                    │        │        │        │
     │                          │        │        │        │
     ▼                          │        │        │        │
  ┌─────────┐ ◄────────────┐    │        │        │        │
  │ analyze │──────────────┼────┘        │        │        │
  └─────────┘              │             │        │        │
     │                     │             │        │        │
     ▼                     │ 反馈循环     │        │        │
  ┌───────────────┐        │ (feedback   │        │        │
  │ quality_check │────────┼──  loop)    │        │        │
  └───────────────┘        │             │        │        │
     │                     │             │        │        │
     │  decide_route()  ───┼─────────────┘        │        │
     │  (conditional edge) │                      │        │
     │                     │                      │        │
     ├── score < 60 ──► ┌─────────┐ ──────────────┘        │
     │   & rewrite<3    │ rewrite │                        │
     │                  └─────────┘                        │
     │                                                     │
     └── score ≥ 60 ──► ┌──────────┐ ──────────────────────┘
                        │ organize │
                        └──────────┘
                             │
                             ▼
                            END

  特征：图结构、运行时条件分支、可回边成环。
  失败处理：quality_check 自动判定 → 自动路由到 rewrite → 回 analyze 重做。
  状态：单一共享 state，节点返回 partial dict 由 LangGraph 合并。
  持久化：MemorySaver 按 thread_id 记录每步 checkpoint。
```

### 关键差异一览

| 维度 | V1 线性 sub-agent | V3 LangGraph StateGraph |
|------|------------------|------------------------|
| 通信 | 文件系统（raw/*.json、stdout） | 内存共享 `PipelineState` |
| 拓扑 | 有向链，3 节点 | 有向图，5 节点 + 1 条件边 + 1 回边 |
| 分支 | 无（must-pass） | `add_conditional_edges` 运行时决策 |
| 循环 | 无 | `rewrite → analyze` 回边 |
| 中断恢复 | 重跑整条管线 | checkpointer 按 thread_id 续跑 |
| 可观测性 | 看磁盘上的中间文件 | 看 state 快照 + 节点日志 |
| 权限隔离 | 每个 agent 独立权限矩阵 | 无（同进程 Python 函数） |

## 实验 1：LangGraph StateGraph vs 线性 Harness 管线架构对比

### 执行

```bash
python langgraph_experiment.py    # topics[0]
```

### 结果

| 指标 | 值 |
|------|-----|
| LLM 调用 | 3 次（search / analyze / organize） |
| 质量评分 | **100/100** |
| 重写次数 | **0** |
| 耗时 | ~14s |
| 走过的路径 | `START → search → analyze → quality_check → organize → END` |
| 产出 | `results/experiment_1_article.md` |

### 产出摘录

> StateGraph 以图结构支持动态路由和循环，灵活但调试复杂；Harness 强调顺序执行和确定性，适合生产环境。

5 条关键要点全部生成，正文 ~800 字，含三级小标题与结论段。质量门禁一次通过，`decide_route()` 返回 `"organize"`。

## 实验 2：AI Agent 中的条件路由与反馈循环设计模式

### 结果

| 指标 | 值 |
|------|-----|
| LLM 调用 | 3 次 |
| 质量评分 | **100/100** |
| 重写次数 | **0** |
| 耗时 | ~15s |
| 走过的路径 | 同实验 1（未触发 rewrite 分支） |
| 产出 | `results/experiment_2_article.md` |

### 产出摘录

> 条件路由通过状态机或 DAG 实现智能体动态调度，替代静态链式调用。反馈循环包含重试、升级和验证步骤。

有趣的自指现象：这一轮让模型写「条件路由与反馈循环」，而承载它的图恰好实现了条件路由与反馈循环——但**这次运行本身没有走反馈循环分支**。文章讨论的模式，运行时并未被触发。

## 实验 3：多 Agent 协作中的状态共享机制

### 结果

| 指标 | 值 |
|------|-----|
| LLM 调用 | 3 次 |
| 质量评分 | **100/100** |
| 重写次数 | **0** |
| 耗时 | ~14s |
| 走过的路径 | 同实验 1 |
| 产出 | `results/experiment_3_article.md` |

### 产出摘录

> 混合式状态共享在延迟和吞吐量上优于集中式和分布式约 30%。

注：本实验的 `search_node` 是**模拟采集**（用 LLM 生成模拟 GitHub Trending / RSS 结果以保证可重复），所以文中的 star 数、论文结论、性能百分比均为模型生成的模拟数据，**不可作为事实引用**。这是实验设计的已知取舍——测的是编排，不是数据真实性。

## 汇总

| 实验 | 主题 | 调用 | 质量 | 重写 | 耗时 |
|:---:|------|:---:|:----:|:---:|:---:|
| 1 | StateGraph vs 线性管线架构对比 | 3 | 100/100 | 0 | ~14s |
| 2 | 条件路由与反馈循环设计模式 | 3 | 100/100 | 0 | ~15s |
| 3 | 多 Agent 状态共享机制 | 3 | 100/100 | 0 | ~14s |
| **合计** | | **9** | **均分 100** | **0** | **~43s** |

## 成本数据

| 指标 | 值 |
|------|-----|
| LLM 调用总数 | **9 次** |
| Token 总消耗 | **5,645** |
| 成本 (CNY) | **¥0.0091** |
| 成本 (USD) | **$0.0013** |
| 单次实验成本 | ~¥0.0030 |
| 单次调用成本 | ~¥0.0010 |
| 平均 Token / 调用 | ~627 |
| 计价 | DeepSeek ¥1.0/M 输入 + ¥2.0/M 输出 |

### 外推

| 场景 | 估算成本 (CNY) |
|------|--------------|
| 单条主题走完整图 | ¥0.003 |
| 每天 30 条 | ¥0.09 |
| 每月（30 条/天） | ¥2.7 |
| 每月 + 平均每条重写 1 次（+33% 调用） | ¥3.6 |

即使把反馈循环全开、每条都重写到上限 3 次，月成本仍在个位数人民币量级。**成本在当前规模下不构成架构约束。**

## 四维对比

### 1. 状态管理：文件系统 vs 共享 State

| | V1 文件系统 | V3 StateGraph |
|---|---|---|
| 传递方式 | `knowledge/raw/*.json` + stdout | 内存 `TypedDict` |
| 序列化开销 | 每步一次 JSON 读写 | 无 |
| 类型约束 | 无（靠 Issue 里的 schema 口头约定） | `TypedDict` 声明 13 个字段 |
| 中间产物可见性 | 天然可见（文件躺在磁盘上） | 需主动 dump state |
| 崩溃后的现场 | 完整保留在磁盘 | 靠 checkpointer，进程退出即失（MemorySaver） |
| 跨进程 / 跨机 | 天然支持 | 需换持久化 checkpointer |

**结论**：StateGraph 省掉了 I/O 中介和序列化往返，字段有类型声明，节点只返回 partial dict、由框架合并——写起来干净得多。代价是中间产物不再天然落盘，可观测性从「白送」变成「要自己做」。

### 2. 条件路由：must-pass vs conditional edge

| | V1 | V3 |
|---|---|---|
| 运行时分支 | 不支持 | `add_conditional_edges` |
| 决策依据 | 无 | `decide_route(state) → Literal["rewrite","organize"]` |
| 决策位置 | 管线外（人看结果决定要不要重跑） | 管线内（`quality_check_node` 写 `should_rewrite`） |
| 本次触发次数 | — | **0 / 3** |

**结论**：能力确实拿到了——路由函数、条件边、循环边全部按预期编译并执行。但**三次实验全部走了 `organize` 分支，`rewrite` 分支一次都没进过**。原因见下节。

### 3. 反馈循环：人工重跑 vs 自动 rewrite loop

质量分公式（`analyze_node`）：

```python
quality_score = min(100, max(0, 60 + len(summary) // 5 - (3 - len(key_points)) * 10))
```

代入实际产出（summary ≈ 120 字，key_points = 5 条）：

```
60 + 120//5 - (3-5)*10  =  60 + 24 + 20  =  104  →  min(100, ·)  →  100
```

**只要模型按 prompt 交出 5 条要点和 100 字以上摘要，分数必然溢出到 100。** 门槛是 60，实际下限约 80——这个门禁在当前 prompt 下**结构上不可能触发**。

所以「零重写、质量分 100/100」不是质量好的证据，是**评分函数没有区分度**的证据。反馈循环这一维，本次实验只验证了「图能编译、边能连通」，没有验证「循环能真正修复质量」。

同时代码审查发现回边存在语义缺陷：`rewrite` 节点算出的 `quality_score + 20` 和改进后的 summary，会在回到 `analyze` 节点后被重新生成的分析结果**覆盖**——`analyze_node` 是从 `raw_content` 从头重算的，不读 `summary`。真正生效的只有 `rewrite_count` 递增（防死循环的计数器）。这条 bug 因为分支从未触发而没有暴露在运行结果里。

| | V1 | V3（设计） | V3（实测） |
|---|---|---|---|
| 检测 | 人工 | `quality_check_node` | ✅ 执行 |
| 决策 | 人工 | `decide_route` | ✅ 执行 |
| 修复 | 人工重跑 | `rewrite → analyze` | ❌ 未触发 |
| 死循环保护 | — | `rewrite_count < 3` | 未验证 |

### 4. 成本

| | V1（Wk2 实测） | V3（本次） |
|---|---|---|
| 每条内容调用数 | 1（analyzer 一次分析） | 3（search + analyze + organize） |
| 单条成本 | ~¥0.0005 | ~¥0.0030 |
| 编排框架自身成本 | ¥0 | **¥0**（LangGraph 纯本地，不额外调模型） |
| 潜在放大 | 无 | 每次 rewrite +1 次调用（上限 +3） |

**结论**：图编排本身不花钱——LangGraph 的调度、路由、checkpoint 全在本地跑，Token 成本 100% 来自节点内的业务调用。V3 比 V1 贵 6 倍，是因为节点数从 1 个有效 LLM 步变成 3 个，不是因为用了图。

真正的成本风险在反馈循环：最坏情况 `3 + 3×2 = 9` 次调用（每轮 rewrite 触发一次 rewrite + 一次 analyze），是当前的 3 倍。这也是 `rewrite_count < 3` 这个 guard 存在的意义——它同时是**正确性保护**和**成本熔断**。

### 四维总评

| 维度 | 结论 | 首轮（07-29） | 修复轮（08-08） |
|------|------|:------------:|:--------------:|
| 状态管理 | 共享 state 显著优于文件传递（无 I/O、有类型） | ✅ | ✅ |
| 条件路由 | 图编排提供了线性管线不具备的运行时决策能力 | ⚠️ 能力可用，分支未走 | ✅ 入口条件边 + 门禁条件边各走通两条分支 |
| 反馈循环 | 设计成立，但首轮评分函数无区分度导致从未触发 | ❌ 未验证 | ✅ 触发 4 次并把分数救回（0→97、26→100、41→100、59→100） |
| 成本 | 编排零成本，风险集中在循环放大 | ✅ | ✅ 实测 rewrite 一次 +50%~+100% token |

## 已知问题

> 状态列为 2026-08-08 修复轮的结论，逐条验证过程见[修复记录](#修复记录2026-08-08)。

| # | 问题 | 严重度 | 状态 | 说明 |
|:-:|------|:-----:|:----:|------|
| 1 | **质量分公式无区分度** | 🔴 高 | ✅ 已修复 | 正常产出必然 ≥80，门槛 60 形同虚设，反馈循环无法触发 → 新公式实测首评分跨度 0-100，12 次首评有 5 次不及格 |
| 2 | **rewrite 结果被 analyze 覆盖** | 🔴 高 | ✅ 已修复 | 回边 `rewrite → analyze` 使 rewrite 的改进产出丢失 → 回边改为 `rewrite → quality_check`，评分动作也移进门禁节点 |
| 3 | **search_node 是模拟采集** | 🟡 中 | ✅ 已修复 | 用 LLM 生成模拟数据 → 新增 `rss_collector.py`，实测从 hackernews / lobsters / arxiv_ai 抓到 9 条真实条目 |
| 4 | **MemorySaver 未被利用** | 🟡 中 | ✅ 已修复 | 无中断/恢复场景验证 → 新增 `checkpoint` 实验（interrupt → get_state → update_state → resume，7 条断言全绿） |
| 5 | **`tokens_used` 字段悬空** | 🟢 低 | ✅ 已修复 | 无节点写它 → 每个节点用 `TokenMeter` 写真实增量，实测与 tracker 差值一致 |
| 6 | **CostTracker 全局累计** | 🟢 低 | ✅ 已修复 | `cost_total_cny` 是进程累计值 → `TokenMeter` 快照差值，每次实验单独计费 |
| 7 | **无权限隔离** | 🟢 低 | ⬜ 不修（架构取舍） | V1 的 sub-agent 有权限矩阵，V3 全是同进程 Python 函数。这是图编排换来性能与状态共享的代价，不是 bug。要隔离得把节点拆成子进程 / 容器，超出 Wk3 范围 |

## 下一步

> 状态列为 2026-08-08 修复轮的结论。

| # | 事项 | 状态 | 落地情况 |
|:-:|------|:----:|---------|
| 1 | **重做质量分** | ✅ 已完成 | 抽成独立模块 `quality.py`（可单测、有自测样本集）。没用 LLM-as-judge——规则评分零成本、完全可复现，且能给 rewrite 提供**结构化扣分理由**（哪个词空洞、缺几条要点），LLM-as-judge 给不了这种可操作反馈 |
| 2 | **修回边语义** | ✅ 已完成 | 回边改为 `rewrite → quality_check`；评分职责从 `analyze_node` 整体搬到 `quality_check_node` |
| 3 | **注入低质量样本** | ✅ 已完成 | 新增 `quality_only` 入口 + 2 条低质样本（空洞用语 / 摘要极短），首评 0 分与 26 分，各触发 1 次 rewrite 后回到 97 / 100。另加 `breaker` 实验专门验证 3 次上限熔断 |
| 4 | **换持久化 checkpointer** | ✅ 已完成 | 装 `langgraph-checkpoint-sqlite`，`SqliteSaver.from_conn_string()`。除了换实例恢复，还用 `subprocess` 拉起**独立 OS 进程**读同一个 DB 作为硬证据 |
| 5 | **接真实采集** | ✅ 已完成 | `rss_collector.py` 复用 Wk2 的 `rss_sources.yaml`，httpx + `xml.etree` 解析 Atom/RSS 2.0，抓不到才降级 |
| 6 | **补 V1/V3 同题对照** | ✅ 已完成 | 做成 **2×2**（V1/V3 × 严格/欠约束 prompt）。只跑一格会得出误导性结论，见[修复记录](#5-v1v3-同题对照2×2)|

## 文件清单

| 文件 | 功能 |
|------|------|
| `langgraph_experiment.py` | StateGraph 定义、5 个节点、3 个入口 + 2 组条件边、7 组实验入口 |
| `quality.py` | 质量评分函数（新公式 + 旧公式对照 + 自测样本集） |
| `rss_collector.py` | 真实 RSS/Atom 采集，复用 Wk2 `rss_sources.yaml` |
| `verify_sqlite_resume.py` | 独立进程读 SQLite checkpoint，跨进程恢复的硬证据 |
| `results/results_all.json` | 全套实验的结构化结果（含每条断言） |
| `results/run_all.log` | 全套实验的完整运行日志 |
| `results/experiment_{1,2,3}_article.md` | 3 个主实验产出 |
| `results/lowq-{1,2}-*.md` | 低质量注入产出 |
| `results/breaker_circuit_breaker.md` | 熔断实验产出 |
| `results/checkpoint_recovery.md` | MemorySaver 中断恢复产出 |
| `results/sqlite_checkpointer.md` | SQLite checkpointer 产出 |
| `results/v1v3_{v1_linear,v3_stategraph}_{normal,terse}.md` | 2×2 同题对照产出 |
| `results/v1_workdir/` | V1 线性管线的中间文件（raw/analysis/article，证明它靠文件传递） |
| `results/checkpoints.sqlite` | SQLite checkpoint 数据库（77 KB） |
| `EXPERIMENT_REPORT.md` | 本报告 |
| `EXPERIMENT_REFLECTION.md` | 深度心得 |

---

# 修复记录（2026-08-08）

首轮报告列了 7 个已知问题和 6 项下一步。这一轮把它们全部处理掉（1 项判定为不修），
重跑了一套扩展到 8 组的实验。**结论有反转**，下面按「改了什么 → 实测什么 → 说明什么」写。

## 0. 一句话总结

首轮的「三次实验质量分全部 100/100、重写零次」不是质量好，是**尺子坏了**。
换掉尺子之后，同样的管线在 12 次首评里有 5 次不及格，反馈循环被触发 4 次，
每次都把分数救回及格线以上。而更意外的发现是：**质量门禁的价值不是恒定的**——
analyzer prompt 写得好的时候它是纯开销，写得差的时候它值 +36 分。

## 1. 代码结构变化

单文件 500 行拆成 4 个模块，为的是让评分和采集能独立测试（首轮它们埋在节点函数里，
没法单独验证，这也是 bug 藏那么久的原因）：

| 文件 | 行数 | 职责 |
|------|:---:|------|
| `quality.py` | ~250 | 评分函数 + 旧公式对照 + 4 条自测样本，`python quality.py` 直接看分布 |
| `rss_collector.py` | ~230 | 真实 RSS/Atom 采集，`python rss_collector.py` 直接看抓到什么 |
| `verify_sqlite_resume.py` | ~60 | 独立进程读 checkpoint，被主实验用 subprocess 拉起 |
| `langgraph_experiment.py` | ~900 | 图定义 + 7 组实验 + CLI 子命令 |

跑法：

```bash
source Wk3/.venv/bin/activate
cd Wk3/experiments/langgraph-pipeline
python langgraph_experiment.py all          # 全套
python langgraph_experiment.py main         # 3 个主实验
python langgraph_experiment.py lowq         # 低质量注入
python langgraph_experiment.py breaker      # 熔断
python langgraph_experiment.py checkpoint   # MemorySaver 中断恢复
python langgraph_experiment.py sqlite       # SQLite 跨进程
python langgraph_experiment.py v1v3         # 2×2 同题对照
```

## 2. Bug #1：质量分公式

### 改了什么

```python
# 旧（analyze_node 里）—— 基线 60 就是门槛本身
quality_score = min(100, max(0, 60 + len(summary) // 5 - (3 - len(key_points)) * 10))

# 新（quality.py::score_quality）—— 基线 40，默认不及格，靠内容质量挣分
score = 40 + avg_len // 5 - bad_hits * 10 + good_hits * 5 - shortfall * 5
```

四个分项都可解释、都能在日志里展开：

| 分项 | 含义 |
|------|------|
| `base` 40 | 低于门槛 60，**默认不及格** |
| `avg_len // 5` | 摘要与要点的平均字数，衡量信息量 |
| `bad_hits × 10` | 18 个空洞用语（赋能/抓手/闭环/打通/对齐/颗粒度/生态/顶层设计…）的命中次数 |
| `good_hits × 5` | 15 个具体性信号（例如/对比/实测/版本/API/延迟/论文…）+ 数字/百分比/单位正则，按**种类数**计 |
| `shortfall × 5` | 要点不足 5 条时每缺一条扣 5 |

关键设计：`bad_hits` 按**出现次数**累计（堆砌废话会被指数级惩罚），`good_hits` 按
**种类数**计（防止刷同一个词）。

### 实测什么

`python quality.py` 的固定样本集，新旧公式并排：

| 样本 | 新公式 | 旧公式 | 分项展开 |
|------|:-----:|:-----:|---------|
| 高质量 | **89** | 100 | 40 + 14(len 72字) - 0 + 35(具体×7) - 0 |
| 中等质量-偏空泛 | **39** | 82 | 40 + 4(len 22字) - 0 + 0 - 5(缺1条) |
| 低质-摘要极短 | **31** | 62 | 40 + 1(len 6字) - 0 + 0 - 10(缺2条) |
| 低质-空洞用语 | **0** | 65 | 40 + 1 - 90(空洞×9) + 5 - 10 → -54 → clamp 0 |
| **区间** | **0-89（跨度 89）** | 62-100（跨度 38） | |
| **门槛 60 判不及格** | **3/4** | **0/4** | |

真实运行里的 12 次首评分数（8 组实验 + 2×2 对照的 4 格）：

```
0, 0, 26, 41, 59, 64, 82, 86, 89, 100, 100, 100
└─────── 5 次不及格 ──────┘└──── 7 次及格 ────┘
```

同样这 12 次，**旧公式会给出 11 次 100 分 + 1 次 53 分**——除了刻意堆砌废话的
sabotage 样本，旧公式对所有真实产出都给满分。

### 说明什么

首轮报告里那句「零重写、质量分 100/100 不是质量好的证据，是评分函数没有区分度的
证据」被完全证实了。更值得记的是**它是怎么被发现的**：不是从运行结果里看出来的
（结果好得很），而是有人去代入了一遍公式。**指标看起来完美的时候，第一件事应该是
怀疑指标，而不是庆祝。**

### 残留限制（诚实说明）

新公式在**及格区内仍会饱和**：高质量产出的 `good_hits` 容易到 7-9 个，raw score
经常超过 100 被 clamp（实测 raw 值有 103、104、109、110）。所以它能可靠区分
「不及格 / 及格」，但**不能给及格的产出排序**——86 分和 100 分之间的差异不可信。
门禁只需要一个阈值判断，这够用；要做「选最好的一版」就得换尺子。这一条没修，
留给 Wk4 的评估专题。

## 3. Bug #2：回边语义

### 改了什么

```diff
- builder.add_edge("rewrite", "analyze")        # rewrite 的产出会被 analyze 重算覆盖
+ builder.add_edge("rewrite", "quality_check")  # rewrite 的产出直接被重新评分
```

以及一个同样重要的配套改动：**评分动作从 `analyze_node` 整体搬进 `quality_check_node`**。
首轮把 `quality_score` 写在 analyze 里，所以哪怕回边改对了，分数也还是会被 analyze
重算。同时删掉了 `rewrite_node` 里 `quality_score + 20` 的假加分——分数现在**完全由
门禁按新内容重算**，不存在人为抬分。

图结构（修复后）：

```
START ─┬─ (full)         ──► search → analyze ─┐
       ├─ (analyze_only) ─────────► analyze ───┤
       └─ (quality_only) ─────────────────────►┴► quality_check
                                                   │ decide_route
                          ┌────────────────────────┤
                          ▼ score<60 且未触顶       ▼ 通过 / 熔断
                      rewrite ──► quality_check  organize → END
                              （回边指向门禁）
```

### 实测什么

`main-2` 的完整路径，score_history 一目了然：

```
search(real_rss) → analyze(terse) → quality_check(59) → rewrite#1 → quality_check(100) → organize
评分轨迹: [59, 100]
```

第二次 `quality_check` 读到的是 **rewrite 的产出**（100 分），不是 analyze 重算的结果。
首轮的架构下第二次评分会重跑 analyze，rewrite 白干。

四次真实触发的轨迹：

| 实验 | 首评 | 重写后 | 增量 |
|------|:---:|:-----:|:---:|
| `main-2(terse)` | 59 | **100** | +41 |
| `lowq-1-空洞用语` | 0 | **97** | +97 |
| `lowq-2-摘要极短` | 26 | **100** | +74 |
| `v1v3 v3(terse)` | 41 | **100** | +59 |

rewrite prompt 拿到的不是「你写得不好，重写」，而是评分器给出的**结构化扣分理由**：

```
- 平均字数只有 26 字，信息量不足
- 要点缺 2 条（需要 5 条）
- 具体性信号只命中 0 个（数字/对比/举例）
- 命中空洞用语 9 次：赋能、闭环、打通、对齐、颗粒度、生态、形成合力、顶层设计、全面提升
```

这是规则评分相对 LLM-as-judge 的实际优势：它知道**具体哪个词扣了分**，反馈可操作。
一次重写就能从 0 分跳到 97 分，很大程度是靠这个。

## 4. Bug #3：真实采集

### 改了什么

新增 `rss_collector.py`，复用 Wk2 `pipeline/rss_sources.yaml`（不维护第二份源列表），
httpx 抓取 + `xml.etree` 解析 Atom 与 RSS 2.0 两种格式，含 `fallback_urls` 依次重试。
`search_node` 默认走真实采集，抓不到才降级 LLM 模拟，并在 state 的
`collection_mode` 字段里**如实记录实际走了哪条路**（`real_rss` / `llm_mock` / `degraded`）。

### 实测什么

5 组用到采集的实验，`collection_mode` 全部为 `real_rss`，每次抓到 9 条（3 源 × 3 条）：

| 源 | 抓到的真实条目（示例） |
|----|---------------------|
| hackernews | The CPU is back: Rethinking the CPU-GPU split for LLM inference — redhat.com |
| hackernews | Now we have a timeline of the OpenAI accidental attack against Hugging Face — simonwillison.net |
| lobsters | The Nixpkgs core team has disbanded — discourse.nixos.org |
| arxiv_ai | 选择性上下文信任基准 MIST / EHR 心衰特征工程管线 |

产出文章里现在带真实 URL，摘要里的数字来自 feed 本身（HN 分数、评论数），
不再是模型编的。首轮报告那句「文中的 star 数、论文结论、性能百分比均为模型生成的
模拟数据，不可作为事实引用」这一轮不再适用。

### 说明什么

一个意外收获：真实采集的内容**天然含具体数字**（HN 分数、评论数、论文编号），
这直接推高了 `good_hits`。首轮的模拟数据虽然也有数字，但那些数字是编的——
换成真实源之后，「具体性」这个指标才真的和「可信」挂上钩。

## 5. Bug #4 + 下一步 #4：checkpointer

### MemorySaver 中断恢复

用 `interrupt_before=["organize"]` 编译，五步验证：

```
① invoke → 在 organize 前挂起，路径 search(real_rss) → analyze(normal) → quality_check(86)
② get_state → next=['organize']，article_body 为空
③ update_state({topic: "...【已被 update_state 改写】"}) → 读回确认生效
④ invoke(None, config) → 从 checkpoint 续跑，走完 organize
⑤ get_state_history → 7 条 checkpoint
```

7 条断言全绿：

| 断言 | 结果 |
|------|:----:|
| `paused_before_organize` | ✅ |
| `article_empty_at_pause` | ✅ |
| `update_state_took_effect` | ✅ |
| `resumed_reached_organize` | ✅ |
| `article_filled_after_resume` | ✅ |
| `topic_carried_marker`（改写的 topic 出现在最终产物里） | ✅ |
| `checkpoint_history_count` | 7 |

最后一条断言是关键：把 `topic` 改成带标记的字符串，恢复后生成的文章标题里确实带着
这个标记——证明续跑读的是**改过的 checkpoint**，不是内存里的旧对象。

### SQLite checkpointer（下一步 #4）

`langgraph 1.2.9` 的 `langgraph.checkpoint.sqlite` 需要额外装
`langgraph-checkpoint-sqlite`（已装），用 `SqliteSaver.from_conn_string(path)` 上下文管理器。

设计了三方对照：

| 角色 | 做什么 | 结果 |
|------|-------|------|
| 进程 A（`with SqliteSaver(...)` 第一段） | 跑到 organize 前中断 | DB 落盘 **77,824 字节** |
| 对照组（全新 `MemorySaver`） | 用同一个 thread_id 读 state | **`{}` 空** —— 内存 checkpointer 拿不到 |
| **独立 OS 进程**（`subprocess` 拉起 `verify_sqlite_resume.py`） | 只给 `(db_path, thread_id)` | **pid=44283 读到 `next=['organize']`, `quality=100`, `article_body_chars=0`** |
| 进程 B（新 `SqliteSaver` 实例） | 从磁盘续跑 | 走完 organize，文章生成 |

7 条断言全绿，包括 `separate_os_process_sees_state: true`。

### 说明什么

「换持久化 checkpointer 就能跨进程恢复」这句话，光换实例证明不了——同进程里换实例，
数据完全可能还在内存。所以额外拉了一个**真正独立的 OS 进程**：它只拿到文件路径和
thread_id，别的什么都不知道，能读出 `next=['organize']` 才算铁证。
对照组那个「全新 MemorySaver 看到 `{}`」也是必要的——它说明这个能力确实来自
SqliteSaver，不是 LangGraph 在别处兜了底。

## 6. 下一步 #3：低质量注入与熔断

新增 `quality_only` 入口（`add_conditional_edges(START, entry_route, ...)`——
LangGraph 支持从 START 起条件边），可以预置 summary/key_points 直接送进门禁。

### 低质量样本

| 样本 | 预置内容 | 首评 | 分项 | 重写后 |
|------|---------|:---:|------|:-----:|
| `lowq-1-空洞用语` | 「通过赋能业务实现闭环，打通生态，对齐颗粒度，形成合力」+ 3 条要点 | **0** | 40+1-40(空洞×4)+5-20 = -14 → 0 | **97** |
| `lowq-2-摘要极短` | 「介绍了一些情况。」+ 2 条要点 | **26** | 40+1-0+0-15 = 26 | **100** |

两条都是 1 次 rewrite 就救回来了。注意 `lowq-1` 首评 **0 分而旧公式给 100 分**——
这是新旧公式差异最极端的一格。

### 熔断（3 次上限）

低质样本一次就被救回，所以熔断打不到。为此加了 `sabotage_rewrite` 模式：
rewrite 节点**故意产出同样低质的内容**（不调 LLM，所以这个实验只花 organize 一次调用的钱），
模拟「模型改了但改不好」。

```
quality_check(0) → rewrite#1(sabotage) → quality_check(0)
                 → rewrite#2(sabotage) → quality_check(0)
                 → rewrite#3(sabotage) → quality_check(0) → organize
评分轨迹: [0, 0, 0, 0]
⚡ 熔断：重写已达上限 3 次，分数仍 0，强制放行
```

| 断言 | 结果 |
|------|:----:|
| `rewrite_count_equals_cap`（正好 3 次，不多不少） | ✅ |
| `circuit_broken` | ✅ |
| `reached_organize`（不是卡死，是放行） | ✅ |
| `quality_checks_run` | 4（1 次初评 + 3 次重评） |

代价 **1 次 LLM 调用 / ¥0.0012**，因为 sabotage 分支不调模型。
另外 `organize_node` 会读 `circuit_broken`，被熔断放行时在 prompt 里要求文章
开头如实说明「本次内容质量未达标」——**不达标的东西可以放行，但必须带标签**。

## 7. Bug #5 / #6：计量

`tokens_used` 字段现在真的被写了：每个节点通过 `TokenMeter` 取全局 tracker 的差值，
累加进 state。实测 `tokens_used_state` 与 `TokenMeter` 的实验级差值完全一致
（如 `main-2`：state 3460 / meter 3460）。

`CostTracker` 全局累计的问题用快照差值解决——每次实验开始建一个 `TokenMeter`，
`cost_cny` 是**这次实验**的花费，不再是进程累计。首轮报告里实验 3 的成本
看起来是实验 1 的三倍，就是这个 bug。

## 8. 下一步 #6：V1/V3 同题对照（2×2）

### 为什么是 2×2 而不是 1×2

第一版对照做出来是 V1=49 / V3=100，看着很漂亮，但**不成立**：V3 那一格走的是
rewrite 的严格 prompt，V1 走的是旧 analyzer prompt——差异里混进了 prompt 因素，
测的不是编排。

重做成 2×2，**V1 和 V3 用完全同一份 `ANALYZE_PROMPTS`**、同一份 `raw_content`
（3,626 字，抓一次两边共用），唯一差别是 V3 的 analyze 后面挂了门禁 + rewrite 回路。
第二个因子是 prompt 质量，因为「有门禁」的价值完全取决于 analyzer 会不会失手。

### 结果

| 维度 | V1/normal | V3/normal | V1/terse | V3/terse |
|------|:---------:|:---------:|:--------:|:--------:|
| 拓扑 | 线性链 3 节点 | 图 5 节点 | 线性链 3 节点 | 图 5 节点 |
| 中间产物 | 3 个文件落盘 | 共享 state，0 文件 | 3 个文件落盘 | 共享 state，0 文件 |
| 质量门禁 | 无 | 有（门槛 60） | 无 | 有（门槛 60） |
| **质量分（新公式）** | **82** | **89** | **64** | **100** |
| 质量分（旧公式） | 100 | 100 | 100 | 100 |
| 评分轨迹 | —（单次） | [89] | —（单次） | **[41, 100]** |
| 重写次数 | 0 | 0 | 0 | **1** |
| LLM 调用 | 2 | 2 | 2 | 3 |
| Token | 2,296 | 2,106 | 1,723 | 3,458 |
| 成本 CNY | 0.0032 | 0.0029 | 0.0024 | 0.0046 |
| 耗时 s | 11.9 | 10.3 | 8.5 | 13.1 |
| 摘要字数 | 387 | 365 | 127 | 314 |
| 要点条数 | 5 | 5 | 8 | 5 |

**门禁带来的质量分增量：normal `+7`，terse `+36`。**

### 说明什么

三点，第一点最重要：

1. **门禁的价值不是恒定的，而是「保险」型的**。严格 prompt 那格差 +7 分，落在
   LLM 采样噪声里（另一轮重跑同样配置得到的是 -5），本质上**门禁是 no-op**——
   analyzer 一次到位，路由函数跑了一遍就直接放行，白白多编排了一层。
   欠约束 prompt 那格差 +36 分，门禁把 41 分的产出拦下来，rewrite 一次到 100 分。
   **只跑严格那一格会得出「图编排没用」，只跑欠约束那一格会得出「图编排大幅提升质量」。
   两个结论都是假的。真实结论是：门禁买的是「失手时的下限」，不是「平均质量」。**

2. **保险费是可量化的**。normal 那格 V3 比 V1 省了一点 token（噪声），terse 那格
   V3 花了 2 倍 token（3,458 vs 1,723）、多 54% 耗时。换算成钱是每条 +¥0.0022。
   所以这笔账是：**平时多一层没用的路由开销，出事时多花一倍钱把产出救回及格线。**
   在意下限（比如自动发布、无人值守）就值，在意成本且有人 review 就不值。

3. **V1/terse 拿到 8 条要点却只有 64 分**，是个好例子：terse prompt 只要求 2 条，
   模型给了 8 条，但每条都短、都空泛，平均字数拉低了分数。**条数不等于质量**——
   旧公式恰恰只数条数，所以给了 100 分。

V1 那三个中间文件（`results/v1_workdir/raw-*.json`、`analysis-*.json`、`article-*.md`）
是刻意保留的——它们是 V1「靠文件系统传递」的物证，也是 V1 唯一的可观测性来源。
V3 一个文件都不落，可观测性全靠日志和 state dump。这一点首轮报告的判断没变：
**共享 state 省掉了 I/O，代价是中间产物不再天然可见，可观测性从「白送」变成「要自己做」。**

## 9. 修复轮成本

一次 `python langgraph_experiment.py all`（8 组实验 + 2×2 对照 = 12 次图执行）：

| 指标 | 值 |
|------|-----|
| LLM 调用 | **25 次** |
| Token | **26,792** |
| 成本 (CNY) | **¥0.0372** |
| 成本 (USD) | **$0.0052** |
| 单次图执行均价 | ~¥0.0031 |
| 计价 | DeepSeek ¥1.0/M 输入 + ¥2.0/M 输出 |

分组明细：

| 实验 | 首评 → 终评 | 重写 | 调用 | Token | 成本 ¥ | 耗时 s |
|------|:----------:|:---:|:---:|:-----:|:-----:|:-----:|
| main-1(normal) | 100 | 0 | 2 | 2,235 | 0.0031 | 17.7 |
| main-2(terse) | 59 → **100** | 1 | 3 | 3,460 | 0.0045 | 20.6 |
| main-3(normal) | 100 | 0 | 2 | 2,203 | 0.0031 | 18.7 |
| lowq-1-空洞用语 | 0 → **97** | 1 | 2 | 2,163 | 0.0031 | 12.0 |
| lowq-2-摘要极短 | 26 → **100** | 1 | 2 | 2,132 | 0.0031 | 11.2 |
| breaker(熔断) | 0 → 0 ⚡ | 3 | 1 | 665 | 0.0012 | 6.7 |
| checkpoint-recovery | 86 | 0 | 2 | 2,101 | 0.0029 | 13.6 |
| sqlite-checkpointer | 100 | 0 | 2 | 2,250 | 0.0032 | 15.6 |
| v1v3 × 4 格 | 见 2×2 表 | 1 | 9 | 9,583 | 0.0131 | 43.8 |

**重写的成本代价实测**：`main-2` 比 `main-1/3` 多 1 次调用、多 ~1,240 token、多 45% 钱。
首轮报告估算「最坏情况 3+3×2=9 次调用」偏高了——因为回边改成指向门禁后，
每轮 rewrite 只多 **1 次**调用（rewrite 自己），不再额外触发 analyze。
新的最坏情况是 `2 + 3 = 5` 次调用，比首轮设计**便宜 44%**。修 bug #2 顺带修了成本模型。

## 10. 残留问题

| # | 问题 | 严重度 | 为什么没修 |
|:-:|------|:-----:|-----------|
| 1 | 评分函数在及格区饱和 | 🟡 中 | raw score 常超 100 被 clamp，能判「过/不过」但不能给及格产出排序。门禁只需阈值，够用；排序需求留 Wk4 评估专题 |
| 2 | 无权限隔离 | 🟢 低 | 图编排的架构取舍。要隔离得把节点拆进子进程/容器，超出 Wk3 范围 |
| 3 | `sabotage_rewrite` 是人造场景 | 🟢 低 | 熔断只能靠「保证改不好」来触发，真实模型几乎总能一次改好。这是测试手段，报告里已明确标注，不当作质量结论 |
| 4 | 未验证 time-travel | 🟢 低 | `get_state_history` 只数了条数（7 条 / 6 条），没做「回到第 k 步换个分支重跑」。checkpoint 的读写恢复已验证，分叉重放留待需要时 |
| 5 | 单次运行，无重复采样 | 🟡 中 | 每格只跑 1 次，LLM 采样方差没量化。2×2 的 normal 格两轮分别得到 +7 和 -5，说明**这个量级的差异不可信**——报告里已按噪声处理，但严格做法是每格跑 5 次取分布 |

第 5 条是这轮最该继续做的：**+7 分的差异和 +36 分的差异，只有后者大到能穿透噪声。**
报告里所有「差异」的结论都按这个标准区分了强弱。
