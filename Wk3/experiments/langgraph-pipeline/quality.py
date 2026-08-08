#!/usr/bin/env python3
"""质量评分函数 —— Wk3 实验 Bug #1 的修复。

旧公式::

    quality_score = min(100, max(0, 60 + len(summary) // 5 - (3 - len(key_points)) * 10))

问题：基线 60 就是门槛本身，只要模型交出 100 字摘要 + 5 条要点，分数必然
溢出到 100。门禁在结构上不可能触发（详见 EXPERIMENT_REPORT.md「已知问题 #1」）。

新公式::

    score = 40 + avg_len // 5 - bad_hits * 10 + good_hits * 5 - shortfall * 5

四个可解释的分项：

* ``base``      —— 基线 40，低于门槛 60，默认不及格，必须靠内容质量挣分
* ``length``    —— ``avg_len // 5``，摘要与要点的平均字数，衡量信息量
* ``bad``       —— 空洞用语命中次数 × 10 的扣分，衡量废话密度
* ``good``      —— 具体性信号（数字、单位、对比词、术语）命中数 × 5 的加分
* ``shortfall`` —— 要点条数不足 5 条时，每缺一条扣 5 分

本模块不依赖 LangGraph 也不依赖 LLM，可以独立单测。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

#: 空洞用语黑名单 —— 命中即扣分。来自中文技术写作里常见的「正确但无信息」词汇。
BAD_KEYWORDS: tuple[str, ...] = (
    "赋能",
    "抓手",
    "闭环",
    "打通",
    "对齐",
    "颗粒度",
    "生态",
    "护城河",
    "顶层设计",
    "组合拳",
    "形成合力",
    "价值链",
    "新常态",
    "底层逻辑",
    "深度融合",
    "全方位",
    "全面提升",
    "有效促进",
)

#: 具体性信号白名单 —— 命中即加分（按去重后的命中「种类数」计，不按次数）。
GOOD_KEYWORDS: tuple[str, ...] = (
    "例如",
    "对比",
    "实测",
    "版本",
    "API",
    "延迟",
    "吞吐",
    "基准",
    "源码",
    "实现",
    "参数",
    "开源",
    "论文",
    "数据集",
    "架构",
)

#: 数字 / 百分比 / 单位模式 —— 出现即算一个具体性信号。
_NUMERIC_SIGNALS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\d+\s*%"),
    re.compile(r"\d+\s*(ms|s|GB|MB|K|B|亿|万|倍)"),
    re.compile(r"\d+\.\d+"),
)

#: 质量门槛。分数低于此值触发 rewrite 分支。
QUALITY_THRESHOLD = 60

#: 要点条数的期望值，不足按 shortfall 扣分。
EXPECTED_KEY_POINTS = 5


@dataclass
class QualityBreakdown:
    """一次评分的完整分项，便于在报告里解释分数是怎么来的。

    Attributes:
        score: 最终得分（已 clamp 到 0-100）。
        raw_score: clamp 之前的原始得分，可能为负或超过 100。
        avg_len: 摘要与要点的平均字数。
        bad_hits: 空洞用语命中总次数。
        good_hits: 具体性信号命中的种类数。
        shortfall: 要点条数距离 EXPECTED_KEY_POINTS 的缺口。
        bad_words: 具体命中了哪些空洞用语，供 rewrite prompt 使用。
        good_words: 具体命中了哪些具体性信号。
    """

    score: int
    raw_score: int
    avg_len: int
    bad_hits: int
    good_hits: int
    shortfall: int
    bad_words: list[str] = field(default_factory=list)
    good_words: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        """转成可 JSON 序列化的 dict（LangGraph state 里要能存）。"""
        return {
            "score": self.score,
            "raw_score": self.raw_score,
            "avg_len": self.avg_len,
            "bad_hits": self.bad_hits,
            "good_hits": self.good_hits,
            "shortfall": self.shortfall,
            "bad_words": self.bad_words,
            "good_words": self.good_words,
        }

    def explain(self) -> str:
        """一行式的评分公式展开，直接贴进日志和报告。"""
        return (
            f"40 (base) + {self.avg_len // 5} (len {self.avg_len}字) "
            f"- {self.bad_hits * 10} (空洞×{self.bad_hits}) "
            f"+ {self.good_hits * 5} (具体×{self.good_hits}) "
            f"- {self.shortfall * 5} (要点缺{self.shortfall}) "
            f"= {self.raw_score} → {self.score}"
        )


def score_quality(summary: str, key_points: list[str]) -> QualityBreakdown:
    """按新公式给一份分析产出打分。

    Args:
        summary: 摘要文本。
        key_points: 关键要点列表。

    Returns:
        含全部分项的 QualityBreakdown。

    Examples:
        >>> score_quality("通过赋能业务实现闭环打通", ["对齐颗粒度"]).score
        0
        >>> score_quality("介绍了一些情况和说明。", ["有一些进展", "后续观察"]).score < 60
        True
    """
    summary = summary or ""
    key_points = [str(kp) for kp in (key_points or []) if str(kp).strip()]

    segments = [seg for seg in [summary, *key_points] if seg.strip()]
    total_chars = sum(len(seg) for seg in segments)
    avg_len = total_chars // len(segments) if segments else 0

    joined = " ".join(segments)

    bad_words = [word for word in BAD_KEYWORDS if word in joined]
    bad_hits = sum(joined.count(word) for word in BAD_KEYWORDS)

    good_words = [word for word in GOOD_KEYWORDS if word in joined]
    for pattern in _NUMERIC_SIGNALS:
        if pattern.search(joined):
            good_words.append(f"数字信号:{pattern.pattern}")
    good_hits = len(good_words)

    shortfall = max(0, EXPECTED_KEY_POINTS - len(key_points))

    raw = (
        40
        + avg_len // 5
        - bad_hits * 10
        + good_hits * 5
        - shortfall * 5
    )
    score = max(0, min(100, raw))

    return QualityBreakdown(
        score=score,
        raw_score=raw,
        avg_len=avg_len,
        bad_hits=bad_hits,
        good_hits=good_hits,
        shortfall=shortfall,
        bad_words=bad_words,
        good_words=good_words,
    )


def legacy_score(summary: str, key_points: list[str]) -> int:
    """旧公式，保留用于「修复前 vs 修复后」的对照。

    Args:
        summary: 摘要文本。
        key_points: 关键要点列表。

    Returns:
        旧公式得分。
    """
    return min(100, max(0, 60 + len(summary or "") // 5 - (3 - len(key_points or [])) * 10))


# ---------------------------------------------------------------------------
# 自测：验证新公式确实有分布（旧公式没有）
# ---------------------------------------------------------------------------

#: 评分函数的固定样本集：(标签, summary, key_points)
SCORING_SAMPLES: tuple[tuple[str, str, list[str]], ...] = (
    (
        "高质量",
        "LangGraph 1.2.9 的 StateGraph 用条件边替代了线性管线的 must-pass 语义，"
        "实测同一主题下 3 次调用降到 2 次；对比 V1 的文件传递，共享 state 省掉了每步一次 JSON 读写。"
        "源码里 add_conditional_edges 只是往 branches 字典注册一个路由函数。",
        [
            "条件边由 decide_route(state) 返回节点名，运行时才决定走向，例如质量不达标走 rewrite",
            "MemorySaver 按 thread_id 存 checkpoint，进程退出即失，换 SqliteSaver 可跨进程恢复",
            "共享 state 用 TypedDict 声明字段，节点只返回 partial dict，由框架 merge",
            "回边 rewrite → quality_check 让重写产出不被 analyze 覆盖，实测分数从 31 升到 78",
            "成本上编排本身 0 花费，token 100% 来自节点内的 API 调用",
        ],
    ),
    (
        "低质-空洞用语",
        "本方案通过赋能业务实现闭环，打通生态，对齐颗粒度。",
        ["形成合力", "顶层设计", "全面提升"],
    ),
    (
        "低质-摘要极短",
        "介绍了一些相关内容和情况。",
        ["有一些进展", "值得关注", "后续观察"],
    ),
    (
        "中等质量-偏空泛",
        "LangGraph 提供图编排能力，支持条件路由与循环，适合需要运行时决策的 Agent 管线。"
        "相比线性管线，调试成本更高。",
        [
            "支持条件边和回边",
            "state 用 TypedDict 声明",
            "checkpointer 可插拔",
            "调试比线性管线难",
        ],
    ),
)


def _self_test() -> int:
    """打印样本集在新旧公式下的分数，验证新公式有区分度。

    Returns:
        退出码：新公式区分度不足时返回 1。
    """
    print("=" * 78)
    print(f"{'样本':<16}{'新公式':>8}{'旧公式':>8}   分项展开")
    print("=" * 78)

    new_scores: list[int] = []
    old_scores: list[int] = []

    for label, summary, key_points in SCORING_SAMPLES:
        breakdown = score_quality(summary, key_points)
        old = legacy_score(summary, key_points)
        new_scores.append(breakdown.score)
        old_scores.append(old)
        print(f"{label:<16}{breakdown.score:>8}{old:>8}   {breakdown.explain()}")

    print("-" * 78)
    new_span = max(new_scores) - min(new_scores)
    old_span = max(old_scores) - min(old_scores)
    print(f"新公式区间: {min(new_scores)}-{max(new_scores)} (跨度 {new_span})")
    print(f"旧公式区间: {min(old_scores)}-{max(old_scores)} (跨度 {old_span})")
    print(f"门槛 {QUALITY_THRESHOLD}: 新公式判不及格 "
          f"{sum(1 for s in new_scores if s < QUALITY_THRESHOLD)}/{len(new_scores)} 条, "
          f"旧公式判不及格 {sum(1 for s in old_scores if s < QUALITY_THRESHOLD)}/{len(old_scores)} 条")
    print("=" * 78)

    return 0 if new_span >= 40 else 1


if __name__ == "__main__":
    raise SystemExit(_self_test())
