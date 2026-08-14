"""bot/knowledge_bot.py — 交互式 AI 知识库检索 Bot。

OOP 架构：
- `KnowledgeSearchEngine` — 加权关键词检索 + 分类 / 日期范围过滤。
- `SubscriptionManager` — 用户订阅增删查，持久化到 `data/subscriptions.json`。
- `KnowledgeBot` — 意图识别 + 指令分发，整合以上两个模块。

纯本地规则匹配，不调用任何 LLM，因此没有 API key 也能完整跑通自测。
"""

import json
import logging
from collections.abc import Callable
from datetime import datetime
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_ARTICLES_DIR = Path("knowledge/articles")
DEFAULT_SUBSCRIPTIONS_PATH = Path("data/subscriptions.json")
INDEX_FILENAME = "index.json"

# 加权检索算法：标题命中 +10，标签命中 +5，摘要命中 +3，
# 再乘以 relevance_score（0–1，AGENTS.md §3.2）做最终排序权重。
TITLE_MATCH_WEIGHT = 10
TAG_MATCH_WEIGHT = 5
SUMMARY_MATCH_WEIGHT = 3

DEFAULT_TOP_N = 5
TAG_DISPLAY_LIMIT = 5


class Intent(Enum):
    """用户输入的意图分类。"""

    SEARCH = "search"
    TODAY = "today"
    TOP = "top"
    SUBSCRIBE = "subscribe"
    UNSUBSCRIBE = "unsubscribe"
    HELP = "help"
    UNKNOWN = "unknown"


# 命令前缀 → 意图。顺序无关：用 startswith 精确匹配前缀本身，不会互相冲突。
COMMAND_PREFIXES: dict[str, Intent] = {
    "/search": Intent.SEARCH,
    "/today": Intent.TODAY,
    "/top": Intent.TOP,
    "/unsubscribe": Intent.UNSUBSCRIBE,
    "/subscribe": Intent.SUBSCRIBE,
    "/help": Intent.HELP,
}

# 自然语言关键词 → 意图。命中即返回，SEARCH 会把关键词从原文里摘掉当作查询词。
NATURAL_LANGUAGE_KEYWORDS: dict[Intent, list[str]] = {
    Intent.TODAY: ["今天", "今日", "daily"],
    Intent.TOP: ["最高分", "排行榜", "top榜", "高分推荐"],
    Intent.SUBSCRIBE: ["订阅"],
    Intent.HELP: ["帮助", "怎么用", "help"],
    Intent.SEARCH: ["搜索", "搜一下", "查询", "查找", "找一下"],
}

HELP_TEXT = """🤖 可用指令：
/search <关键词> — 按关键词检索知识库
/today — 查看今日入库文章
/top [N] — 查看相关性最高的 N 篇（默认 5）
/subscribe <关键词> — 订阅关键词，未来简报优先展示
/unsubscribe <关键词> — 取消订阅
/help — 显示本帮助"""


def recognize_intent(text: str) -> tuple[Intent, str]:
    """识别用户输入的意图与参数。优先匹配命令前缀，再匹配自然语言关键词。

    Args:
        text: 用户原始输入。

    Returns:
        `(意图, 参数字符串)`。命令前缀模式下参数是前缀之后的剩余文本；
        自然语言模式下 SEARCH 会摘掉命中的关键词作为查询词，其余意图参数为空串。
    """
    text = text.strip()
    lowered = text.lower()

    for prefix, intent in COMMAND_PREFIXES.items():
        if lowered.startswith(prefix):
            return intent, text[len(prefix) :].strip()

    for intent, keywords in NATURAL_LANGUAGE_KEYWORDS.items():
        for keyword in keywords:
            if keyword in text:
                if intent == Intent.SEARCH:
                    return intent, text.replace(keyword, "", 1).strip()
                return intent, ""

    return Intent.UNKNOWN, text


def _article_date(article: dict) -> str:
    """取文章的日期戳（优先 fetched_at，其次 collected_at），截取 YYYY-MM-DD。"""
    ts = (
        article.get("fetched_at") or article.get("collected_at") or article.get("analyzed_at") or ""
    )
    return ts[:10] if ts else ""


