"""Router 模式 —— 基于意图分类的请求路由（课件 9-1）。

**两层分类策略**：

1. **关键词快速匹配** —— 零成本、零延迟，覆盖 80% 的常见说法；
2. **LLM 分类兜底** —— 只处理关键词没命中的模糊意图，``max_tokens=50``
   限制输出（分类只需要一个词）。

三种意图各对应一个处理器，注册在 :data:`HANDLERS` 里。新增一种意图
（比如 ``arxiv_search``）只要写一个处理器函数 + 加一条关键词规则 +
在 HANDLERS 注册，**路由逻辑本身一行都不用改** —— 这就是 Router 模式
和「一堆 if-else」的区别。

运行::

    python3 -m patterns.router                       # 跑三类内置演示
    python3 -m patterns.router "搜索 AI Agent 框架"   # 跑单条查询
"""

from __future__ import annotations

import json
import logging
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from workflows.model_client import chat  # noqa: E402

logger = logging.getLogger(__name__)

#: 本模式在成本报告里的名字
NODE_NAME = "router"

#: 知识库索引位置
INDEX_PATH = PROJECT_ROOT / "knowledge" / "articles" / "index.json"

#: GitHub 搜索参数
GITHUB_SEARCH_URL = "https://api.github.com/search/repositories"
GITHUB_TIMEOUT = 10.0
GITHUB_RESULT_LIMIT = 5

#: 知识库查询返回的最大条数
KNOWLEDGE_RESULT_LIMIT = 10

#: LLM 分类的输出上限 —— 只要一个词，不给它发挥的空间
CLASSIFY_MAX_TOKENS = 50

#: 从查询里剔除的噪声词（GitHub 搜索前的清洗）
GITHUB_NOISE_WORDS = ("搜索", "查一下", "找一下", "github", "GitHub", "仓库", "项目")


# ---------------------------------------------------------------------------
# 处理器
# ---------------------------------------------------------------------------


def github_search_handler(query: str) -> str:
    """GitHub 搜索处理器：搜相关仓库并返回摘要。

    Args:
        query: 用户原始查询。

    Returns:
        Markdown 列表形式的搜索结果；失败时返回错误说明。
    """
    keyword = query
    for noise in GITHUB_NOISE_WORDS:
        keyword = keyword.replace(noise, " ")
    keyword = " ".join(keyword.split()) or "ai agent"

    # 必须 quote —— 查询里有空格和中文，不编码会直接 400
    params = urllib.parse.urlencode(
        {"q": keyword, "sort": "stars", "order": "desc", "per_page": GITHUB_RESULT_LIMIT}
    )
    url = f"{GITHUB_SEARCH_URL}?{params}"
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "ai-knowledge-base-v3/1.0",
    }
    token = os.getenv("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"token {token}"

    try:
        request = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request, timeout=GITHUB_TIMEOUT) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - 网络层任何异常都降级为可读提示
        return f"GitHub 搜索失败: {exc}"

    lines = [
        f"- [{repo['full_name']}]({repo['html_url']}) ⭐{repo.get('stargazers_count', 0)}"
        f" — {repo.get('description') or '（无描述）'}"
        for repo in data.get("items", [])[:GITHUB_RESULT_LIMIT]
    ]
    return "GitHub 搜索结果:\n" + "\n".join(lines) if lines else "未找到相关仓库"


def knowledge_query_handler(query: str) -> str:
    """知识库查询处理器：从本地 index.json 检索。

    Args:
        query: 用户原始查询。

    Returns:
        命中条目列表；索引不存在或无命中时返回说明文本。
    """
    if not INDEX_PATH.exists():
        return "知识库为空，请先运行采集工作流：python3 -m workflows.graph"

    try:
        index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return f"知识库索引损坏: {exc}"

    query_lower = query.lower()
    matches = [
        entry for entry in index
        if isinstance(entry, dict)
        and (
            any(token in entry.get("title", "").lower() for token in query_lower.split())
            or query_lower in entry.get("category", "").lower()
            or any(query_lower in str(tag).lower() for tag in entry.get("tags", []))
        )
    ]

    if not matches:
        return f"知识库共 {len(index)} 条，但没有匹配「{query}」的条目。"

    lines = [
        f"- {m.get('title', '?')} [{m.get('category', '?')}] "
        f"(相关度 {m.get('relevance_score', '?')})"
        for m in matches[:KNOWLEDGE_RESULT_LIMIT]
    ]
    return f"找到 {len(matches)} 条相关知识:\n" + "\n".join(lines)


def general_chat_handler(query: str) -> str:
    """通用对话处理器：LLM 直接回答。

    Args:
        query: 用户原始查询。

    Returns:
        模型回答；调用失败时返回错误说明。
    """
    try:
        answer, _ = chat(
            query,
            system="你是一个专业的 AI 技术顾问。简洁、准确地回答，不超过 300 字。",
            node_name=NODE_NAME,
        )
    except Exception as exc:  # noqa: BLE001 - 演示脚本不因网络问题崩掉
        return f"LLM 调用失败: {exc}"
    return answer


# ---------------------------------------------------------------------------
# 路由核心
# ---------------------------------------------------------------------------

