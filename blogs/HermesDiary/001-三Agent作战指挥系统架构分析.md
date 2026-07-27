# 我的 Hermes 日记

> Claude Code + Codex + OpenCode 三 Agent 作战指挥系统架构分析
> 2026-07-23 · 由 Claude Opus 分析，Hermes 调度

---

## 0. 现状盘点：能复用什么 / 要新建什么

| 能力 | 现有实现 | 状态 |
|---|---|---|
| Provider 抽象（换后端） | `providers/base.py:ProviderProfile` + 三个插件：`deepseek`、`openai-codex`、`opencode-zen` | ✅ 直接用 |
| 后端热切换引擎 | `run_agent.py:8378 _try_activate_fallback()`——同一 agent 进程原地换 client/model | ✅ 直接用 |
| 故障触发判定 | `agent/error_classifier.py:FailoverReason`——`rate_limit`/`billing`/`overloaded`/`auth_permanent` | ✅ 直接用 |
| 任务规格格式 | `kanban_specify.py:46`——已强制 `Goal / Approach / Acceptance criteria / Out of scope` 四段式 | ✅ 扩展即可 |
| 任务级审计流水 | `task_events`（append-only）+ `task_runs`（每次尝试一行，含 `outcome`/`error`/`summary`） | ✅ 学习管道的数据源 |
| 重派/重做闭环 | `_record_task_failure`（`running→ready` 重排）+ 熔断 `consecutive_failures>=2 → blocked` + `gave_up` 事件 | ✅ 直接用 |
| 上一次失败喂给下一个 worker | `kanban_db.py:3933 build_worker_context()` | ✅ 知识回灌的钩子 |
| **Provider 健康/熔断状态** | 只有主 provider 的 60s `_rate_limited_until` 冷却 | ⚠️ 需新建 |
| **DeepSeek/OpenCode 额度信号** | `account_usage.py` 只接了 Codex/Anthropic/OpenRouter | ⚠️ 需新建 |
| **同规格双活（Claude↔Codex 互顶）** | 现在是"单 agent 换后端"，不是"两个对等 agent 共享规格" | ⚠️ 需新建路由层 |
| **战术知识库** | 无 | ⚠️ 需新建（OpenCode 管道） |

**核心洞察**：你有两种粒度的"切换"：

- **进程内后端热切**（`_try_activate_fallback`）：一次 worker 运行中，429/欠费时秒级换后端、不丢上下文。用于"打到一半供应商抖了"。
- **任务级重派**（熔断 + 换 assignee）：一次尝试整体崩了/被打回，Kanban 把任务重新排队给**另一个前线 agent**。用于"Claude Code 整体挂了，Codex 顶上"。

---

## 1. 总体架构

```
                        ┌─────────────────────────────────────────────┐
                        │            指挥层  ORCHESTRATOR               │
                        │   (kanban 编排 profile, 非单任务作用域)         │
                        │   kanban_list / kanban_create / kanban_unblock │
                        └───────────────┬─────────────────────────────┘
                                        │ 派发 (dispatch_once)
                                        ▼
        ┌───────────────────────── KANBAN 作战沙盘 (SQLite/WAL) ──────────────────────────┐
        │  tasks(status: triage→todo→ready→running→blocked→done)                          │
        │  task_runs(每次尝试)   task_events(append-only 审计)   task_comments             │
        │  ◀── 规格 body: Goal/Approach/Acceptance + failover/telemetry 元数据 ──▶         │
        └───────┬──────────────────────────────────────────────────────┬────────────────┘
                │ claim (CAS ready→running, 注入 HERMES_KANBAN_*)         │ 只读订阅
                ▼                                                        │ (tail events)
   ┌────────────────────── 前线 · 双活执行 ─────────────────────┐        │
   │                                                            │        │
   │   ┌──────────────┐   健康路由 & 故障切换   ┌──────────────┐   │        │
   │   │  Claude Code │◀───────────────────────▶│    Codex     │   │        │
   │   │ Opus/Sonnet  │   同规格·互为热备        │ gpt-5.6-sol  │   │        │
   │   │ OAuth 订阅    │                          │ OAuth 订阅   │   │        │
   │   └──────┬───────┘                          └──────┬───────┘   │        │
   │          │  ①进程内: _try_activate_fallback(带历史)  │          │        │
   │          │  ②任务级: 熔断→reassign→重排 ready         │          │        │
   │          └──────────── 共享 fallback 链 ─────────────┘          │        │
   └────────────────────────────────────────────────────────────────┘        │
                                                                              ▼
                              ┌──────────────────── 后方 · 学习分析 (不阻塞前线) ─────────────────┐
                              │                    OpenCode · DeepSeek v4-pro (API key)           │
                              │                                                                  │
                              │   [采集] tail task_events + task_runs  ──▶  归一化战例            │
                              │   [提炼] 什么成功/什么失败/为何被打回  ──▶  模式抽取 (LLM)          │
                              │   [沉淀] 战术知识库 (tactics.db / md)                              │
                              │   [回灌] 注入 build_worker_context & specify 提示  ──▶ 回到前线    │
                              └──────────────────────────────────────────────────────────────────┘
```

