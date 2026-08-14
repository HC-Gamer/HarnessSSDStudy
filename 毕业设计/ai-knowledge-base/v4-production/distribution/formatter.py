"""distribution/formatter.py — 格式化层。

把 `knowledge/articles/` 里的结构化文章 JSON（schema 见 AGENTS.md §3.1）转换成
Markdown 简报 / Telegram 消息两种展示格式。

纯函数模块：只读文件、拼字符串，不发任何网络请求（网络归 `distribution/publisher.py`）。
"""

import json
import logging
from html import escape as html_escape
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_ARTICLES_DIR = Path("knowledge/articles")
INDEX_FILENAME = "index.json"

# 相关性分档阈值（0–1 浮点，AGENTS.md §3.2）
HIGH_RELEVANCE_THRESHOLD = 0.8
MEDIUM_RELEVANCE_THRESHOLD = 0.6

TAG_DISPLAY_LIMIT = 5
TELEGRAM_MAX_MESSAGE_LENGTH = 4096
TELEGRAM_TRUNCATION_SUFFIX = "…（已截断）"


def load_articles(articles_dir: Path | str = DEFAULT_ARTICLES_DIR) -> list[dict]:
    """从索引 + 单篇 JSON 加载全部文章的完整字段。

    `index.json` 只含 id/title/category/tags/relevance_score/source_url/
    collected_at/status 等精简字段；本函数按索引里的 `id` 逐条读取
    `<id>.json` 补全 summary/key_insight/metadata 等展示所需字段。
    单篇文件缺失时退化为只用索引行（保证不中断）。

    Args:
        articles_dir: 文章目录，默认 `knowledge/articles`。

    Returns:
        文章 dict 列表，字段见 AGENTS.md §3.1。
    """
    articles_dir = Path(articles_dir)
    index_path = articles_dir / INDEX_FILENAME
    if not index_path.exists():
        logger.warning("索引文件不存在：%s", index_path)
        return []

    with index_path.open("r", encoding="utf-8") as f:
        index = json.load(f)

    articles = []
    for entry in index:
        article_path = articles_dir / f"{entry['id']}.json"
        if article_path.exists():
            with article_path.open("r", encoding="utf-8") as f:
                articles.append(json.load(f))
        else:
            logger.warning("单篇 JSON 缺失，退化用索引行：%s", article_path)
            articles.append(entry)
    return articles


def _relevance_badge(score: float) -> str:
    """按 0–1 相关性分值返回颜色标记。"""
    if score >= HIGH_RELEVANCE_THRESHOLD:
        return "🟢"
    if score >= MEDIUM_RELEVANCE_THRESHOLD:
        return "🟡"
    return "🔴"


def _article_date(article: dict) -> str:
    """取文章的展示日期（优先发布/分析/采集时间），截取前 10 位 YYYY-MM-DD。"""
    ts = (
        article.get("published_at")
        or article.get("analyzed_at")
        or article.get("fetched_at")
        or article.get("collected_at")
        or ""
    )
    return ts[:10] if ts else "未知日期"


def _markdown_entry(article: dict) -> str:
    """单篇文章的 Markdown 片段。"""
    score = article.get("relevance_score", 0.0)
    tags = ", ".join(f"`{tag}`" for tag in article.get("tags", [])[:TAG_DISPLAY_LIMIT])
    summary = article.get("key_insight") or article.get("summary") or "暂无摘要"
    return (
        f"### {article.get('title', '未知标题')}\n\n"
        f"- **来源**：{article.get('source', '未知')}\n"
        f"- **日期**：{_article_date(article)}\n"
        f"- **相关性**：{_relevance_badge(score)} {score:.2f}\n"
        f"- **标签**：{tags}\n\n"
        f"{summary}\n\n"
        f"🔗 [原文链接]({article.get('source_url', '#')})\n"
    )


def format_markdown(articles: list[dict]) -> str:
    """把文章列表格式化为 Markdown 简报。

    Args:
        articles: 文章 dict 列表（`load_articles()` 的返回值）。

    Returns:
        完整 Markdown 简报字符串；文章列表为空时返回提示语。
    """
    if not articles:
        return "📭 暂无新增知识条目"

    parts = [f"# 📚 AI 知识库简报（{len(articles)} 条）\n"]
    parts.extend(_markdown_entry(article) for article in articles)
    return "\n---\n\n".join(parts)


def _telegram_entry(article: dict) -> str:
    """单篇文章的 Telegram HTML 片段（`parse_mode=HTML`）。"""
    title = html_escape(article.get("title", "未知标题"))
    url = html_escape(article.get("source_url", "#"), quote=True)
    summary = html_escape(article.get("key_insight") or article.get("summary") or "暂无摘要")
    source = html_escape(article.get("source", "未知"))
    score = article.get("relevance_score", 0.0)
    tags = " ".join(
        f"#{html_escape(tag.replace(' ', '_'))}"
        for tag in article.get("tags", [])[:TAG_DISPLAY_LIMIT]
    )
    return (
        f'📌 <a href="{url}"><b>{title}</b></a>\n'
        f"{summary}\n"
        f"📊 相关性：{_relevance_badge(score)} {score:.2f} | 来源：{source}\n"
        f"{tags}"
    )


def format_telegram(articles: list[dict]) -> str:
    """把文章列表格式化为一条 Telegram 消息（HTML 标记，`parse_mode=HTML`）。

    Telegram 单条消息上限 4096 字符，超出按 `TELEGRAM_MAX_MESSAGE_LENGTH`
    截断并追加提示后缀，避免推送时被 API 拒绝。

    Args:
        articles: 文章 dict 列表（`load_articles()` 的返回值）。

    Returns:
        HTML 格式的 Telegram 消息字符串；文章列表为空时返回提示语。
    """
    if not articles:
        return "📭 暂无新增知识条目"

    header = f"📚 <b>AI 知识库每日简报</b>（{len(articles)} 条）\n"
    body = "\n\n".join(_telegram_entry(article) for article in articles)
    message = header + "\n" + body

    if len(message) > TELEGRAM_MAX_MESSAGE_LENGTH:
        cut = TELEGRAM_MAX_MESSAGE_LENGTH - len(TELEGRAM_TRUNCATION_SUFFIX)
        message = message[:cut] + TELEGRAM_TRUNCATION_SUFFIX
    return message


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    _articles = load_articles()
    print(f"共加载 {len(_articles)} 篇文章\n")

    print("=" * 20, "Markdown 预览（前 800 字）", "=" * 20)
    print(format_markdown(_articles)[:800])
    print()

    print("=" * 20, "Telegram 预览（前 800 字）", "=" * 20)
    print(format_telegram(_articles)[:800])
