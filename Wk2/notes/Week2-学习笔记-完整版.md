# Week 2 学习笔记：Agent设计模式之美 — Harness工程实战

讲师：黄佳 | 主题：从手动到自动 — Hooks + MCP + CI/CD + 成本控制

---

## 第5节：Hooks 事件驱动 — 工程思想：反馈驱动循环

### 核心概念（课件讲解）

**V1 回顾与痛点：**
- V1：AGENTS.md + 3个Agent（collector/analyzer/organizer）+ 2个Skill
- V1 工作方式：OpenCode 生成代码骨架，但每步都要人驱动对话触发
- 三大痛点：
  1. 人驱动：忘了触发就断更，依赖人驱动效率低
  2. 无质量检查：JSON格式错误、必填字段缺失、摘要空洞→知识库价值归零
  3. 无反馈循环：开环系统，问题不知道也不自动修

**核心思想：反馈驱动循环**
> "Agent不是一次性脚本，它的本质是持续运行的反馈循环。Hooks就是循环中的'验证'节点。"
- Gather → Act → Verify → Repeat
- 开环：输入→处理→输出→（无人检查）
- 闭环：输入→处理→输出→Hook校验→反馈→修正→再校验

**Hook 定义：**
- Hook = 在特定时机自动执行的代码
- 类比：Git Hooks（commit前跑lint）、CI/CD Pipeline（push后跑测试）、React Hooks（组件渲染后自动执行）
- Agent场景的Hook：
  - tool.execute.before — 执行前拦截危险操作（"守门员"）
  - tool.execute.after — 执行后校验产出质量（"传令兵"）
  - Stop — 停止前最终质检（"兜底检查"）

**OpenCode Plugin Hook 体系：**
- 配置方式：TypeScript 代码（`.opencode/plugins/*.ts`），不是JSON声明式
- 包名：`@opencode-ai/plugin`
- 真实API事件：tool.execute.before、tool.execute.after、chat.message、command.execute.before、shell.env
- Plugin签名：`export const MyHook: Plugin = async ({ $ }) => { return { "tool.execute.after": async (input) => {...} } }`

**关键设计理念：**
> "不依赖 OpenCode，可在任何环境使用" — Python校验脚本既是Hook调用的对象，也可独立运行

**空洞用词黑名单：**
- 为什么要检测？AI 生成的文本天然倾向于使用模糊、积极、无信息量的表达
- 知识库要的是事实和数据，不是营销文案
- 原则：用事实替代形容词，用数字替代感叹号
- 黑名单示例：赋能、抓手、闭环、打通、全链路、底层逻辑、颗粒度、对齐、拉通、沉淀、强大的、革命性的

**核心金句：**
> "Agent 系统的可靠性不来自执行能力，而来自反馈循环。没有反馈循环的系统是开环的——错误会累积、扩散、不可控。有反馈循环的系统是闭环的——错误会被检测、修正、收敛。"
> "从'做了'到'做对了'——差的就是一个 Verify 节点。"

### 实操过程

**实操1：编写 JSON 格式校验脚本（validate_json.py）**
- 用 AI 编程工具（OpenCode/Claude Code/Cursor等）根据提示词生成
- 核心机制：`REQUIRED_FIELDS: dict[str, type]` 同时校验存在性和类型
- ID格式：`{source}-{YYYYMMDD}-{NNN}`
- Status 校验：draft/review/published/archived
- URL格式校验、摘要最少20字、标签≥1个、score范围1-10
- 支持单文件和多文件通配符输入
- 成功exit 0，失败exit 1
- 测试方法：创建正确文件(test-good.json)和错误文件(test-bad.json)，分别校验

**实操2：编写质量评分脚本（check_quality.py）**
- 5维度评分（加权总分100分）：
  1. 摘要质量 (25分)：≥50字满分，含技术关键词有奖励(+5)
  2. 技术深度 (25分)：基于score字段 1-10→0-25 映射
  3. 格式规范 (20分)：id/title/source_url/status/时间戳各4分
  4. 标签精度 (15分)：1-3个合法标签最佳，有标准标签列表校验
  5. 空洞词检测 (15分)：每出现一个空洞词扣3分
