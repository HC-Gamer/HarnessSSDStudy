#!/usr/bin/env python3
"""知识库 MCP Server（零依赖，stdio JSON-RPC 2.0）。

把 ``knowledge/articles/`` 下的知识条目暴露成三个 MCP 工具：

===================  ==================================================
工具                  说明
===================  ==================================================
search_articles      在 title / tags / summary 上做大小写不敏感模糊搜索
get_article          按 id 返回条目完整 JSON
knowledge_stats      条目总数、日期范围、标签分布
===================  ==================================================

只用标准库实现协议本身（stdio + 逐行 JSON-RPC），不需要 mcp / fastmcp 等包。

用法::

    python mcp_knowledge_server.py
    python mcp_knowledge_server.py --articles-dir knowledge/articles

在 MCP 客户端中的配置示例::

    {
      "mcpServers": {
        "knowledge": {
          "command": "python3",
          "args": ["/abs/path/to/mcp_knowledge_server.py"]
        }
      }
    }

条目格式与 pipeline/pipeline.py 的 ``Article`` 及 hooks/validate_json.py 的
校验规则一致：id / title / source_url / summary / tags / status / score /
collected_at / source / audience / analyzed_by / extra。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_ARTICLES_DIR = PROJECT_ROOT / "knowledge" / "articles"

SERVER_NAME = "knowledge"
SERVER_VERSION = "1.0.0"

#: 本 Server 实现的协议版本；客户端请求其他版本时按此版本回应
PROTOCOL_VERSION = "2024-11-05"

#: JSON-RPC 2.0 标准错误码
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

#: search_articles 默认/最大返回条数
DEFAULT_SEARCH_LIMIT = 10
MAX_SEARCH_LIMIT = 100

#: 搜索命中权重：标题 > 标签 > 摘要
WEIGHT_TITLE = 3
WEIGHT_TAG = 2
WEIGHT_SUMMARY = 1

#: knowledge_stats 返回的标签分布最多列出多少个
TOP_TAGS = 20


# ---------------------------------------------------------------------------
# 数据加载
# ---------------------------------------------------------------------------


@dataclass
class Store:
    """内存中的知识库快照。

    Attributes:
        articles_dir: 文章目录。
        articles: 按 id 索引的条目。
        load_errors: 加载失败的文件及原因。
    """

    articles_dir: Path
    articles: dict[str, dict[str, Any]] = field(default_factory=dict)
    load_errors: list[tuple[str, str]] = field(default_factory=list)

    def load(self) -> None:
        """扫描 articles_dir 下全部 .json 并载入内存。

        支持文件顶层为单个对象或对象数组（与 hooks 的处理方式一致）。
        单个文件损坏不影响其他文件，原因记入 ``load_errors``。
        """
        self.articles.clear()
        self.load_errors.clear()

        if not self.articles_dir.is_dir():
            self.load_errors.append((str(self.articles_dir), "目录不存在"))
            return

        for path in sorted(self.articles_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                self.load_errors.append((path.name, f"JSON 解析失败: 第 {exc.lineno} 行 - {exc.msg}"))
                continue
            except (OSError, UnicodeDecodeError) as exc:
                self.load_errors.append((path.name, f"读取失败: {exc}"))
                continue

            entries = data if isinstance(data, list) else [data]
            for index, entry in enumerate(entries):
                if not isinstance(entry, dict):
                    self.load_errors.append((path.name, f"[{index}] 不是对象，已跳过"))
                    continue
                article_id = entry.get("id")
                if not isinstance(article_id, str) or not article_id.strip():
                    self.load_errors.append((path.name, f"[{index}] 缺少合法 id，已跳过"))
                    continue
                # 同 id 后加载的覆盖先加载的；文件名有序，行为可预期
                self.articles[article_id] = entry


def _text_of(article: dict[str, Any], key: str) -> str:
    """取字段的字符串形式，非字符串或缺失时返回空串。

    Args:
        article: 知识条目。
        key: 字段名。

    Returns:
        小写化前的原始字符串。
    """
    value = article.get(key)
    return value if isinstance(value, str) else ""


def _tags_of(article: dict[str, Any]) -> list[str]:
    """取标签列表，过滤掉非字符串元素。

    Args:
        article: 知识条目。

    Returns:
        标签字符串列表。
    """
    tags = article.get("tags")
    if not isinstance(tags, list):
        return []
    return [t for t in tags if isinstance(t, str) and t.strip()]


def _brief(article: dict[str, Any]) -> dict[str, Any]:
    """把条目裁剪成搜索结果用的摘要视图。

    Args:
        article: 完整条目。

    Returns:
        只含常用字段的字典。
    """
    return {
        "id": article.get("id"),
        "title": article.get("title"),
        "source_url": article.get("source_url"),
        "summary": _text_of(article, "summary")[:200],
        "tags": _tags_of(article),
        "score": article.get("score"),
        "source": article.get("source"),
        "status": article.get("status"),
        "collected_at": article.get("collected_at"),
    }


# ---------------------------------------------------------------------------
# 三个工具的实现
# ---------------------------------------------------------------------------


def tool_search_articles(store: Store, arguments: dict[str, Any]) -> dict[str, Any]:
    """在 title / tags / summary 上做大小写不敏感的子串搜索。

    query 按空白拆成多个关键词，条目需命中**全部**关键词才算匹配（AND 语义）。
    命中位置带权重：标题 3 分、标签 2 分、摘要 1 分，按总分降序返回。

    Args:
        store: 知识库快照。
        arguments: 工具入参，需含 ``query``，可选 ``limit``。

    Returns:
        含 query / total / results 的结果字典。

    Raises:
        ValueError: query 缺失或为空。
    """
    query = arguments.get("query")
    if not isinstance(query, str) or not query.strip():
        raise ValueError("参数 query 必填，且不能为空字符串")

    raw_limit = arguments.get("limit", DEFAULT_SEARCH_LIMIT)
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError):
        limit = DEFAULT_SEARCH_LIMIT
    limit = max(1, min(limit, MAX_SEARCH_LIMIT))

    keywords = [k for k in query.lower().split() if k]
    scored: list[tuple[int, dict[str, Any]]] = []

    for article in store.articles.values():
        title = _text_of(article, "title").lower()
        summary = _text_of(article, "summary").lower()
        tags = " ".join(_tags_of(article)).lower()

        total = 0
        for keyword in keywords:
            hit = 0
            if keyword in title:
                hit += WEIGHT_TITLE
            if keyword in tags:
                hit += WEIGHT_TAG
            if keyword in summary:
                hit += WEIGHT_SUMMARY
            if hit == 0:
                total = 0
                break
            total += hit

        if total > 0:
            scored.append((total, article))

    # 同分时按 id 排序，保证结果稳定可复现
    scored.sort(key=lambda pair: (-pair[0], str(pair[1].get("id", ""))))

    return {
        "query": query,
        "total": len(scored),
        "returned": min(len(scored), limit),
        "results": [
            {**_brief(article), "relevance": score} for score, article in scored[:limit]
        ],
    }


def tool_get_article(store: Store, arguments: dict[str, Any]) -> dict[str, Any]:
    """按 id 返回条目的完整 JSON。

    Args:
        store: 知识库快照。
        arguments: 工具入参，需含 ``id``。

    Returns:
        条目完整字典。

    Raises:
        ValueError: id 缺失，或库中不存在该 id。
    """
    article_id = arguments.get("id")
    if not isinstance(article_id, str) or not article_id.strip():
        raise ValueError("参数 id 必填，且不能为空字符串")

    article = store.articles.get(article_id.strip())
    if article is None:
        similar = [
            known for known in store.articles if article_id.strip().lower() in known.lower()
        ][:5]
        hint = f"，相近的 id: {', '.join(similar)}" if similar else ""
        raise ValueError(f"未找到 id 为 {article_id!r} 的条目（共 {len(store.articles)} 条）{hint}")

    return article


def tool_knowledge_stats(store: Store, arguments: dict[str, Any]) -> dict[str, Any]:
    """统计条目总数、采集时间范围与标签分布。

    Args:
        store: 知识库快照。
        arguments: 工具入参（本工具无参数，保留形参以统一调用签名）。

    Returns:
        含 count / date_range / tags / sources / statuses / score 的统计字典。
    """
    articles = list(store.articles.values())

    timestamps = sorted(
        t for t in (_text_of(a, "collected_at") for a in articles) if t
    )
    tag_counter: Counter[str] = Counter()
    source_counter: Counter[str] = Counter()
    status_counter: Counter[str] = Counter()
    scores: list[float] = []

    for article in articles:
        tag_counter.update(t.strip().lower() for t in _tags_of(article))
        source_counter[_text_of(article, "source") or "unknown"] += 1
        status_counter[_text_of(article, "status") or "unknown"] += 1
        score = article.get("score")
        if not isinstance(score, bool) and isinstance(score, (int, float)):
            scores.append(float(score))

    return {
        "count": len(articles),
        "articles_dir": str(store.articles_dir),
        "date_range": {
            "earliest": timestamps[0] if timestamps else None,
            "latest": timestamps[-1] if timestamps else None,
            "with_timestamp": len(timestamps),
        },
        "tags": {
            "distinct": len(tag_counter),
            "distribution": [
                {"tag": tag, "count": count} for tag, count in tag_counter.most_common(TOP_TAGS)
            ],
        },
        "sources": [
            {"source": name, "count": count} for name, count in source_counter.most_common()
        ],
        "statuses": [
            {"status": name, "count": count} for name, count in status_counter.most_common()
        ],
        "score": {
            "average": round(sum(scores) / len(scores), 2) if scores else None,
            "min": min(scores) if scores else None,
            "max": max(scores) if scores else None,
        },
        "load_errors": [{"file": name, "reason": reason} for name, reason in store.load_errors],
    }


#: 工具名 → (实现函数, MCP 工具声明)
TOOLS: dict[str, tuple[Any, dict[str, Any]]] = {
    "search_articles": (
        tool_search_articles,
        {
            "name": "search_articles",
            "description": (
                "在知识库中模糊搜索。对 title / tags / summary 做大小写不敏感的子串匹配，"
                "多个关键词以空格分隔且需全部命中。返回按相关度降序的条目摘要。"
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索关键词，空格分隔多个词（AND 语义）",
                    },
                    "limit": {
                        "type": "integer",
                        "description": f"最多返回条数，默认 {DEFAULT_SEARCH_LIMIT}，上限 {MAX_SEARCH_LIMIT}",
                        "minimum": 1,
                        "maximum": MAX_SEARCH_LIMIT,
                    },
                },
                "required": ["query"],
            },
        },
    ),
    "get_article": (
        tool_get_article,
        {
            "name": "get_article",
            "description": "按条目 ID（如 github-20260727-001）返回该条目的完整 JSON。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "id": {
                        "type": "string",
                        "description": "条目 ID，格式 {source}-{YYYYMMDD}-{NNN}",
                    },
                },
                "required": ["id"],
            },
        },
    ),
    "knowledge_stats": (
        tool_knowledge_stats,
        {
            "name": "knowledge_stats",
            "description": "返回知识库统计：条目总数、采集时间范围、标签分布、来源与评分概况。",
            "inputSchema": {"type": "object", "properties": {}},
        },
    ),
}


# ---------------------------------------------------------------------------
# JSON-RPC 2.0 / MCP 协议层
# ---------------------------------------------------------------------------


def _result(request_id: Any, payload: dict[str, Any]) -> dict[str, Any]:
    """构造 JSON-RPC 成功响应。"""
    return {"jsonrpc": "2.0", "id": request_id, "result": payload}


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    """构造 JSON-RPC 错误响应。"""
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def handle_initialize(store: Store, params: dict[str, Any]) -> dict[str, Any]:
    """处理 initialize：声明协议版本与能力。

    Args:
        store: 知识库快照（用于在 instructions 里报告已加载条数）。
        params: 客户端参数，可能含 ``protocolVersion``。

    Returns:
        initialize 的 result 载荷。
    """
    requested = params.get("protocolVersion")
    version = requested if isinstance(requested, str) and requested else PROTOCOL_VERSION

    return {
        "protocolVersion": version,
        "capabilities": {"tools": {"listChanged": False}},
        "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        "instructions": (
            f"AI 技术知识库，已加载 {len(store.articles)} 条条目（{store.articles_dir}）。"
            "用 search_articles 检索、get_article 取全文、knowledge_stats 看整体分布。"
        ),
    }


def handle_tools_call(store: Store, params: dict[str, Any]) -> dict[str, Any]:
    """处理 tools/call：分发到具体工具并包装成 MCP content 结构。

    工具自身的入参错误通过 ``isError: true`` 返回给模型，而不是 JSON-RPC
    error —— 这样客户端能把错误信息喂回模型让它自行纠正。

    Args:
        store: 知识库快照。
        params: 含 ``name`` 与 ``arguments``。

    Returns:
        tools/call 的 result 载荷。

    Raises:
        KeyError: 工具名不存在。
    """
    name = params.get("name")
    arguments = params.get("arguments")
    if not isinstance(arguments, dict):
        arguments = {}

    if name not in TOOLS:
        raise KeyError(f"未知工具: {name!r}，可用工具: {', '.join(TOOLS)}")

    func, _ = TOOLS[name]
    try:
        payload = func(store, arguments)
    except ValueError as exc:
        return {"content": [{"type": "text", "text": f"错误: {exc}"}], "isError": True}

    return {
        "content": [
            {"type": "text", "text": json.dumps(payload, ensure_ascii=False, indent=2)}
        ],
        "isError": False,
    }


def dispatch(store: Store, message: dict[str, Any]) -> dict[str, Any] | None:
    """路由单条 JSON-RPC 请求。

    Args:
        store: 知识库快照。
        message: 已解析的请求对象。

    Returns:
        响应对象；通知（无 id）返回 None 表示不回包。
    """
    method = message.get("method")
    request_id = message.get("id")
    params = message.get("params")
    if not isinstance(params, dict):
        params = {}

    # 通知（notification）没有 id，按规范不能有响应
    is_notification = "id" not in message

    if not isinstance(method, str):
        return None if is_notification else _error(request_id, INVALID_REQUEST, "缺少 method 字段")

    if method == "initialize":
        return _result(request_id, handle_initialize(store, params))

    if method in ("notifications/initialized", "initialized"):
        return None

    if method == "ping":
        return _result(request_id, {})

    if method == "tools/list":
        return _result(request_id, {"tools": [decl for _, decl in TOOLS.values()]})

    if method == "tools/call":
        try:
            return _result(request_id, handle_tools_call(store, params))
        except KeyError as exc:
            return _error(request_id, INVALID_PARAMS, str(exc.args[0]))

    if is_notification:
        return None
    return _error(request_id, METHOD_NOT_FOUND, f"不支持的方法: {method}")


def serve(store: Store, stdin: Any = None, stdout: Any = None) -> int:
    """stdio 主循环：逐行读 JSON-RPC 请求，逐行写响应。

    Args:
        store: 知识库快照。
        stdin: 输入流，默认 sys.stdin。
        stdout: 输出流，默认 sys.stdout。

    Returns:
        进程退出码，正常结束为 0。
    """
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout

    def write(response: dict[str, Any]) -> None:
        stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
        stdout.flush()

    for line in stdin:
        line = line.strip()
        if not line:
            continue

        try:
            message = json.loads(line)
        except json.JSONDecodeError as exc:
            write(_error(None, PARSE_ERROR, f"JSON 解析失败: {exc.msg}"))
            continue

        if not isinstance(message, dict):
            write(_error(None, INVALID_REQUEST, "请求顶层必须是对象"))
            continue

        try:
            response = dispatch(store, message)
        except Exception as exc:  # 兜底：任何内部异常都不该终止 Server
            write(_error(message.get("id"), INTERNAL_ERROR, f"{type(exc).__name__}: {exc}"))
            continue

        if response is not None:
            write(response)

    return 0


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """构造命令行解析器。"""
    parser = argparse.ArgumentParser(
        description="知识库 MCP Server（stdio JSON-RPC 2.0，零第三方依赖）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--articles-dir",
        type=Path,
        default=DEFAULT_ARTICLES_DIR,
        help="知识条目目录",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """脚本入口。

    Args:
        argv: 不含程序名的命令行参数，None 时读 sys.argv。

    Returns:
        进程退出码。
    """
    args = build_parser().parse_args(argv)

    store = Store(articles_dir=args.articles_dir.expanduser().resolve())
    store.load()

    # stdout 是协议通道，任何日志只能走 stderr
    print(
        f"[{SERVER_NAME}] 已加载 {len(store.articles)} 条条目，来源 {store.articles_dir}",
        file=sys.stderr,
    )
    for name, reason in store.load_errors:
        print(f"[{SERVER_NAME}] 跳过 {name}: {reason}", file=sys.stderr)

    try:
        return serve(store)
    except (KeyboardInterrupt, BrokenPipeError):
        return 0


if __name__ == "__main__":
    sys.exit(main())
