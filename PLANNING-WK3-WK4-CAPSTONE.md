# Wk3 / Wk4 / 毕业设计 —— 目标设计与执行路径

> 文档版本：v1.1（D1 已确认：实体放 OpenCodeStudy 盘符 + HOME 软链） ｜ 编写日期：2026-08-12 ｜ 依据：Wk3/Wk4 全套课件实操任务原文 + 本机环境探测 + 现有资产盘点
> 适用范围：极客时间《多 Agent 设计与工程化行动营》第 9–16 节实操 + V4 毕业项目交付
> 本文所有「必修」项均可回溯到课件原文；标注「加分」的是课件明示可选或课件未要求的自选项。

---

## 0. 结论摘要（先读这一页）

### 0.1 三个目标一句话

| 目标 | 一句话定义 | 判定完成的唯一硬标准 |
|:--|:--|:--|
| **G1 · Wk3** | 把已有的 LangGraph 实验资产，重构为课件规定的 `v3-multi-agent/` 项目形态，补齐第 9/11/12 节缺失模块，并让 CostGuard / Security 真正接入生产路径 | 12-4 步骤 7 的 V3 完整性检查脚本 14 个文件全 `[OK]`，且 `BUDGET_YUAN=0.001` 能让管线中途熔断 |
| **G2 · Wk4** | 在 `v4-production/` 上做产品化：OpenClaw 网关 + 知识库接入 + 分发层 + 交互 Bot + 定时推送 | 16-1 上线前 Checklist 10 项全绿 |
| **G3 · 毕业设计** | 交付一个可被陌生人 clone 起来跑的 GitHub 公开仓库 | 16-2 完整性检查 18 个文件全 `[OK]` + README + 截图 ≥3 张 + push 成功 + V1→V4 自查清单全勾 |

### 0.2 五个必须先拍板的决策（本文给出推荐，执行前请确认）

| # | 决策点 | 推荐方案 | 理由 |
|:--|:--|:--|:--|
| D1 | 项目实体目录放哪 | **✅ 已确认：实体放 `/Volumes/M4_Workspace/AIHarness/OpenCode/OpenCodeStudy/毕业设计/ai-knowledge-base/`（OpenCodeStudy 盘符）**，同时在 `~/ai-knowledge-base` 建软链指向它 | 用户拍板跟随 OpenCodeStudy 盘符；软链保底满足课件写死的 `~/ai-knowledge-base` 路径 + cron/daemon 绝对路径；挂载检查兜底见 §9 R5 |
| D2 | 毕业仓库用哪个 | **新建独立公开仓 `HC-Gamer/ai-knowledge-base`**；`HarnessSSDStudy` 继续做学习仓（实验/报告/博客） | 毕业仓库要面向陌生用户，不应混入课件 PDF（有版权风险，且 courseware 目前 untracked，建议直接加 .gitignore）、blogs、Wk1-Wk4 实验目录 |
| D3 | Python 版本 | **在 `~/ai-knowledge-base/.venv` 建 Python 3.12 环境** | 本机 `python3` = 3.9.6，课件参考实现大量使用 `str \| None`（PEP 604，需 3.10+），直接跑必然 `SyntaxError`；Docker 加餐基镜像也钉 3.12 |
| D4 | `relevance_score` 量纲 | **统一 0–1 浮点**（index.json 与 Bot/Skill 用）；保留 `analysis.relevance_score`（0–10）为原始分，生成 index 时归一 | 课件自身矛盾（见 §8.2），0–1 是 13-2 / 14-3 / 15-1 三处的多数写法 |
| D5 | Docker 做不做 | **列为 M4 加分项，不进主线** | 16-2 自查清单原文即写「Dockerfile + docker-compose.yml（可选）」；本机无 Docker，需先装 colima/Docker Desktop，成本高于收益 |

### 0.3 里程碑总览

```
M0 收尾清理 ──→ M1 Wk3 补齐（课程形态 V3） ──→ M2 Wk4 实现 ──→ M3 毕业交付
   (仓库卫生     (9/11/12 节 + 端到端 +        (13/14/15 节)    (16 节 + README
    + 环境)       V3 自查)                                      + 截图 + push)
                       │                                              ▲
                       └──→ M1.5 Wk3 收尾产出（报告/心得/博客8-9/CI）──┘
                                    （可与 M2 并行）

                                          M4 加分项（Docker / time-travel / eval 报告 / 落地页）
```

---

## 1. 事实基线

### 1.1 本机环境探测结果（2026-08-12 实测）

| 项 | 实测值 | 影响 |
|:--|:--|:--|
| node | v26.4.0 ✅ | 满足 OpenClaw 要求（≥ v22） |
| npm | 11.17.0 ✅ | 可 `npm i -g openclaw@latest` |
| openclaw | **未安装** | M2 第一步 |
| docker | **未安装** | 加餐降级，见 §7.2 |
| python3（系统） | **3.9.6 ⚠️** | 不可用于课件代码，见 D3 |
| Wk3/.venv | Python 3.13 | 仅本地实验用，与课程 3.12 不一致 |
| gh | 2.95.0 ✅ | 可 `gh repo create` / `gh secret set` / `gh run list` |
| crontab | 已有 2 条（Hermes 写博 / 课件提取） | 新增 daily_digest 一行即可，注意用 venv 绝对路径 |
| git remote | `git@github.com:HC-Gamer/HarnessSSDStudy.git` | 毕业仓库另建（D2） |

### 1.2 现有知识库数据（Wk4 的直接输入，有缺口）

`knowledge/articles/` 现有 17 个文件，单条 schema：

```
id / title / source / source_url / collected_at / summary / analysis{tech_highlights, relevance_score(0-10), score_reason} / tags / status
```

**缺口（Wk4 会直接卡住）**：
- ❌ 无 `index.json` —— 13-2、14-3、15-2 的 Bot 与 Skill 全部以 `Read knowledge/articles/index.json` 为第一步，没有它 Bot 只能瞎猜
- ❌ 无 `category` 字段 —— 13-2 验收题就是「知识库里有多少篇 agent 类文章」，靠 category 匹配
- ❌ 无顶层 `relevance_score` —— 现在埋在 `analysis` 里且是 0–10

→ 派生任务 **T2.0「知识库 schema 对齐」**，是 M2 的前置。现有 `v3-pipeline/graph.py` 里的 `quality_to_relevance()` / `derive_tags()` / `to_knowledge_entry()` 可直接复用来生成 index。

### 1.3 已有资产 → 课程文件的映射（Wk3 重构底稿）

