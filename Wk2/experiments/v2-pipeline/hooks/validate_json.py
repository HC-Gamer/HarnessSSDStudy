#!/usr/bin/env python3
"""知识条目 JSON 格式校验脚本。

用法::

    python hooks/validate_json.py <json_file> [...]
    python hooks/validate_json.py knowledge/articles/*.json

通过返回 exit 0，任一文件失败返回 exit 1 并打印错误列表与汇总统计。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# 校验规则常量
# ---------------------------------------------------------------------------

#: 必填字段及其期望的 Python 类型
REQUIRED_FIELDS: dict[str, type] = {
    "id": str,
    "title": str,
    "source_url": str,
    "summary": str,
    "tags": list,
    "status": str,
}

#: ID 格式：{source}-{YYYYMMDD}-{NNN}，例如 github-20260317-001
ID_PATTERN = re.compile(r"^[a-z0-9_]+-\d{8}-\d{3}$")

#: URL 格式：http:// 或 https:// 开头
URL_PATTERN = re.compile(r"^https?://\S+$")

#: status 合法取值
VALID_STATUS: frozenset[str] = frozenset({"draft", "review", "published", "archived"})

#: audience 合法取值（可选字段）
VALID_AUDIENCE: frozenset[str] = frozenset({"beginner", "intermediate", "advanced"})

#: 摘要最少字数
MIN_SUMMARY_LENGTH = 20

#: 标签最少个数
MIN_TAG_COUNT = 1

#: score 取值范围
SCORE_MIN = 1
SCORE_MAX = 10


# ---------------------------------------------------------------------------
# 单条目校验
# ---------------------------------------------------------------------------


def validate_required_fields(data: dict) -> list[str]:
    """校验必填字段是否存在且类型正确。

    Args:
        data: 解析后的 JSON 对象。

    Returns:
        错误信息列表，无错误时为空列表。
    """
    errors: list[str] = []
    for field, expected_type in REQUIRED_FIELDS.items():
        if field not in data:
            errors.append(f"缺少必填字段: {field}")
            continue
        value = data[field]
        # bool 是 int 的子类，这里字段无 int 类型需求，直接用 isinstance 即可
        if not isinstance(value, expected_type):
            errors.append(
                f"字段 {field} 类型错误: 期望 {expected_type.__name__}，"
                f"实际 {type(value).__name__}"
            )
    return errors


def validate_id(value: str) -> list[str]:
    """校验 ID 格式 {source}-{YYYYMMDD}-{NNN}。"""
    if not ID_PATTERN.match(value):
        return [f"id 格式错误: {value!r}，应为 {{source}}-{{YYYYMMDD}}-{{NNN}}（如 github-20260317-001）"]
    return []


def validate_status(value: str) -> list[str]:
    """校验 status 是否在合法枚举内。"""
    if value not in VALID_STATUS:
        return [f"status 非法: {value!r}，可选值 {sorted(VALID_STATUS)}"]
    return []


def validate_url(value: str) -> list[str]:
    """校验 source_url 是否为 http(s) 链接。"""
    if not URL_PATTERN.match(value):
        return [f"source_url 格式错误: {value!r}，应以 http:// 或 https:// 开头"]
    return []


def validate_summary(value: str) -> list[str]:
    """校验摘要长度。"""
    length = len(value.strip())
    if length < MIN_SUMMARY_LENGTH:
        return [f"summary 太短: {length} 字，至少需要 {MIN_SUMMARY_LENGTH} 字"]
    return []


def validate_tags(value: list) -> list[str]:
    """校验标签数量与元素类型。"""
    errors: list[str] = []
    if len(value) < MIN_TAG_COUNT:
        errors.append(f"tags 至少需要 {MIN_TAG_COUNT} 个，当前 {len(value)} 个")
    for index, tag in enumerate(value):
        if not isinstance(tag, str):
            errors.append(f"tags[{index}] 类型错误: 期望 str，实际 {type(tag).__name__}")
        elif not tag.strip():
            errors.append(f"tags[{index}] 为空字符串")
    return errors


def validate_optional_fields(data: dict) -> list[str]:
    """校验可选字段 score 与 audience。"""
    errors: list[str] = []

    if "score" in data:
        score = data["score"]
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            errors.append(f"score 类型错误: 期望数字，实际 {type(score).__name__}")
        elif not SCORE_MIN <= score <= SCORE_MAX:
            errors.append(f"score 超出范围: {score}，应在 {SCORE_MIN}-{SCORE_MAX} 之间")

    if "audience" in data:
        audience = data["audience"]
        if not isinstance(audience, str):
            errors.append(f"audience 类型错误: 期望 str，实际 {type(audience).__name__}")
        elif audience not in VALID_AUDIENCE:
            errors.append(f"audience 非法: {audience!r}，可选值 {sorted(VALID_AUDIENCE)}")

    return errors


def validate_entry(data: dict) -> list[str]:
    """校验单个知识条目对象。

    Args:
        data: 解析后的 JSON 对象。

    Returns:
        错误信息列表，无错误时为空列表。
    """
    errors = validate_required_fields(data)

    # 类型正确的字段才继续做内容校验，避免重复报错
    if isinstance(data.get("id"), str):
        errors += validate_id(data["id"])
    if isinstance(data.get("status"), str):
        errors += validate_status(data["status"])
    if isinstance(data.get("source_url"), str):
        errors += validate_url(data["source_url"])
    if isinstance(data.get("summary"), str):
        errors += validate_summary(data["summary"])
    if isinstance(data.get("tags"), list):
        errors += validate_tags(data["tags"])
    if isinstance(data.get("title"), str) and not data["title"].strip():
        errors.append("title 为空字符串")

    errors += validate_optional_fields(data)
    return errors


# ---------------------------------------------------------------------------
# 文件级校验
# ---------------------------------------------------------------------------


def validate_file(path: Path) -> list[str]:
    """校验单个 JSON 文件。

    支持顶层为单个对象，或对象数组（批量条目）。

    Args:
        path: JSON 文件路径。

    Returns:
        错误信息列表，无错误时为空列表。
    """
    if not path.exists():
        return ["文件不存在"]
    if not path.is_file():
        return ["不是普通文件"]

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"读取失败: {exc}"]
    except UnicodeDecodeError as exc:
        return [f"编码错误（需要 UTF-8）: {exc}"]

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return [f"JSON 解析失败: 第 {exc.lineno} 行第 {exc.colno} 列 - {exc.msg}"]

    if isinstance(data, dict):
        return validate_entry(data)

    if isinstance(data, list):
        if not data:
            return ["JSON 数组为空"]
        errors: list[str] = []
        for index, item in enumerate(data):
            if not isinstance(item, dict):
                errors.append(f"[{index}] 类型错误: 期望对象，实际 {type(item).__name__}")
                continue
            errors += [f"[{index}] {msg}" for msg in validate_entry(item)]
        return errors

    return [f"JSON 顶层类型错误: 期望对象或数组，实际 {type(data).__name__}"]


def expand_paths(patterns: list[str]) -> list[Path]:
    """展开命令行参数中的路径与通配符。

    Shell 通常已展开 ``*.json``；这里额外处理未展开的情况（如引号包裹）。

    Args:
        patterns: 原始命令行参数。

    Returns:
        去重并排序后的路径列表。
    """
    paths: list[Path] = []
    for pattern in patterns:
        if any(ch in pattern for ch in "*?[") :
            base = Path(pattern)
            root = base.parent if str(base.parent) != "" else Path(".")
            matched = sorted(root.glob(base.name))
            if matched:
                paths.extend(matched)
            else:
                paths.append(base)
        else:
            paths.append(Path(pattern))

    seen: set[Path] = set()
    unique: list[Path] = []
    for path in paths:
        if path not in seen:
            seen.add(path)
            unique.append(path)
    return unique


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


def main(argv: list[str]) -> int:
    """脚本入口。

    Args:
        argv: 不含程序名的命令行参数。

    Returns:
        进程退出码：全部通过 0，存在失败 1。
    """
    if not argv:
        print("用法: python hooks/validate_json.py <json_file> [...]", file=sys.stderr)
        return 1

    paths = expand_paths(argv)
    passed: list[Path] = []
    failed: list[tuple[Path, list[str]]] = []

    for path in paths:
        errors = validate_file(path)
        if errors:
            failed.append((path, errors))
        else:
            passed.append(path)

    print("=" * 60)
    print("JSON 格式校验")
    print("=" * 60)

    for path in passed:
        print(f"✅ {path}")

    for path, errors in failed:
        print(f"❌ {path}")
        for error in errors:
            print(f"   - {error}")

    total = len(paths)
    error_count = sum(len(errors) for _, errors in failed)

    print("-" * 60)
    print(f"共 {total} 个文件：通过 {len(passed)}，失败 {len(failed)}，错误 {error_count} 条")
    print("=" * 60)

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
