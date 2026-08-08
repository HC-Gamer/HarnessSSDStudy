# Week 3 — 图编排（LangGraph StateGraph）

> 首轮实验：2026-07-29 · 修复轮：2026-08-08
> 状态：**实验完成，7 个已知问题已处理（6 修 1 判定不修），6 项下一步全部完成**

---

## 这周做了什么

把 Wk2 的「采集 → 分析 → 组织」线性管线用 LangGraph `StateGraph` 重写，验证图编排相对
线性 Harness 管线的四个维度：状态管理、条件路由、反馈循环、成本。

**核心结论**（详见 [实验报告](experiments/langgraph-pipeline/EXPERIMENT_REPORT.md)）：

1. **共享 state 显著优于文件传递** —— 省掉 I/O 中介和序列化往返，字段有类型声明。
   代价是中间产物不再天然落盘，可观测性从「白送」变成「要自己做」。
2. **质量门禁的价值是「保险」型的，不是「提升」型的**。2×2 对照实测：
   analyzer prompt 严格时门禁是 no-op（差异 +7 分，落在噪声里），
   prompt 欠约束时门禁值 **+36 分**（41 分产出被拦下，重写一次到 100 分）。
   **只跑一格会得出误导性结论。**
3. **首轮报告的「质量分 100/100」是评分函数失效的症状，不是质量好的证据**。
   旧公式基线 60 正好等于门槛 60，任何正常产出必然及格。换公式后，12 次首评有 5 次不及格。
4. **图编排本身零成本** —— LangGraph 的调度、路由、checkpoint 全在本地跑，
   token 100% 来自节点内的业务调用。全套 12 次图执行共 ¥0.0372。

---

## 目录

```
Wk3/
├── README.md                              # 本文件
├── .venv/                                 # Python 3.13 venv（已 gitignore）
└── experiments/langgraph-pipeline/
    ├── langgraph_experiment.py            # 图定义 + 5 节点 + 3 入口 + 7 组实验 + CLI
    ├── quality.py                         # 质量评分函数（新公式 + 旧公式对照 + 自测样本集）
    ├── rss_collector.py                   # 真实 RSS/Atom 采集，复用 Wk2 rss_sources.yaml
    ├── verify_sqlite_resume.py            # 独立进程读 SQLite checkpoint（跨进程恢复的硬证据）
    ├── EXPERIMENT_REPORT.md               # 实验报告（含文末「修复记录」段）
    ├── EXPERIMENT_REFLECTION.md           # 深度心得
    └── results/
        ├── results_all.json               # 全套实验的结构化结果（含每条断言）
        ├── run_all.log                    # 完整运行日志
        ├── experiment_{1,2,3}_article.md  # 3 个主实验产出
        ├── lowq-{1,2}-*.md                # 低质量注入产出
        ├── breaker_circuit_breaker.md     # 熔断实验产出
        ├── checkpoint_recovery.md         # MemorySaver 中断恢复产出
        ├── sqlite_checkpointer.md         # SQLite checkpointer 产出
        ├── v1v3_{v1_linear,v3_stategraph}_{normal,terse}.md   # 2×2 同题对照产出
        ├── v1_workdir/                    # V1 线性管线的中间文件（它靠文件传递的物证）
        └── checkpoints.sqlite             # SQLite checkpoint 数据库
```

---

## 怎么跑

```bash
source Wk3/.venv/bin/activate
cd Wk3/experiments/langgraph-pipeline

python langgraph_experiment.py all          # 全套（12 次图执行，~¥0.037，~3 分钟）
python langgraph_experiment.py main         # 3 个主实验（真实 RSS 采集）
python langgraph_experiment.py lowq         # 低质量样本注入
python langgraph_experiment.py breaker      # 3 次重写上限熔断（只花 1 次调用）
python langgraph_experiment.py checkpoint   # MemorySaver 中断 → 改写 → 恢复
python langgraph_experiment.py sqlite       # SQLite checkpointer 跨进程恢复
python langgraph_experiment.py v1v3         # V1/V3 同题对照（2×2）

# 单模块自测，不花钱
python quality.py                           # 新旧公式在固定样本集上的分布对比
python rss_collector.py                     # 抓一次真实 feed 看结果
```

