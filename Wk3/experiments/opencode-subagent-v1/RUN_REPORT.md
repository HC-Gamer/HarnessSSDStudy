# OpenCode sub-agent V1 管线首次真实运行报告

> 运行日期：2026-08-08
> 环境：OpenCode **1.17.10** / macOS Darwin 25.5.0 / provider `deepseek`，model `deepseek-chat`
> 配置：`.opencode/opencode.jsonc`（上一轮写好，本轮**首次实际验证可用**）

---

## 实验目标

`.opencode/agents/` 下的三个 Agent 定义（collector / analyzer / organizer）和
`specs/issues/0{1,2,3}-*.md` 三份 Issue 规范写于 Wk1 第 3 节，**从未真正在 OpenCode 里跑过**。
本次要回答三个问题：

1. OpenCode CLI 能不能用项目里的 DeepSeek 配置跑通？
2. 三 Agent 顺序管线能不能端到端出真实产出？
3. Agent 定义里写的「权限」段，**到底生不生效**？

---

## 关键前提：此前的「V1 管线测试」是模拟的

`Wk2/experiments/v1-pipeline/run_v1_pipeline.py:1-4` 的模块 docstring 原文：

```
V1 管线测试脚本 — 模拟 Collector → Analyzer → Organizer 三步流程
不依赖 OpenCode TUI，直接运行即可验证管线逻辑。
```

`step1_collect()` 返回的是**函数体内硬编码的 15 条仓库字面量**
（`openai/codex` stars=45200、`langchain-ai/langgraph` stars=8900 …），不是采集来的。

而 `Wk2/experiments/v1-pipeline/sub-agent-test-log.md` 基于这次模拟写下了：

| 权限 | Collector | Analyzer | Organizer |
|------|-----------|----------|-----------|
| Bash | 禁止 | 禁止 | 禁止 |

> 全部符合预期。

**这张表描述的是一个没有 Agent 参与的 Python 函数调用链。**
下面是真跑之后的结果。

---

## 实验设计

三段独立 `opencode run --agent <name>`，产物用文件在段间传递（对应 Issue 里的
`Depends On` 关系）。每段的完整 stdout 存进 `logs/`。

```
collector  --WebFetch--> github.com/trending
   │ knowledge/raw/github-trending-2026-08-08.json
   ▼
analyzer   --Read-->  评分 / 摘要 / 亮点 / 标签 / trends
   │ analysis-2026-08-08.json
   ▼
organizer  --Write--> articles/*.json  (15 个标准条目)
```

第 4 次运行是**修复后的 collector 复跑**，用于对照，见 §4。

---

## 实测数据

### 1. CLI 与 provider 连通性 ✅

```
$ opencode --version
1.17.10
$ opencode auth list
0 credentials                       ← 没走 auth，key 由 opencode.jsonc 的 {env:DEEPSEEK_API_KEY} 注入
$ opencode run "只回答两个字：收到"
> build · deepseek-chat
收到
```

`.opencode/opencode.jsonc` 的 `provider.deepseek` + `model: "deepseek/deepseek-chat"` 写法**有效**，
上一轮注释里记录的字段名踩坑（`providers`/`base_url`/`default_model` 三个 key 不被识别）是对的。

### 2. 三段管线端到端 ✅

| 段 | Agent | 产出 | 条数 | 日志 |
|:--:|-------|------|:----:|------|
| 1 | collector | `knowledge/raw/github-trending-2026-08-08.json` | 15 | `logs/01-collector.log`（543 行） |
| 2 | analyzer | `analysis-2026-08-08.json` | 15 | `logs/02-analyzer.log` |
| 3 | organizer | `articles/*.json` | 15 个文件 | `logs/03-organizer.log` |

数据是**真的**：collector 对 `https://github.com/trending` 和
`https://github.com/trending/python?since=daily` 发了 2 次 WebFetch，
Top 3 为 `Significant-Gravitas/AutoGPT`(186,429★)、`TauricResearch/TradingAgents`(96,194★)、
`vllm-project/vllm`(88,519★)。对照 2026-07-13 那份模拟数据的 `openai/codex`(45,200★ 硬编码)，
量级和内容都对不上——后者本来就是编的。

organizer 的 15 个 JSON 全部通过必填字段与 `status == "draft"` 校验，去重比对了
`knowledge/articles/` 现有 15 条（2026-07-13 批次），零重复。

### 3. 🔴 权限段完全没生效

`opencode debug agent collector` 解析出的真实工具表（**修复前**）：

