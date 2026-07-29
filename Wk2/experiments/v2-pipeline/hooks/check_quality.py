#!/usr/bin/env python3
"""知识条目 5 维度质量评分脚本。

用法::

    python hooks/check_quality.py <json_file> [...]
    python hooks/check_quality.py knowledge/articles/*.json

维度与权重（总分 100）：

===============  ====  ==========================================
维度              分值  说明
===============  ====  ==========================================
摘要质量           25   >=50 字满分，>=20 字基本分，技术关键词奖励
技术深度           25   基于 score 字段 1-10 线性映射
格式规范           20   id/title/source_url/status/时间戳 各 4 分
标签精度           15   1-3 个合法标签最佳，标签过多扣分
空洞词检测         15   每发现一个空洞词扣 3 分
===============  ====  ==========================================

等级：A(>=80) / B(>=60) / C(<60)。存在 C 级条目时 exit 1，否则 exit 0。
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# 评分规则常量
# ---------------------------------------------------------------------------

#: 各维度满分
MAX_SUMMARY = 25
MAX_DEPTH = 25
MAX_FORMAT = 20
MAX_TAGS = 15
MAX_BUZZWORD = 15
MAX_TOTAL = MAX_SUMMARY + MAX_DEPTH + MAX_FORMAT + MAX_TAGS + MAX_BUZZWORD

#: 空洞词黑名单（中文）
BUZZWORDS_ZH: tuple[str, ...] = (
    "赋能",
    "抓手",
    "闭环",
    "打通",
    "全链路",
    "底层逻辑",
    "颗粒度",
    "对齐",
    "拉通",
    "沉淀",
    "强大的",
    "革命性的",
)

#: 空洞词黑名单（英文，匹配时不区分大小写）
BUZZWORDS_EN: tuple[str, ...] = (
    "groundbreaking",
    "revolutionary",
    "game-changing",
    "cutting-edge",
    "state-of-the-art",
    "leverage",
    "synergy",
    "paradigm shift",
    "disruptive",
    "next-generation",
    "world-class",
)

#: 合法标签白名单
VALID_TAGS: frozenset[str] = frozenset(
    {
        "agent",
        "rag",
        "mcp",
        "llm",
        "fine-tuning",
        "prompt-engineering",
        "multi-agent",
        "tool-use",
        "evaluation",
        "deployment",
        "security",
        "reasoning",
        "code-generation",
        "vision",
        "audio",
        "robotics",
    }
)

#: 摘要中出现即加分的技术关键词（不区分大小写）
TECH_KEYWORDS: tuple[str, ...] = (
    "模型",
    "推理",
    "训练",
    "微调",
    "架构",
    "算法",
    "上下文",
    "向量",
    "检索",
    "工具调用",
    "基准",
    "延迟",
    "吞吐",
    "参数",
    "量化",
    "token",
    "transformer",
    "embedding",
    "benchmark",
    "latency",
    "throughput",
    "inference",
    "fine-tune",
    "quantization",
    "context window",
    "api",
)

#: 摘要长度阈值
SUMMARY_FULL_LENGTH = 50
SUMMARY_BASE_LENGTH = 20

#: 摘要技术关键词奖励上限与单个奖励分
KEYWORD_BONUS_PER_HIT = 1
KEYWORD_BONUS_CAP = 5

#: 单个空洞词扣分
BUZZWORD_PENALTY = 3

#: 标签数量最佳区间
TAG_IDEAL_MIN = 1
TAG_IDEAL_MAX = 3

#: 时间戳候选字段
TIMESTAMP_FIELDS: tuple[str, ...] = ("collected_at", "created_at", "updated_at", "published_at")

#: 等级阈值
GRADE_A_THRESHOLD = 80
GRADE_B_THRESHOLD = 60


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass
class DimensionScore:
    """单个评分维度的结果。

    Attributes:
        name: 维度名称。
        score: 实际得分。
        max_score: 该维度满分。
        details: 得分/扣分说明。
    """

    name: str
    score: float
    max_score: int
    details: list[str] = field(default_factory=list)

    @property
    def ratio(self) -> float:
        """得分率，范围 0.0-1.0。"""
        if self.max_score <= 0:
            return 0.0
        return max(0.0, min(1.0, self.score / self.max_score))

    def bar(self, width: int = 20) -> str:
        """渲染文本进度条。

        Args:
            width: 进度条字符宽度。

        Returns:
            由 █ 和 ░ 组成的进度条字符串。
        """
        filled = int(round(self.ratio * width))
        return "█" * filled + "░" * (width - filled)


@dataclass
class QualityReport:
    """单个文件的质量评分报告。

    Attributes:
        path: 被评分的文件路径。
        dimensions: 各维度得分。
        error: 文件无法解析时的错误信息。
    """

    path: Path
    dimensions: list[DimensionScore] = field(default_factory=list)
    error: str | None = None

    @property
    def total(self) -> float:
        """加权总分（各维度直接累加，满分 100）。"""
        return sum(dim.score for dim in self.dimensions)

    @property
    def grade(self) -> str:
        """等级 A/B/C。解析失败视为 C。"""
        if self.error is not None:
            return "C"
        if self.total >= GRADE_A_THRESHOLD:
            return "A"
        if self.total >= GRADE_B_THRESHOLD:
            return "B"
        return "C"


# ---------------------------------------------------------------------------
# 5 个维度的评分函数
# ---------------------------------------------------------------------------


def score_summary(data: dict) -> DimensionScore:
    """摘要质量（25 分）。

    >=50 字给满分基础分 20，>=20 字给基本分 12，不足给按比例分；
    命中技术关键词每个 +1，最多 +5。

    Args:
        data: 知识条目对象。

    Returns:
        该维度的 DimensionScore。
    """
    details: list[str] = []
    summary = data.get("summary")

    if not isinstance(summary, str) or not summary.strip():
        return DimensionScore("摘要质量", 0.0, MAX_SUMMARY, ["缺少 summary 字段"])

    text = summary.strip()
    length = len(text)

    if length >= SUMMARY_FULL_LENGTH:
        base = 20.0
        details.append(f"长度 {length} 字（>= {SUMMARY_FULL_LENGTH}）+20")
    elif length >= SUMMARY_BASE_LENGTH:
        base = 12.0
        details.append(f"长度 {length} 字（>= {SUMMARY_BASE_LENGTH}）+12")
    else:
        base = round(12.0 * length / SUMMARY_BASE_LENGTH, 1)
        details.append(f"长度 {length} 字（< {SUMMARY_BASE_LENGTH}）仅 +{base}")

    lowered = text.lower()
    hits = [kw for kw in TECH_KEYWORDS if kw.lower() in lowered]
    bonus = min(len(hits) * KEYWORD_BONUS_PER_HIT, KEYWORD_BONUS_CAP)
    if hits:
        shown = "、".join(hits[:5])
        details.append(f"技术关键词 {len(hits)} 个（{shown}）+{bonus}")
    else:
        details.append("未命中技术关键词 +0")

    return DimensionScore("摘要质量", min(base + bonus, MAX_SUMMARY), MAX_SUMMARY, details)


def score_depth(data: dict) -> DimensionScore:
    """技术深度（25 分）。

    基于 score 字段 1-10 线性映射到 0-25；缺失时给中位分。

    Args:
        data: 知识条目对象。

    Returns:
        该维度的 DimensionScore。
    """
    raw = data.get("score")

    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return DimensionScore(
            "技术深度",
            MAX_DEPTH / 2,
            MAX_DEPTH,
            ["缺少有效 score 字段，按中位分计算"],
        )

    clamped = max(1.0, min(10.0, float(raw)))
    # 1 分映射到 0，10 分映射到 25
    value = round((clamped - 1) / 9 * MAX_DEPTH, 1)
    details = [f"score={raw} → {value}/{MAX_DEPTH}"]
    if clamped != float(raw):
        details.append(f"score 超出 1-10 范围，已截断为 {clamped}")
    return DimensionScore("技术深度", value, MAX_DEPTH, details)


def score_format(data: dict) -> DimensionScore:
    """格式规范（20 分）。

    id / title / source_url / status / 时间戳 各 4 分。

    Args:
        data: 知识条目对象。

    Returns:
        该维度的 DimensionScore。
    """
    details: list[str] = []
    total = 0.0

    checks: list[tuple[str, bool]] = [
        ("id", isinstance(data.get("id"), str) and bool(data["id"].strip())),
        ("title", isinstance(data.get("title"), str) and bool(data["title"].strip())),
        (
            "source_url",
            isinstance(data.get("source_url"), str)
            and data["source_url"].startswith(("http://", "https://")),
        ),
        (
            "status",
            data.get("status") in {"draft", "review", "published", "archived"},
        ),
        (
            "时间戳",
            any(
                isinstance(data.get(f), str) and bool(data[f].strip())
                for f in TIMESTAMP_FIELDS
            ),
        ),
    ]

    for name, ok in checks:
        if ok:
            total += 4
            details.append(f"{name} ✓ +4")
        else:
            details.append(f"{name} ✗ +0")

    return DimensionScore("格式规范", total, MAX_FORMAT, details)


def score_tags(data: dict) -> DimensionScore:
    """标签精度（15 分）。

    1-3 个合法标签得满分；非法标签不计入有效标签；标签过多按超出数量扣分。

    Args:
        data: 知识条目对象。

    Returns:
        该维度的 DimensionScore。
    """
    tags = data.get("tags")
    if not isinstance(tags, list) or not tags:
        return DimensionScore("标签精度", 0.0, MAX_TAGS, ["缺少 tags 字段或为空"])

    normalized = [t.strip().lower() for t in tags if isinstance(t, str) and t.strip()]
    valid = [t for t in normalized if t in VALID_TAGS]
    invalid = [t for t in normalized if t not in VALID_TAGS]

    details: list[str] = []
    if not valid:
        details.append(f"无合法标签（白名单外: {', '.join(invalid) or '无'}）")
        return DimensionScore("标签精度", 0.0, MAX_TAGS, details)

    if TAG_IDEAL_MIN <= len(valid) <= TAG_IDEAL_MAX:
        score = float(MAX_TAGS)
        details.append(f"{len(valid)} 个合法标签（{', '.join(valid)}）满分")
    else:
        over = len(valid) - TAG_IDEAL_MAX
        penalty = min(over * 3, MAX_TAGS)
        score = float(MAX_TAGS - penalty)
        details.append(f"{len(valid)} 个合法标签，超出 {over} 个 -{penalty}")

    if invalid:
        invalid_penalty = min(len(invalid) * 2, score)
        score -= invalid_penalty
        details.append(f"非法标签 {len(invalid)} 个（{', '.join(invalid)}）-{invalid_penalty}")

    return DimensionScore("标签精度", max(score, 0.0), MAX_TAGS, details)


def score_buzzwords(data: dict) -> DimensionScore:
    """空洞词检测（15 分）。

    在 title + summary 中检索空洞词，每命中一个扣 3 分，最低 0 分。

    Args:
        data: 知识条目对象。

    Returns:
        该维度的 DimensionScore。
    """
    parts: list[str] = []
    for key in ("title", "summary"):
        value = data.get(key)
        if isinstance(value, str):
            parts.append(value)
    text = " ".join(parts)
    lowered = text.lower()

    hits: list[str] = [w for w in BUZZWORDS_ZH if w in text]
    hits += [w for w in BUZZWORDS_EN if w.lower() in lowered]

    if not hits:
        return DimensionScore("空洞词检测", float(MAX_BUZZWORD), MAX_BUZZWORD, ["未发现空洞词 满分"])

    penalty = min(len(hits) * BUZZWORD_PENALTY, MAX_BUZZWORD)
    details = [f"发现 {len(hits)} 个空洞词（{', '.join(hits)}）-{penalty}"]
    return DimensionScore("空洞词检测", float(MAX_BUZZWORD - penalty), MAX_BUZZWORD, details)


# ---------------------------------------------------------------------------
# 报告生成
# ---------------------------------------------------------------------------


def evaluate(data: dict, path: Path) -> QualityReport:
    """对单个知识条目执行全部 5 个维度的评分。

    Args:
        data: 知识条目对象。
        path: 来源文件路径，用于报告展示。

    Returns:
        完整的 QualityReport。
    """
    return QualityReport(
        path=path,
        dimensions=[
            score_summary(data),
            score_depth(data),
            score_format(data),
            score_tags(data),
            score_buzzwords(data),
        ],
    )


def check_file(path: Path) -> list[QualityReport]:
    """读取并评分单个 JSON 文件（支持单对象或对象数组）。

    Args:
        path: JSON 文件路径。

    Returns:
        该文件产生的报告列表；解析失败时返回单个带 error 的报告。
    """
    if not path.is_file():
        return [QualityReport(path=path, error="文件不存在或不是普通文件")]

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [QualityReport(path=path, error=f"JSON 解析失败: 第 {exc.lineno} 行 - {exc.msg}")]
    except (OSError, UnicodeDecodeError) as exc:
        return [QualityReport(path=path, error=f"读取失败: {exc}")]

    if isinstance(data, dict):
        return [evaluate(data, path)]

    if isinstance(data, list):
        reports: list[QualityReport] = []
        for index, item in enumerate(data):
            label = Path(f"{path}[{index}]")
            if isinstance(item, dict):
                reports.append(evaluate(item, label))
            else:
                reports.append(QualityReport(path=label, error="数组元素不是对象"))
        return reports or [QualityReport(path=path, error="JSON 数组为空")]

    return [QualityReport(path=path, error="JSON 顶层类型应为对象或数组")]


def print_report(report: QualityReport) -> None:
    """打印单份报告（进度条 + 每维度得分 + 等级）。

    Args:
        report: 待打印的报告。
    """
    print()
    print(f"📄 {report.path}")

    if report.error is not None:
        print(f"   ❌ {report.error}")
        print(f"   等级: C  总分: 0/{MAX_TOTAL}")
        return

    for dim in report.dimensions:
        print(f"   {dim.name:<6} {dim.bar()} {dim.score:>5.1f}/{dim.max_score}")
        for detail in dim.details:
            print(f"          · {detail}")

    icon = {"A": "🏆", "B": "✅", "C": "⚠️"}[report.grade]
    print(f"   {icon} 总分 {report.total:.1f}/{MAX_TOTAL}  等级 {report.grade}")


def expand_paths(patterns: list[str]) -> list[Path]:
    """展开命令行参数中的路径与通配符。

    Args:
        patterns: 原始命令行参数。

    Returns:
        去重并保持顺序的路径列表。
    """
    paths: list[Path] = []
    for pattern in patterns:
        if any(ch in pattern for ch in "*?["):
            base = Path(pattern)
            root = base.parent if str(base.parent) != "" else Path(".")
            matched = sorted(root.glob(base.name))
            paths.extend(matched or [base])
        else:
            paths.append(Path(pattern))

    seen: set[Path] = set()
    unique: list[Path] = []
    for path in paths:
        if path not in seen:
            seen.add(path)
            unique.append(path)
    return unique


def main(argv: list[str]) -> int:
    """脚本入口。

    Args:
        argv: 不含程序名的命令行参数。

    Returns:
        进程退出码：存在 C 级返回 1，否则 0。
    """
    if not argv:
        print("用法: python hooks/check_quality.py <json_file> [...]", file=sys.stderr)
        return 1

    reports: list[QualityReport] = []
    for path in expand_paths(argv):
        reports.extend(check_file(path))

    print("=" * 60)
    print("知识条目质量评分（5 维度 / 满分 100）")
    print("=" * 60)

    for report in reports:
        print_report(report)

    grades = {"A": 0, "B": 0, "C": 0}
    for report in reports:
        grades[report.grade] += 1
    average = sum(r.total for r in reports) / len(reports) if reports else 0.0

    print()
    print("-" * 60)
    print(f"共 {len(reports)} 条  平均分 {average:.1f}/{MAX_TOTAL}")
    print(f"A 级 {grades['A']}  B 级 {grades['B']}  C 级 {grades['C']}")
    print("=" * 60)

    return 1 if grades["C"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
