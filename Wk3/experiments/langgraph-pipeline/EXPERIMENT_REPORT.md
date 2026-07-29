# Week 3 实验报告：LangGraph StateGraph vs 线性 Harness 管线

> 日期：2026-07-29
> 对照组：Wk2 V1 线性 sub-agent 管线（collector → analyzer → organizer）

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

| 维度 | 结论 | 实测验证 |
|------|------|:-------:|
| 状态管理 | 共享 state 显著优于文件传递（无 I/O、有类型） | ✅ |
| 条件路由 | 图编排提供了线性管线不具备的运行时决策能力 | ⚠️ 能力可用，分支未走 |
| 反馈循环 | 设计成立，但评分函数无区分度导致从未触发 | ❌ 未验证 |
| 成本 | 编排零成本，风险集中在循环放大 | ✅ |

## 已知问题

| # | 问题 | 严重度 | 说明 |
|:-:|------|:-----:|------|
| 1 | **质量分公式无区分度** | 🔴 高 | 正常产出必然 ≥80，门槛 60 形同虚设，反馈循环无法触发 |
| 2 | **rewrite 结果被 analyze 覆盖** | 🔴 高 | 回边 `rewrite → analyze` 使 rewrite 的改进产出丢失，只有计数器生效 |
| 3 | **search_node 是模拟采集** | 🟡 中 | 用 LLM 生成模拟数据保证可重复，但产出文章中的数字/项目/论文均非真实 |
| 4 | **MemorySaver 未被利用** | 🟡 中 | checkpointer 已装但无中断/恢复/time-travel 场景验证 |
| 5 | **`tokens_used` 字段悬空** | 🟢 低 | state 里声明了但没有节点写它，实际统计走的是全局 `tracker` |
| 6 | **CostTracker 全局累计** | 🟢 低 | 三次实验共用一个 tracker，`cost_total_cny` 是累计值不是单次值 |
| 7 | **无权限隔离** | 🟢 低 | V1 的 sub-agent 有权限矩阵，V3 全是同进程 Python 函数，无边界 |

## 下一步

1. **重做质量分**：改用 LLM-as-judge 或复用 Wk2 的 `check_quality.py` 五维评分，让分数真的有分布，而不是恒定 100
2. **修回边语义**：改为 `rewrite → quality_check`（跳过 analyze），或让 `analyze_node` 感知 `rewrite_count` 走不同 prompt
3. **注入低质量样本**：手动构造一条必然不及格的输入，专门验证 rewrite 分支和 3 次上限的熔断
4. **换持久化 checkpointer**：SQLite / Postgres，验证中断续跑和 time-travel
5. **接真实采集**：把 `search_node` 换成 MCP web_fetch 或 Wk2 的 RSS pipeline，去掉模拟数据
6. **补 V1/V3 同题对照**：同一个 topic 两条管线各跑一遍，做产出质量的横向比较

## 文件清单

| 文件 | 功能 |
|------|------|
| `langgraph_experiment.py` | StateGraph 定义、5 个节点、条件边、实验入口 |
| `results/experiment_1_article.md` | 实验 1 产出 |
| `results/experiment_2_article.md` | 实验 2 产出 |
| `results/experiment_3_article.md` | 实验 3 产出 |
| `EXPERIMENT_REPORT.md` | 本报告 |
| `EXPERIMENT_REFLECTION.md` | 深度心得 |