依赖：`langgraph`、`langgraph-checkpoint-sqlite`、`httpx`、`pyyaml`、`python-dotenv`。
密钥：`DEEPSEEK_API_KEY`，从 `Wk2/experiments/v2-pipeline/.env` 读（脚本会按 4 个候选路径找 `.env`）。

---

## 图结构

```
START ─┬─ (full)         ──► search → analyze ─┐
       ├─ (analyze_only) ─────────► analyze ───┤
       └─ (quality_only) ─────────────────────►┴► quality_check
                                                   │ decide_route
                          ┌────────────────────────┤
                          ▼ score<60 且未触顶       ▼ 通过 / 熔断
                      rewrite ──► quality_check  organize → END
```

三个入口分别服务于：主实验（`full`）、同题对照（`analyze_only`，跳过重复采集）、
低质量注入与熔断（`quality_only`，直接送预置样本进门禁）。

回边指向 `quality_check` 而不是 `analyze`——这是首轮 bug #2 的修复，
首轮回边会让 analyze 从 `raw_content` 从头重算，把 rewrite 的改进产出覆盖掉。

---

## 实测数据速览

| 实验 | 首评 → 终评 | 重写 | 调用 | Token | 成本 ¥ |
|------|:----------:|:---:|:---:|:-----:|:-----:|
| main-1(normal) | 100 | 0 | 2 | 2,235 | 0.0031 |
| main-2(terse) | 59 → **100** | 1 | 3 | 3,460 | 0.0045 |
| main-3(normal) | 100 | 0 | 2 | 2,203 | 0.0031 |
| lowq-1-空洞用语 | 0 → **97** | 1 | 2 | 2,163 | 0.0031 |
| lowq-2-摘要极短 | 26 → **100** | 1 | 2 | 2,132 | 0.0031 |
| breaker(熔断) | 0 → 0 ⚡ | 3 | 1 | 665 | 0.0012 |
| checkpoint-recovery | 86 | 0 | 2 | 2,101 | 0.0029 |
| sqlite-checkpointer | 100 | 0 | 2 | 2,250 | 0.0032 |
| v1v3 × 4 格 | 见报告 2×2 表 | 1 | 9 | 9,583 | 0.0131 |
| **合计** | | **8** | **25** | **26,792** | **¥0.0372** |

12 次首评的分数分布：`0, 0, 26, 41, 59, 64, 82, 86, 89, 100, 100, 100`
（5 次不及格）。**同样这 12 次，旧公式会给 11 次 100 分 + 1 次 53 分。**

---

## 残留问题

| # | 问题 | 严重度 | 说明 |
|:-:|------|:-----:|------|
| 1 | 评分函数在及格区饱和 | 🟡 中 | raw score 常超 100 被 clamp，能判「过/不过」但不能给及格产出排序。留给 Wk4 评估专题 |
| 2 | 无权限隔离 | 🟢 低 | 图编排的架构取舍，要隔离得把节点拆进子进程/容器 |
| 3 | `sabotage_rewrite` 是人造场景 | 🟢 低 | 熔断只能靠「保证改不好」触发，报告已明确标注 |
| 4 | 未验证 time-travel | 🟢 低 | 只数了 checkpoint 条数，没做分叉重放 |
| 5 | 单次运行，方差未量化 | 🟡 中 | 2×2 的 normal 格两轮分别得到 +7 和 -5，说明这个量级的差异不可信 |

第 5 条是最该继续做的：**补重复采样和置信区间**，成本只有 ¥0.037 × N。

---

## 相关文档

- [实验报告](experiments/langgraph-pipeline/EXPERIMENT_REPORT.md) —— 完整数据、修复记录、2×2 对照
- [深度心得](experiments/langgraph-pipeline/EXPERIMENT_REFLECTION.md)
- [博客 blog7](../blogs/harness-study/blog7_langgraph_stategraph_实验报告_2026-07-29.md) —— 首轮的对外版本
- [编码规范](../specs/coding-standards.md) —— 本周代码遵循的规范
- [Wk4 准备](../Wk4/README.md) —— 本周留下的坑在那里接
