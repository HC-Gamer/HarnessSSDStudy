"""Collector Agent —— 采集节点（V3 流水线节点 ②，课件 10-2 + 12-4 接入点 ④）。

三级采集策略，任何一级失败都自动降级，保证图一定能跑完：

1. **GitHub Search API** —— 课件默认路径，按 star 排序取 AI/Agent 相关仓库；
2. **RSS/Atom** —— 复用 V2 的 ``pipeline/rss_collector.py``（不另写一份采集器）；
3. **离线种子** —— 全断网时用内置样本，``collection_mode`` 记为 ``degraded``，
   下游据此知道产出不可引用。

**安全接入（12-4 接入点 ④）**：GitHub description / RSS title 都是外部输入，
直接拼进 LLM prompt 就是 OWASP LLM01 Prompt 注入。所以在**离开 collect 之前**
对每条 source 的 ``title`` / ``description`` 调用
:func:`~tests.security.sanitize_input` 洗一遍 —— 越早洗越省 token。
"""

from __future__ import annotations

import json
import logging
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests.security import sanitize_input  # noqa: E402
from workflows.state import KBState  # noqa: E402

logger = logging.getLogger(__name__)

#: GitHub Search API：AI + Agent 主题、按 star 降序
GITHUB_SEARCH_URL = "https://api.github.com/search/repositories"
GITHUB_QUERY = "topic:ai topic:agent"
GITHUB_TIMEOUT = 15.0

#: 默认每源采集条数（plan.per_source_limit 缺失时的兜底）
DEFAULT_PER_SOURCE_LIMIT = 10

#: 采集模式取值，写进每条 source 供 validate.py 与报告使用
COLLECTION_MODES = ("github", "rss", "degraded")

#: 全断网时的离线种子（只用于让图跑完，不产出可引用内容）
OFFLINE_SEEDS: list[dict[str, Any]] = [
    {
        "title": "langchain-ai/langgraph",
        "url": "https://github.com/langchain-ai/langgraph",
        "description": "Build resilient language agents as graphs: StateGraph, conditional edges, checkpointing.",
        "stars": 12000,
    },
    {
        "title": "microsoft/autogen",
        "url": "https://github.com/microsoft/autogen",
        "description": "A programming framework for agentic AI with multi-agent conversation patterns.",
        "stars": 34000,
    },
    {
        "title": "crewAIInc/crewAI",
        "url": "https://github.com/crewAIInc/crewAI",
        "description": "Framework for orchestrating role-playing autonomous AI agents with task delegation.",
        "stars": 21000,
    },
]


def _now_iso() -> str:
    """当前 UTC 时间的 ISO 字符串。"""
    return datetime.now(timezone.utc).isoformat()


def _fetch_github(limit: int) -> list[dict[str, Any]]:
    """调用 GitHub Search API 取仓库列表。

    Args:
        limit: 取多少条。

    Returns:
        原始 source 列表；失败时抛异常由调用方降级。

    Raises:
        urllib.error.URLError: 网络不可达。
        ValueError: 响应不是预期的 JSON 结构。
    """
    params = urllib.parse.urlencode(
        {"q": GITHUB_QUERY, "sort": "stars", "order": "desc", "per_page": limit}
    )
    url = f"{GITHUB_SEARCH_URL}?{params}"
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "ai-knowledge-base-v3/1.0",
    }
    token = os.getenv("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"token {token}"

    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=GITHUB_TIMEOUT) as response:
        payload = json.loads(response.read().decode("utf-8"))

    items = payload.get("items")
    if not isinstance(items, list):
        raise ValueError(f"GitHub 响应缺少 items 字段: {list(payload)[:5]}")

    return [
        {
            "source": "github",
            "title": repo.get("full_name", ""),
            "url": repo.get("html_url", ""),
            "description": repo.get("description") or "",
            "stars": int(repo.get("stargazers_count", 0) or 0),
            "language": repo.get("language") or "",
            "collection_mode": "github",
            "collected_at": _now_iso(),
        }
        for repo in items[:limit]
    ]