| 现有资产 | 课程目标文件 | 改造动作 |
|:--|:--|:--|
| `langgraph_experiment.py: search_node` | `workflows/collector.py` | 拆文件 + 入口接 `sanitize_input` |
| `langgraph_experiment.py: analyze_node` | `workflows/analyzer.py` | 拆文件 + `node_name="analyze"` |
| `langgraph_experiment.py: quality_check_node` | `workflows/reviewer.py` | **重写评分**：改为 5 维加权（25/25/20/15/15），代码重算加权分，≥7.0 通过，只审前 5 条，temperature=0.1 |
| `langgraph_experiment.py: rewrite_node` | `workflows/reviser.py` | 改为「只改不评」，temperature=0.4 |
| `langgraph_experiment.py: organize_node` | `workflows/organizer.py` | 出口接 `filter_output` |
| `langgraph_experiment.py: abort_node` | `workflows/human_flag.py` | 改为落盘 `knowledge/pending_review/` |
| `PipelineState`（8 节点用） | `workflows/state.py: KBState` | 重定义为课程 9 字段 |
| `build_pipeline_graph()` | `workflows/graph.py` | 7 节点 + 3 路条件边 + cost_guard 收尾 |
| `validate.py`（段间校验） | 课程无对应物 | **保留为加分项**，挂在 collector/analyzer 之后，作为项目亮点写进 README |
| `quality.py` | 被 reviewer.py 取代 | 保留做对照，报告里写「规则评分 vs LLM 5 维加权」的差异 |
| `Wk2/v2-pipeline/{model_client,pipeline,hooks}` | `pipeline/` + `hooks/` | 整体拷入 v3-multi-agent，model_client 再接 CostGuard |
| `plan-and-execute/` | 课程无对应物 | 不进 V3 主线；作为「Planner 设计取舍」的实验依据写进博客 8 |

---

## 2. G1 · Wk3 目标定义

### 2.1 目标

> 产出一个符合课件 12-4 步骤 7 目录规范的 `v3-multi-agent/` 项目：7 节点 LangGraph 工作流 + 2 个设计模式 + 3 个生产防护模块，且防护模块**已接入生产路径**（不是摆设）。

### 2.2 范围

**In（必修）**
- 第 9 节：`patterns/router.py`、`patterns/supervisor.py`
- 第 10 节：`workflows/state.py`（KBState）、5→7 节点工作流、审核循环 —— 以现有实验资产重构达成
- 第 11 节：`workflows/reviewer.py`、`workflows/reviser.py`、`workflows/human_flag.py`、`workflows/planner.py`
- 第 12 节：`tests/cost_guard.py`、`tests/eval_test.py`、`tests/security.py` + 12-4 四个接入点
- V1/V2 资产迁入（`AGENTS.md`、`.opencode/`、`pipeline/`、`hooks/`、`.github/workflows/`）

**In（加分）**
- 段间 schema 校验 `validate.py` 接入图（现成资产）
- 第 10 节 time-travel 分叉重放
- SQLite checkpoint 续跑（现成资产）

**Out（明确不做）**
- 不把 `plan-and-execute/` 塞进 V3 主线 —— 它与课程 `planner.py` 形态不同（前者是执行型 Plan-and-Execute，后者是「只规划不执行」的图入口节点），混进去反而破坏课程拓扑
- 不重跑 LangGraph 2×2 对照实验（已完成，只补报告口径修正）

### 2.3 完成标准（可勾选）

**结构与文件**
- [ ] `毕业设计/ai-knowledge-base/v3-multi-agent/` 已建（`~/ai-knowledge-base` 软链指向实体），Python 3.12 venv 可用
- [ ] 12-4 步骤 7 检查脚本 14 项全 `[OK]`：`patterns/router.py`、`workflows/{state,planner,collector,analyzer,reviewer,reviser,organizer,human_flag,graph,model_client}.py`、`tests/{cost_guard,security,eval_test}.py`
- [ ] `patterns/supervisor.py` 存在（脚本未列但 9-2 必修、V4 检查会查）
- [ ] `python3 -c "from workflows.state import KBState; print(len(KBState.__annotations__))"` 输出 **9**

**第 9 节**
- [ ] `python -m patterns.router` 三类查询（github_search / knowledge_query / general_chat）分类正确；关键词命中不调 LLM，未命中走 LLM 兜底
- [ ] `python -m patterns.supervisor` 跑出「Worker 产出 → Supervisor 评分（准确性/深度/格式 1-10）→ 带反馈重做」循环，最多 3 轮后退出

**第 10/11 节**
- [ ] `python3 -m workflows.graph` 端到端跑通，日志出现 `[Planner] 策略：standard`
- [ ] `PLANNER_TARGET_COUNT` 切换能看到 lite / standard / full 三档差异
- [ ] Reviewer 输出 5 维分且**加权总分由 Python 重算**（不采信模型算术）；≥7.0 通过
- [ ] 三路分支可达：正常 → organize；打回 → revise；超轮次 → human_flag（落盘 `knowledge/pending_review/`）

**第 12 节（接入是重点）**
- [ ] `grep -l "cost_guard\|sanitize_input\|filter_output" workflows/*.py` **非空**
- [ ] `BUDGET_YUAN=0.001 python3 -m workflows.graph` 中途熔断，**未产出 organize/save**
- [ ] 注入样例被 `sanitize_input` 检出（warnings ≥ 1）
- [ ] PII 样例被掩码为 `[PHONE_CN_MASKED]` / `[EMAIL_MASKED]` / `[IP_ADDRESS_MASKED]`
- [ ] 跑完写出 `knowledge/cost-report.json`，含按节点分组成本
- [ ] `pytest tests/` 全绿（注意 12-2 文件名 `eval_test.py` 不符合 pytest 默认发现规则，需在 `pytest.ini` 配 `python_files = test_*.py eval_test.py`）
- [ ] 12-4 步骤 6 接入清单 8 项全 `是`
- [ ] 12-4 步骤 9 的 V1→V3 自查清单全勾

**收尾产出（课程未强制，但属于既定学习目标）**
- [ ] `plan-and-execute` 实验报告 + 心得 + 博客 8
- [ ] `v3-pipeline` 实验报告 + 心得 + 博客 9
- [ ] LangGraph 实验报告修订：补「评分饱和」「单次采样噪声」两个局限说明
- [ ] V3 CI（`.github/workflows/daily-collect.yml` 指向 v3 工作流）跑通一次

---

## 3. G2 · Wk4 目标定义

### 3.1 目标

> 在 `v4-production/`（= v3 全量继承 + 增量）上，让知识库长出「嘴」和「耳朵」：能主动定时推送，能被动响应查询，且跑在受控的权限与预算边界内。

### 3.2 范围

