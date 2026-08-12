"""Organizer Agent —— 整理入库节点（V3 流水线节点 ⑥，课件 11-2 + 12-4 接入点 ⑤）。

正常终点。做四件事：

1. **过滤** —— 丢掉 ``relevance_score`` 低于 ``plan.relevance_threshold`` 的条目；
2. **去重** —— 按 URL 严格去重；
3. **PII 掩码（12-4 接入点 ⑤）** —— 写盘前对 ``title`` / ``summary`` /
   ``key_insight`` 调 :func:`~tests.security.filter_output`；
4. **落盘** —— 写 ``knowledge/articles/<id>.json`` 并更新 ``index.json``。

**为什么掩码挂在 organize 而不是中间节点**：organize 的下一步就是写盘。
LLM 输出永远不可信 —— 即便 prompt 干净，模型也可能「联想」出训练数据里见过的
真实邮箱。一旦落进 ``knowledge/articles/`` 再推到公开仓，就是永久泄露。
所以掩码必须是**写盘前最后一道**。中间节点（analyze / review / revise）
不洗，让它们专心做业务，横切关注集中在两端。
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests.security import filter_output  # noqa: E402
from workflows.state import KBState  # noqa: E402

logger = logging.getLogger(__name__)

#: 知识库落盘目录
ARTICLES_DIR = PROJECT_ROOT / "knowledge" / "articles"

#: 索引文件（Wk4 的 Bot / Skill / formatter 的唯一输入）
INDEX_PATH = ARTICLES_DIR / "index.json"

#: plan.relevance_threshold 缺失时的兜底阈值
DEFAULT_RELEVANCE_THRESHOLD = 0.5

#: 需要做 PII 掩码的文本字段
PII_SCAN_FIELDS = ("title", "summary", "key_insight")

#: 条目状态：入库即 draft，人工/下游确认后才 published（AGENTS.md 红线：published 前必须审核）
DEFAULT_STATUS = "draft"


def _slug(source: str) -> str:
    """把来源名收敛成 id 里可用的短标识。

    Args:
        source: 原始来源名。

    Returns:
        小写、仅含字母数字与连字符的短标识。

    Examples:
        >>> _slug("GitHub Trending")
        'github-trending'
        >>> _slug("")
        'unknown'
    """
    cleaned = "".join(ch if ch.isalnum() else "-" for ch in str(source).lower())
    cleaned = "-".join(part for part in cleaned.split("-") if part)
    return cleaned or "unknown"


def _to_knowledge_entry(item: dict, index: int, today: str) -> dict[str, Any]:
    """把一条 analysis 转成 AGENTS.md 定义的知识条目 schema。

    Args:
        item: analyses 里的一条。
        index: 当天序号，从 1 开始。
        today: ``YYYYMMDD`` 日期串。

    Returns:
        知识条目字典。
    """
    source = _slug(item.get("source", "unknown"))
    now = datetime.now(timezone.utc).isoformat()
    tags = [str(t) for t in (item.get("tags") or [])]

    return {
        "id": f"{source}-{today}-{index:03d}",
        "title": item.get("title", ""),
        "source": source,
        "source_url": item.get("url", ""),
        "summary": item.get("summary", ""),
        "key_insight": item.get("key_insight", ""),
        "tags": tags,
        "keywords": tags[:3],
        "category": item.get("category", "industry"),
        "relevance_score": item.get("relevance_score", 0.0),
        "status": DEFAULT_STATUS,
        "fetched_at": item.get("collected_at", now),
        "analyzed_at": now,
        "published_at": None,
        "metadata": {
            "stars": item.get("stars", 0),
            "language": item.get("language", ""),
            "author": (item.get("title", "") or "/").split("/")[0],
            "upvotes": item.get("upvotes", 0),
            "comments": item.get("comments", 0),
            "collection_mode": item.get("collection_mode", ""),
        },
    }


def _mask_pii(articles: list[dict]) -> tuple[list[dict], int]:
    """★ 12-4 接入点 ⑤ —— 写盘前对每条 article 做 PII 掩码。

    Args:
        articles: 待落盘的知识条目。

    Returns:
        ``(masked_articles, total_pii)``。
    """
    masked: list[dict] = []
    total_pii = 0

    for article in articles:
        record = dict(article)
        for field in PII_SCAN_FIELDS:
            value = record.get(field)
            if isinstance(value, str) and value:
                filtered, detections = filter_output(value, mask=True)
                record[field] = filtered
                if detections:
                    total_pii += len(detections)
                    logger.warning(
                        "[Security] %s %s 掩码 PII：%s", record.get("id", "?"), field, detections
                    )
        masked.append(record)

    return masked, total_pii


def _write_articles(articles: list[dict]) -> int:
    """把条目写入 ``knowledge/articles/`` 并更新索引。

    Args:
        articles: 已掩码的知识条目。

    Returns:
        实际写盘的条目数。
    """
    ARTICLES_DIR.mkdir(parents=True, exist_ok=True)

    for article in articles:
        target = ARTICLES_DIR / f"{article['id']}.json"
        with open(target, "w", encoding="utf-8") as handle:
            json.dump(article, handle, ensure_ascii=False, indent=2)

    index: list[dict] = []
    if INDEX_PATH.exists():
        try:
            index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.warning("[Organizer] index.json 损坏，重建索引")
            index = []

    by_id = {entry.get("id"): entry for entry in index if isinstance(entry, dict)}
    for article in articles:
        by_id[article["id"]] = {
            "id": article["id"],
            "title": article["title"],
            "category": article["category"],
            "tags": article["tags"],
            "relevance_score": article["relevance_score"],
            "source_url": article["source_url"],
            "collected_at": article["fetched_at"],
            "status": article["status"],
        }

    with open(INDEX_PATH, "w", encoding="utf-8") as handle:
        json.dump(list(by_id.values()), handle, ensure_ascii=False, indent=2)

    return len(articles)


def organize_node(state: KBState) -> dict:
    """LangGraph 节点 ⑥：过滤 + 去重 + PII 掩码 + 落盘。

    Args:
        state: 当前 KBState，读 ``analyses`` 与 ``plan.relevance_threshold``。

    Returns:
        ``{"articles": [...]}`` 部分状态更新。
    """
    analyses = state.get("analyses", []) or []
    plan = state.get("plan", {}) or {}
    threshold = float(plan.get("relevance_threshold", DEFAULT_RELEVANCE_THRESHOLD))

    qualified = [
        item for item in analyses
        if float(item.get("relevance_score", 0) or 0) >= threshold
        and not item.get("analysis_failed")
    ]
    dropped = len(analyses) - len(qualified)

    seen: set[str] = set()
    unique: list[dict] = []
    for item in qualified:
        url = item.get("url", "")
        if url and url in seen:
            continue
        if url:
            seen.add(url)
        unique.append(item)

    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    articles = [_to_knowledge_entry(item, i, today) for i, item in enumerate(unique, start=1)]

    articles, total_pii = _mask_pii(articles)
    if total_pii:
        logger.warning("[Security] organize 阶段共掩码 %d 处 PII", total_pii)

    logger.info(
        "[Organizer] 整理出 %d 条知识条目（阈值 %.1f 过滤掉 %d 条 · 去重 %d 条）",
        len(articles), threshold, dropped, len(qualified) - len(unique),
    )

    written = _write_articles(articles) if articles else 0
    logger.info("[Organizer] 已写入 %d 篇到磁盘（%s）", written, ARTICLES_DIR)

    return {"articles": articles}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    from workflows.state import make_initial_state

    demo = make_initial_state(
        plan={"relevance_threshold": 0.5},
        analyses=[
            {
                "source": "github", "title": "demo/repo", "url": "https://github.com/demo/repo",
                "summary": "联系作者 13812345678 或 author@example.com 获取完整代码",
                "key_insight": "自测条目", "tags": ["agent"], "category": "agent",
                "relevance_score": 0.9, "stars": 1, "collected_at": "2026-08-12T00:00:00+00:00",
            },
            {"title": "低分条目", "url": "https://x", "relevance_score": 0.1},
        ],
    )
    out = organize_node(demo)
    print(json.dumps(out["articles"], ensure_ascii=False, indent=2))
