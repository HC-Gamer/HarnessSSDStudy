# M1 完工报告 —— Wk3 课程形态 V3

> 日期：2026-08-12 ｜ 环境：macOS 26.5 / Python 3.12.10（`~/ai-knowledge-base/.venv`）/ DeepSeek `deepseek-chat`
> 依据：Wk3 课件第 9/10/11/12 节实操任务原文 + `PLANNING-WK3-WK4-CAPSTONE.md` §2.3 完成标准
> 项目根：`毕业设计/ai-knowledge-base/v3-multi-agent/`

---

## 0. 一句话结论

**13 项硬验收全部通过**，其中 7 项是花真钱跑出来的实测（累计 ¥0.081），不是静态检查凑数。
V4 可以直接 `cp -rn` 继承。

---

## 1. 13 项硬验收自查

| # | 验收项 | 状态 | 实测证据 |
|:--|:--|:--|:--|
| 1 | `KBState.__annotations__` 长度 = 9 | ✅ 通过 | 输出 `9`；字段为 `plan / sources / analyses / articles / review_feedback / review_passed / iteration / needs_human_review / cost_tracker` |
| 2 | `python -m patterns.router` 三类分类正确 | ✅ 通过 | **3/3**。前两条关键词命中（零成本，测试里用「命中就不许调 LLM」的断言钉死），第三条走 LLM 兜底判为 `general_chat` |
| 3 | `python -m patterns.supervisor` ≤3 轮退出 | ✅ 通过 | 第 1 轮得分 8/10 通过即退出；3 个单测分别覆盖「一次过」「带反馈重做后过」「三轮都不过带 warning 退出」 |
| 4 | `python3 -m workflows.graph` 端到端 + `[Planner] 策略：standard` | ✅ 通过 | 完整链路：plan → collect(10) → analyze(10) → review(7.25 通过) → organize(10 篇落盘)；日志首行即 `[Planner] 策略：standard · 每源限 10 条 · 阈值 0.5 · 最大迭代 2` |
| 5 | `PLANNER_TARGET_COUNT` 三档有差异 | ✅ 通过 | lite：5 条 / 阈值 0.7 / 迭代 1 / ¥0.0065；standard：10 条 / 0.5 / 2；full：20 条 / 0.4 / 3 / ¥0.0194。**采集量、过滤阈值、迭代上限三个维度全部生效** |
| 6 | Reviewer 加权分 Python 重算，≥7.0 通过 | ✅ 通过 | `compute_weighted_score()` 用代码算 25/25/20/15/15；实测明细 `{8,6,9,5,8}` → 手算 `8×.25+6×.25+9×.20+5×.15+8×.15 = 7.25`，与日志一致；5 个参数化单测钉死算式（含全 10 分 → 10.0、边界 7.0） |
| 7 | 三路分支可达 | ✅ 通过 | **三条都真跑到了**：① 默认阈值 → `organize` 落盘 10 篇；② `REVIEWER_PASS_THRESHOLD=9.0` → `[Reviser] 定向修改 5 条`，第 2 轮分数 **7.25 → 8.3**（反馈闭环真的提分）；③ 同一次跑满 `max_iterations=2` → `[HumanFlag] 已保存 10 条到 knowledge/pending_review/pending-2026-08-12-064140.json` |
| 8 | `grep -l "cost_guard\|sanitize_input\|filter_output" workflows/*.py` 非空 | ✅ 通过 | 命中 **7** 个文件：`model_client.py`（记账+熔断）、`collector.py`（入口清洗）、`organizer.py`（出口掩码）、`analyzer.py`/`reviewer.py`/`reviser.py`（熔断异常透传）、`graph.py`（收尾报告） |
| 9 | `BUDGET_YUAN=0.001` 中途熔断 | ✅ 通过 | `[Analyzer] 预算熔断，已完成 1 条，中断分析` → `[FATAL] 成本已超出预算！当前 ¥0.0017, 预算 ¥0.0010`。**日志里没有 `[Organizer]`，没有落盘**，证明是真的卡住了调用链而不是跑完再报警 |
| 10 | 注入 warnings≥1；PII 三种掩码 | ✅ 通过 | `python3 tests/verify_injection.py` 走的是**生产函数**：注入样例检出 **2** 条模式；PII 掩码结果 `联系作者 [PHONE_CN_MASKED] 或 [EMAIL_MASKED] 获取完整代码 · IP [IP_ADDRESS_MASKED]` |
| 11 | `knowledge/cost-report.json` 含按节点成本 | ✅ 通过 | 含 `cost_by_node` / `calls_by_node` / `tokens_by_node` 三张分组表，例：`{"analyze": 0.008982, "review": 0.002934}` |
| 12 | `pytest tests/` 全绿 | ✅ 通过 | **73 passed, 8 deselected**（0.12s，全部离线）；LLM 用例单独跑 `pytest tests/ -m slow` → **8 passed**（41s） |
| 13 | 12-4 步骤 6/7/9 三张清单 | ✅ 通过 | `bash scripts/check_v3.sh` 输出「V3 完整性检查全部通过」：步骤 7 的 14 个文件全 `[OK]`，步骤 6 的接入清单 8 项全 `[OK]`，步骤 9 的 V1→V3 自查见下表 |