def _fetch_rss(limit: int) -> list[dict[str, Any]]:
    """降级路径：复用 V2 的 RSS 采集器。

    Args:
        limit: 取多少条。

    Returns:
        原始 source 列表。
    """
    from pipeline import rss_collector  # 延迟导入：无网络时不必付出 httpx 初始化代价

    per_source = max(1, limit // 3)
    entries = rss_collector.collect(max_sources=3, per_source=per_source)
    return [
        {
            "source": entry.source,
            "title": entry.title,
            "url": entry.url,
            "description": entry.summary,
            "stars": 0,
            "language": "",
            "collection_mode": "rss",
            "collected_at": _now_iso(),
        }
        for entry in entries[:limit]
    ]


def _offline_seeds(limit: int) -> list[dict[str, Any]]:
    """最后兜底：内置种子数据。

    Args:
        limit: 取多少条。

    Returns:
        标记为 ``degraded`` 的 source 列表。
    """
    seeds = (OFFLINE_SEEDS * ((limit // len(OFFLINE_SEEDS)) + 1))[:limit]
    return [
        {
            **seed,
            "source": "offline-seed",
            "language": "",
            "collection_mode": "degraded",
            "collected_at": _now_iso(),
        }
        for seed in seeds
    ]


def _sanitize_sources(sources: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """★ 12-4 接入点 ④ —— 对每条 source 的文本字段做输入清洗。

    Args:
        sources: 原始采集结果。

    Returns:
        ``(cleaned_sources, total_warnings)``。
    """
    cleaned_sources: list[dict[str, Any]] = []
    total_warnings = 0

    for item in sources:
        record = dict(item)
        hits: list[str] = []
        for field in ("title", "description"):
            value = record.get(field)
            if isinstance(value, str):
                cleaned, warnings = sanitize_input(value)
                record[field] = cleaned
                hits.extend(warnings)
        if hits:
            total_warnings += len(hits)
            record["security_warnings"] = hits
            logger.warning(
                "[Security] %s 检出注入模式：%s", record.get("url", "?"), hits
            )
        cleaned_sources.append(record)

    return cleaned_sources, total_warnings


def collect_node(state: KBState) -> dict:
    """LangGraph 节点 ②：采集原始数据并做入口安全清洗。

    Args:
        state: 当前 KBState，读 ``plan.per_source_limit``。

    Returns:
        ``{"sources": [...]}`` 部分状态更新。
    """
    plan = state.get("plan", {}) or {}
    limit = int(plan.get("per_source_limit", DEFAULT_PER_SOURCE_LIMIT))

    sources: list[dict[str, Any]] = []
    for name, fetcher in (("github", _fetch_github), ("rss", _fetch_rss)):
        try:
            sources = fetcher(limit)
        except Exception as exc:  # noqa: BLE001 - 采集层任何异常都应降级而非中断
            logger.warning("[Collector] %s 采集失败，降级：%s", name, exc)
            continue
        if sources:
            break
        logger.warning("[Collector] %s 采集 0 条，继续降级", name)

    if not sources:
        logger.error("[Collector] 全部采集路径失败，启用离线种子（产出不可引用）")
        sources = _offline_seeds(limit)

    cleaned_sources, total_warnings = _sanitize_sources(sources)
    if total_warnings:
        logger.warning("[Security] collect 阶段共拦截 %d 处可疑输入", total_warnings)

    mode = cleaned_sources[0].get("collection_mode", "degraded") if cleaned_sources else "degraded"
    logger.info(
        "[Collector] 采集到 %d 条原始数据（模式：%s · 限额 %d）",
        len(cleaned_sources), mode, limit,
    )
    return {"sources": cleaned_sources}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    from workflows.state import make_initial_state

    demo_state = make_initial_state(plan={"per_source_limit": 5})
    result = collect_node(demo_state)
    for source in result["sources"]:
        print(f"  ⭐{source['stars']:>6}  {source['title']}  —  {source['description'][:60]}")