**In（必修）**
- 13-1 OpenClaw 安装 + Telegram 连通 + DM pairing
- 13-2 v3→v4 继承 + workspace 切换 + 清占位 + 软链 knowledge + 改 `openclaw/AGENTS.md` 为 messaging profile 友好版
- 14-1 `distribution/formatter.py`（Markdown / Telegram 两种格式）
- 14-2 `distribution/publisher.py`（异步 + Telegram/飞书 + 无凭证时返回 `PublishResult(success=False)` 而非崩溃）
- 14-3 `daily_digest.py` + `openclaw/skills/daily-digest/SKILL.md` + cron
- 15-1 `bot/knowledge_bot.py`（意图识别 + 加权搜索 title+10/tags+5/summary+3 + `/search /today /top /subscribe /help`）
- 15-2 自写新 Skill `openclaw/skills/top-rated/SKILL.md`，Telegram 可触发
- **T2.0 知识库 schema 对齐**（本文新增的前置任务，见 §1.2）

**In（加分）**
- 飞书渠道真跑通（课件原文「佳哥只测试了 Telegram，飞书等格式请大家自行开发」）
- LLM rerank / 同义词扩展 / 搜索历史（15-1 扩展节）
- Skill description 精度回归用例（15-2 扩展节）

**Out**
- 微信/钉钉渠道
- Cloudflare Tunnel 公网暴露（16-2 进阶项，移入 M4）

### 3.3 完成标准（可勾选）

**前置**
- [ ] `knowledge/articles/index.json` 生成，含 `id/title/category/relevance_score(0-1)/tags/collected_at`
- [ ] 每篇 article JSON 补齐 `category` 与顶层 `relevance_score`
- [ ] 索引生成脚本 `scripts/build_index.py` 可重复执行（幂等）

**13 节**
- [ ] `openclaw --version` 有输出；`openclaw daemon status` 运行中
- [ ] `openclaw channel list` 显示 telegram Online
- [ ] Telegram 发「你好」，Bot 回复（DM pairing 已 approve）
- [ ] `openclaw config get agents.defaults.workspace` = `/Users/huangcheng/ai-knowledge-base/v4-production/openclaw`（软链穿透到盘符实体；课件写 `/home/$USER`，macOS 是 `/Users/`）
- [ ] `ls v4-production/openclaw/*.md` 只剩 `AGENTS.md` + `SOUL.md`
- [ ] `ls v4-production/openclaw/knowledge/articles/index.json` 能找到（软链生效）
- [ ] `openclaw config get tools.alsoAllow` = `["read"]`
- [ ] 本地：`openclaw agent --local --agent main --message "知识库里有多少篇 agent 类文章?"` 返回准确数字
- [ ] Telegram：`/start` 开新会话后问同一问题，返回同样准确的数字

**14 节**
- [ ] `formatter.py` 用真实数据产出 Markdown 与 Telegram 两种格式，且是纯函数（无 IO 副作用）
- [ ] `publisher.py` dry-run（无凭证）不崩溃，返回 `success=False`
- [ ] 真实推送成功，Telegram 收到消息（MarkdownV2 特殊字符已转义，`.` `-` `(` `)` 不报 400）
- [ ] `python3 daily_digest.py` 手动跑成功，打印「N/M 个渠道成功」
- [ ] `crontab -l | grep daily_digest` 命中；用「1 分钟后触发」法验证过一次真实执行（macOS 用 `date -v+1M +"%M %H"`，非课件的 `date -d`）
- [ ] `openclaw/skills/daily-digest/SKILL.md` 存在，`allowed-tools` 只有 `Read`

**15 节**
- [ ] `recognize_intent` 6 条测试用例全过（含 `/top 3` 带参数、自然语言「搜一下 RAG」）
- [ ] `KnowledgeBot.handle_message` 五个 handler 全部可达
- [ ] `openclaw/skills/top-rated/SKILL.md` 存在，Telegram 说「推荐几篇高分的」能触发并返回准确 Top N
- [ ] Skill 未命中时能 fallback 到主 Agent 的 `Read index.json` 路线（不报错、不卡死）

**16-1 上线前 Checklist（10 项，逐项留证）**
- [ ] 1 API Keys：`.env` 权限 600、`git ls-files .env` 空、`.env.example` 完整
- [ ] 2 权限策略：2 个 Skill 的 `allowed-tools` 只有 `Read`；`SKILL.md`/`AGENTS.md` 不再提 Glob/Grep/exec；无 Skill 写 `knowledge/`
- [ ] 3 备份：`knowledge/` 有数据、git 有远程且已推送（Docker 镜像标签项按 §7.2 降级）
- [ ] 4 日志轮转：`logs/` 有轮转策略且不含敏感信息（无 Docker 时用 `newsyslog`/脚本轮转替代 compose 的 10m×3）
- [ ] 5 成本预算：CostGuard 预算与熔断阈值已设，月成本估算写进 README
- [ ] 6 版本固定：`requirements.txt` 全部带版本号
- [ ] 7 测试通道：管线手动跑通 + `pytest tests/` 通过 + Telegram 测试消息成功
- [ ] 8 回滚方案：文档写明「git tag 回滚 + knowledge/ 恢复」两条路径
- [ ] 9 OpenClaw：daemon 监听 18789（macOS 用 `lsof -nP -iTCP:18789 -sTCP:LISTEN`，非课件的 `ss -tlnp`）、默认模型 ≠ `openai/gpt-5.5`、模型可调、workspace 指向 v4
- [ ] 10 GitHub Actions：`DEEPSEEK_API_KEY` secret 已配，`daily-collect-v4.yml` 24h 内有 success，`git log` 能看到 `chore(v4)` 入库 commit

---

## 4. G3 · 毕业设计目标定义

### 4.1 目标

> 交付一个陌生人能读懂、能 clone、能跑起来的 GitHub 公开仓库，证明 V1→V4 四周演进真实发生过。

### 4.2 范围

**In（必修）**
- 仓库创建 + push（`HC-Gamer/ai-knowledge-base`，公开）
- README（7 个部分：架构图 / 快速开始 / 目录结构表 / 技术栈 / 版本历史 / 月度成本 / MIT License）
- 截图 ≥3 张：① 管线运行成功 ② Telegram 推送或搜索 ③ 日志/成本统计
- 16-2 步骤 1 完整性检查 18 个文件全 `[OK]`
- 16-2 步骤 6 的 V1→V2→V3→V4 自查清单全勾

**In（加分，课件明示）**
- Dockerfile + docker-compose.yml（16-2 原文标「可选」）
- Cloudflare Tunnel 公网地址
- GitHub Pages 产品落地页
- 博客/知识星球分享（本项目已有 9 篇博客，天然满足并超额）
- 评估报告：10–20 条真实 query × Skill 触发率/准确率（呼应 SDD eval 议题）