- 等级：A(≥80) / B(≥60) / C(<60)
- 退出码：存在C级返回1
- 使用 dataclass：DimensionScore 和 QualityReport
- 可视化进度条输出
- 测试：高质量条目(84.5分/A级) vs 低质量条目(39.5分/C级)

**实操3（选修）：配置 OpenCode TypeScript Hook**
- 手动模拟反馈循环四步：Agent产出→校验脚本检查→错误反馈给Agent→再校验
- Plugin 自动Hook：监听 tool.execute.after 事件，检测到 knowledge/articles/*.json 写入时自动调 validate_json.py
- 关键踩坑：
  - `.nothrow()` 而非 `.quiet()`（.quiet() 会导致 OpenCode 卡死）
  - 必须 try/catch 包裹所有 shell 调用
  - `input.args?.file_path ?? input.args?.filePath` 两种写法兼容不同版本

---

## 第6节：MCP 外部数据连接 — 工程思想：标准化接口

### 核心概念（课件讲解）

**MCP = AI世界的USB接口**
- Model Context Protocol — 让AI工具连接外部世界的标准协议
- 没有MCP之前：M×N（每个Agent都要自己适配每个服务）→ 2个Agent×3个服务=5个自定义适配器
- 有了MCP：M+N（标准协议统一）→ M个Agent+N个Server=M+N个对接

**MCP 架构：**
- Client ↔ Server 模型
- OpenCode (MCP Client) → 选择工具 → 调用 MCP Server
- 协议：JSON-RPC 2.0
- 核心能力：Tools（工具调用）/ Resources（数据读取）/ Prompts（提示模板）

**三种传输方式：**
| 方式 | 协议 | 场景 |
|------|------|------|
| stdio | 标准输入输出 | 本地进程通信（最常用） |
| SSE | Server-Sent Events | 远程服务/实时推送 |
| HTTP | 标准HTTP请求 | 简单远程调用/REST API封装 |

**关键洞察：MCP vs Python Pipeline**
> "LLM 的理解能力正在消解结构化协议的必要性。Claude 能读 stderr、能解析非结构化输出 = JSON Schema 约束的边际价值下降。"

| MCP方案 | Python Pipeline方案 |
|---------|---------------------|
| AI动态决策用哪个工具 | 代码直接调API |
| 适合交互式探索 | 适合确定性流水线 |
| 每次调用都消耗Token | 零Token成本 |
| 采集30条=30次AI决策 | 采集30条=1次API调用 |

**核心设计原则：免费采集 + 付费分析 = 成本最优**
- Step 1-2：纯API采集 → 零成本（Python urllib/httpx）
- Step 3：AI深度分析 → 有成本（DeepSeek ~0.02元/30条）
- Step 4：整理入库 → 零成本（Python字符串处理）
- 每日运行成本：采集60条免费 + AI分析60条≈0.04元(DeepSeek)
- 一个月≈1.2-6元

**Pipeline 四步流水线架构：**
```
pipeline.py (流水线编排器)
  Step 1: GitHub API采集 → 纯API零成本 → raw/github.json
  Step 2: RSS订阅采集   → 纯API零成本 → raw/rss.json
  Step 3: AI深度分析    → 调用LLM有成本 → analyzed/*.json
  Step 4: 整理入库      → 去重+格式化零成本 → articles/*.json
```

**核心金句：**
> "原则：能用代码解决的就不用AI。"
> "MCP的核心价值：把你的数据变成AI可调用的工具，用对话代替命令行。"

### 实操过程

**实操1：编写统一模型客户端（model_client.py）**
- 设计模式：工厂模式+策略模式
- LLMProvider 抽象基类 → OpenAICompatibleProvider 实现
- 支持DeepSeek/Qwen/OpenAI，通过环境变量 LLM_PROVIDER 切换
- 核心数据结构：Usage dataclass + LLMResponse dataclass
- 价格表 PRICING：按模型名索引（如 deepseek-chat vs deepseek-reasoner 不同价）
- chat_with_retry()：3次指数退避重试（1s→2s→4s）
- quick_chat()：便捷函数，自动创建/关闭provider
- 不依赖openai SDK，直接用httpx调OpenAI兼容API
- 依赖：httpx + python-dotenv

**实操2：编写 Pipeline 流水线（pipeline.py）**
- CLI参数：--sources github,rss、--limit 20、--dry-run、--verbose、--step
- collect_github()：GitHub Search API（topic:ai+agent+llm），用httpx.Client
- collect_rss()：从rss_sources.yaml读取配置，正则解析RSS XML
- step_analyze()：格式化prompt→调LLM→解析JSON→合并原始数据和分析结果
- step_organize()：按source_url去重（先读已有文章URL）+格式标准化
- step_save()：独立JSON文件到knowledge/articles/，支持dry-run
- run_pipeline()主流程：支持指定步骤执行（--step 1 --step 2）
- 关键设计：去重按source_url而非title（URL更唯一）

**实操3：RSS 数据源配置（rss_sources.yaml）**
- 9个数据源，4个分类：
  - 综合技术：Hacker News Best、Lobsters AI/ML
  - AI研究：arXiv cs.AI、arXiv cs.CL(默认disabled)
  - 公司博客：OpenAI、Anthropic、HuggingFace、LangChain
  - 中文社区：机器之心、量子位(默认disabled)
- enabled字段控制是否采集
- 量太大的源默认disabled（如arXiv cs.CL）

**实操4：MCP 知识库 Server 实战**
- 用Python标准库（零依赖）写MCP Server：mcp_knowledge_server.py
- 3个工具：search_articles(keyword)、get_article(article_id)、knowledge_stats()
- 协议：JSON-RPC 2.0 over stdio（通过stdin/stdout通信）
- 三步流程：initialize → tools/list → tools/call
- 配置到OpenCode：opencode.json中声明MCP Server路径
- 手动测试：echo JSON-RPC请求→pipe到Python脚本
- 效果：自然语言"搜索关于RAG的文章"→MCP自动调tool→返回结果

---

## 第7节：CI/CD 定时触发 — 工程思想：手动到自动

### 核心概念（课件讲解）

**本节目标：** 把pipeline.py从"手动跑"变成"每天自动跑"

**CI/CD 基本概念：**
- CI（持续集成）：代码一提交，自动构建、自动测试
- CD（持续交付）：测试通过后，自动部署
- 对知识库项目：CI=每天自动采集+自动校验格式，CD=自动提交到仓库+自动更新知识库
- GitHub Actions = 免费的云端自动化平台（公开仓库完全免费）

**GitHub Actions 核心概念：**
- Workflow：`.github/workflows/*.yml`
- 触发器：schedule（cron定时）、workflow_dispatch（手动按钮）、push、pull_request
- Job：runs-on ubuntu-latest → 多个Step顺序执行

**免费采集策略（核心智慧）：**
- Steps 1-2：自动采集（免费）→ schedule 定时触发 → 数据自动积累
- Steps 3-4：AI分析（按需）→ workflow_dispatch 手动触发 → 控制成本
- 每天自动跑零token成本，AI分析手动触发或每周一次

**GitHub Secrets 安全管理：**
- API Key不能写在代码里
- Settings → Secrets and variables → Actions
- Secret一旦保存无法再查看原始值
- Fork仓库不会继承Secrets

**本地备选方案：**
- Linux/Mac：crontab（`0 8 * * * cd ~/ai-knowledge-base && python pipeline.py --step 1 --step 2`）
- Windows：Task Scheduler

**Headless 模式：**
- `opencode run "指令"` — 不启动交互终端，直接执行并返回结果
- 适用场景：需要AI决策的自动化任务、需要Skill的复杂操作

**V1→V2→V3→V4 自动化演进：**
- V1：编码自动化（人驱动）
- V2：编码自动化 + CI/CD定时（cron→采集+分析+整理→JSON落盘）
- V3：+ Agent审核（cron→采集+分析+整理→多Agent审核→合格才落盘）
- V4：+ Bot服务（cron→采集+分析+整理→审核→落盘→推送Bot/Telegram/飞书）

**核心金句：**
> "自动化 = 把人的工作交给机器。从'依赖人的纪律'到'依赖系统的规则'。用确定性替代不确定性——这就是工程化的核心价值。"

### 实操过程

**实操1：配置 GitHub Actions 定时采集**
- 创建 `.github/workflows/daily-collect.yml`
- cron: `"0 8 * * *"`（UTC 08:00 = 北京时间16:00）
- 同时支持 workflow_dispatch 手动触发
- permissions: contents: write（授权workflow推送代码）
- 5个Step：checkout→Setup Python 3.11→pip install→Run pipeline→Validate→Commit+Push
- Validate步骤：先ls检查是否有JSON文件再跑校验
- Commit消息包含文章数量：`git diff --staged --name-only | grep -c '\.json$'`
- 无新数据不commit（`git diff --staged --quiet`）

**实操2：本地 crontab 定时任务**
- 两条cron配置：
  1. 每天08:00自动采集（free）：`python pipeline.py --step 1 --step 2`
  2. 每周日10:00自动分析（需要API Key）：`python pipeline.py --step 3 --step 4`
- 日志追加到logs/collect.log和logs/analyze.log
- 手动先跑一次确认路径和权限

---

## 第8节：成本控制实战 — 工程思想：Token 经济学

### 核心概念（课件讲解）

**核心思想：Token 经济学**
> "每个 token 都有成本，成本从第一天就塑造架构。不是'先做完再优化'，而是'成本意识融入设计'。"

**三个核心概念：**
1. **Token Debt（Token债务）**：因架构设计不当而产生的持续性token浪费
2. **Token Leverage（Token杠杆）**：用少量token撬动大量高质量输出
3. **Token Refactoring Dividend（Token重构红利）**：重构prompt/架构后获得的长期token节省

**Token 基础知识：**
- 中文字≈1.5-2 tokens，英文单词≈1-1.5 tokens
- 输出token通常比输入token贵2-4倍
- API按token计费，不按次数

**国产模型价格矩阵（2026年3月）：**
| 模型 | 输入价格 | 输出价格 | 定位 |
|------|---------|---------|------|
| GLM-4-Flash | 免费 | 免费 | 入门级 |
| DeepSeek-V3 | ¥1/M | ¥2/M | 性价比之王 |
| Qwen-Plus | ¥4/M | ¥12/M | 中高档 |
| Kimi | ¥12/M | ¥12/M | 长上下文 |
| DeepSeek-R1 | ¥4/M | ¥16/M | 推理增强 |
| GPT-4o | ¥45/M | ¥135/M | 国际顶级 |

**成本速算：**
- 用 DeepSeek-V3 分析一篇文章：输入2500tokens + 输出500tokens ≈ ¥0.0035
- 分析1000篇文章才花3-5块钱
- 成本直觉：单次调用极便宜→关键是控制调用次数和token量

**三档模型路由策略：**
| 档位 | 任务 | 模型 | 成本 |
|------|------|------|------|
| 第1档·零成本 | 搜索/采集 | 纯API调用 | ¥0/次 |
| 第2档·低成本 | 分析/总结 | DeepSeek-V3/GLM-4-Flash | ¥0.003/次 |
| 第3档·按需 | 决策/审核 | Qwen-Plus/DeepSeek-R1 | ¥0.02-0.05/次 |

**月度成本估算：**
- 每天1次完整流水线：¥0.008×30=¥0.24/月
- 手动调试测试：¥2-3/月
- 综合：¥3-10/月
- 对比：ChatGPT Plus ¥140/月，我们的系统成本低15-30倍

**对比实验：全高档 vs 混合路由**
- 方案A（全用Qwen-Plus）：月成本≈¥7.20
- 方案B（混合路由）：月成本≈¥0.24
- 实际质量差异：<5%

**Prompt 优化4个技巧：**
1. 精简system prompt（2000→500 tokens，每次省1500）
2. 约束输出格式（要求JSON→输出token减少60-80%）
3. 批量处理vs逐条处理（10条一次发→省9次system prompt开销）
4. 分层提问（免费模型粗筛→付费模型深分析）

**缓存策略：**
- 增量采集vs全量采集
- 文件指纹（hash）判断变化
- 结果缓存24小时有效期
- 经验数据：缓存可减少40-70% token消耗

**两条工程思想总结卡：**
1. 反馈驱动循环（第5节）：系统行为应由事件驱动，不是人工干预驱动
2. Token经济学（第8节）：每个token都有成本，成本从第一天就塑造架构

### 实操过程

**实操1：加入 Token 消耗统计（CostTracker）**
- 在 model_client.py 中添加 CostTracker 类
- record(usage, provider)：记录每次调用
- estimated_cost(provider)：国产模型价格表（元/百万tokens）
  - deepseek: 输入1, 输出2
  - qwen: 输入4, 输出12
  - openai(gpt-4o-mini): 输入150, 输出600
- report(provider)：打印成本报告（调用次数/输入tokens/输出tokens/总成本）
- 全局tracker实例，chat()函数自动record
- Pipeline末尾调tracker.report()

**实操2：模型路由策略**
- 不同Pipeline步骤用不同provider：
  - 采集Steps 1-2：无LLM调用（纯API）
  - 分析Step 3：DeepSeek Chat（最便宜）
  - 重要决策：DeepSeek R1 / Qwen（更贵但更强）
- CLI支持 `--provider deepseek` / `--provider qwen` 切换
- 每次运行后对比成本差异

**实操3：提交 V2 完整项目**
- 完整目录结构：
  ```
  ai-knowledge-base/
  ├── AGENTS.md
  ├── .env / .env.example
  ├── .opencode/ (agents/skills/plugins)
  ├── pipeline/ (model_client.py + pipeline.py + rss_sources.yaml)
  ├── hooks/ (validate_json.py + check_quality.py)
  ├── .github/workflows/ (daily-collect.yml)
  ├── knowledge/ (raw/ + articles/)
  └── logs/
  ```
- V2 特性总结：
  - 自动化流水线：4步Python脚本
  - 多数据源：GitHub + HN + RSS
  - 质量校验：格式校验 + 5维度评分 + 空洞用词检测
  - 成本控制：Token统计 + 模型路由 + 预算守卫
  - CI/CD：每日免费采集
  - 月成本：5-10元
  - 角色分离：OpenCode写代码，Pipeline独立运行

---

## Week 2 总结：四大工程思想

| 节 | 主题 | 工程思想 | 核心产出 |
|----|------|----------|----------|
| 第5节 | Hooks事件驱动 | 反馈驱动循环 | validate_json.py + check_quality.py |
| 第6节 | MCP外部连接 | 标准化接口 | model_client.py + pipeline.py |
| 第7节 | CI/CD定时触发 | 手动到自动 | daily-collect.yml + crontab |
| 第8节 | 成本控制实战 | Token经济学 | CostTracker + 模型路由 |

**从V1到V2的跨越：**
- V1：编码自动化（人驱动对话→OpenCode生成代码）
- V2：采集自动化（代码自己跑+自动校验+CI/CD定时+成本可控）
- 从"依赖人的纪律"到"依赖系统的规则"