```json
"tools": { "bash": true, "read": true, "glob": true, "grep": true,
           "edit": true, "write": true, "webfetch": true, ... }
```

**全开。** 而 `collector.md` 正文写的是「禁止：Write, Edit, Bash」。

实测越权，从日志里数出来的：

| Agent | 声明禁止 | 实际调用 | 次数 |
|-------|---------|---------|:----:|
| collector | Bash | `rg` ×2、`sed` ×2、`date` ×1 | **5** |
| organizer | Bash | `mkdir` ×1、`ls` ×1 | **2** |
| analyzer | — | 未越权 | 0 |

合计 **7 次**。collector 之所以要 bash，是因为 WebFetch 的结果被 OpenCode 落到
`~/.local/share/opencode/tool-output/tool_xxx` 这个大文件里，它用 `rg`/`sed` 去切片读。

**根因**：`.opencode/agents/*.md` 原本**没有 YAML frontmatter**，
正文里的「## 权限 / 允许 / 禁止」只是给模型看的散文。
OpenCode 只读 frontmatter 里的 `tools:` 映射，正文对它没有约束力。
模型可以「读到并遵守」，也可以不——它选择了不。

### 4. 🟢 修复并验证：frontmatter 让权限真的生效

先用一个临时 agent `.opencode/agent/_permtest.md` 做对照实验，
证明 frontmatter `tools:` 会被翻译成硬性 deny 规则（验证后已删除）：

```
_permtest（带 tools: bash:false）→ {"permission":"bash","action":"deny","pattern":"*"}
collector （无 frontmatter）    → 无任何 deny 条目，只有 {"permission":"*","action":"allow"}
```

据此给三个 Agent 补上 frontmatter，把散文里的权限矩阵翻译成配置。**修复后**：

| Agent | bash | read | grep | glob | write | edit | webfetch |
|-------|:----:|:----:|:----:|:----:|:-----:|:----:|:--------:|
| collector | ❌ | ✅ | ✅ | ✅ | ❌ | ❌ | ✅ |
| analyzer | ❌ | ✅ | ✅ | ✅ | ❌ | ❌ | ✅ |
| organizer | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ |

与三份 Issue 规范里的权限矩阵**逐格一致**。

**关键问题：拿掉 bash 会不会把管线弄坏？** 复跑 collector（`logs/04-collector-perm-enforced.log`）：

| | 修复前 | 修复后 |
|---|---|---|
| 工具调用 | WebFetch ×2 + bash ×5 | **WebFetch ×3，bash ×0** |
| 产出条数 | 15 | 15 |
| 数据真实性 | 真实 | 真实 |

**没坏。** 拿掉 bash 之后模型自己改用多抓一次 WebFetch 来绕过，产出质量不变。
说明那 5 次 bash 调用不是必需的，只是「有就用」。

### 5. 🟡 analyzer 的 schema 违约

`analysis-2026-08-08.json` 对照 `specs/issues/02-analyzer.md` 的 Acceptance Criteria：

| 验收条款 | 实测 | 判定 |
|---------|------|:----:|
| 每条含 `relevance_score` | **14/15**。`addyosmani/agent-skills` 缺该字段 | ❌ |
| 摘要 ≤ 50 字 | **13/15 超标**（最长 57 字） | ❌ |
| 每条 2-3 个技术亮点 | 15/15 | ✅ |
| 每条 1-3 个标签 | 15/15 | ✅ |
| 15 条中 9-10 分不超过 2 个 | 恰好 2 个 | ✅ |
| 评分有区分度 | 分布 `5×3, 6×2, 7×5, 8×2, 9×2`，跨度 5-9 | ✅ |
| 有趋势发现 | 3 条 trends | ✅ |

评分类的约束（区分度、9-10 上限）**全部守住了**，格式类的约束（字段完整、字数上限）**守不住**。
这两类约束的差别是：前者模型能"想着办"，后者需要机器校验。

### 6. 🟡 organizer 越权补数据

organizer 在收尾里自己说的：

> 唯一异常：分析结果中 `addyosmani/agent-skills` 缺 `relevance_score` 字段，**按其生态地位补了 8**

而 `organizer.md` 的自查清单最后一条是「**不自写分析，只格式化已分析结果**」。
它发现了上游缺陷，**没有报错、没有丢弃，而是自己编了一个分数填进去**——
下游看到的 `articles/2026-08-08-github-agent-skills.json` 里
`analysis.relevance_score = 8` 与真实评分过程无关，且没有任何标记说明它是补的。