class KnowledgeSearchEngine:
    """本地知识库加权检索引擎。"""

    def __init__(self, articles_dir: Path | str = DEFAULT_ARTICLES_DIR) -> None:
        """初始化检索引擎。

        Args:
            articles_dir: 文章目录，需包含 `index.json` 与逐篇 `<id>.json`。
        """
        self.articles_dir = Path(articles_dir)

    def _load_all(self) -> list[dict]:
        """加载全库文章的完整字段（索引 + 单篇 JSON）。"""
        index_path = self.articles_dir / INDEX_FILENAME
        if not index_path.exists():
            logger.warning("索引文件不存在：%s", index_path)
            return []

        with index_path.open("r", encoding="utf-8") as f:
            index = json.load(f)

        articles = []
        for entry in index:
            article_path = self.articles_dir / f"{entry['id']}.json"
            if article_path.exists():
                with article_path.open("r", encoding="utf-8") as f:
                    articles.append(json.load(f))
            else:
                articles.append(entry)
        return articles

    def _score(self, article: dict, keyword: str) -> float:
        """按标题 / 标签 / 摘要命中加权，乘以 relevance_score 归一化后的得分。"""
        kw = keyword.lower()
        title_hit = kw in article.get("title", "").lower()
        tag_hit = any(kw in tag.lower() for tag in article.get("tags", []))
        summary_hit = kw in (article.get("summary") or "").lower()

        weight = (
            TITLE_MATCH_WEIGHT * title_hit
            + TAG_MATCH_WEIGHT * tag_hit
            + SUMMARY_MATCH_WEIGHT * summary_hit
        )
        if weight == 0:
            return 0.0
        return weight * article.get("relevance_score", 0.0)

    def search(
        self,
        keyword: str | None = None,
        category: str | None = None,
        date_range: tuple[str, str] | None = None,
        top_n: int = DEFAULT_TOP_N,
    ) -> list[dict]:
        """检索知识库。

        Args:
            keyword: 关键词，命中标题 / 标签 / 摘要才计分；为空则不按关键词过滤。
            category: 精确匹配 `category` 字段。
            date_range: `(start_date, end_date)`，均为 `YYYY-MM-DD`，按文章日期闭区间过滤。
            top_n: 返回条数上限。

        Returns:
            按加权得分（无关键词时按 relevance_score）降序排列的 Top-N 文章列表。
        """
        articles = self._load_all()

        if category:
            articles = [a for a in articles if a.get("category") == category]

        if date_range:
            start, end = date_range
            articles = [a for a in articles if start <= _article_date(a) <= end]

        if keyword:
            scored = [(a, self._score(a, keyword)) for a in articles]
            scored = [(a, s) for a, s in scored if s > 0]
        else:
            scored = [(a, a.get("relevance_score", 0.0)) for a in articles]

        scored.sort(key=lambda pair: pair[1], reverse=True)
        return [a for a, _ in scored[:top_n]]

    def today(self, top_n: int = DEFAULT_TOP_N, reference_date: str | None = None) -> list[dict]:
        """返回今日入库文章；今日无数据时回退到全库最近一次入库的日期。

        Args:
            top_n: 返回条数上限。
            reference_date: 参照日期（`YYYY-MM-DD`），缺省用当前系统日期，主要供测试注入。

        Returns:
            按 relevance_score 降序排列的文章列表。
        """
        articles = self._load_all()
        target_date = reference_date or datetime.now().strftime("%Y-%m-%d")

        todays = [a for a in articles if _article_date(a) == target_date]
        if not todays:
            known_dates = sorted(
                {_article_date(a) for a in articles if _article_date(a)}, reverse=True
            )
            if known_dates:
                todays = [a for a in articles if _article_date(a) == known_dates[0]]

        todays.sort(key=lambda a: a.get("relevance_score", 0.0), reverse=True)
        return todays[:top_n]

    def top(self, top_n: int = DEFAULT_TOP_N) -> list[dict]:
        """返回全库 relevance_score 最高的 Top-N 文章。"""
        articles = self._load_all()
        articles.sort(key=lambda a: a.get("relevance_score", 0.0), reverse=True)
        return articles[:top_n]


class SubscriptionManager:
    """用户订阅关键词管理，持久化到本地 JSON。"""

    def __init__(self, storage_path: Path | str = DEFAULT_SUBSCRIPTIONS_PATH) -> None:
        """初始化订阅管理器并加载已持久化的订阅。

        Args:
            storage_path: 订阅数据落盘路径。
        """
        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self._subscriptions: dict[str, list[str]] = self._load()

    def _load(self) -> dict[str, list[str]]:
        if not self.storage_path.exists():
            return {}
        with self.storage_path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def _save(self) -> None:
        with self.storage_path.open("w", encoding="utf-8") as f:
            json.dump(self._subscriptions, f, ensure_ascii=False, indent=2)

    def subscribe(self, user_id: str, keyword: str) -> None:
        """为用户新增一个订阅关键词，已存在则忽略。"""
        keywords = self._subscriptions.setdefault(user_id, [])
        if keyword not in keywords:
            keywords.append(keyword)
            self._save()

    def unsubscribe(self, user_id: str, keyword: str) -> None:
        """移除用户的一个订阅关键词，不存在则忽略。"""
        keywords = self._subscriptions.get(user_id, [])
        if keyword in keywords:
            keywords.remove(keyword)
            self._save()

    def list_subscriptions(self, user_id: str) -> list[str]:
        """返回用户当前的订阅关键词列表。"""
        return list(self._subscriptions.get(user_id, []))