### 12-4 步骤 9 · V1→V3 自查清单

```
Week 1 (V1) — 基础搭建:
[x] AGENTS.md 编写完成                    → 本项目 AGENTS.md（V3 版：补了数据契约与红线）
[x] 3 个 Agent 角色文件                   → .opencode/agents/{collector,analyzer,organizer}.md
[x] 2+ 个 Skill 封装                      → .opencode/skills/{github-trending,tech-summary}/SKILL.md
[x] V1 手动流程跑通                       → Wk1 已验收，资产迁入

Week 2 (V2) — 自动化:
[x] pipeline/model_client.py 统一模型客户端 → 迁入，V3 的 workflows/model_client 在它之上加记账
[x] pipeline/pipeline.py 四步流水线        → 迁入
[x] hooks/ 质量校验脚本                    → validate_json.py + check_quality.py
[x] GitHub Actions 配置                    → .github/workflows/daily-collect.yml（入口改指 V3 图）

Week 3 (V3) — 多 Agent 协作 + 生产保护:
[x] workflows/state.py KBState（9 字段 · 含 plan + needs_human_review）
[x] workflows/planner.py Planner Agent（节点 ①）
[x] patterns/router.py Router 模式（意图路由）
[x] workflows/{collector,analyzer,reviewer,reviser,organizer,human_flag}.py
[x] workflows/graph.py LangGraph 7 节点 + 3 路条件边 + 审核循环
[x] tests/cost_guard.py CostGuard 预算守卫 + BudgetExceededError
[x] tests/eval_test.py 评估测试（4 用例 + LLM-as-Judge）
[x] tests/security.py 安全防护（注入 + PII + 限流 + 审计）
[x] ★ 12-4 接入: model_client.chat 后 record/check
[x] ★ 12-4 接入: collector 入口 sanitize / organizer 出口 filter
[x] 端到端跑通 + 熔断验证（BUDGET_YUAN=0.001）
[ ] 所有文件已提交 Git                     → 按约定由 Hermes 统一提交，本轮不做 git 操作
```

---

## 2. 加分项（课件未要求）

| 项 | 状态 | 说明 |
|:--|:--|:--|
| **段间 schema 校验接入图** | ✅ 已接入 | `validate.py` 新增 `validate_sources_segment` / `validate_analyses_segment`，挂在 collect / analyze 之后做闸门。坏数据 → `human_flag` 而非继续（3 个单测覆盖：好数据放行、坏数据拦截、`VALIDATE_SEGMENTS=0` 可关闭做对照） |
| **人工兜底带诊断** | ✅ | `human_flag` 落盘时重跑校验，在 JSON 里写清 `reason`（`validation_failed` / `review_not_passed`）与 `validation_errors`，人工能直接看到是结构坏了还是质量不够 |
| **分支验证不改代码** | ✅ | 课件让「临时把 `REVIEWER_PASS_THRESHOLD` 改成 9.0，测完记得改回来」。这里改成读环境变量 —— 验证分支不动代码，也就没有「忘了改回来」这个事故 |
| **三级采集降级** | ✅ | GitHub API → RSS（复用 V2 `rss_collector`）→ 离线种子。全断网也能跑完图，`collection_mode` 如实标记 `degraded` 让下游知情 |
| **成本报告三张分组表** | ✅ | 课件只要 `cost_by_node`，这里额外给 `calls_by_node` / `tokens_by_node`，能看出「贵是因为调用多还是单次长」 |