**Out**
- 云服务器部署（课件 README 模板列了服务器成本，但实操未要求真买）

### 4.3 完成标准（可勾选）

- [ ] `gh repo create ai-knowledge-base --public --source=. --push` 成功，仓库可匿名访问
- [ ] 16-2 完整性检查 18 项全 `[OK]`（`AGENTS.md`、`pipeline/pipeline.py`、`workflows/{graph,nodes,state,model_client}.py`、`patterns/{planner,router,supervisor}.py`、`Dockerfile`、`docker-compose.yml`、`bot/knowledge_bot.py`、`distribution/{formatter,publisher}.py`、`daily_digest.py`、`openclaw/{openclaw.json5,AGENTS.md,SOUL.md}`、`openclaw/skills/{daily-digest,top-rated}/SKILL.md`）
  - ⚠️ 注意 `workflows/nodes.py`：课程 V3 里它是「向后兼容 re-export」，V4 检查会查它是否存在，不能删
  - ⚠️ 注意 `patterns/planner.py`：见 §8.1 的矛盾处理
  - ⚠️ Docker 两文件若走降级路径（§7.2），需在 README 明确说明「以 launchd/cron 替代」，并接受该两项标 `[!!]`
- [ ] README 七部分齐全，架构图为文本框图（终端可读）
- [ ] `screenshots/` ≥3 张，文件名自解释（`01-pipeline-run.png` 等）
- [ ] 仓库内**无** `.env`、无课件 PDF、无 `.venv`、无 `__pycache__`
- [ ] `git log --oneline` 呈现「一行一节实操」的演进史（至少 V3/V4 部分可辨认）
- [ ] 陌生环境冒烟：另建空目录 clone → `cp .env.example .env` 填 key → 按 README 三步能跑出结果（不含 Telegram 部分）

---

## 5. 未完成事项归并表

| # | 未完成事项 | 归入目标 | 归入里程碑 | 必修/加分 | 备注 |
|:--|:--|:--|:--|:--|:--|
| 1 | Wk3 第9节 Router / Supervisor | G1 | M1-T1.2 | 必修 | 完全没做，课程正题 |
| 2 | 第11节 reviewer 5维加权 / reviser / human_flag | G1 | M1-T1.4 | 必修 | 现有 quality_check+rewrite 需按课程口径重写 |
| 3 | 第11节 planner.py 三档策略 | G1 | M1-T1.5 | 必修 | 与 plan-and-execute 实验概念相关、形态不同，不复用代码 |
| 4 | 第12节 cost_guard / eval_test / security | G1 | M1-T1.6 | 必修 | 三个独立模块 |
| 5 | 第12节任务4 三处接入 | G1 | M1-T1.7 | 必修 | **本周最关键一步**，「写代码 ≠ 起作用」 |
| 6 | plan-and-execute 报告 + 心得 + 博客8 | G1 | M1.5-T1.9 | 学习目标 | 代码已完成，只缺产出 |
| 7 | v3-pipeline 报告 + 心得 + 博客9 | G1 | M1.5-T1.10 | 学习目标 | 同上 |
| 8 | V3 CI 未接 | G1/G3 | M1.5-T1.11 | 必修（16-1 检查 10 会查） | 与 `daily-collect-v4.yml` 共用一套模板 |
| 9 | time-travel 分叉重放 | G1 | M4 | 加分（课件标「自选补充」） | |
| 10 | LangGraph 报告残留（评分饱和 / 单次采样噪声） | G1 | M1.5-T1.12 | 学习目标 | 只需补「局限性」一节 |
| 11 | Wk2 SDD 加餐包未解压 | — | M4 | 加分 | 与主线无依赖 |
| 12 | Wk2 cost_comparison 模型路由对比（Qwen 无 Key） | — | M4 | 加分 | 降级见 §7.3 |
| 13 | Wk2 本地 crontab 未配 | G2 | M2-T2.6 | 必修（14-3） | 直接被 14-3 覆盖，不必单独做 |
| 14 | Wk2 TypeScript Hook | — | 不做 | 选修 | 明确放弃 |
| 15 | Wk4 全部（13–16 节） | G2/G3 | M2 / M3 | 必修 | |
| 16 | 仓库卫生（validate.py 等未提交） | — | M0 | 必修（工程纪律） | |
| 17 | **知识库缺 index.json / category（新发现）** | G2 | M2-T2.0 | 必修（Wk4 前置） | 不做则 13-2/14-3/15-2 全部卡住 |
| 18 | **Python 3.12 环境缺失（新发现）** | G1 | M0-T0.3 | 必修 | 不做则 M1 第一行代码就 SyntaxError |
| 19 | **课件 PDF 版权风险（新发现）** | G3 | M0-T0.2 | 必修 | courseware 加 .gitignore |

---

## 6. 重合点与依赖关系

### 6.1 V3 → V4 继承关系图

```
   Wk1 (V1)                Wk2 (V2)                    Wk3 (V3)                       Wk4 (V4)
┌────────────┐        ┌────────────────┐        ┌────────────────────┐        ┌──────────────────────┐
│ AGENTS.md  │───────▶│                │───────▶│                    │───────▶│  v4-production/      │
│ .opencode/ │        │ pipeline/      │        │ patterns/          │  13-2  │                      │
│  agents/   │        │  model_client  │        │  router.py    ①    │ 步骤0  │  ├ AGENTS.md    (V1) │
│  skills/   │        │  pipeline.py   │        │  supervisor.py①    │  cp -rn│  ├ .opencode/   (V1) │
└────────────┘        │ hooks/         │        │  planner.py  (薄)  │ ══════▶│  ├ pipeline/    (V2) │
                      │  validate_json │        │ workflows/         │        │  ├ hooks/       (V2) │
                      │  check_quality │        │  state.py     ②    │        │  ├ workflows/   (V3) │
                      │ .github/       │        │  planner.py   ③    │        │  ├ patterns/    (V3) │
                      │  workflows/    │        │  collector.py ④    │        │  ├ tests/       (V3) │
                      └────────────────┘        │  analyzer.py       │        │  ├ knowledge/   (V3) │
                                                │  reviewer.py  ③    │        │  │                   │
                                                │  reviser.py   ③    │        │  ├ openclaw/   ★13节 │
                                                │  organizer.py ④    │        │  ├ distribution/★14节│
                                                │  human_flag.py③    │        │  ├ bot/        ★15节 │
                                                │  graph.py          │        │  ├ daily_digest.py★14│
                                                │  nodes.py (兼容)   │        │  ├ Dockerfile  ★加餐 │
                                                │  model_client ⑤    │        │  ├ README.md   ★16节 │
                                                │ tests/             │        │  └ screenshots/★16节 │
                                                │  cost_guard.py⑥    │        └──────────────────────┘
                                                │  security.py  ⑥    │                   │
                                                │  eval_test.py ⑥    │                   ▼
                                                └────────────────────┘         16-2 完整性检查 18 项
                                                          │                    ├─ 7 项来自 V1/V2/V3 继承
                                                          └── 12-4 接入 ⑦      └─ 11 项为 V4 新增

  ① 第9节  ② 第10节  ③ 第11节  ④ 第10节+第12节接入  ⑤ 第10节+第12节接入  ⑥ 第12节  ⑦ 第12节任务4
```