def format_search_results(results: list[dict], query: str = "") -> str:
    """把检索结果格式化为可读文本。

    Args:
        results: `KnowledgeSearchEngine` 系列方法返回的文章列表。
        query: 用于展示的查询描述，仅用于文案，不参与检索。

    Returns:
        供 CLI / Bot 直接展示的文本。
    """
    if not results:
        return f"🔍 没有找到与「{query}」相关的内容" if query else "🔍 没有找到相关内容"

    lines = [
        (
            f"🔍 找到 {len(results)} 条与「{query}」相关的内容："
            if query
            else f"🔍 找到 {len(results)} 条内容："
        ),
        "",
    ]
    for i, article in enumerate(results, start=1):
        tags = ", ".join(article.get("tags", [])[:TAG_DISPLAY_LIMIT])
        lines.append(f"📌 {i}. {article.get('title', '未知标题')}")
        lines.append(
            f"   📊 {article.get('relevance_score', 0.0):.2f} | "
            f"{article.get('source', '未知')} | {_article_date(article) or '未知日期'} | {tags}"
        )
    return "\n".join(lines)


class KnowledgeBot:
    """AI 知识库交互式机器人：意图识别 + 指令分发。"""

    def __init__(
        self,
        articles_dir: Path | str = DEFAULT_ARTICLES_DIR,
        subscriptions_path: Path | str = DEFAULT_SUBSCRIPTIONS_PATH,
    ) -> None:
        """初始化 Bot 及其依赖的检索引擎 / 订阅管理器。"""
        self.search_engine = KnowledgeSearchEngine(articles_dir)
        self.subscription_manager = SubscriptionManager(subscriptions_path)

    def handle_message(self, user_id: str, text: str) -> str:
        """处理一条用户消息，返回响应文本。"""
        intent, payload = recognize_intent(text)
        handler = self._handlers().get(intent, self._handle_unknown)
        return handler(user_id, payload)

    def _handlers(self) -> dict[Intent, Callable[[str, str], str]]:
        return {
            Intent.SEARCH: self._handle_search,
            Intent.TODAY: self._handle_today,
            Intent.TOP: self._handle_top,
            Intent.SUBSCRIBE: self._handle_subscribe,
            Intent.UNSUBSCRIBE: self._handle_unsubscribe,
            Intent.HELP: self._handle_help,
            Intent.UNKNOWN: self._handle_unknown,
        }

    def _handle_search(self, user_id: str, payload: str) -> str:
        if not payload:
            return "请提供搜索关键词，例如：/search agent"
        results = self.search_engine.search(keyword=payload)
        return format_search_results(results, query=payload)

    def _handle_today(self, user_id: str, payload: str) -> str:
        results = self.search_engine.today()
        return format_search_results(results, query="今日入库")

    def _handle_top(self, user_id: str, payload: str) -> str:
        top_n = int(payload) if payload.strip().isdigit() else DEFAULT_TOP_N
        results = self.search_engine.top(top_n=top_n)
        return format_search_results(results, query=f"Top {top_n}")

    def _handle_subscribe(self, user_id: str, payload: str) -> str:
        if not payload:
            return "请提供订阅关键词，例如：/subscribe agent"
        self.subscription_manager.subscribe(user_id, payload)
        return f"✅ 已订阅关键词「{payload}」"

    def _handle_unsubscribe(self, user_id: str, payload: str) -> str:
        if not payload:
            return "请提供要取消订阅的关键词"
        self.subscription_manager.unsubscribe(user_id, payload)
        return f"🗑️ 已取消订阅「{payload}」"

    def _handle_help(self, user_id: str, payload: str) -> str:
        return HELP_TEXT

    def _handle_unknown(self, user_id: str, payload: str) -> str:
        return "抱歉，没有理解你的意图。输入 /help 查看可用指令。"


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    print("=== 意图识别自测 ===")
    for sample in ["/search agent", "/today", "/top 3", "/help", "搜一下 RAG", "随便聊聊"]:
        _intent, _payload = recognize_intent(sample)
        print(f"  {sample!r:20s} -> {_intent.name:12s} payload={_payload!r}")

    print()
    print("=== Bot 消息处理自测 ===")
    _bot = KnowledgeBot()
    for sample in ["/help", "/search agent", "/today", "/top 3", "/subscribe rag", "搜索 RAG 相关"]:
        print(f"输入: {sample}")
        print(f"回复: {_bot.handle_message('cli-user', sample)}")
        print()
