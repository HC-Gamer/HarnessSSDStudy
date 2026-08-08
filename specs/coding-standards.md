# AI 知识库 · 编码规范 v1.0

> 适用范围：HarnessSSDStudy 仓库内全部代码与数据，包括 `Wk*/experiments/`、
> `Wk*/hooks/`、`scripts/`、`.github/workflows/`。
> 上游文档：[`AGENTS.md`](../AGENTS.md)（项目定义）、[`project-vision.md`](project-vision.md)、[`agents-prd.md`](agents-prd.md)。
> 更新日期：2026-08-08（v0.1 的 16 行骨架重写为可执行规范）

本文件是**规范**，不是建议。人类和 Agent 提交代码前都以此为准。
每条规则尽量给出「怎么做」和「怎么验证」；无法自动验证的标注为「人工 review」。

---

## 0. 总原则

1. **一致性 > 个人偏好**。新代码读起来要像旁边的老代码。改动前先看同目录已有文件的写法。
2. **可复现 > 聪明**。实验代码必须能被别人用同一条命令跑出同一类结果；随机性要么固定种子，要么在报告里声明方差未量化。
3. **不重复实现已有能力**。LLM 调用走 `Wk2/experiments/v2-pipeline/pipeline/model_client.py`，
   RSS 采集走 `Wk3/experiments/langgraph-pipeline/rss_collector.py`，
   质量评分走 `Wk3/experiments/langgraph-pipeline/quality.py`。要新写一份先说明为什么不能复用。
4. **诚实优先于好看**。跑失败就写失败，降级了就在产出里标降级，指标可疑就写可疑。
   反面教材见 `Wk3/.../EXPERIMENT_REPORT.md`：一个坏掉的评分函数让首轮报告出现「质量分 100/100」，
   看起来漂亮，实际是指标失效。

---

## 1. Python 编码规范

### 1.1 版本与环境

| 项 | 规定 |
|----|------|
| 最低版本 | Python **3.11**；实际开发与 CI 用 **3.13** |
| 解释器 | 本机用 `/opt/homebrew/bin/python3`，**不要用系统 Python** |
| 虚拟环境 | 每周一个：`Wk3/.venv/`、`Wk4/.venv/`。`.venv/` 已在 `.gitignore` |
| 依赖声明 | 每个实验目录一份 `requirements.txt`，钉住直接依赖，不钉传递依赖 |
| 第三方 SDK | **禁止**引入厂商 AI SDK（openai / anthropic / dashscope 等）。统一走 OpenAI 兼容 HTTP 接口 + `httpx` |

### 1.2 格式化与静态检查

```bash
black --line-length 100 .
ruff check --fix .
```

| 工具 | 配置 | 说明 |
|------|------|------|
| `black` | `--line-length 100` | 唯一的格式化权威，不手工调格式，不与 black 争论 |
| `ruff` | 默认规则集 + `E,F,W,I,B,UP,ANN` | `I` 管 import 排序，`UP` 管现代语法，`ANN` 管类型标注缺失 |
| 行宽 | **100** | 现有代码（`model_client.py` 等）就是这个宽度 |
| 缩进 | 4 空格，禁止 Tab | |
| 引号 | 双引号（black 默认） | |

尚未落地的部分：仓库根目录**还没有** `pyproject.toml`，上面两条命令目前靠手工传参。
**待办**：新增 `pyproject.toml` 集中配置 black / ruff，并接入 CI（见 §5.3）。

### 1.3 类型标注

- 每个模块顶部写 `from __future__ import annotations`（现有代码全部如此）
- **所有**函数的参数和返回值都要标注类型；`ANN` 规则会检查
- 用 PEP 604 写联合类型：`str | None`，不用 `Optional[str]`
- 用内置泛型：`list[str]`、`dict[str, Any]`，不用 `typing.List`
- 字面量枚举用 `Literal`，LangGraph 路由函数必须标注返回的节点名：

```python
def decide_route(state: PipelineState) -> Literal["rewrite", "organize"]:
    ...
```