---

## 3. 课件矛盾与偏差处理（每条都有据可依）

| # | 冲突 / 偏差 | 处理 | 依据 |
|:--|:--|:--|:--|
| 1 | **KBState 字段名**：本次任务书建议 `query/plan/raw_items/analysis/review/revised/article/cost/status`；课件 10-1/11-2/11-3 定的是另一套 | **以课件为准**，用课件的 9 字段 | 任务书明写「课件与计划冲突时以课件为准」；且 V4 的 `cp -rn` 继承与 12-4 自查清单都按课件字段名写 |
| 2 | `planner.py` 在 `workflows/` 还是 `patterns/`：11-3 与 12-4 写 `workflows/`，16-2 写 `patterns/` | 主体放 `workflows/planner.py`，`patterns/planner.py` 做 re-export | PLANNING §8.1 |
| 3 | `relevance_score` 量纲三处不一致（0–1 / 0–10 / 0–100） | 统一 **0–1**；`_normalize_score()` 归一任意量纲，`validate.py` 把越界判硬错误 | PLANNING §8.2 / D4 |
| 4 | 12-2 文件名 `eval_test.py` 不匹配 pytest 默认发现规则；16-2 自查里又写 `test_eval.py` | `pytest.ini` 配 `python_files = test_*.py eval_test.py`，另加 `tests/test_eval.py` 一行 import 别名 | PLANNING §8.4 |
| 5 | 12-4 参考实现用 OpenAI SDK（`client.chat.completions.create`） | 复用 V2 已跑通的 `pipeline/model_client.py`（httpx + 重试退避 + 多提供商），`workflows/model_client.py` 只做接口适配 + CostGuard 接入 | AGENTS.md §6「不重复实现已有能力」；少一个依赖，少一层 API 漂移风险 |
| 6 | 课件 Planner 参考实现里出现 `chat_json(..., node_name="plan")` | Planner **不调 LLM**，按 11-3 参考实现做纯规则 | 11-3 正文明写「只规划不执行」；规划规则是确定性策略，用 LLM 既贵又不稳 |
| 7 | 课件拓扑是 7 节点无闸门 | 段间校验做成**条件边**而非节点，拓扑仍是 7 节点 | 保证 `build_graph().nodes` 数量 = 7，不破坏课件验收 |

---

## 4. 实测中踩到并修掉的坑

| 坑 | 现象 | 修法 |
|:--|:--|:--|
| **SOCKS 代理缺包** | 首次端到端跑，10 条分析全失败：`Using SOCKS proxy, but the 'socksio' package is not installed` | `pip install socksio`。**注意这类失败会被节点的「单条失败不拖垮整批」逻辑吞掉**，表面上「完成 10 条分析」，实际全是失败占位 —— 所以 organizer 过滤时把 `analysis_failed` 也算进去 |
| **Reviser 输出被截断** | `max_tokens=2000` 装不下 5 条改写稿，返回半个 JSON 数组，解析必失败，修订空转（分数两轮都是 7.25） | 提到 4000，并且只把 5 个内容字段送进 prompt / 要回来（url、stars 等溯源字段不进 LLM）。修完分数 7.25 → 8.3 |
| **Supervisor 模型把三维分加起来** | 打分返回 `score: 26`（9+7+10），远超 1–10 量纲 | 和 Reviewer 同一个教训：**算术交给代码**。`normalize_score()` 有维度分就取平均，`passed` 也由代码判定 |
| **Router LLM 兜底判错** | 「LangGraph 和 CrewAI 有什么区别」被判成 `knowledge_query` | 分类 prompt 加 4 条 few-shot 示例。分类边界靠举例说清，比在类别描述里堆形容词有效 |
| **`pip install` 直连超时** | 官方源反复 `incomplete-download` | 换清华镜像 `-i https://pypi.tuna.tsinghua.edu.cn/simple` |
| **`rss_collector.py` 相对路径** | 从 Wk3 拷进来后 `DEFAULT_SOURCES_YAML` 指向不存在的目录 | 改成指向本目录的 `pipeline/rss_sources.yaml` |