### 6.2 关键重合点（做一次，交两次账）

| 重合点 | Wk3 侧 | Wk4/毕业侧 | 结论 |
|:--|:--|:--|:--|
| **R1 patterns/ + workflows/ + tests/** | 第 9/11/12 节的全部产出 | 16-2 完整性检查里 7 个 V3 继承项 | Wk3 做扎实 = V4 检查白送 7 项 |
| **R2 12-4 「提交 V3」** | 第 12 节任务 4 | 13-2 步骤 0 的 `cp -rn` 源头 | V3 没提交干净，V4 就是拷了一堆半成品过去 |
| **R3 V1→V3 自查清单** | 12-4 步骤 9 | 16-2 步骤 6 前三节完全相同 | 12-4 时逐条勾，16-2 直接复用 |
| **R4 CostGuard 预算配置** | 12-1 + 12-4 接入 | 16-1 检查 5「成本预算」 | 同一份配置 |
| **R5 security.py PII 掩码** | 12-3 + 12-4 接入 | 毕业仓库公开 → 防止真实邮箱/手机号进公开仓 | 从「课程要求」升级为「真实必要」 |
| **R6 `.github/workflows/`** | V2 遗产 + Wk3 CI 债 | 16-1 检查 10 `daily-collect-v4.yml` | 一次写好，改个 workflow 名复用 |
| **R7 knowledge/ 数据** | V3 管线的产出 | Bot / Skill / formatter 的**唯一输入** | schema 必须在 M2 之前对齐（T2.0） |
| **R8 validate.py 段间校验** | 加分项 | README「工程亮点」+ 评估报告素材 | 已完成的资产，用来抬高毕业项目辨识度 |
| **R9 博客 8/9** | Wk3 收尾 | 16-2 进阶项「写一篇博客分享」 | 已有 7 篇 + 补 2 篇 = 加分项超额达成 |

### 6.3 硬依赖链（不可乱序）

```
D3 Python 3.12 环境 ──▶ M1 全部
M1-T1.1 v3 骨架 ──▶ T1.2 patterns ──▶ T1.3 workflows 拆分 ──▶ T1.4/T1.5 ──▶ T1.6 tests ──▶ T1.7 接入 ──▶ T1.8 V3 自查
T1.8 V3 通过 ──▶ M2-T2.1 (13-2 的 cp -rn 依赖 v3 完整)
T2.0 index.json ──▶ T2.2 (13-2 Bot 验收) & T2.4 (formatter) & T2.7 (knowledge_bot)
T2.1 OpenClaw 装通 ──▶ T2.2 ──▶ T2.6 (daily-digest Skill) ──▶ T2.8 (top-rated Skill，15-2 前置写明依赖 14-3)
T2.5 publisher ──▶ T2.6 daily_digest
M2 全部 ──▶ M3-T3.1 (16-1 Checklist 前置要求「13/14/15 已跑通」)
```

---

## 7. 执行路径

> **委派约定**
> - **AI 辅助**：架构决策、跨文件重构方案、评分口径设计、报告与博客写作、验收审阅
> - **DeepSeek / OpenCode**：按课件参考实现生成代码、写单测、写脚本（课件每个任务都给了提示词，直接喂）
> - **OpenCode sub-agent**：批量机械改造（`node_name` 透传、import 路径调整、逐项检查脚本执行）
> - **人工（不可委派）**：BotFather 建 bot、DM pairing 审批、截图、`gh secret` 配置、代理网络配置

### M0 · 收尾清理与环境准备

| ID | 任务 | 依赖 | 委派 | 完成标准 |
|:--|:--|:--|:--|:--|
| T0.1 | 提交现有未提交改动（validate.py + valid-* 样本 + langgraph 修复轮结果 + plan-and-execute + Wk4 骨架） | — | OpenCode | `git status` 干净（除有意忽略项） |
| T0.2 | `.gitignore` 加 `Wk*/courseware/`（版权）+ `**/.venv/`；若已入库则 `git rm --cached` | T0.1 | OpenCode | `git ls-files \| grep courseware` 为空 |
| T0.3 | 装 Python 3.12（`brew install python@3.12` 或 uv），建 `~/ai-knowledge-base/.venv` | — | 人工 | `.venv/bin/python -V` → 3.12.x |
| T0.4 | 建 `OpenCodeStudy/毕业设计/ai-knowledge-base/{v3-multi-agent,v4-production}`；建 `~/ai-knowledge-base` 软链指向实体（课件路径兼容） | T0.3 | OpenCode | 两目录存在，软链可 `ls` 穿透 |
| T0.5 | 决策确认 D1–D5（人工拍板） | — | 人工 | 本文 §0.2 五行全部签字 |

### M1 · Wk3 补齐（课程形态 V3）

| ID | 任务 | 依赖 | 委派 | 完成标准 |
|:--|:--|:--|:--|:--|
| T1.1 | 搭 v3-multi-agent 骨架：迁入 Wk1 的 `AGENTS.md`/`.opencode/`，Wk2 的 `pipeline/`/`hooks/`/`.github/`，建 `knowledge/{raw,articles,pending_review}` | T0.4 | OpenCode | V1/V2 段检查脚本全 `[OK]` |
| T1.2 | 第 9 节：`patterns/router.py` + `patterns/supervisor.py` | T1.1 | DeepSeek 生成 + AI 辅助 审 | `python -m patterns.router` / `.supervisor` 按 §2.3 通过 |
| T1.3 | 第 10 节重构：`state.py`(KBState) + 从 `langgraph_experiment.py` 拆出 collector/analyzer/organizer + `graph.py` + `nodes.py` re-export | T1.1 | AI 辅助 出拆分方案 → OpenCode 执行 | KBState 9 字段；`python3 -m workflows.graph` 能跑到 organize |
| T1.4 | 第 11-1/11-2：`reviewer.py`（5 维加权，Python 重算）+ `reviser.py`（只改不评）+ `human_flag.py` + graph 三路分支 | T1.3 | DeepSeek 生成 + **AI 辅助 审评分口径** | 三路分支均可达；加权分与手算一致 |
| T1.5 | 第 11-3：`planner.py` 三档策略 + KBState 加 `plan` + 挂图入口 | T1.4 | DeepSeek | 三档 env 切换生效；11-3 步骤 6 验证清单全过 |
| T1.6 | 第 12-1/2/3：`tests/{cost_guard,eval_test,security}.py` + `pytest.ini` | T1.1 | DeepSeek | 三个模块独立自测通过；`pytest tests/` 全绿 |
| T1.7 | **第 12-4 接入**：model_client 记账+熔断、各节点透传 `node_name`、collector 入口 sanitize、organizer 出口 filter、graph 收尾写 `cost-report.json` | T1.5 + T1.6 | OpenCode sub-agent（机械） + AI 辅助 审 | §2.3「第12节」全部勾选，尤其熔断中途停 |
| T1.8 | V3 整体自查 + 提交（commit message: `feat: wire CostGuard + Security into graph (V3 real completion)`） | T1.7 | OpenCode | 12-4 步骤 6/7/9 三张清单全过 |
| T1.9 | 加分：接入 `validate.py` 段间校验为 collector/analyzer 后置闸门 | T1.3 | OpenCode | 坏数据被拦，走 human_flag |

### M1.5 · Wk3 收尾产出（可与 M2 并行）

| ID | 任务 | 依赖 | 委派 | 完成标准 |
|:--|:--|:--|:--|:--|
| T1.10 | plan-and-execute 实验报告 + 心得 + 博客 8 | — | AI 辅助 | 报告含 Plan-and-Execute vs ReAct 的成本/步数/失败模式对照 |
| T1.11 | v3-pipeline 实验报告 + 心得 + 博客 9 | — | AI 辅助 | 含 92 分 / ¥0.0028 那次运行的完整复盘 |
| T1.12 | LangGraph 报告补「局限性」：评分饱和、单次采样噪声 | — | AI 辅助 | 报告新增一节，结论口径收敛 |
| T1.13 | V3 CI：`.github/workflows/daily-collect.yml` 指向 v3 工作流并跑通一次 | T1.8 | OpenCode + 人工配 secret | `gh run list` 有 success |

### M2 · Wk4 实现

| ID | 任务 | 依赖 | 委派 | 完成标准 |
|:--|:--|:--|:--|:--|
| T2.0 | **知识库 schema 对齐**：`scripts/build_index.py` 生成 `index.json`，补 `category` + 顶层 `relevance_score`(0-1) | T1.8 | DeepSeek + AI 辅助 定 schema | index.json 字段齐全且幂等可重跑 |
| T2.1 | 13-1：装 OpenClaw + onboard + 建 Telegram Bot + 渠道 + DM pairing | T0.3 | 人工（BotFather/审批）+ OpenCode 排错 | 13-1 检查清单 8 项全过 |
| T2.2 | 13-2：v3→v4 `cp -rn` + 切 workspace + 清占位 + 软链 knowledge + 改 `openclaw/AGENTS.md`（messaging profile） | T1.8 + T2.0 + T2.1 | OpenCode | 13-2 检查清单 8 项全过；Telegram 新会话返回准确数字 |
| T2.3 | 14-1：`distribution/formatter.py` | T2.0 | DeepSeek | 两种格式产出正确；纯函数 |
| T2.4 | 14-2：`distribution/publisher.py`（异步 + Telegram + 飞书 + MarkdownV2 转义） | T2.3 | DeepSeek | dry-run 不崩；真实推送成功 |
| T2.5 | 14-3：`daily_digest.py` + `openclaw/skills/daily-digest/SKILL.md` + crontab | T2.4 | DeepSeek + 人工配 cron | 手动跑成功；cron 1 分钟验证法跑出日志 |
| T2.6 | 15-1：`bot/knowledge_bot.py`（意图 + 加权搜索 + 5 指令 + 权限） | T2.0 | DeepSeek | 意图 6 用例全过；5 handler 可达 |
| T2.7 | 15-2：`openclaw/skills/top-rated/SKILL.md` | T2.5 | AI 辅助 写 description + OpenCode | Telegram 自然语言可触发，返回准确 Top N |
| T2.8 | GitHub Actions `daily-collect-v4.yml` + `DEEPSEEK_API_KEY` secret | T1.13 | OpenCode + 人工 | 24h 内有 success，`chore(v4)` commit 入库 |

### M3 · 毕业交付

| ID | 任务 | 依赖 | 委派 | 完成标准 |
|:--|:--|:--|:--|:--|
| T3.1 | 16-1：10 项 Checklist 逐项验证并留证（macOS 命令替换见 §8.3） | M2 全部 | OpenCode 执行 + AI 辅助 审 | 10 项全绿或有明示降级说明 |
| T3.2 | 16-2 步骤 1：V4 完整性检查 18 项 | T3.1 | OpenCode | 全 `[OK]`（Docker 两项按 §7.2 处理） |
| T3.3 | README.md（7 部分） | T3.2 | AI 辅助 | 七部分齐全，架构图为文本框图 |
| T3.4 | 截图 ≥3 张进 `screenshots/` | T3.1 | 人工 | 三类场景各一张，文件名自解释 |
| T3.5 | 建独立公开仓 + push + V1→V4 自查清单全勾 | T3.3 + T3.4 | 人工 + OpenCode | 仓库匿名可访问；清单全勾 |
| T3.6 | 陌生环境冒烟：空目录 clone 按 README 跑通 | T3.5 | OpenCode | 三步走通（Telegram 部分除外） |

### M4 · 加分项（按投入产出排序，可全部不做）

| 优先 | 任务 | 价值 | 成本 |
|:--|:--|:--|:--|
| ★★★ | **评估报告**：10–20 条 query × Skill 触发率/准确率 | 16-2 明示加分，且是全班差异化点；与 SDD eval 议题呼应 | 低（有 validate.py 与现成数据） |
| ★★★ | 博客 8/9（已在 M1.5） | 16-2 进阶项，已有 7 篇基础 | 低 |
| ★★ | time-travel 分叉重放 | 第 10 节自选补充，LangGraph 深度体现 | 中（checkpoint 已就绪） |
| ★★ | GitHub Pages 落地页 | 让毕业项目有终端用户入口 | 低 |
| ★ | Docker + compose | 16-2 标可选；本机需先装 colima | 高（见 §7.2） |
| ★ | Cloudflare Tunnel | 公网可访问 | 中（叠加网络风险） |
| ★ | Wk2 SDD 加餐包 / Qwen 路由对比 | 与主线无依赖 | 中（Qwen 需 Key） |

---

## 8. 课件内部矛盾与平台差异（执行前必读）

### 8.1 `planner.py` 到底在 `workflows/` 还是 `patterns/`？

- 11-3 原文：「目标文件：`workflows/planner.py`（新增）」
- 12-4 步骤 7 目录树：`workflows/planner.py`
- 12-4 步骤 9 自查：`workflows/planner.py`
- **16-2 步骤 1 V4 完整性检查：`patterns/planner.py`** ← 唯一的异类

**处理**：主体实现放 `workflows/planner.py`；`patterns/planner.py` 写 3 行 re-export（`from workflows.planner import planner_node, make_plan  # noqa: F401`）。两处检查都过，且符合 `patterns/` 是「通用设计模式演示」的定位。