三条数据流：**派发**（指挥→沙盘→前线）、**审计**（前线→沙盘 events）、**学习回灌**（沙盘 events→后方→知识库→前线 context）。后方对前线是**只读订阅 + 异步回灌**，永远不在关键路径上。

---

## 2. 任务规格格式（前线双活的基石）

规格必须是 **agent 无关的**——Claude Code 和 Codex 拿到同一份 `body` 都能执行。

**规格 = `tasks.body`（人读四段）+ fenced 元数据块（机读）**

```markdown
## Goal
用一句话描述用户可见的结果。

## Approach
- 2~5 条要点（策略，不绑定具体 agent）

## Acceptance criteria
- [ ] 可验证项 1（决定"做完/打回"的唯一标准）
- [ ] 可验证项 2

## Out of scope
- 明确不做的

<!-- HERMES-SPEC v1 -->
```yaml
spec_version: 1
eligible_agents: [claude-code, codex]   # 双活白名单；顺序=偏好
require_parity: true                    # 两者必须能互顶(禁用 agent 特有工具)
verify:
  command: "pytest tests/ -q"           # 客观验收命令（打回判定的机器依据）
  must_pass: true
failover:
  intra_run: fallback_chain             # ①进程内热切走 fallback 链
  cross_agent_on: [gave_up, timed_out, crashed]  # ②任务级换人触发
  max_agent_switches: 1                 # 一个任务最多跨 agent 切 1 次，防乒乓
telemetry:
  emit: [attempt_start, verify_result, rejection_reason]  # 喂给后方
```
```

---

## 3. 故障切换协议（Claude Code ⇄ Codex 无缝互顶）

### 层 ①：进程内后端热切（秒级，保上下文）

fallback 链配置成**跨 agent 对等**：

```yaml
fallback_providers:
  - {provider: anthropic,    model: claude-opus-4-8}                        # 主
  - {provider: anthropic,    model: claude-sonnet-5}                        # 同provider降级
  - {provider: openai-codex, model: gpt-5.6-sol, api_mode: codex_responses} # 跨到Codex
```

| `FailoverReason` | 动作 |
|---|---|
| `rate_limit` (429) | 主 provider 打 60s 冷却 → 尝试凭证池轮换 → 仍不行才跳链 |
| `billing` (402/额度耗尽) | **立即**跳链，不 backoff |
| `overloaded`/`server_error` (503/500) | backoff 后跳链 |
| `auth_permanent` | 跳链 |
| `context_overflow`/`format_error` | **不跳链**，压缩/中止 |

### 层 ②：任务级换人（一次尝试整体崩了 / 被打回）

```
              worker(claude-code) 运行
                       │
        ┌──────────────┼──────────────────────────┐
        │ crashed/timed_out           verify 失败   │
        ▼                              ▼            │
  _record_task_failure          reviewer 打回      │
  running → ready               (block→comment)    │
  consecutive_failures++              │            │
        │                             ▼            │
        │  达到 max_retries?    unblock → ready     │
        ├── 否 ──▶ 同 agent 重排 (build_worker_context 带上次失败原因)
        └── 是 ──▶ cross_agent_switch:
                    if switches < max_agent_switches:
                       reassign(claude-code → codex)
                       consecutive_failures = 0   # 换人重置计数
                       emit event: agent_failover
                    else:
                       → blocked (人工介入)
```

---

## 4. OpenCode 学习管道（后方 · DeepSeek v4-pro）

设计原则：**只读、异步、幂等、绝不阻塞前线**。