- 结构化 state 用 `TypedDict`；需要累加的字段用 `Annotated[list[str], operator.add]`
- 数据载体用 `@dataclass`；不可变配置用 `@dataclass(frozen=True)`

### 1.4 Docstring

统一 **Google 风格**（`Args:` / `Returns:` / `Raises:`），中文正文。

**模块 docstring**：一行摘要 + 空行 + 说明；有 CLI 的模块必须给 `用法::` 示例。

```python
#!/usr/bin/env python3
"""质量评分函数 —— Wk3 实验 Bug #1 的修复。

新公式::

    score = 40 + avg_len // 5 - bad_hits * 10 + good_hits * 5 - shortfall * 5

本模块不依赖 LangGraph 也不依赖 LLM，可以独立单测。
"""
```

**函数 docstring**：公开函数**必须**有；私有函数（`_` 前缀）至少一行摘要。

```python
def score_quality(summary: str, key_points: list[str]) -> QualityBreakdown:
    """按新公式给一份分析产出打分。

    Args:
        summary: 摘要文本。
        key_points: 关键要点列表。

    Returns:
        含全部分项的 QualityBreakdown。

    Raises:
        ValueError: 当 ... 时。

    Examples:
        >>> score_quality("通过赋能业务实现闭环打通", ["对齐颗粒度"]).score
        0
    """
```

- `dataclass` 在类 docstring 的 `Attributes:` 里逐字段说明
- 模块级常量用 Sphinx 的 `#:` 注释：

```python
#: 空洞用语黑名单 —— 命中即扣分。
BAD_KEYWORDS: tuple[str, ...] = ("赋能", "抓手", "闭环", ...)
```

- `Examples:` 里的 doctest 必须真的能过：`python -m doctest <module>.py`

### 1.5 命名

| 对象 | 约定 | 例 |
|------|------|-----|
| 模块 / 包 | `snake_case` | `model_client.py`、`rss_collector.py` |
| 函数 / 变量 | `snake_case` | `score_quality`、`raw_content` |
| 类 | `PascalCase` | `CostTracker`、`QualityBreakdown` |
| 常量 | `UPPER_SNAKE` | `QUALITY_THRESHOLD`、`DEFAULT_TIMEOUT` |
| 私有 | 单下划线前缀 | `_clean`、`_ProviderStat` |
| LangGraph 节点函数 | `<动词>_node` | `search_node`、`quality_check_node` |
| 布尔 | `is_` / `has_` / `should_` 前缀 | `should_rewrite`、`circuit_broken` |

**禁止魔法字符串和魔法数字**。阈值、价格、超时、黑名单一律提为模块级命名常量。

```python
# ❌
if score < 60: ...
should_rewrite = quality < 60 and rewrites < 3

# ✅
QUALITY_THRESHOLD = 60
MAX_REWRITES = 3
if score < QUALITY_THRESHOLD: ...
```

### 1.6 模块结构

按固定顺序，段落之间用分隔注释（现有代码用两种，都可以，一个文件内保持一致）：

```python
# ═══════════════════════════════════════════════════════════════════
# 1. 状态定义
# ═══════════════════════════════════════════════════════════════════

# ---------------------------------------------------------------------------
# 提供商配置
# ---------------------------------------------------------------------------
```

顺序：shebang → 模块 docstring → `from __future__` → 标准库 → 第三方 → 本地 →
常量 → 数据结构 → 核心逻辑 → CLI / 自测 → `if __name__ == "__main__":`

入口一律写成：

```python
if __name__ == "__main__":
    raise SystemExit(main())
```

### 1.7 错误处理

- **不裸 `except:`**，也不用光秃秃的 `except Exception`——除了「采集层降级」这类边界，
  且必须写 `# noqa: BLE001` 并注明理由：

```python
except Exception as exc:  # noqa: BLE001 - 采集层任何异常都应降级而非中断实验
```