### 8.2 `relevance_score` 量纲三处不一致

| 出处 | 量纲 | 阈值 |
|:--|:--|:--|
| 13-2 `openclaw/AGENTS.md` 示例 | 0–1 | — |
| 14-3 daily-digest SKILL.md | 0–1 | `>= 0.6` |
| 14-3 daily_digest.py 需求 | 疑似 0–100 | `< 60` 过滤 |
| 15-1 输出示例 | 0–1（0.95 / 0.85） | — |
| **本项目现有数据** | **0–10（埋在 `analysis` 里）** | — |

**处理（D4）**：index.json 与所有 Bot/Skill/formatter 统一用 **0–1 浮点**；`daily_digest.py` 阈值写 `0.6`；原始 `analysis.relevance_score`(0–10) 保留，`build_index.py` 除以 10 归一。在 README 的数据字典里写清楚。

### 8.3 课件是 Ubuntu，本机是 macOS —— 必须替换的命令

| 课件（Linux） | macOS 等价 | 出现处 |
|:--|:--|:--|
| `/home/$USER/...` | `/Users/huangcheng/...`（实体在盘符 `毕业设计/ai-knowledge-base/`，`~/ai-knowledge-base` 软链穿透） | 13-2、14-3、16-1 |
| `ss -tlnp \| grep 18789` | `lsof -nP -iTCP:18789 -sTCP:LISTEN` | 16-1 检查 9 |
| `date -d "+1 minute" +"%M %H"` | `date -v+1M +"%M %H"` | 14-3 步骤 5 |
| `apt` 装 Docker + systemd | `brew install colima docker docker-compose` + `colima start` | 加餐 |
| `openclaw onboard --install-daemon` 装 systemd 服务 | 落到 launchd；若失败改用 `openclaw daemon start` + launchd plist 手工托管 | 13-1 |
| `>> ~/.bashrc` | `>> ~/.zshrc`（本机 shell 为 zsh） | 13-1 |