```
┌──────────── 采集 COLLECT (增量, 断点续读) ────────────┐
│  游标: last_seen_event_id (存在 tactics.db)            │
│  轮询 task_events WHERE id > cursor                    │
│    关注 kind ∈ {completed, gave_up, crashed,          │
│                 timed_out, kicked_back, agent_failover}│
│  JOIN task_runs 拿 outcome/error/summary/profile       │
│  JOIN tasks 拿 body(规格) + eligible_agents            │
└───────────────────────┬───────────────────────────────┘
                        ▼
┌──────────── 归一 SHAPE ──────────────────────────────┐
│  一条"战例" = {                                        │
│    task_id, agent, outcome,                           │
│    spec_goal, verify_cmd,                             │
│    attempts: [{run, outcome, error, duration}],       │
│    kicked_back_reasons: [...],                        │
│    failover: claude→codex? }                          │
└───────────────────────┬───────────────────────────────┘
                        ▼
┌──────────── 提炼 EXTRACT (DeepSeek v4-pro) ──────────┐
│  批处理 N 条战例 → 结构化输出:                          │
│   • pattern: "涉及 X 的任务在 Codex 上首过率更高"       │
│   • failure_mode: "规格缺 verify_cmd → 打回率↑"        │
│   • fix_recipe: "对 Y 类任务, Approach 应包含 Z"        │
│   支持度/置信度打分, 低于阈值丢弃                        │
└───────────────────────┬───────────────────────────────┘
                        ▼
┌──────────── 沉淀 STORE (战术知识库) ─────────────────┐
│  tactics.db:                                          │
│   tactics(id, scope, pattern, recipe, agent_bias,     │
│           support_count, confidence, updated_at)      │
│   agent_scorecard(agent, task_class, first_pass_rate, │
│                   avg_attempts, sample_n)             │
└───────────────────────┬───────────────────────────────┘
                        ▼
┌──────────── 回灌 FEED-BACK (两个注入点) ─────────────┐
│  A. specify: 给 kanban_specify 提示追加"相关战术"      │
│     → 新任务规格一出生就更好                            │
│  B. worker_context: build_worker_context 尾部拼接      │
│     命中的 recipe → 重试/新 worker 带着教训上场         │
│  C. routing bias: agent_scorecard 影响任务级换人时      │
│     eligible_agents 的选择顺序                          │
└───────────────────────────────────────────────────────┘
```

---

## 5. 实现步骤（按优先级）

### P0 — 前线双活最小闭环

1. **配对等 fallback 链**：把 Codex 挂到 Claude Code worker 链后，反向也配一条。→ 立刻拿到**层①进程内热切**，零改码。
2. **规格加 YAML 元数据块**：改 `kanban_specify.py` 提示，产出 `eligible_agents/verify/failover`。入队时校验双活可移植性（skills 取交集）。
3. **任务级换人**：在 `_record_task_failure` 熔断分支插入 `reassign` 到备用 agent + `agent_failover` 事件 + `max_agent_switches` 防乒乓。→ 拿到**层②**。

*验收*：手动杀掉 Claude Code 的凭证，一个 running 任务应① 进程内切到 Codex 续跑，或② 崩溃后被重派给 Codex。

### P1 — 健康感知，别往死 provider 派

4. **Provider 健康表** + `error_classifier` 结果写入。
5. **`dispatch_once` 选 assignee 时读健康表**，跳过 `down`；叠加额度预测性回避。
6. **"打回重做"事件化**：新增 `kicked_back` kind。

*验收*：把 Codex 额度打满，派发器停止派给它并自动倒向 Claude Code；恢复后自愈。

### P2 — 后方学习管道（OpenCode/DeepSeek）

7. **采集器**：独立 profile + cursor 增量读 `task_events`/`task_runs`，落归一化战例到 `tactics.db`。
8. **提炼**：DeepSeek v4-pro 批处理战例 → `tactics` + `agent_scorecard`，带置信度阈值。
9. **cron 定时触发**，5~15 分钟一轮。

*验收*：跑一批任务后，`tactics.db` 出现有支撑度的模式；`agent_scorecard` 能看出某类任务谁首过率高。

### P3 — 闭环回灌

10. **回灌 A**：`kanban_specify` 提示注入相关战术。
11. **回灌 B**：`build_worker_context` 尾部拼接命中的 recipe。
12. **路由偏置**：任务级换人时按 `agent_scorecard` 排 `eligible_agents` 顺序。

---

## 关键设计权衡

- **进程内热切 vs 任务级换人**：前者保上下文、秒级、但两个后端在**同一对话历史**里跑（Codex 要能接 Claude 起的头）；后者干净隔离、`build_worker_context` 重新组织上下文、但丢中间态。建议**默认层①，崩溃/超时才层②**。
- **打回判定要客观**：用 `verify.command` 的退出码，不要让 reviewer agent 主观判"感觉没做好"——否则后方学到的"失败模式"全是噪声。
- **防乒乓**：`max_agent_switches: 1` 是硬约束，两个 agent 都失败就 `blocked` 转人工，别无限互踢。
- **后方永远只读**：任何时候 OpenCode 管道都不能写 `tasks` 可变列。它慢了、挂了、学歪了，前线照常打仗。

---

*2026-07-23 · 由 Hermes Agent 调度 Claude Code Opus 生成*
