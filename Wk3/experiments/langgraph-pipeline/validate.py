#!/usr/bin/env python3
"""段间 schema 校验 —— `opencode-subagent-v1/RUN_REPORT.md` 两个发现的修复。

那次真跑三 Agent 管线暴露了两件事：

1. **analyzer 产出缺字段 / 超字数**——`specs/issues/02-analyzer.md` 写了 `<= 50 字`
   和「每条 2-3 个亮点」，但没有任何一处代码检查它，下游照单全收。
2. **organizer 发现上游缺字段后自行编造数据填补且不标记**——最严重的一条。
   坏数据不但没被拦，还在下一段被「补全」成了看起来合法的好数据。

本模块把 `specs/issues/0{1,2,3}-*.md` 的 Schema 段落翻译成可执行的校验函数，
校验逻辑沿用 `Wk2/experiments/v2-pipeline/hooks/validate_json.py` 的形状
（必填字段表 + 类型检查 + 内容检查 + 错误信息列表），但有三点扩展：

* 返回 ``(passed, errors, warnings)`` 三元组而不是单一 errors 列表 ——
  「缺字段 / 类型错 / 数值越界」是硬错误，「字数超标 / 评分区分度不足」是警告
* 阈值集中在 :class:`ValidationConfig`，可按调用场景放宽（例如 CI 只采 5 条时
  不该按 spec 的「>= 15 条」判失败）
* :func:`validate_organizer` 接受 ``upstream`` 参数做**跨段一致性检查**，
  专门抓「上游没有的条目凭空出现在下游」这类编造

模块内还有一组 :func:`validate_search_segment` / :func:`validate_analyze_segment`，
校验的是 LangGraph 的 ``PipelineState``（字段名与 spec 不同，见各函数 docstring），
供 `langgraph_experiment.py` 的段间校验节点调用。

用法::

    python validate.py                                  # 跑内置好/坏样本自测
    python validate.py knowledge/raw/github-trending-*.json --kind collector
    python validate.py analysis.json --kind analyzer
    python validate.py knowledge/articles/*.json --kind organizer

本模块不依赖 LangGraph，也不调 LLM，可以独立单测。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# 校验结果
# ---------------------------------------------------------------------------

#: 校验函数的统一返回类型：(是否通过, 硬错误, 警告)
ValidationResult = tuple[bool, list[str], list[str]]


@dataclass(frozen=True)
class ValidationConfig:
    """校验阈值，按调用场景可调。

    默认值取自 `specs/issues/0{1,2,3}-*.md` 的 Acceptance Criteria。
    调用方（例如只采 5 条的 CI 任务）应显式放宽，而不是让校验形同虚设。

    Attributes:
        min_items: collector 至少产出几条（spec: >= 15）。
        max_analyzer_summary_chars: analyzer 摘要字数上限（spec: <= 50 字）。
        max_organizer_summary_chars: organizer 摘要字数上限（spec: <= 100 字）。
        min_highlights: 每条至少几个技术亮点（spec: 2-3 个）。
        max_highlights: 每条至多几个技术亮点。
        min_tags: 每条至少几个标签（spec: 1-3 个）。
        max_tags: 每条至多几个标签。
        max_top_scores: 9-10 分的条目上限（spec: 15 条中不超过 2 个）。
        min_score_spread: 评分极差下限，低于此值判「区分度不足」。
        min_distinct_scores: 不同分值的种类数下限。
        score_min: relevance_score 合法下界。
        score_max: relevance_score 合法上界。
    """

    min_items: int = 15
    max_analyzer_summary_chars: int = 50
    max_organizer_summary_chars: int = 100
    min_highlights: int = 2
    max_highlights: int = 3
    min_tags: int = 1
    max_tags: int = 3
    max_top_scores: int = 2
    min_score_spread: int = 3
    min_distinct_scores: int = 3
    score_min: int = 1
    score_max: int = 10


#: 默认配置（严格按 spec）
DEFAULT_CONFIG = ValidationConfig()

#: 放宽版：只检查结构不检查规模，供小批量运行（如 CI `--limit 5`）使用
RELAXED_CONFIG = ValidationConfig(min_items=1, max_top_scores=99, min_distinct_scores=1,
                                  min_score_spread=0)


@dataclass
class _Collector:
    """错误 / 警告收集器，避免每个校验函数都手写 append 逻辑。"""

    prefix: str = ""
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def error(self, message: str) -> None:
        """记一条硬错误。"""
        self.errors.append(f"{self.prefix}{message}")

    def warn(self, message: str) -> None:
        """记一条警告。"""
        self.warnings.append(f"{self.prefix}{message}")

    def child(self, prefix: str) -> _Collector:
        """派生一个带更深前缀、但共享底层列表的收集器。"""
        sub = _Collector(prefix=f"{self.prefix}{prefix}")
        sub.errors = self.errors
        sub.warnings = self.warnings
        return sub

    def result(self) -> ValidationResult:
        """导出 ``(passed, errors, warnings)``。"""
        return (not self.errors, list(self.errors), list(self.warnings))


# ---------------------------------------------------------------------------
# 通用校验原语
# ---------------------------------------------------------------------------

#: URL 必须是 http(s)
URL_PATTERN = re.compile(r"^https?://\S+$")

#: organizer 的 id 格式：YYYY-MM-DD-source-slug
ORGANIZER_ID_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}-[a-z0-9]+(?:-[a-z0-9._-]+)+$", re.IGNORECASE)

#: organizer 的 status 合法取值（spec 03 第 16 行）
VALID_ORGANIZER_STATUS: frozenset[str] = frozenset({"draft", "reviewed", "published"})

#: collector 的 collection 模式（LangGraph 段用）
VALID_COLLECTION_MODES: frozenset[str] = frozenset(
    {"real_rss", "llm_mock", "degraded", "github_trending_file", "none"}
)


def _check_fields(data: dict[str, Any], spec: dict[str, type | tuple[type, ...]],
                  bag: _Collector) -> set[str]:
    """检查必填字段存在且类型正确。

    Args:
        data: 待校验的对象。
        spec: 字段名 → 期望类型（或类型元组）。
        bag: 收集器。

    Returns:
        通过了类型检查、可以继续做内容校验的字段名集合。
    """
    ok: set[str] = set()
    for name, expected in spec.items():
        if name not in data:
            bag.error(f"缺少必填字段 {name}")
            continue
        value = data[name]
        # bool 是 int 的子类，数值字段要显式排除，否则 True 会被当成 1
        if expected in (int, (int, float)) and isinstance(value, bool):
            bag.error(f"字段 {name} 类型错误: 期望数字，实际 bool")
            continue
        if not isinstance(value, expected):
            names = (expected.__name__ if isinstance(expected, type)
                     else "/".join(t.__name__ for t in expected))
            bag.error(f"字段 {name} 类型错误: 期望 {names}，实际 {type(value).__name__}")
            continue
        ok.add(name)
    return ok


def _check_str_list(value: list[Any], label: str, bag: _Collector) -> list[str]:
    """检查列表元素都是非空字符串。

    Args:
        value: 待检查的列表。
        label: 字段名，用于错误信息。
        bag: 收集器。

    Returns:
        通过检查的字符串列表。
    """
    good: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str):
            bag.error(f"{label}[{index}] 类型错误: 期望 str，实际 {type(item).__name__}")
        elif not item.strip():
            bag.error(f"{label}[{index}] 为空字符串")
        else:
            good.append(item)
    return good


def _check_range(value: int | float, label: str, low: int, high: int, bag: _Collector) -> None:
    """检查数值在闭区间内，越界记为硬错误。"""
    if not low <= value <= high:
        bag.error(f"{label} 越界: {value}，应在 {low}-{high} 之间")


def _chars(text: str) -> int:
    """去掉首尾空白后的字符数（中文按字计）。"""
    return len(text.strip())


# ---------------------------------------------------------------------------
# 01-collector
# ---------------------------------------------------------------------------

#: collector 顶层必填字段（specs/issues/01-collector.md「Schema」段）
COLLECTOR_TOP_FIELDS: dict[str, type | tuple[type, ...]] = {
    "source": str,
    "collected_at": str,
    "items": list,
}

#: collector 单条目必填字段
COLLECTOR_ITEM_FIELDS: dict[str, type | tuple[type, ...]] = {
    "name": str,
    "url": str,
    "summary": str,
    "stars": int,
    "language": str,
    "topics": list,
}


def validate_collector(data: Any, config: ValidationConfig = DEFAULT_CONFIG) -> ValidationResult:
    """校验采集 Agent 的产出（`specs/issues/01-collector.md`）。

    硬错误：顶层或条目缺必填字段、类型错误、``stars`` 为负、``url`` 非 http(s)、
    ``full_name`` 重复（spec 第 15 行要求按 ``full_name`` 去重）。

    警告：条目数不足 ``config.min_items``、未按 star 降序排列、摘要过短、
    ``topics`` 为空。

    Args:
        data: 解析后的 JSON 对象。
        config: 阈值配置。

    Returns:
        ``(passed, errors, warnings)``。

    Examples:
        >>> ok, errs, _ = validate_collector({"source": "x", "collected_at": "t", "items": []},
        ...                                  RELAXED_CONFIG)
        >>> ok
        False
    """
    bag = _Collector()

    if not isinstance(data, dict):
        bag.error(f"顶层类型错误: 期望 object，实际 {type(data).__name__}")
        return bag.result()

    ok_fields = _check_fields(data, COLLECTOR_TOP_FIELDS, bag)
    if "items" not in ok_fields:
        return bag.result()

    items = data["items"]
    if not items:
        bag.error("items 为空数组（spec 要求 >= 1 条；失败时应输出空数组并由调用方判定）")
        return bag.result()
    if len(items) < config.min_items:
        bag.warn(f"items 只有 {len(items)} 条，spec 要求 >= {config.min_items} 条")

    seen: dict[str, int] = {}
    stars_seq: list[int] = []

    for index, item in enumerate(items):
        sub = bag.child(f"items[{index}] ")
        if not isinstance(item, dict):
            sub.error(f"类型错误: 期望 object，实际 {type(item).__name__}")
            continue

        item_ok = _check_fields(item, COLLECTOR_ITEM_FIELDS, sub)

        if "stars" in item_ok:
            if item["stars"] < 0:
                sub.error(f"stars 越界: {item['stars']}，不能为负")
            else:
                stars_seq.append(item["stars"])
        if "url" in item_ok and not URL_PATTERN.match(item["url"]):
            sub.error(f"url 格式错误: {item['url']!r}，应以 http:// 或 https:// 开头")
        if "topics" in item_ok:
            _check_str_list(item["topics"], "topics", sub)
            if not item["topics"]:
                sub.warn("topics 为空，无法用 spec 的 ai/llm/agent/ml 过滤条件复核")
        if "summary" in item_ok and _chars(item["summary"]) < 10:
            sub.warn(f"summary 只有 {_chars(item['summary'])} 字，信息量可疑")
        if "name" in item_ok:
            name = item["name"]
            if name in seen:
                sub.error(f"name 重复: {name!r}（首次出现在 items[{seen[name]}]，spec 要求去重）")
            else:
                seen[name] = index

    if stars_seq and stars_seq != sorted(stars_seq, reverse=True):
        bag.warn("items 未按 stars 降序排列（spec 第 16 行）")

    return bag.result()


# ---------------------------------------------------------------------------
# 02-analyzer
# ---------------------------------------------------------------------------

#: analyzer 顶层必填字段（specs/issues/02-analyzer.md「Schema」段）
ANALYZER_TOP_FIELDS: dict[str, type | tuple[type, ...]] = {
    "source": str,
    "analyzed_at": str,
    "trends": list,
    "items": list,
}

#: analyzer 单条目必填字段
ANALYZER_ITEM_FIELDS: dict[str, type | tuple[type, ...]] = {
    "name": str,
    "summary": str,
    "highlights": list,
    "relevance_score": int,
    "score_reason": str,
    "tags": list,
}


def validate_analyzer(data: Any, config: ValidationConfig = DEFAULT_CONFIG) -> ValidationResult:
    """校验分析 Agent 的产出（`specs/issues/02-analyzer.md`）。

    硬错误：缺必填字段、类型错误、``relevance_score`` 不在 1-10。

    警告（RUN_REPORT 里实际踩到的两类）：摘要超过 ``max_analyzer_summary_chars`` 字、
    亮点条数不在 ``[min_highlights, max_highlights]``、标签条数越界、``score_reason``
    过短、``trends`` 为空，以及**评分区分度不足**——9-10 分条目超过 ``max_top_scores``、
    分数极差小于 ``min_score_spread``、不同分值种类少于 ``min_distinct_scores``。

    Args:
        data: 解析后的 JSON 对象。
        config: 阈值配置。

    Returns:
        ``(passed, errors, warnings)``。
    """
    bag = _Collector()

    if not isinstance(data, dict):
        bag.error(f"顶层类型错误: 期望 object，实际 {type(data).__name__}")
        return bag.result()

    ok_fields = _check_fields(data, ANALYZER_TOP_FIELDS, bag)

    if "trends" in ok_fields:
        _check_str_list(data["trends"], "trends", bag)
        if not data["trends"]:
            bag.warn("trends 为空（spec 第 18 行要求有趋势发现）")

    if "items" not in ok_fields:
        return bag.result()

    items = data["items"]
    if not items:
        bag.error("items 为空数组")
        return bag.result()

    scores: list[int] = []

    for index, item in enumerate(items):
        sub = bag.child(f"items[{index}] ")
        if not isinstance(item, dict):
            sub.error(f"类型错误: 期望 object，实际 {type(item).__name__}")
            continue

        item_ok = _check_fields(item, ANALYZER_ITEM_FIELDS, sub)

        if "relevance_score" in item_ok:
            _check_range(item["relevance_score"], "relevance_score",
                         config.score_min, config.score_max, sub)
            if config.score_min <= item["relevance_score"] <= config.score_max:
                scores.append(item["relevance_score"])

        if "summary" in item_ok:
            length = _chars(item["summary"])
            if length > config.max_analyzer_summary_chars:
                sub.warn(f"summary {length} 字，超过 spec 的 {config.max_analyzer_summary_chars} 字")
            elif length < 8:
                sub.warn(f"summary 只有 {length} 字，信息量可疑")

        if "highlights" in item_ok:
            good = _check_str_list(item["highlights"], "highlights", sub)
            if not config.min_highlights <= len(good) <= config.max_highlights:
                sub.warn(
                    f"highlights {len(good)} 条，spec 要求 "
                    f"{config.min_highlights}-{config.max_highlights} 条"
                )

        if "tags" in item_ok:
            good = _check_str_list(item["tags"], "tags", sub)
            if not config.min_tags <= len(good) <= config.max_tags:
                sub.warn(f"tags {len(good)} 个，spec 要求 {config.min_tags}-{config.max_tags} 个")

        if "score_reason" in item_ok and _chars(item["score_reason"]) < 8:
            sub.warn(f"score_reason 只有 {_chars(item['score_reason'])} 字，等于没给理由")

    bag.warnings.extend(check_score_discrimination(scores, config))
    return bag.result()


def check_score_discrimination(scores: list[int],
                               config: ValidationConfig = DEFAULT_CONFIG) -> list[str]:
    """检查一组评分是否有区分度。

    spec 02 第 15 行只写了「15 条中 9-10 分不超过 2 个」，但实践里更常见的失效形态是
    **所有条目打同一个分**——形式上没违反那条规则，实质上评分没起作用。所以这里查三件事：
    高分溢出、极差过小、分值种类过少。

    Args:
        scores: 已确认落在合法区间内的评分列表。
        config: 阈值配置。

    Returns:
        警告信息列表；区分度足够时为空列表。
    """
    if not scores:
        return []

    warnings: list[str] = []

    top = [s for s in scores if s >= 9]
    if len(top) > config.max_top_scores:
        warnings.append(
            f"评分区分度不足: 9-10 分有 {len(top)} 条，超过上限 {config.max_top_scores} 条"
        )

    spread = max(scores) - min(scores)
    if spread < config.min_score_spread:
        warnings.append(
            f"评分区分度不足: 极差只有 {spread}（{min(scores)}-{max(scores)}），"
            f"低于阈值 {config.min_score_spread}"
        )

    distinct = len(set(scores))
    if distinct < config.min_distinct_scores:
        warnings.append(
            f"评分区分度不足: {len(scores)} 条只用了 {distinct} 种分值，"
            f"低于阈值 {config.min_distinct_scores}"
        )

    return warnings


# ---------------------------------------------------------------------------
# 03-organizer
# ---------------------------------------------------------------------------

#: organizer 单条目必填字段（specs/issues/03-organizer.md「Schema」段）
ORGANIZER_FIELDS: dict[str, type | tuple[type, ...]] = {
    "id": str,
    "title": str,
    "source": str,
    "source_url": str,
    "collected_at": str,
    "summary": str,
    "analysis": dict,
    "tags": list,
    "status": str,
}

#: organizer 的 analysis 子对象必填字段
ORGANIZER_ANALYSIS_FIELDS: dict[str, type | tuple[type, ...]] = {
    "tech_highlights": list,
    "relevance_score": int,
    "score_reason": str,
}


def validate_organizer(
    data: Any,
    config: ValidationConfig = DEFAULT_CONFIG,
    *,
    upstream: dict[str, Any] | None = None,
) -> ValidationResult:
    """校验整理 Agent 的产出（`specs/issues/03-organizer.md`）。

    接受两种形态：单个知识条目对象，或条目数组。

    硬错误：缺必填字段、类型错误、``relevance_score`` 越界、``id`` 格式不符
    ``YYYY-MM-DD-source-slug``、``status`` 不在 draft/reviewed/published、
    ``source_url`` 非 http(s)、条目间 ``source_url`` 重复（spec 要求按 URL 去重）。

    传入 ``upstream``（analyzer 的产出）时**额外做跨段一致性检查**，这是 RUN_REPORT
    第二个发现的直接修复——organizer 曾在上游缺字段时自行编造数据填补且不标记。
    检查两条：下游条目的 ``title`` 必须能在上游 ``items[].name`` 里找到；
    ``analysis.relevance_score`` 必须与上游同名条目一致。任一不符判**硬错误**，
    因为「凭空出现的条目」比「字段缺失」更危险：它看起来完全合法。

    Args:
        data: 单个条目对象或条目数组。
        config: 阈值配置。
        upstream: 可选的上游 analyzer 产出，用于跨段一致性检查。

    Returns:
        ``(passed, errors, warnings)``。
    """
    bag = _Collector()

    if isinstance(data, dict):
        entries: list[Any] = [data]
    elif isinstance(data, list):
        entries = data
        if not entries:
            bag.error("条目数组为空")
            return bag.result()
    else:
        bag.error(f"顶层类型错误: 期望 object 或 array，实际 {type(data).__name__}")
        return bag.result()

    seen_urls: dict[str, int] = {}

    for index, entry in enumerate(entries):
        prefix = f"[{index}] " if len(entries) > 1 else ""
        sub = bag.child(prefix)
        if not isinstance(entry, dict):
            sub.error(f"类型错误: 期望 object，实际 {type(entry).__name__}")
            continue

        ok_fields = _check_fields(entry, ORGANIZER_FIELDS, sub)

        if "id" in ok_fields and not ORGANIZER_ID_PATTERN.match(entry["id"]):
            sub.error(f"id 格式错误: {entry['id']!r}，应为 YYYY-MM-DD-source-slug")
        if "status" in ok_fields and entry["status"] not in VALID_ORGANIZER_STATUS:
            sub.error(f"status 非法: {entry['status']!r}，"
                      f"可选 {sorted(VALID_ORGANIZER_STATUS)}")
        if "title" in ok_fields and not entry["title"].strip():
            sub.error("title 为空字符串")
        if "source_url" in ok_fields:
            url = entry["source_url"]
            if not URL_PATTERN.match(url):
                sub.error(f"source_url 格式错误: {url!r}，应以 http:// 或 https:// 开头")
            elif url in seen_urls:
                sub.error(f"source_url 重复: {url}（首次出现在 [{seen_urls[url]}]，"
                          "spec 要求按 URL hash 去重）")
            else:
                seen_urls[url] = index
        if "tags" in ok_fields:
            good = _check_str_list(entry["tags"], "tags", sub)
            if not good:
                sub.warn("tags 为空")
        if "summary" in ok_fields:
            length = _chars(entry["summary"])
            if length > config.max_organizer_summary_chars:
                sub.warn(f"summary {length} 字，超过 spec 的 "
                         f"{config.max_organizer_summary_chars} 字")
            elif length < 10:
                sub.warn(f"summary 只有 {length} 字，信息量可疑")

        if "analysis" in ok_fields:
            ana = bag.child(f"{prefix}analysis.")
            ana_ok = _check_fields(entry["analysis"], ORGANIZER_ANALYSIS_FIELDS, ana)
            if "relevance_score" in ana_ok:
                _check_range(entry["analysis"]["relevance_score"], "relevance_score",
                             config.score_min, config.score_max, ana)
            if "tech_highlights" in ana_ok:
                good = _check_str_list(entry["analysis"]["tech_highlights"],
                                       "tech_highlights", ana)
                if not config.min_highlights <= len(good) <= config.max_highlights:
                    ana.warn(f"tech_highlights {len(good)} 条，spec 要求 "
                             f"{config.min_highlights}-{config.max_highlights} 条")

    if upstream is not None:
        cross_errors, cross_warnings = check_upstream_consistency(entries, upstream)
        bag.errors.extend(cross_errors)
        bag.warnings.extend(cross_warnings)

    return bag.result()


#: 跨段字段映射：organizer 的字段路径 → analyzer 的字段名
#: 只放「下游不该自己生成」的字段——这些值必须原样来自上游。
UPSTREAM_FIELD_MAP: tuple[tuple[tuple[str, ...], str], ...] = (
    (("analysis", "relevance_score"), "relevance_score"),
    (("analysis", "score_reason"), "score_reason"),
    (("summary",), "summary"),
)


def _dig(entry: dict[str, Any], path: tuple[str, ...]) -> Any:
    """按路径取嵌套字段，任一层缺失返回 None。"""
    cursor: Any = entry
    for key in path:
        if not isinstance(cursor, dict):
            return None
        cursor = cursor.get(key)
    return cursor


def check_upstream_consistency(
    entries: list[Any], upstream: dict[str, Any]
) -> tuple[list[str], list[str]]:
    """检查 organizer 条目是否忠实于 analyzer 的上游数据。

    专抓 RUN_REPORT 第 214 行记录的那种失败：**上游字段缺失，下游自己补了一个值且不标记**
    （实测 organizer 给 `addyosmani/agent-skills` 缺失的评分补了个 8）。
    补出来的条目本身格式完全合法，单段校验永远抓不到——只有对着上游比才看得见。

    三类硬错误，按危险程度递减：

    * **疑似编造**——下游出现了上游根本没有的条目
    * **疑似填补**——上游该字段缺失 / 为 null，下游却有值（最隐蔽的一种）
    * **疑似篡改**——两边都有值但不相等

    两类警告：``summary`` 允许下游改写（spec 03 的字数上限与 02 不同），
    只在改动时提醒；上游条目在下游丢失也只警告，因为去重会合法地减少条目。

    Args:
        entries: organizer 产出的条目列表。
        upstream: analyzer 的产出（需含 ``items[].name``）。

    Returns:
        ``(errors, warnings)``。
    """
    if not isinstance(upstream, dict) or not isinstance(upstream.get("items"), list):
        return (["upstream 不是合法的 analyzer 产出（缺 items 数组），无法做跨段一致性检查"], [])

    up_index: dict[str, dict[str, Any]] = {}
    for item in upstream["items"]:
        if isinstance(item, dict) and isinstance(item.get("name"), str):
            up_index[item["name"]] = item

    errors: list[str] = []
    warnings: list[str] = []
    matched: set[str] = set()

    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        title = entry.get("title")
        if not isinstance(title, str):
            continue

        source = up_index.get(title)
        if source is None:
            errors.append(
                f"[{index}] 疑似编造: title {title!r} 在上游 analyzer 的 "
                f"{len(up_index)} 条产出里不存在"
            )
            continue
        matched.add(title)

        for path, up_key in UPSTREAM_FIELD_MAP:
            label = ".".join(path)
            down_value = _dig(entry, path)
            up_value = source.get(up_key)

            if up_value is None and down_value is not None:
                errors.append(
                    f"[{index}] 疑似填补: {title!r} 上游没有 {up_key}，"
                    f"下游却给了 {label}={down_value!r}，且未标记为推断值"
                )
            elif up_value is not None and down_value is None:
                warnings.append(f"[{index}] {title!r} 丢失了上游的 {up_key}")
            elif up_value != down_value and up_value is not None:
                # summary 允许下游按 spec 03 的字数上限改写，只提醒不拦
                bucket = warnings if path == ("summary",) else errors
                verb = "改写" if path == ("summary",) else "疑似篡改"
                bucket.append(
                    f"[{index}] {verb}: {title!r} 的 {label} 下游 {down_value!r} "
                    f"≠ 上游 {up_value!r}"
                )

        down_hl = _dig(entry, ("analysis", "tech_highlights"))
        up_hl = source.get("highlights")
        if isinstance(down_hl, list) and isinstance(up_hl, list):
            extra = [h for h in down_hl if h not in up_hl]
            if extra:
                errors.append(
                    f"[{index}] 疑似编造: {title!r} 的 tech_highlights 有 {len(extra)} 条"
                    f"上游没有的内容，首条 {extra[0]!r}"
                )

    missing = sorted(set(up_index) - matched)
    if missing:
        warnings.append(
            f"上游 {len(up_index)} 条里有 {len(missing)} 条在下游没出现"
            f"（去重可能是合法原因）：{'、'.join(missing[:3])}"
            f"{' …' if len(missing) > 3 else ''}"
        )

    return (errors, warnings)


# ---------------------------------------------------------------------------
# LangGraph 段间校验（校验对象是 PipelineState，不是 spec 里的 JSON）
# ---------------------------------------------------------------------------
#
# 为什么不直接复用上面三个函数：LangGraph 的 state 字段是 raw_content / summary /
# key_points，跟 spec 的 items[] 结构不是一回事，硬套要先做一层失真的适配。而且
# 阈值方向相反 —— spec 的 analyzer 摘要要求 <= 50 字（面向条目卡片），LangGraph 的
# analyze 节点要求 >= 150 字（面向文章素材）。所以这里单列，共用上面的校验原语。

#: LangGraph analyze 段的摘要字数下限（对应 ANALYZE_PROMPTS["normal"] 的「150 字以上」）
GRAPH_MIN_SUMMARY_CHARS = 60

#: LangGraph analyze 段的要点条数下限（对应 quality.EXPECTED_KEY_POINTS 的一半）
GRAPH_MIN_KEY_POINTS = 2

#: LangGraph search 段的原始内容字数下限
GRAPH_MIN_RAW_CHARS = 100


def validate_search_segment(state: dict[str, Any]) -> ValidationResult:
    """校验 ``search`` 节点交给 ``analyze`` 的东西。

    硬错误：``raw_content`` 缺失 / 非 str / 空串、``sources`` 非 list、
    ``collection_mode`` 不是已知模式。

    警告：``raw_content`` 过短、``sources`` 为空、走了 ``degraded`` 降级路径
    （能跑通但产出不可引用，下游要知情）。

    Args:
        state: LangGraph 的 PipelineState（当 dict 用）。

    Returns:
        ``(passed, errors, warnings)``。
    """
    bag = _Collector()

    raw = state.get("raw_content")
    if not isinstance(raw, str):
        bag.error(f"raw_content 类型错误: 期望 str，实际 {type(raw).__name__}")
    elif not raw.strip():
        bag.error("raw_content 为空——采集段没交出任何内容，不能让 analyze 凭空发挥")
    elif len(raw) < GRAPH_MIN_RAW_CHARS:
        bag.warn(f"raw_content 只有 {len(raw)} 字，低于 {GRAPH_MIN_RAW_CHARS} 字")

    sources = state.get("sources")
    if not isinstance(sources, list):
        bag.error(f"sources 类型错误: 期望 list，实际 {type(sources).__name__}")
    else:
        _check_str_list(sources, "sources", bag)
        if not sources:
            bag.warn("sources 为空，产出将无法溯源")

    mode = state.get("collection_mode")
    if mode not in VALID_COLLECTION_MODES:
        bag.error(f"collection_mode 非法: {mode!r}，可选 {sorted(VALID_COLLECTION_MODES)}")
    elif mode == "degraded":
        bag.warn("collection_mode=degraded：真实采集与 LLM 模拟都失败，产出不可引用")

    return bag.result()


def validate_analyze_segment(state: dict[str, Any]) -> ValidationResult:
    """校验 ``analyze`` 节点交给 ``quality_check`` 的东西。

    硬错误：``summary`` 缺失 / 非 str / 空串、``key_points`` 非 list、
    ``key_points`` 元素非 str。

    警告：摘要短于 ``GRAPH_MIN_SUMMARY_CHARS``、要点少于 ``GRAPH_MIN_KEY_POINTS`` 条。
    这两条**故意只是警告**——低质产出正是质量门禁要处理的场景，在门禁之前就
    终止的话，rewrite 回路永远没机会跑。校验节点管「结构对不对」，
    门禁管「内容好不好」，职责不重叠。

    Args:
        state: LangGraph 的 PipelineState（当 dict 用）。

    Returns:
        ``(passed, errors, warnings)``。
    """
    bag = _Collector()

    summary = state.get("summary")
    if not isinstance(summary, str):
        bag.error(f"summary 类型错误: 期望 str，实际 {type(summary).__name__}")
    elif not summary.strip():
        bag.error("summary 为空——analyze 段没有产出，不能静默传给门禁")
    elif _chars(summary) < GRAPH_MIN_SUMMARY_CHARS:
        bag.warn(f"summary 只有 {_chars(summary)} 字，低于 {GRAPH_MIN_SUMMARY_CHARS} 字，"
                 "预计过不了质量门禁")

    key_points = state.get("key_points")
    if not isinstance(key_points, list):
        bag.error(f"key_points 类型错误: 期望 list，实际 {type(key_points).__name__}")
    else:
        good = _check_str_list(key_points, "key_points", bag)
        if len(good) < GRAPH_MIN_KEY_POINTS:
            bag.warn(f"key_points 只有 {len(good)} 条，低于 {GRAPH_MIN_KEY_POINTS} 条")

    return bag.result()


# ---------------------------------------------------------------------------
# 统一入口
# ---------------------------------------------------------------------------

#: kind → 校验函数
VALIDATORS = {
    "collector": validate_collector,
    "analyzer": validate_analyzer,
    "organizer": validate_organizer,
}


def format_result(label: str, result: ValidationResult) -> str:
    """把校验结果渲染成可读文本。

    Args:
        label: 被校验对象的名字。
        result: ``(passed, errors, warnings)``。

    Returns:
        多行文本。
    """
    passed, errors, warnings = result
    lines = [f"{'✅' if passed else '❌'} {label}"]
    for message in errors:
        lines.append(f"   ✗ {message}")
    for message in warnings:
        lines.append(f"   ⚠ {message}")
    if passed and not warnings:
        lines.append("   （无错误、无警告）")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 自测样本集：已知好 / 已知坏
# ---------------------------------------------------------------------------

#: 已知**好**的 collector 样本（15 条，star 降序，无重复）
GOOD_COLLECTOR: dict[str, Any] = {
    "source": "github-trending",
    "skill": "github-trending",
    "collected_at": "2026-08-09T00:00:00Z",
    "items": [
        {
            "name": f"org{i}/repo{i}",
            "url": f"https://github.com/org{i}/repo{i}",
            "summary": f"第 {i} 个项目：做 AI Agent 编排，值得关注的原因是它给出了可复现的基准。",
            "stars": 20000 - i * 500,
            "language": "Python",
            "topics": ["ai", "agent"],
        }
        for i in range(15)
    ],
}

#: 已知**坏**的 collector 样本：缺 url、stars 为负、name 重复、未降序
BAD_COLLECTOR: dict[str, Any] = {
    "source": "github-trending",
    "collected_at": "2026-08-09T00:00:00Z",
    "items": [
        {
            "name": "a/b",
            "summary": "缺了 url 字段的条目。",
            "stars": 100,
            "language": "Python",
            "topics": ["ai"],
        },
        {
            "name": "a/b",
            "url": "not-a-url",
            "summary": "name 与上一条重复，url 也不是 http。",
            "stars": -5,
            "language": "Go",
            "topics": [],
        },
        {
            "name": "c/d",
            "url": "https://github.com/c/d",
            "summary": "短",
            "stars": 900,
            "language": "Rust",
            "topics": ["llm"],
        },
    ],
}

#: 已知**好**的 analyzer 样本：字数达标、亮点 2-3 条、评分有分布
GOOD_ANALYZER: dict[str, Any] = {
    "source": "github-trending",
    "analyzed_at": "2026-08-09T00:05:00Z",
    "trends": ["多 Agent 编排框架集中出现", "推理侧优化从算子下沉到调度"],
    "items": [
        {
            "name": "org0/repo0",
            "summary": "多 Agent 编排框架，用图描述协作拓扑。",
            "highlights": ["支持条件边与回边，运行时决定路由", "checkpoint 可换 SQLite 跨进程恢复"],
            "relevance_score": 9,
            "score_reason": "给出了可复现的对照实验和成本数据。",
            "tags": ["agent", "orchestration"],
        },
        {
            "name": "org1/repo1",
            "summary": "推理引擎，主打 PagedAttention 显存复用。",
            "highlights": ["吞吐较基线提升 2 倍以上", "支持连续批处理"],
            "relevance_score": 7,
            "score_reason": "工程价值明确，但与本项目主题相关性一般。",
            "tags": ["inference"],
        },
        {
            "name": "org2/repo2",
            "summary": "命令行 Agent，做代码库问答。",
            "highlights": ["索引走本地嵌入，不上传源码", "支持增量索引"],
            "relevance_score": 5,
            "score_reason": "同类实现较多，差异化不足。",
            "tags": ["cli", "rag"],
        },
    ],
}

#: 已知**坏**的 analyzer 样本：RUN_REPORT 实际踩到的形态
#: —— 缺 score_reason、summary 超 50 字、highlights 只有 1 条、评分全是 9 分（无区分度）
BAD_ANALYZER: dict[str, Any] = {
    "source": "github-trending",
    "analyzed_at": "2026-08-09T00:05:00Z",
    "trends": [],
    "items": [
        {
            "name": "org0/repo0",
            "summary": "这是一个非常长的摘要，长到已经明显超过了 spec 里写的 50 字上限，"
                       "而且里面并没有比短摘要多出任何具体信息，只是把同一件事换着说法重复了好几遍。",
            "highlights": ["只有一条亮点"],
            "relevance_score": 9,
            "tags": ["a", "b", "c", "d", "e"],
        },
        {
            "name": "org1/repo1",
            "summary": "正常长度的摘要。",
            "highlights": ["亮点一", "亮点二"],
            "relevance_score": 9,
            "score_reason": "好",
            "tags": ["b"],
        },
        {
            "name": "org2/repo2",
            "summary": "正常长度的摘要。",
            "highlights": ["亮点一", "亮点二"],
            "relevance_score": 99,
            "score_reason": "分数越界到了 99。",
            "tags": ["c"],
        },
    ],
}

#: 已知**好**的 organizer 样本（与 GOOD_ANALYZER 一一对应）
GOOD_ORGANIZER: list[dict[str, Any]] = [
    {
        "id": "2026-08-09-github-repo0",
        "title": "org0/repo0",
        "source": "github-trending",
        "source_url": "https://github.com/org0/repo0",
        "collected_at": "2026-08-09T00:00:00Z",
        "summary": "多 Agent 编排框架，用图描述协作拓扑。",
        "analysis": {
            "tech_highlights": ["支持条件边与回边，运行时决定路由", "checkpoint 可换 SQLite 跨进程恢复"],
            "relevance_score": 9,
            "score_reason": "给出了可复现的对照实验和成本数据。",
        },
        "tags": ["agent", "orchestration"],
        "status": "draft",
    },
    {
        "id": "2026-08-09-github-repo1",
        "title": "org1/repo1",
        "source": "github-trending",
        "source_url": "https://github.com/org1/repo1",
        "collected_at": "2026-08-09T00:00:00Z",
        "summary": "推理引擎，主打 PagedAttention 显存复用。",
        "analysis": {
            "tech_highlights": ["吞吐较基线提升 2 倍以上", "支持连续批处理"],
            "relevance_score": 7,
            "score_reason": "工程价值明确，但与本项目主题相关性一般。",
        },
        "tags": ["inference"],
        "status": "draft",
    },
    {
        "id": "2026-08-09-github-repo2",
        "title": "org2/repo2",
        "source": "github-trending",
        "source_url": "https://github.com/org2/repo2",
        "collected_at": "2026-08-09T00:00:00Z",
        "summary": "命令行 Agent，做代码库问答。",
        "analysis": {
            "tech_highlights": ["索引走本地嵌入，不上传源码", "支持增量索引"],
            "relevance_score": 5,
            "score_reason": "同类实现较多，差异化不足。",
        },
        "tags": ["cli", "rag"],
        "status": "draft",
    },
]

#: 上游**带缺口**的 analyzer 样本：items[1] 没有 relevance_score。
#: 这是 `opencode-subagent-v1/RUN_REPORT.md` 实测到的真实形态
#: （`addyosmani/agent-skills` 那条上游就是缺评分的）。
UPSTREAM_WITH_GAP: dict[str, Any] = {
    "source": "github-trending",
    "analyzed_at": "2026-08-09T00:05:00Z",
    "trends": ["多 Agent 编排框架集中出现"],
    "items": [
        {
            "name": "org0/repo0",
            "summary": "多 Agent 编排框架，用图描述协作拓扑。",
            "highlights": ["支持条件边与回边，运行时决定路由", "checkpoint 可换 SQLite 跨进程恢复"],
            "relevance_score": 9,
            "score_reason": "给出了可复现的对照实验和成本数据。",
            "tags": ["agent"],
        },
        {
            "name": "org1/repo1",
            "summary": "推理引擎，主打 PagedAttention 显存复用。",
            "highlights": ["吞吐较基线提升 2 倍以上", "支持连续批处理"],
            "score_reason": "工程价值明确，但与本项目主题相关性一般。",
            "tags": ["inference"],
        },
    ],
}

#: 下游把上游的缺口**自己补上了**且不标记 —— 除了这一处，其余字段全部忠实。
#: 单段校验对它一句话都说不出来：格式完全合法。
FABRICATED_ORGANIZER: list[dict[str, Any]] = [
    {
        "id": "2026-08-09-github-repo0",
        "title": "org0/repo0",
        "source": "github-trending",
        "source_url": "https://github.com/org0/repo0",
        "collected_at": "2026-08-09T00:00:00Z",
        "summary": "多 Agent 编排框架，用图描述协作拓扑。",
        "analysis": {
            "tech_highlights": ["支持条件边与回边，运行时决定路由", "checkpoint 可换 SQLite 跨进程恢复"],
            "relevance_score": 9,
            "score_reason": "给出了可复现的对照实验和成本数据。",
        },
        "tags": ["agent"],
        "status": "draft",
    },
    {
        "id": "2026-08-09-github-repo1",
        "title": "org1/repo1",
        "source": "github-trending",
        "source_url": "https://github.com/org1/repo1",
        "collected_at": "2026-08-09T00:00:00Z",
        "summary": "推理引擎，主打 PagedAttention 显存复用。",
        "analysis": {
            "tech_highlights": ["吞吐较基线提升 2 倍以上", "支持连续批处理"],
            "relevance_score": 8,
            "score_reason": "工程价值明确，但与本项目主题相关性一般。",
        },
        "tags": ["inference"],
        "status": "draft",
    },
]

#: 已知**坏**的 organizer 样本：id 格式错、status 非法、source_url 重复、
#: 以及一条上游根本不存在的「凭空条目」（RUN_REPORT 记录的编造行为）
BAD_ORGANIZER: list[dict[str, Any]] = [
    {
        "id": "repo0",
        "title": "org0/repo0",
        "source": "github-trending",
        "source_url": "https://github.com/org0/repo0",
        "collected_at": "2026-08-09T00:00:00Z",
        "summary": "id 少了日期前缀。",
        "analysis": {
            "tech_highlights": ["亮点一", "亮点二"],
            "relevance_score": 9,
            "score_reason": "理由文本够长可以通过。",
        },
        "tags": ["agent"],
        "status": "pending",
    },
    {
        "id": "2026-08-09-github-repo0",
        "title": "org0/repo0",
        "source": "github-trending",
        "source_url": "https://github.com/org0/repo0",
        "collected_at": "2026-08-09T00:00:00Z",
        "summary": "source_url 与上一条重复。",
        "analysis": {
            "tech_highlights": ["亮点一", "亮点二"],
            "relevance_score": 3,
            "score_reason": "理由文本够长可以通过。",
        },
        "tags": ["agent"],
        "status": "draft",
    },
    {
        "id": "2026-08-09-github-ghostrepo",
        "title": "ghost/repo",
        "source": "github-trending",
        "source_url": "https://github.com/ghost/repo",
        "collected_at": "2026-08-09T00:00:00Z",
        "summary": "上游 analyzer 里根本没有这一条，是下游自己补出来的。",
        "analysis": {
            "tech_highlights": ["编造的亮点一", "编造的亮点二"],
            "relevance_score": 8,
            "score_reason": "编造的理由，格式完全合法。",
        },
        "tags": ["agent"],
        "status": "draft",
    },
]

#: LangGraph 段样本：(标签, state 片段, 期望 passed)
GRAPH_SAMPLES: tuple[tuple[str, str, dict[str, Any], bool], ...] = (
    (
        "search 好样本",
        "search",
        {
            "raw_content": "# 研究主题: AI Agent\n" + "真实采集到的正文内容。" * 20,
            "sources": ["https://example.com/a", "https://example.com/b"],
            "collection_mode": "real_rss",
        },
        True,
    ),
    (
        "search 坏样本(空内容)",
        "search",
        {"raw_content": "", "sources": [], "collection_mode": "real_rss"},
        False,
    ),
    (
        "search 坏样本(模式非法)",
        "search",
        {"raw_content": "内容" * 80, "sources": ["https://a.com"], "collection_mode": "magic"},
        False,
    ),
    (
        "analyze 好样本",
        "analyze",
        {
            "summary": "LangGraph 1.2.9 的条件边把路由决策推迟到运行时，"
                       "实测同一主题下把 3 次调用降到 2 次；对比 V1 的文件传递，"
                       "共享 state 省掉了每步一次 JSON 读写。" * 1,
            "key_points": ["条件边由路由函数返回节点名", "回边指向门禁而不是分析节点"],
        },
        True,
    ),
    (
        "analyze 坏样本(空摘要)",
        "analyze",
        {"summary": "   ", "key_points": ["a", "b"]},
        False,
    ),
    (
        "analyze 坏样本(要点类型错)",
        "analyze",
        {"summary": "足够长的摘要文本，" * 10, "key_points": [1, 2, 3]},
        False,
    ),
    (
        "analyze 边界(低质但结构合法→放行给门禁)",
        "analyze",
        {"summary": "介绍了一些情况。", "key_points": ["有进展"]},
        True,
    ),
)


def _self_test() -> int:
    """跑内置的已知好 / 已知坏样本，验证好的通过、坏的被拦。

    Returns:
        退出码：所有断言符合预期返回 0，否则 1。
    """
    cases: list[tuple[str, ValidationResult, bool]] = [
        ("collector 好样本", validate_collector(GOOD_COLLECTOR), True),
        ("collector 坏样本", validate_collector(BAD_COLLECTOR), False),
        ("analyzer 好样本", validate_analyzer(GOOD_ANALYZER), True),
        ("analyzer 坏样本", validate_analyzer(BAD_ANALYZER), False),
        ("organizer 好样本", validate_organizer(GOOD_ORGANIZER, upstream=GOOD_ANALYZER), True),
        ("organizer 坏样本", validate_organizer(BAD_ORGANIZER, upstream=GOOD_ANALYZER), False),
        ("organizer 编造样本(单段校验)", validate_organizer(FABRICATED_ORGANIZER), True),
        ("organizer 编造样本(跨段校验)",
         validate_organizer(FABRICATED_ORGANIZER, upstream=UPSTREAM_WITH_GAP), False),
    ]
    for label, kind, state, expected in GRAPH_SAMPLES:
        checker = validate_search_segment if kind == "search" else validate_analyze_segment
        cases.append((label, checker(state), expected))

    print("=" * 78)
    print("  validate.py 自测：已知好 / 已知坏样本")
    print("=" * 78)

    failures = 0
    for label, result, expected in cases:
        passed, errors, warnings = result
        verdict = "符合预期" if passed == expected else "❗与预期不符"
        if passed != expected:
            failures += 1
        print(f"\n{format_result(label, result)}")
        print(f"   → 期望 {'通过' if expected else '拦截'}，实际 "
              f"{'通过' if passed else '拦截'}（{len(errors)} 错 / {len(warnings)} 警）— {verdict}")

    print("\n" + "-" * 78)
    print(f"共 {len(cases)} 个样本，{len(cases) - failures} 个符合预期，{failures} 个不符")
    print("=" * 78)
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    """CLI 入口：无参数跑自测，带文件参数校验文件。

    Args:
        argv: 命令行参数，默认取 ``sys.argv[1:]``。

    Returns:
        退出码：全部通过 0，存在硬错误 1。
    """
    parser = argparse.ArgumentParser(description="段间 schema 校验（Wk3 任务 2）")
    parser.add_argument("files", nargs="*", help="要校验的 JSON 文件；不给则跑内置自测")
    parser.add_argument("--kind", choices=sorted(VALIDATORS), default="organizer",
                        help="按哪一段的 schema 校验")
    parser.add_argument("--upstream", help="organizer 校验时的上游 analyzer JSON 路径")
    parser.add_argument("--relaxed", action="store_true", help="用放宽阈值（小批量运行）")
    args = parser.parse_args(argv)

    if not args.files:
        return _self_test()

    config = RELAXED_CONFIG if args.relaxed else DEFAULT_CONFIG
    upstream: dict[str, Any] | None = None
    if args.upstream:
        upstream = json.loads(Path(args.upstream).read_text(encoding="utf-8"))

    failed = 0
    for name in args.files:
        path = Path(name)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"❌ {path}\n   ✗ 读取或解析失败: {exc}")
            failed += 1
            continue

        if args.kind == "organizer":
            result = validate_organizer(data, config, upstream=upstream)
        else:
            result = VALIDATORS[args.kind](data, config)

        print(format_result(str(path), result))
        if not result[0]:
            failed += 1

    print("-" * 78)
    print(f"共 {len(args.files)} 个文件，失败 {failed} 个")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