### 8.4 其他小差异

- 16-1 标题写「8 项 Checklist」，正文实为 **10 项** —— 以 10 项为准
- 16-2 自查清单写 `tests/test_eval.py`，12-2 实操写 `tests/eval_test.py` —— 以 `eval_test.py` 为准，在 `pytest.ini` 配 `python_files = test_*.py eval_test.py`，必要时加一个 `test_eval.py` 一行 import 别名双保险
- 13-1 示例配置里出现真实 API Key 与 Token（课件截图未脱敏）—— 提醒：自己的 `openclaw.json`/`openclaw.json5` 含明文 key，**绝不能进公开仓**；毕业仓库里应放 `openclaw/openclaw.json5` 的**脱敏模板**（16-2 检查只查文件存在）

---

## 9. 风险与降级方案

| # | 风险 | 触发信号 | 降级路径 | 对验收的影响 |
|:--|:--|:--|:--|:--|
| **R1** | **Telegram 不可达**（中国大陆网络） | `openclaw channel add telegram` 超时；Bot 无响应 | ① 给 daemon 注入代理：`HTTPS_PROXY`/`ALL_PROXY` 环境变量后重启（launchd plist 里也要写）② 仍不通 → **切飞书**：课件示例 `openclaw.json5` 本身就带 feishu channel，14-2 publisher 也要求飞书；`openclaw channel add feishu` + webhook ③ 再不通 → **本地渠道**：`openclaw agent --local` 完成 13-2/15-2 的本地验证，截图用本地对话 + 文件落盘的 digest | 13-1「Telegram 回复」与 16-1 检查 7「Telegram 测试消息」改为「飞书/本地等价验证」，README 明示替代方案并附截图。课件原文允许：「没有 Telegram 只能搜索连接飞书、微信等其它 Bot 的方法」 |
| **R2** | **Docker 不可用**（本机未装，Apple Silicon 无 Docker Desktop） | `docker --version` 失败 | ① 装 colima：`brew install colima docker docker-compose && colima start`（≈10 分钟，纯本地）② 不装 → **主线不受影响**：16-2 自查原文标「Dockerfile + docker-compose.yml（可选）」。仍写出这两个文件（保证 16-2 完整性检查 18 项全 `[OK]`），但**不构建镜像**，README 注明「已提供容器化配置，本机以 launchd/cron 直跑」 | 16-1 检查 3「Docker 镜像版本标签」→ 改为 **git tag 版本标记**；检查 4「compose 日志轮转 10m×3」→ 改为 `logs/` 目录 + 脚本或 `newsyslog` 轮转；检查 8「回滚 Docker 镜像」→ 改为 `git checkout <tag>` + 重启 daemon。三项在文档中写明等价替代 |
| **R3** | **Qwen 无 Key**，模型路由对比做不了 | 申请不到/不想申请 | ① 用 **DeepSeek 两档模型**（`deepseek-chat` vs `deepseek-reasoner`，单价 0.27/1.1 vs 0.55/2.19）做路由对比 —— 便宜档跑 collect/organize，贵档跑 review，成本对比数据真实可得 ② 或用「同模型不同 max_tokens/temperature」做成本-质量曲线 | 该项本就是 Wk2 遗留加分项，不影响任何必修验收。写进 README「模型分级路由」一节即可（16-2 结语提到「成本控制 — CostGuard + 模型分级路由」） |
| **R4** | OpenClaw 版本漂移（课件版本 2026.4.23，现已数月） | CLI 子命令改名、`openclaw.json` vs `openclaw.json5` 差异 | 课件自己写明「工具演进很快，最好去 GitHub 查最新安装方法」。以 `openclaw --help` 为准，配置项用 `openclaw config get/set` 而非手改 JSON；把实际用的版本号写进 README「技术栈」 | 无影响，但要求 16-2 检查里的 `openclaw/openclaw.json5` 文件名按实际生成的来（若实际是 `.json`，两份都放或做软链） |
| **R5** | 盘符卷未挂载导致 cron/daemon 全线失败 | `/Volumes/M4_Workspace` 未挂载 | 本机 M4_Workspace 为内置卷，常态挂载、风险低；兜底：cron/launchd 命令前加 `test -d /Volumes/M4_Workspace/... || exit 1` 挂载检查，未挂载静默跳过；daemon 重启脚本先验软链穿透 | 无 |
| **R6** | 系统 Python 3.9 被 cron 误用 | cron 日志 `SyntaxError: invalid syntax` 指向 `str \| None` | crontab 里写 venv 绝对路径（软链穿透）：`/Users/huangcheng/ai-knowledge-base/.venv/bin/python`，不写 `/usr/bin/python3`（课件原文就是这么写的，会踩坑） | 无 |
| **R7** | 明文密钥泄露进公开仓 | `openclaw.json`、`.env`、截图里的 token | ① `.gitignore` 覆盖 `.env` / `~/.openclaw/` ② 仓库只放脱敏模板 ③ 截图前先 revoke/打码 ④ push 前 `git log -p \| grep -iE "sk-\|bot[0-9]{8}:"` 自查 | 一旦泄露需 BotFather `/revoke` + DeepSeek 后台换 key |
| **R8** | 知识库数据量太小（17 条），Bot 检索/Top N 效果差 | `/top` 返回不足 5 条 | 先跑 2–3 次 V3 管线补充数据（`PLANNER_TARGET_COUNT=full`），成本 ¥0.01 级；或把 Wk1-Wk3 的实验产出也归一化入库 | 影响截图观感与 15-2 验收「返回准确结果」的说服力 |