---

## 5. 成本账（本轮全部真实调用）

| 场景 | 调用数 | 成本 |
|:--|:--|:--|
| standard 端到端（正常通过） | 11 | ¥0.0119 |
| 阈值 9.0（revise + human_flag 分支） | 13 | ¥0.0208 |
| lite | 6 | ¥0.0065 |
| full | 21 | ¥0.0194 |
| 熔断验证 | 2 | ¥0.0017 |
| router / supervisor 演示 + slow eval 用例 | ~15 | ≈ ¥0.02 |
| **合计** | **≈68** | **≈ ¥0.081** |

单次 standard 管线 ¥0.012，与课件估算的「一次正常管线 ≈ ¥0.012」完全吻合。

---

## 6. 已知限制（如实记录，不粉饰）

1. **知识条目 id 按天+序号编号**，同一天多次运行会互相覆盖（`github-20260812-001` 被后一次跑的第一条盖掉）。
   当天多次运行时 `index.json` 里的标题与文件内容可能来自不同批次。V4 做 `build_index.py` 时应改为
   基于 URL hash 的稳定 id。
2. **Reviewer 评分饱和**：五次独立运行（standard / lite / full / 阈值 9.0 两次）的首轮 5 维明细
   全都是 `{8,6,9,5,8}`，加权分恒为 7.25。
   `temperature=0.1` 换来了一致性，代价是分辨率低 —— 它更像一个「阈值开关」而不是「刻度尺」。
   这与 Wk3 LangGraph 实验里「评分饱和」的观察一致，是 LLM-as-Judge 的固有局限。
3. **段间校验只管结构不管内容**，这是有意的职责划分：内容质量归 Reviewer。
   所以「摘要太短」是警告不是错误 —— 否则低质产出会在进审核循环前就被打死，revise 回路永远没机会跑。
4. **Git 提交未做**（按约定由 Hermes 统一提交）。步骤 9 自查表里唯一未勾的就是这一项。
5. **`.env` 在本地**，含真实 DeepSeek Key，已被 `.gitignore` 覆盖并用 `git check-ignore` 验证过。

---

## 7. 交付清单

```
v3-multi-agent/
├── AGENTS.md                    V1 项目定义（V3 版：补数据契约 + 红线）
├── .env.example / .gitignore / requirements.txt / pytest.ini / run.sh
├── .opencode/{agents,skills}/   V1 三个 Agent + 两个 Skill
├── pipeline/                    V2 迁入（model_client / pipeline / rss_collector / rss_sources.yaml）
├── hooks/                       V2 迁入（validate_json / check_quality）
├── patterns/                    router.py · supervisor.py · planner.py(re-export)
├── workflows/                   7 节点 + state / graph / nodes(兼容) / model_client
├── tests/                       cost_guard · security · eval_test · test_eval(别名)
│                                · test_workflow_units · test_router · verify_injection
├── scripts/check_v3.sh          12-4 步骤 6/7 的可执行清单
├── validate.py                  段间 schema 校验（加分项，已接入图）
├── quality.py                   V1/V2 规则评分（保留做「规则 vs LLM 5 维」对照）
├── knowledge/{raw,articles,pending_review}/ + cost-report.json
└── .github/workflows/daily-collect.yml
```

**下一步（M1.5 / M2）**：Wk3 收尾产出（实验报告 / 心得 / 博客 8-9）、V3 CI 真跑一次、
以及 M2 前置任务 T2.0（`scripts/build_index.py` 稳定 id + schema 对齐）。
