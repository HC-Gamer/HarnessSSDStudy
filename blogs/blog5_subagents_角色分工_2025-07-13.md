# 三个 Agent 一个管线：从 PRD 到 Issue 到角色文件的 SDD 实践 (2025-07-13)

## 为什么需要 Agent 角色分工

单个 AI 做一件事可以很强。但当任务变成一条流水线——采数据、分析数据、归档数据——你就面临一个经典的管理问题：**三个工人挤在一个工位上干活，谁都伸不开手**。

AI Agent 的架构和人类团队一模一样。如果你的系统中只有一个 Agent 负责所有事情：

- 它要同时掌握 WebFetch（抓取数据）和 Write（写文件）两种能力
- 每次对话的上下文都要塞进"我是采集者"和"我是分析者"两种角色定义
- 失败时你不知道是采集阶段出了问题还是分析阶段出了问题

这就是为什么多 Agent 设计的第一个原则是**单一职责**：一个 Agent 只做一件事，做好它。

## 问题：角色和协作是两张皮

我们为 AI 知识库项目设计了三个 Agent：

```
collector (采集) → analyzer (分析) → organizer (整理)
```

看起来清晰。但真正的坑藏在看似清晰的分工里。

如果你直接对 AI 说："帮我写三个 Agent 角色定义文件，collector 抓 GitHub Trending，analyzer 打标签，organizer 输出 MD"，你会得到三个各有模样的文件。每个 Agent 都知道自己要做什么，但**谁先谁后、谁触发谁、上游失败下游怎么办、数据格式长什么样**——这些东西全在空气里。

测试时你才会发现：analyzer 在 collector 还没写完输出文件时就启动读取了。因为它们的"协作"是口头约定的，不是代码级约束的。

## SDD 解法：用 Issue 把依赖显式化

解决方法是**Specify → Clarify → Implement**三步走，用一个叫 `to-issues` 的工具把高阶 PRD 展开成带依赖和验收标准的任务票。

### 第一步：写高阶 PRD

先不纠结细节，写一个粗糙的 PRD，把大框架定下来：

```markdown
# 三 Agent PRD v0.1

总流程：每天 UTC 0:00 触发 · collector → analyzer → organizer · 串行

Agent 职责：
- collector: 抓 GitHub Trending Top 50 · 过滤 AI 相关 · 存 knowledge/raw/
- analyzer: 读 raw · 给每条打 3 维度标签
- organizer: 读已标注 · 整理成 MD

开放问题（待细化）：
- 上游失败下游怎么办？
- 数据怎么传？文件 or 消息？
- 重跑策略？
- 进度追踪？
```

关键技巧：**故意留下几个问号**。这些 `?` 是给后面工具展开的素材。你不需要一开始就想清楚所有问题——先写你能想到的。

### 第二步：展开成 Issue 任务票

每个 Agent 对应一份 Issue，包含三样东西：

**depends_on** — 依赖关系显式化

```markdown
## Depends On
- 01-collector (analyzer 依赖 collector 的输出)
```

这解决了"谁先谁后"的问题。三份 Issue 通过 depends_on 形成一条链：collector → analyzer → organizer。没有 depends_on 的 collector 是起点。

**acceptance** — 验收清单可执行化

```markdown
## Acceptance Criteria
- [ ] 过滤条件：仅保留 topics 含 ai/llm/agent/ml 的项目
- [ ] 条目数量：>= 15 条
- [ ] 排序规则：按 star 数降序
- [ ] 摘要格式：中文，公式「项目名 + 做什么 + 为什么值得关注」
```

这些不是空话。每条验收标准都能转化为测试脚本中的断言。

**schema** — 数据格式契约化

```markdown
## Schema
{
  "source": "github-trending",
  "items": [
    {"name": "...", "stars": 1234, "language": "Python"}
  ]
}
```

schema 定义了 Agent 之间传递数据的接口契约。analyzer 知道 collector 输出的 items 一定有 stars 和 language 字段，可以直接依赖它们做分析逻辑。

### 第三步：从 Issue 派生 Agent 配置文件

Issue 是"真相源"，Agent 配置文件从 Issue 派生。`.opencode/agents/collector.md` 直接从 `specs/issues/01-collector.md` 取其职责和 schema。

这样就形成了一个三层结构：

```
specs/agents-prd.md（高阶 PRD → 为什么）
  → specs/issues/{01,02,03}.md（Issue → 怎么做）
    → .opencode/agents/{collector,analyzer,organizer}.md（配置 → 谁来做）
```

改动时，改 PRD → 改 Issue → 改配置。不会出现"改了配置忘了改 PRD"的情况。

## 权限矩阵：最小权限原则

三个 Agent 的权限设计遵循最小权限原则：

| 权限 | Collector | Analyzer | Organizer |
|------|-----------|----------|-----------|
| Read/Grep/Glob | ✅ | ✅ | ✅ |
| WebFetch | ✅ | ✅ | ❌ |
| Write/Edit | ❌ | ❌ | ✅ |
| Bash | ❌ | ❌ | ❌ |

为什么这样设计？

- **Collector** 要抓网页，必须有 WebFetch。但它不自写文件（由主 Agent 写入），所以没有 Write 权限。
- **Analyzer** 要搜索验证，需要 WebFetch。同样不自写文件，没有 Write 权限。
- **Organizer** 要存知识条目，需要 Write/Edit。但它不需要访问外网，所以禁止 WebFetch。

这种隔离的意义在测试时体现出来：当 Collector 试图写入文件时，权限约束立刻阻断。你不用等到"文件被意外覆盖"才发现问题。

## 实操验证

写一个管线测试脚本，模拟三个 Agent 的顺序调用：

```python
# Step 1: Collector 采集
raw_data = step1_collect()     # → knowledge/raw/github-trending-*.json

# Step 2: Analyzer 分析
analyzed = step2_analyze(raw_data)  # → stdout JSON

# Step 3: Organizer 归档
created = step3_organize(raw_data, analyzed)  # → knowledge/articles/*.json
```

**验证结果：**
- Collector：15 条，全部有 name + url + summary（中文），按 star 降序 ✅
- Analyzer：15 条，评分 6-9，9 分仅 2 个（评分约束生效） ✅
- Organizer：15 个独立 JSON 文件，URL hash 去重正常 ✅

有趣的是二次运行时的表现：Organizer 基于 source_url 做 URL hash 去重，第二次运行时 15 条全部跳过，输出"新建条目: 0 个"。这验证了依赖的显式化确实能防止重复处理。

## 关键理解

多 Agent = 多依赖。依赖必须显式化成 Issue 的 `depends_on`，验收必须显式化成 `acceptance`。**任务票才是真相源。**

不要相信"口头约定"——在单 Agent 场景下，AI 能记住你 5 分钟前说的协作方式。但在多 Agent 场景下，每个 Agent 启动时只有自己的角色定义文件，看不到其他 Agent 做了什么。唯一的沟通方式是文件系统和明确的接口契约。

这是 SDD（Specification-Driven Development）在 Agent 工程中的核心价值：它不是帮你写代码，是逼你想清楚依赖关系。