---

## 10. 最终验收清单（毕业提交前逐条走）

> 用法：全部走完再 push。任一项 `[!!]` 都不算完成，除非在 README 有明示降级说明。

### 10.1 V1 → V4 自查（16-2 步骤 6 原文）

```
Week 1 (V1) — 基础搭建:
[ ] AGENTS.md 编写完成
[ ] 3 个 Agent 角色文件编写完成
[ ] 2+ 个 Skill 封装完成
[ ] V1 手动流程跑通

Week 2 (V2) — 自动化:
[ ] model_client.py 统一模型客户端
[ ] pipeline.py 流水线
[ ] validate_json.py 格式校验
[ ] cost_tracker.py Token 消耗统计

Week 3 (V3) — 多 Agent 协作:
[ ] workflows/graph.py LangGraph 工作流
[ ] cost_guard.py 预算守卫 + 熔断器
[ ] security.py 安全防护三道防线
[ ] tests/eval_test.py 评估测试

Week 4 (V4) — 部署上线:
[ ] OpenClaw + Telegram 通过 (13 节)
[ ] Bot 接入 v4 知识库 (13-2 切 workspace)
[ ] formatter + publisher 推送测过 (14 节)
[ ] knowledge_bot.py + 至少 1 个自写 Skill (15 节)
[ ] 上线 Checklist 10 项通过 (16-1)
[ ] Dockerfile + docker-compose.yml（可选）
[ ] GitHub Actions daily-collect-v4 已配 secret 跑通
[ ] README.md 含架构图 + 快速开始
[ ] 运行截图 >= 3 张
[ ] 所有文件已提交 Git + push 到 GitHub
```

### 10.2 文件完整性（16-2 步骤 1，18 项）

```
[ ] AGENTS.md
[ ] pipeline/pipeline.py
[ ] workflows/graph.py      [ ] workflows/nodes.py
[ ] workflows/state.py      [ ] workflows/model_client.py
[ ] patterns/planner.py     [ ] patterns/router.py     [ ] patterns/supervisor.py
[ ] Dockerfile              [ ] docker-compose.yml
[ ] bot/knowledge_bot.py
[ ] distribution/formatter.py   [ ] distribution/publisher.py
[ ] daily_digest.py
[ ] openclaw/openclaw.json5 [ ] openclaw/AGENTS.md     [ ] openclaw/SOUL.md
[ ] openclaw/skills/daily-digest/SKILL.md
[ ] openclaw/skills/top-rated/SKILL.md
```

### 10.3 行为验收（不是「文件在」，是「真起作用」）

```
[ ] python3 -m workflows.graph                     端到端跑通，7 节点日志齐全
[ ] BUDGET_YUAN=0.001 python3 -m workflows.graph   中途熔断，未产出 organize
[ ] 注入样例 → sanitize_input warnings >= 1
[ ] PII 样例 → [PHONE_CN_MASKED]/[EMAIL_MASKED]/[IP_ADDRESS_MASKED]
[ ] knowledge/cost-report.json 存在且含按节点成本
[ ] pytest tests/ 全绿
[ ] python -m patterns.router      3 类意图分类正确
[ ] python -m patterns.supervisor  审核循环 <= 3 轮
[ ] python3 daily_digest.py        推送结果汇总打印
[ ] Telegram（或飞书/本地）：「知识库里有多少篇 agent 类文章」→ 准确数字
[ ] Telegram（或替代）：「推荐几篇高分的」→ top-rated Skill 触发
[ ] crontab -l | grep daily_digest 命中，且已用 1 分钟法真实触发过
[ ] gh run list --workflow daily-collect-v4.yml    24h 内有 success
```

### 10.4 交付卫生

```
[ ] git ls-files .env                → 空
[ ] git ls-files | grep -i courseware → 空（课件 PDF 不进公开仓）
[ ] git ls-files | grep -E "\.venv|__pycache__" → 空
[ ] git log -p | grep -iE "sk-[a-zA-Z0-9]{20,}|bot[0-9]{8,}:" → 空（历史里也无密钥）
[ ] openclaw/openclaw.json5 为脱敏模板（无真实 token / apiKey）
[ ] requirements.txt 全部带版本号
[ ] README 七部分齐全，且所有降级方案都写明了
[ ] screenshots/ >= 3 张，无密钥出镜
[ ] 空目录 clone → cp .env.example .env → 按 README 跑通（Telegram 部分除外）
[ ] 作业链接已提交：https://u.geekbang.org/lesson/861?article=973476
```

---

## 附录 A · 一句话记住每个里程碑的「真完成」标志

| 里程碑 | 假完成 | 真完成 |
|:--|:--|:--|
| M0 | 「目录建好了」 | `.venv/bin/python -V` 是 3.12，`git status` 干净 |
| M1 | 「三个 tests 模块写完了，单测都过」 | `grep -l "cost_guard" workflows/*.py` 非空，且 `BUDGET_YUAN=0.001` 真能把管线打断 |
| M2 | 「Bot 能聊天」 | Telegram 新会话里问知识库问题，返回的数字**和 `ls knowledge/articles` 对得上** |
| M3 | 「push 上去了」 | 陌生目录 clone 下来，照 README 三步能跑出结果 |

> 12-4 原文说得最好：**「能力 + 接入 = 保护；保护 + 整体 check + commit = 真正完工」**。本计划的每一个完成标准，都是照这句话写的。