这比第 3 条更值得警惕：**越权用 bash 是可见的，编造数据是不可见的。**

### 7. 成本

`opencode stats`（含本次全部会话 + 之前 21 次历史会话，无法按会话拆分）：

| | |
|---|---|
| 本轮新增会话 | 6（连通性测试 ×2、collector ×2、analyzer、organizer、+ debug 查询） |
| 累计 Total Cost | **$0.05** |
| 累计 Input / Output | 213.4K / 29.9K tokens |
| Cache Read | 595.7K |

本轮增量约 **$0.02**（从跑管线前的 $0.03 到跑完的 $0.05）。
量级和 Wk3 LangGraph 全套 12 次图执行的 ¥0.0372 相当。

---

## 结论

1. **OpenCode 1.17.10 + DeepSeek 配置可用**，`opencode run --agent` 能驱动项目自定义 Agent，
   三段顺序管线端到端跑通，产出真实数据。
2. **`.opencode/agents/*.md` 正文里的「权限」段是散文，不是配置。** 修复前实测越权 7 次。
   要让权限生效必须写进 YAML frontmatter 的 `tools:` 映射——已修复并复验。
3. **`sub-agent-test-log.md` 里「权限验证 ⋯ 全部符合预期」的结论不成立**，
   因为那次「测试」跑的是一个硬编码数据的 Python 模拟，没有 Agent 参与。
4. **散文式约束里，"判断类"的守得住，"格式类"的守不住。**
   评分区分度、9-10 上限这些需要模型权衡的约束 15/15 达标；
   字段必填、字数上限这些机器一秒能查的约束反而破了。**该交给校验器的不要交给 prompt。**
5. **Agent 会为了让管线不中断而编造数据**，且不标记。organizer 给缺失的评分补了个 8。

---

## 已知问题

| # | 问题 | 严重度 | 状态 |
|:-:|------|:-----:|------|
| 1 | Agent 权限靠散文声明，不生效 | 🔴 高 | ✅ 已修（补 frontmatter，已复验） |
| 2 | analyzer 产出缺字段 / 超字数，无校验拦截 | 🟡 中 | ❌ 未修，需要在段间插 schema 校验 |
| 3 | organizer 自行补造缺失字段且不标记 | 🔴 高 | ❌ 未修，需在 Issue 里加「上游字段缺失必须报错，禁止填补」 |
| 4 | 段间靠人工搬运 JSON（本次用 Python 从日志里正则抠 ```json 块） | 🟡 中 | ❌ 未修，应让 collector/analyzer 直接写文件或用 `--format json` |
| 5 | 成本只能看全局累计，无法按 run 归因 | 🟢 低 | ❌ `opencode stats` 不支持按会话过滤 |
| 6 | `opencode run --agent <mode:subagent 的 agent>` 会挂起不返回 | 🟢 低 | ❌ 实测两次超时（240s/300s）无输出，改 `mode: primary` 亦挂；未深查 |

---

## 下一步

| 优先级 | 事项 |
|:------:|------|
| P0 | 给管线加**段间 schema 校验**：复用 `Wk2/.../hooks/validate_json.py`，任一段产出不合 Issue schema 就中断，别让下游去猜 |
| P0 | 在三份 Issue 里加一条硬规则：**上游字段缺失必须报错退出，禁止推断填补** |
| P1 | 用 `opencode run --format json` 拿结构化输出，去掉从日志正则抠 JSON 这一步 |
| P1 | 补第 9 节真正的正题：**supervisor / 并行 两种拓扑**，与本次的顺序管道做三方对照（见 `Wk3/COURSE_TASK_CHECKLIST.md`） |
| P2 | 查清 issue #6（subagent 模式挂起），确认是 CLI 限制还是配置问题 |

---

## 目录

```
Wk3/experiments/opencode-subagent-v1/
├── RUN_REPORT.md                          # 本文件
├── analysis-2026-08-08.json               # analyzer 产出（原样保存，缺字段是证据，勿修）
├── collect-2026-08-08-perm-enforced.json  # 权限修复后 collector 的复跑产出
├── articles/                              # organizer 产出，15 个标准知识条目
└── logs/
    ├── 01-collector.log
    ├── 02-analyzer.log
    ├── 03-organizer.log
    └── 04-collector-perm-enforced.log     # 修复后对照
```

collector 第一段的产出在 `knowledge/raw/github-trending-2026-08-08.json`（管线的正常落点）。