- 自定义异常继承合适的内置类型：`class LLMError(RuntimeError)`
- 用 `raise ... from exc` 保留因果链
- 外部调用（HTTP / LLM / 文件）必须有超时与重试策略：
  - HTTP 默认超时 **60s**（`DEFAULT_TIMEOUT`）
  - 重试指数退避，默认 **3** 次（`DEFAULT_MAX_RETRIES` / `DEFAULT_BACKOFF_BASE = 2.0`）
  - 重试用尽后**降级**而不是整体崩掉；降级要在产出和日志里留痕（见 §6.3）
- 解析外部 JSON 一律容错：模型回复可能带 ```` ```json ```` 围栏和前后废话，
  用 `parse_json_reply()` 这类函数处理，失败返回空 dict 而不是抛异常

### 1.8 禁止事项

- ❌ 提交 `TODO` / `FIXME` / `XXX` 到 `main`。要留就开 issue 或写进报告的「下一步」
- ❌ 提交被注释掉的死代码
- ❌ `print()` 用于日志（`print` 只用于 CLI 面向用户的输出，见 §6.2）
- ❌ 可变默认参数（`def f(x: list = [])`）
- ❌ 通配 import（`from x import *`）
- ❌ 硬编码绝对路径。用 `Path(__file__).parent` 系列推导

---

## 2. JSON / 数据格式规范

### 2.1 知识条目 schema

`knowledge/articles/*.json` 的字段契约（现行实现见 `pipeline/pipeline.py`）：

```json
{
  "id": "hackernews-20260728-001",
  "title": "Ask HN: ...",
  "source_url": "https://news.ycombinator.com/item?id=49084404",
  "summary": "用户报告在访问 ... 的攻击手法。",
  "tags": ["security"],
  "status": "review",
  "score": 6,
  "collected_at": "2026-07-28T15:14:51.478897+00:00",
  "source": "hackernews",
  "audience": "intermediate",
  "analyzed_by": "deepseek/deepseek-chat",
  "extra": { "description": "..." }
}
```

### 2.2 字段规则

| 字段 | 类型 | 规则 |
|------|------|------|
| `id` | string | **必填**，格式 `<source>-<YYYYMMDD>-<NNN>`，`NNN` 为当日三位序号（从 `001` 起） |
| `title` | string | 必填，非空 |
| `source_url` | string | 必填，`http://` 或 `https://` 开头 |
| `summary` | string | 必填，**≥ 20 字**（`check_quality.py` 的基本分线，≥ 50 字满分） |
| `tags` | string[] | 必填，**1-3 个**为最佳；超过 3 个扣分。取值见 §2.4 |
| `status` | enum | 必填，见 §2.3 |
| `score` | int | 必填，**1-10**（注意：与质量分 0-100 不是同一把尺子） |
| `collected_at` | string | 必填，**ISO 8601 带时区**，UTC 优先 |
| `source` | string | 必填，与 `rss_sources.yaml` 的 `name` 一致 |
| `audience` | enum | `beginner` / `intermediate` / `advanced` |
| `analyzed_by` | string | `<provider>/<model>`，如 `deepseek/deepseek-chat` |
| `extra` | object | 可选，非契约字段都放这里，不污染顶层 |

- 字段名一律 **snake_case**
- 时间字段一律以 `_at` 结尾
- **不要**新增顶层字段。要扩展就放 `extra`；确实要进契约的，先改本文件再改代码
- 文件写盘用 `ensure_ascii=False, indent=2`，中文可读

### 2.3 状态枚举

| 值 | 含义 | 谁能写 |
|----|------|--------|
| `draft` | 刚采集，未分析 | collector |
| `review` | 已分析，待人工核验（**默认落库状态**） | analyzer |
| `published` | 核验通过 | 人工 / organizer |
| `failed` | 采集或分析失败，进 dead-letter | 任意步骤 |

状态只能单向前进：`draft → review → published`；任何步骤可转 `failed`。

### 2.4 标签词表

`agent` / `llm` / `rag` / `tool-use` / `memory` / `reasoning` / `deployment` /
`security` / `eval` / `orchestration`

- 全小写，连字符分词（`tool-use` 不是 `tool_use`）
- 要加新标签先在本文件登记，避免同义词分裂

### 2.5 校验

```bash
python Wk2/experiments/v2-pipeline/hooks/validate_json.py knowledge/articles/*.json
python Wk2/experiments/v2-pipeline/hooks/check_quality.py knowledge/articles/*.json
```

`check_quality.py` 输出 A(≥80) / B(≥60) / C(<60)；**存在 C 级条目时 exit 1**。
这两个脚本是 Hook，也应在 CI 里跑（见 §5.3）。

### 2.6 YAML 配置

- 数据源配置只有一份：`Wk2/experiments/v2-pipeline/pipeline/rss_sources.yaml`。
  其他周复用它，**不允许**再维护第二份源列表
- 每个字段上方写注释说明用途
- 用 `yaml.safe_load()`，**禁止** `yaml.load()`

---

## 3. Shell 脚本规范

```bash
#!/bin/bash
# ── 脚本用途一行说明 ──
# crontab: 0 22 * * *          # 有定时用途就写清楚

set -euo pipefail
```

| 规则 | 说明 |
|------|------|
| Shebang | `#!/bin/bash`（本仓库依赖 bash 特性，不写 `#!/bin/sh`） |
| 严格模式 | **`set -euo pipefail`**。现有 `scripts/extract_course_tasks.sh` 只有 `set -e`，属待修 |
| 变量引用 | 一律加引号：`"$VAR"`、`"${ARR[@]}"` |
| 变量命名 | 脚本级常量 `UPPER_SNAKE`，局部变量用 `local` |
| 路径 | 顶部集中定义 `PROJECT_DIR` 等，不散落在各处 |
| 静态检查 | `shellcheck <script>.sh` 无 error |
| 日志 | 写 `/tmp/<name>_$(date +%Y%m%d_%H%M).log`，配合 `exec > >(tee -a "$LOG") 2>&1` |
| 可执行位 | `chmod +x`，并 `git update-index --chmod=+x` |
| 幂等 | 重复执行不产生副作用；`mkdir -p` 而不是 `mkdir` |
| 危险操作 | `rm -rf` 必须作用于脚本内构造的变量路径，且先校验非空：`[[ -n "$DIR" ]] \|\| exit 1` |

超过 ~300 行、或需要结构化数据处理的脚本，**改用 Python 重写**。

---

## 4. Git 提交规范

### 4.1 Conventional Commits

```
<type>(<scope>): <subject>

<body>

<footer>
```

| type | 用于 |
|------|------|
| `feat` | 新功能、新实验、新脚本 |
| `fix` | 修 bug |
| `docs` | 文档、报告、博客、README |
| `refactor` | 重构，行为不变 |
| `test` | 测试 |
| `chore` | 依赖、配置、目录骨架 |
| `ci` | GitHub Actions |
| `perf` | 性能或成本优化 |

scope 用周或模块：`wk1` / `wk2` / `wk3` / `wk4` / `specs` / `pipeline` / `hooks` / `blogs` / `opencode`

```
fix(wk3): 修正质量分公式与 rewrite 回边语义

- 评分抽到 quality.py，基线 40 分，实测首评分跨度 0-100（旧 62-100）
- 回边改为 rewrite → quality_check，重写产出不再被 analyze 覆盖
- 新增真实 RSS 采集、SQLite checkpointer、2×2 同题对照

Refs: Wk3/experiments/langgraph-pipeline/EXPERIMENT_REPORT.md
```

规则：
- subject **≤ 50 字**（中文按字计），祈使语气，句尾不加句号
- body 每行 ≤ 72 字符，说**为什么**改，不复述 diff
- 破坏性变更在 footer 写 `BREAKING CHANGE:`
- **一次提交只做一件事**。修 bug 顺手格式化 → 拆两个提交

> 历史说明：`main` 上 2026-08-08 之前的提交（如 `Wk3 心得：收紧各节篇幅`）不符合本规范，
> **不追溯改写**。本规范对之后的提交生效。

### 4.2 分支与推送

- 直接在 `main` 上做学习记录类改动是允许的（单人仓库）
- 涉及多文件重构或可能失败的实验，先开 `wk4/<topic>` 分支
- 推送前确认身份：`git config user.email`
- **禁止** `git push --force` 到 `main`（`HarnessSSDStudyRules.md` 里的 force push 条款
  与本规范冲突，以本规范为准：历史是学习过程的一部分，不覆盖）

### 4.3 不入库的内容

`.gitignore` 已覆盖：`.env`、`secrets.env`、`*.log`、`.venv/`、`__pycache__/`、
`*.pyc`、`node_modules/`、`.DS_Store`、`.obsidian/`

补充规则：
- 实验产出（`results/*.md`、`results/*.json`）**入库**——它们是实验证据
- 运行日志**通常不入库**（`*.log` 已忽略）；作为报告证据需要保留时单独 `git add -f`，并在报告里引用
- checkpoint 数据库（`*.sqlite`）体积小于 1 MB 可入库作为证据，更大的不要

---

## 5. 测试规范

### 5.1 分层

| 层 | 位置 | 要求 |
|----|------|------|
| 自测函数 | 模块内 `_self_test()` | **最低要求**。每个可独立运行的模块都要有，`python <module>.py` 直接跑 |
| doctest | docstring 的 `Examples:` | 关键纯函数必须有，`python -m doctest <module>.py` 通过 |
| 单元测试 | `tests/test_<module>.py` | 纯函数（评分、解析、格式化）必须覆盖 |
| 集成测试 | `tests/test_<flow>_integration.py` | 打 `@pytest.mark.integration`，默认跳过（会花钱） |

### 5.2 命名与组织

- 测试文件 `test_<被测模块>.py`，测试函数 `test_<行为>_<条件>_<预期>`
- 一个断言一个意图；用 `pytest.mark.parametrize` 覆盖多组输入
- **禁止**在单元测试里真调 LLM 或访问网络。用固定样本或 mock
- 评分类函数必须配**已知好 / 已知坏**样本集，先证明有区分度再用于真实产出
  （范例：`quality.py::SCORING_SAMPLES`，`python quality.py` 直接看新旧公式分布对比）

### 5.3 覆盖率与 CI

| 目标 | 值 |
|------|-----|
| `pipeline/`、`hooks/`、纯函数模块 | 行覆盖 **≥ 80%** |
| 实验脚本（含 LLM 调用的编排代码） | 无硬性覆盖率要求，但**必须有断言**（见 §5.4） |

```bash
pytest -q --cov=pipeline --cov=hooks --cov-report=term-missing --cov-fail-under=80
```

现状与待办：仓库**还没有** `tests/` 目录，也没有 lint/test 的 CI job。
现有两个 workflow（`daily-collect.yml`、`daily-publish.yml`）只跑数据管线。
**待办**：新增 `ci.yml` 跑 `ruff` + `black --check` + `pytest` + `validate_json.py` + `check_quality.py`。
在此之前，本节的覆盖率目标属于**目标而非现状**，不要在报告里声称已达成。

### 5.4 实验代码的断言要求

实验不写传统单测，但**每个声称验证了某能力的实验必须输出可检查的断言**，
并把断言结果写进结果 JSON。范例（`langgraph_experiment.py`）：

```python
result["assertions"] = {
    "paused_before_organize": next_nodes == ["organize"],
    "update_state_took_effect": after_update.values.get("topic") == marker,
    "resumed_reached_organize": "organize" in resumed.get("path", []),
}
```

规则：
- 断言名说清**验证了什么**，不是 `check1` / `ok`
- 报告里的每条「✅ 已验证」都要能追溯到一条断言或一段实测数字
- **没跑过的结论不许写进报告**

---

## 6. 日志规范

### 6.1 初始化

```python
import logging

logger = logging.getLogger(__name__)          # 库模块：只取 logger，不配置
```

```python
logging.basicConfig(                           # 只在入口脚本 / __main__ 里配
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)   # 压掉第三方噪声
```

**库模块不得调用 `basicConfig()`**，那是应用层的职责。

### 6.2 级别

| 级别 | 用于 | 例 |
|------|------|-----|
| `DEBUG` | 排障细节，正常运行不看 | 请求 URL、payload 大小 |
| `INFO` | 关键节点的进展与结果 | 节点进入/退出、评分、路由决策、成本 |
| `WARNING` | 降级、重试、跳过、熔断 | `真实采集 0 条，降级为 LLM 模拟` |
| `ERROR` | 失败且无法继续当前动作 | `LLM 连续失败，降级为规则处理` |
| `CRITICAL` | 几乎不用 | |

`print()` 只用于 CLI 面向用户的汇总输出（表格、报告）；一切过程信息走 logger。

### 6.3 内容规则

- **用 lazy `%` 格式化，不要在 logger 调用里拼 f-string**：

```python
logger.info("采集成功 %d 条 ← %s", len(entries), url)     # ✅
logger.info(f"采集成功 {len(entries)} 条 ← {url}")        # ❌ 无条件求值
```

- 消息带上**可定位的上下文**：节点名 / 源名 / thread_id / 实验标签

```python
logger.info("[quality_check_node] 评分 %d/100 (门槛 %d) | 已重写 %d/%d", ...)
```

- **决策必须留痕**。凡是分支、降级、熔断、重试，都要有一行日志说明「做了什么、为什么」：

```python
logger.warning("⚡ 熔断：重写已达上限 %d 次，分数仍 %d，强制放行", cap, score)
```

- 关键指标要能被 grep：评分展开、token、成本各占一行固定格式
- **禁止**记录 API key、完整 prompt 正文、用户数据（见 §7.2）
- 长日志写文件（`results/run_all.log`），不要只留在终端

---

## 7. 安全规范

### 7.1 密钥存储

| 规则 | 说明 |
|------|------|
| 唯一来源 | `.env` 文件 + 环境变量。`.env` 已在 `.gitignore` |
| 读取方式 | `os.getenv(config.api_key_env, "").strip()`，缺失时抛明确异常并提示配哪个变量 |
| 变量命名 | `<PROVIDER>_API_KEY`：`DEEPSEEK_API_KEY` / `DASHSCOPE_API_KEY` / `OPENAI_API_KEY` |
| **禁止** | 硬编码密钥、写进 docstring/注释/README、放进 JSON 产出、放进 commit message |
| CI | 用 GitHub Actions Secrets（`${{ secrets.DEEPSEEK_API_KEY }}`），不用明文 env |
| 提交前自查 | `git diff --cached \| grep -iE 'sk-[a-zA-Z0-9]{16,}\|api_key\s*=\s*["\x27]'` |
| 泄露处置 | 立刻在提供商控制台吊销并换新，然后才考虑清历史。**先吊销，别先删 commit** |
| 仓库内示例 | 只写 `DEEPSEEK_API_KEY=sk-xxxxxxxx`，不放真 key，且放在 `.env.example`（入库）而非 `.env` |

### 7.2 敏感信息处理

- 日志与产出里的密钥必须脱敏，只保留前缀：`sk-550***REDACTED`
- 不记录完整 prompt / completion 正文（可能含抓来的第三方内容），只记长度与 token 数
- 抓取的第三方内容：只存标题、URL、摘要片段（`_clean(text, limit=600)` 截断），
  **不落全文**（`AGENTS.md` §5「不存储原始网页全文」）
- 报告里引用外部内容要给原始 URL，可溯源
- 产出中的模型生成内容，如果不是真实采集来的，必须标注（`collection_mode` 字段就是为此存在）

### 7.3 外部输入

- 一切 HTTP 响应视为不可信：校验 `status_code`、`try/except` 包 JSON 解析、
  用 `xml.etree` 解析前 `try` 住 `ParseError`
- 抓取带 `User-Agent`，标明来源仓库，尊重对方站点
- **禁止** `eval()` / `exec()` / `pickle.loads()` 处理外部数据
- 文件路径来自外部输入时，校验解析后仍在预期目录内（防路径穿越）
- `subprocess` 调用传 list 而非字符串，**不用** `shell=True`，并给 `timeout`

### 7.4 成本安全

成本是本项目的真实风险之一，按安全项管理：

- 任何带循环的编排必须有**次数上限**（`MAX_REWRITES = 3`）和熔断标记（`circuit_broken`）
- LLM 调用统一走 `model_client`，由全局 `CostTracker` 计量；
  单次实验成本用 `TokenMeter` 快照差值，**不要拿进程累计值当单次成本**
- 每份实验报告必须有成本段：调用次数、token、CNY/USD、单次均价、计价来源
- CI 里默认跑零成本路径（`--no-analyze`），要花钱的路径必须显式开关

---

## 8. 文档与报告规范

- 实验报告固定结构：**实验目标 → 环境 → 设计 → 实测数据 → 结论 → 已知问题 → 下一步**
- 「已知问题」和「下一步」必须带**状态列**，后续轮次回来更新，不删旧结论
- 历史结论**不覆盖**。修复后的新结论追加为「修复记录」段，并在文首加阅读提示
  （范例：`Wk3/.../EXPERIMENT_REPORT.md`）
- 每个数字都要能追溯到日志或结果 JSON
- 区分「实测」与「推断」：推断必须明确标注，例如 `Wk4/README.md` 的主题推断段
- 差异结论要说明是否穿透噪声。单次运行得到的小差异（如 ±7 分）按噪声处理，不当结论

---

## 9. 提交前检查清单

```bash
# 1. 格式与静态检查
black --line-length 100 . && ruff check .

# 2. 模块自测与 doctest
python <改动的模块>.py
python -m doctest <改动的模块>.py

# 3. 数据校验（如动了 knowledge/）
python Wk2/experiments/v2-pipeline/hooks/validate_json.py knowledge/articles/*.json
python Wk2/experiments/v2-pipeline/hooks/check_quality.py knowledge/articles/*.json

# 4. 密钥自查
git diff --cached | grep -iE 'sk-[a-zA-Z0-9]{16,}|API_KEY\s*=\s*["\x27][^"\x27]{8,}'

# 5. 确认无 TODO / 死代码
git diff --cached | grep -nE '^\+.*(TODO|FIXME|XXX)'
```

- [ ] black / ruff 干净
- [ ] 改动的模块 `_self_test()` 与 doctest 通过
- [ ] 类型标注与 docstring 完整（公开函数）
- [ ] 无魔法数字 / 硬编码路径 / 裸 except
- [ ] 无密钥、无 TODO、无死代码
- [ ] 报告里每个结论都有数据支撑，没跑过的不写
- [ ] commit message 符合 Conventional Commits

---

## 10. 未落地项汇总

本规范里有几条**尚未在仓库中生效**，列出来避免被误读为现状：

| # | 项 | 现状 | 待办 |
|:-:|----|------|------|
| 1 | `pyproject.toml` 集中配置 black / ruff | 不存在，靠手工传参 | 新增并钉住工具版本 |
| 2 | `tests/` 目录与 pytest | 不存在，只有模块内 `_self_test()` | 先给 `quality.py`、`validate_json.py`、`check_quality.py` 补单测 |
| 3 | lint + test 的 CI job | 只有数据管线 workflow | 新增 `.github/workflows/ci.yml` |
| 4 | 覆盖率 ≥ 80% | 未测量 | 接入 `pytest-cov` 后才能声称 |
| 5 | `.env.example` | 不存在 | 新增，登记所有需要的环境变量名 |
| 6 | `scripts/extract_course_tasks.sh` 用 `set -euo pipefail` | 只有 `set -e` | 补齐并过 shellcheck |