#: 意图 → 处理器。新增意图只需在这里注册，route() 一行不用改。
HANDLERS: dict[str, Callable[[str], str]] = {
    "github_search": github_search_handler,
    "knowledge_query": knowledge_query_handler,
    "general_chat": general_chat_handler,
}

#: 关键词规则。用 list[tuple] 而不是 dict：**顺序即优先级**，
#: 先命中先返回；dict 表达不了「谁先谁后」。
KEYWORD_RULES: list[tuple[tuple[str, ...], str]] = [
    (("知识库", "已收录", "收录了", "库里", "knowledge base"), "knowledge_query"),
    (("github", "仓库", "repo", "开源项目", "trending", "star"), "github_search"),
]

#: 分类失败时的默认意图 —— 降级到通用对话，不报错
FALLBACK_INTENT = "general_chat"

#: LLM 分类 prompt。带 few-shot —— 实测「LangGraph 和 CrewAI 有什么区别」
#: 在无示例时会被判成 knowledge_query（模型把「技术名词」当成了「查资料」）。
#: 分类边界靠举例说清楚，比在类别描述里堆形容词有效得多。
CLASSIFY_PROMPT = """请判断以下用户查询的意图类别。

可选类别:
- github_search: 想去 GitHub 上**找项目**（关键动作是搜索仓库）
- knowledge_query: 想查**本地知识库里已经收录**的内容（关键动作是检索已有条目）
- general_chat: 需要**直接解答**的技术问题，包括概念解释、方案对比、选型建议

示例:
查询: 有没有做 RAG 的开源库 → github_search
查询: 我们之前收录过哪些多模态的文章 → knowledge_query
查询: LangGraph 和 CrewAI 有什么区别 → general_chat
查询: 什么时候该用向量数据库 → general_chat

查询: {query}

只返回类别名称，不要任何其他内容。"""


def classify_intent(query: str) -> tuple[str, bool]:
    """两层意图分类。

    Args:
        query: 用户查询。

    Returns:
        ``(intent, used_llm)``；``used_llm=False`` 表示关键词命中、零成本。

    Examples:
        >>> classify_intent("知识库里有什么关于 RAG 的内容")
        ('knowledge_query', False)
        >>> classify_intent("搜索 GitHub 上的 Agent 仓库")
        ('github_search', False)
    """
    query_lower = query.lower()

    # 第一层：关键词匹配（零成本，不调 LLM）
    for keywords, intent in KEYWORD_RULES:
        if any(keyword in query_lower for keyword in keywords):
            return intent, False

    # 第二层：LLM 兜底
    try:
        text, _ = chat(
            CLASSIFY_PROMPT.format(query=query),
            system="你是意图分类器。只返回类别名称。",
            temperature=0.0,
            max_tokens=CLASSIFY_MAX_TOKENS,
            node_name=NODE_NAME,
        )
    except Exception as exc:  # noqa: BLE001 - 分类失败降级而不是报错
        logger.warning("[Router] LLM 分类失败，降级为 %s：%s", FALLBACK_INTENT, exc)
        return FALLBACK_INTENT, True

    intent = text.strip().strip("`\"' 。.").lower()
    for candidate in HANDLERS:
        if candidate in intent:
            return candidate, True
    return FALLBACK_INTENT, True


def route(query: str) -> str:
    """路由入口：分类意图并调用对应处理器。

    Args:
        query: 用户查询。

    Returns:
        处理器的返回文本。
    """
    intent, used_llm = classify_intent(query)
    logger.info("[Router] 意图: %s（%s）", intent, "LLM 兜底" if used_llm else "关键词命中，零成本")
    return HANDLERS[intent](query)


#: 演示用的三类查询，各覆盖一种意图
DEMO_QUERIES = (
    ("搜索最近的 AI Agent 框架仓库", "github_search"),
    ("知识库里有什么关于 RAG 的内容", "knowledge_query"),
    ("LangGraph 和 CrewAI 有什么区别", "general_chat"),
)


def _demo() -> int:
    """跑三类内置演示，验证分类正确性。

    Returns:
        0 表示三类都分类正确。
    """
    print("=" * 60)
    print("Router 模式演示 —— 三类查询分类")
    print("=" * 60)

    failures = 0
    for query, expected in DEMO_QUERIES:
        intent, used_llm = classify_intent(query)
        ok = intent == expected
        failures += 0 if ok else 1
        source = "LLM 兜底" if used_llm else "关键词命中（零成本）"
        print(f"\n查询: {query}")
        print(f"  意图: {intent}（期望 {expected}）— {'OK' if ok else 'FAIL'} · {source}")

    print("\n" + "-" * 60)
    print(f"分类正确 {len(DEMO_QUERIES) - failures}/{len(DEMO_QUERIES)}")

    print("\n=== 实际路由一条（会真的调处理器）===")
    demo_query = DEMO_QUERIES[1][0]
    print(f"查询: {demo_query}\n{route(demo_query)}")
    return 1 if failures else 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if len(sys.argv) > 1:
        user_query = " ".join(sys.argv[1:])
        print(f"查询: {user_query}\n")
        print(route(user_query))
        raise SystemExit(0)
    raise SystemExit(_demo())
