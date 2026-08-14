#!/usr/bin/env python3
"""四步知识库流水线：采集 → 采集 → AI 分析 → 整理入库。

四个步骤：

===========  ========  ==================================================
Step         是否计费  说明
===========  ========  ==================================================
1 GitHub     免费      GitHub Search API 拉取近期高星 AI 仓库
2 RSS        免费      按 rss_sources.yaml 抓取并解析 RSS/Atom
3 AI 分析    **计费**  调 LLM 生成摘要 / 标签 / 技术深度评分
4 整理入库   免费      写 JSON 到 knowledge/articles/
===========  ========  ==================================================

用法::

    python pipeline/pipeline.py --sources github,rss --limit 5 --verbose
    python pipeline/pipeline.py --sources github --limit 5 --provider deepseek
    python pipeline/pipeline.py --sources rss --no-analyze   # 只跑免费采集

不带 ``--no-analyze`` 时会调用 LLM；缺少 API Key 会自动降级为规则摘要，
并在最终报告中注明。
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import httpx
import yaml

# 支持两种运行方式：项目根目录 `python pipeline/pipeline.py` 或 pipeline/ 目录内
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.model_client import (  # noqa: E402
    LLMError,
    get_provider,
    tracker,
)

logger = logging.getLogger("pipeline")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ARTICLES_DIR = PROJECT_ROOT / "knowledge" / "articles"
RAW_DIR = PROJECT_ROOT / "knowledge" / "raw"
RSS_CONFIG = Path(__file__).resolve().parent / "rss_sources.yaml"

HTTP_TIMEOUT = 45.0
#: arXiv Atom API 响应慢，用更长超时
ARXIV_TIMEOUT = 90.0
USER_AGENT = "v2-pipeline/1.0 (+https://github.com/huangcheng/OpenCodeStudy)"

#: 部分站点（Hugging Face / Cloudflare 前置）对脚本 UA 直接返回 403，抓 feed 时用浏览器 UA
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
FEED_HEADERS = {
    "User-Agent": BROWSER_USER_AGENT,
    "Accept": (
        "application/rss+xml, application/atom+xml, application/xml;q=0.9, "
        "text/xml;q=0.8, text/html;q=0.7, */*;q=0.5"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    # Cloudflare 前置的站点（Hugging Face）会对「无 Accept-Encoding」的请求判定为脚本
    "Accept-Encoding": "gzip, deflate",
}
PAGE_HEADERS = {
    "User-Agent": BROWSER_USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

#: 重试策略：最多 3 次，指数退避 1s → 2s
HTTP_MAX_ATTEMPTS = 3
HTTP_BACKOFF_BASE = 2.0
#: 只有这些状态码值得重试；403/404 换个时间点重试仍然是 403/404
RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})

#: 摘要短于此长度时，尝试回原文页面补正文（越大越激进，Lobsters 这类纯标题源需要它）
MIN_SUMMARY_CHARS = 80
#: 从原文页面提取的正文长度
ARTICLE_TEXT_CHARS = 300
#: 每个源最多回源抓取多少篇正文（避免一个纯标题源把整条流水线拖慢）
MAX_ENRICH_PER_SOURCE = 10
#: 回源抓正文用更短的超时/更少的重试，失败就降级，不值得等
ENRICH_TIMEOUT = 20.0
ENRICH_ATTEMPTS = 2
#: feed 里只有标题的源，回源是唯一正文来源，值得用完整超时/重试再试一次
RELAXED_ENRICH_SOURCES = frozenset({"lobsters"})

#: arXiv RSS 经常连接超时，识别出分类后回退到官方 Atom API
ARXIV_RSS_PATTERN = re.compile(r"https?://(?:[\w.-]+\.)?arxiv\.org/rss/([\w.\-+]+)", re.I)
ARXIV_API_URL = "https://export.arxiv.org/api/query"
#: arXiv 两个接口都比其他源慢，单独放宽超时（全局 45s 对 arXiv 不够）
ARXIV_HOST_PATTERN = re.compile(r"https?://(?:[\w.-]+\.)?arxiv\.org/", re.I)


#: GitHub Search API：近 N 天创建的仓库算「trending」
GITHUB_SEARCH_URL = "https://api.github.com/search/repositories"
GITHUB_TRENDING_WINDOW_DAYS = 30
GITHUB_TOPIC_QUERY = "llm OR agent OR rag OR mcp OR gpt"

#: check_quality.py 的标签白名单，AI 分析结果按此裁剪
VALID_TAGS: frozenset[str] = frozenset(
    {
        "agent", "rag", "mcp", "llm", "fine-tuning", "prompt-engineering",
        "multi-agent", "tool-use", "evaluation", "deployment", "security",
        "reasoning", "code-generation", "vision", "audio", "robotics",
    }
)

#: 降级摘要用的关键词 → 标签映射
KEYWORD_TAGS: tuple[tuple[str, str], ...] = (
    ("agent", "agent"),
    ("rag", "rag"),
    ("retriev", "rag"),
    ("mcp", "mcp"),
    ("model context protocol", "mcp"),
    ("fine-tun", "fine-tuning"),
    ("finetun", "fine-tuning"),
    ("prompt", "prompt-engineering"),
    ("tool call", "tool-use"),
    ("function call", "tool-use"),
    ("benchmark", "evaluation"),
    ("eval", "evaluation"),
    ("deploy", "deployment"),
    ("serving", "deployment"),
    ("inference", "deployment"),
    ("security", "security"),
    ("jailbreak", "security"),
    ("reason", "reasoning"),
    ("chain-of-thought", "reasoning"),
    ("code", "code-generation"),
    ("vision", "vision"),
    ("image", "vision"),
    ("speech", "audio"),
    ("audio", "audio"),
    ("robot", "robotics"),
)

ANALYZE_SYSTEM_PROMPT = """你是 AI 技术知识库的分析助手。给定一条技术资讯，输出严格的 JSON 对象：

{
  "summary": "中文摘要，50-120 字，必须包含具体技术要点（模型/架构/推理/训练/上下文/基准等），禁止空话",
  "tags": ["从白名单中选 1-3 个"],
  "score": 技术深度 1-10 的整数,
  "audience": "beginner | intermediate | advanced"
}

标签白名单：agent, rag, mcp, llm, fine-tuning, prompt-engineering, multi-agent,
tool-use, evaluation, deployment, security, reasoning, code-generation, vision,
audio, robotics

评分标准：1-3 泛泛新闻，4-6 有工程细节，7-8 有架构/算法深度，9-10 原创研究突破。
严禁使用「赋能/闭环/革命性的/强大的/groundbreaking/cutting-edge」等空洞词。
只输出 JSON，不要 markdown 代码块。"""


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass
class RawItem:
    """采集到的原始条目（尚未经过 AI 分析）。

    Attributes:
        source: 数据源标识，如 ``github`` / ``hackernews``。
        title: 标题。
        url: 原文链接。
        raw_text: 用于喂给 LLM 的原始描述文本。
        default_tags: 数据源自带的默认标签。
        extra: 额外元信息（stars / 语言 / 发布时间等）。
    """

    source: str
    title: str
    url: str
    raw_text: str = ""
    default_tags: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class Article:
    """最终入库的知识条目。字段与 hooks/validate_json.py 的校验规则对齐。"""

    id: str
    title: str
    source_url: str
    summary: str
    tags: list[str]
    status: str
    score: int
    collected_at: str
    source: str
    audience: str = "intermediate"
    analyzed_by: str = "rule-based"
    extra: dict[str, Any] = field(default_factory=dict)


class PipelineStats:
    """流水线各步骤的计数器。"""

    def __init__(self) -> None:
        """初始化全零统计。"""
        self.github_fetched = 0
        self.rss_fetched = 0
        self.rss_ok: list[str] = []
        self.rss_failed: list[tuple[str, str]] = []
        self.analyzed_llm = 0
        self.analyzed_fallback = 0
        self.saved = 0
        self.skipped_duplicate = 0


# ---------------------------------------------------------------------------
# HTTP 工具：超时 + 指数退避重试
# ---------------------------------------------------------------------------


def http_get(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, str] | None = None,
    timeout: float = HTTP_TIMEOUT,
    attempts: int = HTTP_MAX_ATTEMPTS,
    label: str = "",
    sleep: Any = time.sleep,
) -> tuple[httpx.Response | None, str]:
    """带指数退避重试的 GET。

    网络层异常（连接超时 / 读超时 / DNS）与可重试状态码（见 RETRYABLE_STATUS）
    会退避后重试；403/404 这类确定性失败立即返回，不浪费退避时间。

    Args:
        url: 目标地址。
        headers: 请求头。
        params: 查询参数。
        timeout: 单次请求超时（秒）。
        attempts: 最多尝试次数（含首次）。
        label: 日志前缀，通常是数据源名。
        sleep: 退避函数，测试时可注入。

    Returns:
        ``(response, reason)``。成功时 reason 为空字符串；失败时 response 为
        None，reason 是可直接写进统计报告的中文原因。
    """
    tag = f"{label} " if label else ""
    reason = "未发起请求"

    for attempt in range(1, max(attempts, 1) + 1):
        try:
            response = httpx.get(
                url, headers=headers, params=params, timeout=timeout, follow_redirects=True
            )
        except httpx.HTTPError as exc:
            reason = f"请求失败: {type(exc).__name__}"
            logger.warning("%s(%d/%d) %s 请求异常: %s", tag, attempt, attempts, url, exc)
        else:
            if response.status_code == 200:
                return response, ""
            reason = f"HTTP {response.status_code}"
            if response.status_code not in RETRYABLE_STATUS:
                logger.warning("%s%s → HTTP %d（不重试）", tag, url, response.status_code)
                return None, reason
            logger.warning(
                "%s(%d/%d) %s → HTTP %d", tag, attempt, attempts, url, response.status_code
            )

        if attempt < attempts:
            delay = HTTP_BACKOFF_BASE ** (attempt - 1)
            logger.debug("%s退避 %.1fs 后重试", tag, delay)
            sleep(delay)

    return None, f"{reason}（重试 {attempts} 次仍失败）"


# ---------------------------------------------------------------------------
# Step 1: GitHub 采集（免费）
# ---------------------------------------------------------------------------


def fetch_github_trending(limit: int) -> list[RawItem]:
    """从 GitHub Search API 拉取近期高星 AI 相关仓库。

    GitHub 没有官方 trending API，这里用 Search API 近似：按「最近
    GITHUB_TRENDING_WINDOW_DAYS 天创建 + AI 关键词 + 星数降序」检索。

    Args:
        limit: 最多返回条数。

    Returns:
        RawItem 列表；请求失败时返回空列表（不抛异常，保证流水线继续）。
    """
    since = (date.today() - timedelta(days=GITHUB_TRENDING_WINDOW_DAYS)).isoformat()
    params = {
        "q": f"{GITHUB_TOPIC_QUERY} created:>{since}",
        "sort": "stars",
        "order": "desc",
        "per_page": str(min(max(limit, 1), 100)),
    }
    headers = {"Accept": "application/vnd.github+json", "User-Agent": USER_AGENT}

    logger.info("[Step 1] GitHub 采集: q=%r since=%s limit=%d", GITHUB_TOPIC_QUERY, since, limit)

    response, reason = http_get(
        GITHUB_SEARCH_URL, params=params, headers=headers, label="[Step 1] GitHub"
    )
    if response is None:
        logger.error("[Step 1] GitHub 采集失败: %s", reason)
        return []

    items: list[RawItem] = []
    for repo in response.json().get("items", [])[:limit]:
        description = repo.get("description") or ""
        topics = repo.get("topics") or []
        items.append(
            RawItem(
                source="github",
                title=repo.get("full_name", "") or repo.get("name", ""),
                url=repo.get("html_url", ""),
                raw_text=(
                    f"GitHub 仓库 {repo.get('full_name')}\n"
                    f"描述: {description}\n"
                    f"主语言: {repo.get('language') or '未知'}\n"
                    f"Stars: {repo.get('stargazers_count', 0)}\n"
                    f"Topics: {', '.join(topics) or '无'}"
                ),
                extra={
                    "stars": repo.get("stargazers_count", 0),
                    "language": repo.get("language"),
                    "topics": topics,
                    "description": description,
                },
            )
        )

    logger.info("[Step 1] GitHub 采集完成，获得 %d 条", len(items))
    return items


# ---------------------------------------------------------------------------
# Step 2: RSS 采集（免费）
# ---------------------------------------------------------------------------


def load_rss_config(path: Path = RSS_CONFIG) -> list[dict[str, Any]]:
    """读取 RSS 数据源配置。

    Args:
        path: YAML 配置路径。

    Returns:
        启用状态的数据源配置列表。
    """
    if not path.is_file():
        logger.warning("[Step 2] RSS 配置不存在: %s", path)
        return []

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    sources = data.get("sources") or []
    enabled = [s for s in sources if s.get("enabled", True)]
    logger.info("[Step 2] RSS 配置加载: %d 个源，其中启用 %d 个", len(sources), len(enabled))
    return enabled


def _strip_html(text: str) -> str:
    """去掉 HTML 标签并压缩空白。

    Args:
        text: 可能含 HTML 的原始字符串。

    Returns:
        纯文本。
    """
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = re.sub(r"&[a-zA-Z#0-9]+;", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _first_text(node: ET.Element, tags: Iterable[str]) -> str:
    """在节点下按优先级查找第一个非空文本子元素。

    同时尝试无命名空间与 Atom 命名空间两种写法。

    Args:
        node: 父节点。
        tags: 候选标签名（不含命名空间）。

    Returns:
        找到的文本，没有则空字符串。
    """
    for tag in tags:
        for candidate in (tag, f"{{http://www.w3.org/2005/Atom}}{tag}"):
            found = node.find(candidate)
            if found is None:
                continue
            if found.text and found.text.strip():
                return found.text.strip()
            # Atom 的 <link href="..."/> 没有 text，取属性
            href = found.get("href")
            if href:
                return href.strip()
    return ""


def parse_feed(xml_text: str, limit: int) -> list[tuple[str, str, str]]:
    """解析 RSS 2.0 / Atom feed。

    Args:
        xml_text: feed 原始 XML。
        limit: 最多返回条数。

    Returns:
        ``(title, link, description)`` 三元组列表。

    Raises:
        ET.ParseError: XML 无法解析。
    """
    root = ET.fromstring(xml_text)

    entries = root.findall(".//item")
    if not entries:
        entries = root.findall(".//{http://www.w3.org/2005/Atom}entry")

    results: list[tuple[str, str, str]] = []
    for entry in entries[:limit]:
        title = _strip_html(_first_text(entry, ["title"]))
        link = _first_text(entry, ["link", "id"])
        description = _strip_html(
            _first_text(entry, ["description", "summary", "content"])
        )
        if title and link:
            results.append((title, link, description))
    return results


def _arxiv_api_fallback(url: str, limit: int) -> str | None:
    """把 arXiv RSS 地址翻译成官方 Atom API 地址。

    ``export.arxiv.org/rss/cs.AI`` 经常连接超时，而 ``/api/query`` 走的是另一套
    服务，返回的 Atom 正好能被 parse_feed 直接解析。

    Args:
        url: 原始 RSS 地址。
        limit: 需要的条数。

    Returns:
        API 地址；不是 arXiv RSS 时返回 None。
    """
    match = ARXIV_RSS_PATTERN.search(url)
    if not match:
        return None
    category = match.group(1)
    return (
        f"{ARXIV_API_URL}?search_query=cat:{category}"
        f"&start=0&max_results={max(limit, 1)}"
        "&sortBy=submittedDate&sortOrder=descending"
    )


def _feed_urls(source: dict[str, Any], limit: int) -> list[str]:
    """构造一个源的抓取地址链：主地址 + 配置的备用地址 + 内置降级地址。

    Args:
        source: 单个源配置。
        limit: 该源需要的条数（arXiv API 需要它拼 max_results）。

    Returns:
        去重后的候选地址列表，按尝试顺序排列。
    """
    candidates = [source.get("url", "")]
    candidates += [u for u in (source.get("fallback_urls") or []) if isinstance(u, str)]

    # 任一候选是 arXiv RSS 就补一条 API 地址；主地址已经是 API 时靠后面的去重丢掉
    for candidate in list(candidates):
        arxiv_api = _arxiv_api_fallback(candidate, limit)
        if arxiv_api:
            candidates.append(arxiv_api)

    ordered: list[str] = []
    for url in candidates:
        if url and url not in ordered:
            ordered.append(url)
    return ordered


def _feed_headers(url: str) -> dict[str, str]:
    """按目标地址补齐 feed 请求头。

    Hugging Face 这类 Cloudflare 前置的站点会检查请求是否「像浏览器点进来的」，
    缺 Referer 时偶发 403。这里给每个 feed 带上它自己站点根地址作为 Referer。

    Args:
        url: feed 地址。

    Returns:
        FEED_HEADERS 的副本，可能多一个 Referer。
    """
    headers = dict(FEED_HEADERS)
    origin = re.match(r"(https?://[^/]+)", url)
    if origin:
        headers["Referer"] = f"{origin.group(1)}/"
    return headers


def _feed_timeout(url: str) -> float:
    """按目标地址选超时。arXiv 比其他源慢得多，单独放宽。

    Args:
        url: feed 地址。

    Returns:
        单次请求超时（秒）。
    """
    return ARXIV_TIMEOUT if ARXIV_HOST_PATTERN.search(url) else HTTP_TIMEOUT


def fetch_feed(
    name: str, urls: list[str], per_source: int
) -> tuple[list[tuple[str, str, str]], str]:
    """依次尝试一个源的多个地址，第一个解析出条目的即为结果。

    Args:
        name: 源标识，用于日志。
        urls: 候选地址链（主地址在前）。
        per_source: 最多返回条数。

    Returns:
        ``(entries, reason)``。成功时 reason 为空；全部地址失败时 entries 为空，
        reason 汇总每个地址的失败原因。
    """
    failures: list[str] = []

    for index, url in enumerate(urls):
        response, reason = http_get(
            url,
            headers=_feed_headers(url),
            timeout=_feed_timeout(url),
            label=f"[Step 2] {name}",
        )
        if response is None:
            failures.append(f"{url} → {reason}")
            continue

        try:
            parsed = parse_feed(response.text, per_source)
        except ET.ParseError as exc:
            failures.append(f"{url} → XML 解析失败: {exc}")
            continue

        if not parsed:
            failures.append(f"{url} → feed 为空或无可识别条目")
            continue

        if index > 0:
            logger.info("[Step 2] %s 主地址失败，改用备用地址 %s", name, url)
        return parsed, ""

    return [], "; ".join(failures) or "无可用地址"


def _extract_page_text(html: str, chars: int = ARTICLE_TEXT_CHARS) -> str:
    """从 HTML 页面里抽取正文纯文本。

    先整段删掉 script/style/noscript（它们的内容不是正文但会被 _strip_html
    当成文本留下），再复用 _strip_html 去标签。

    Args:
        html: 页面 HTML。
        chars: 截取长度。

    Returns:
        正文前 ``chars`` 个字符；抽不出有效文本时返回空字符串。
    """
    cleaned = re.sub(
        r"<(script|style|noscript|head)\b.*?</\1>", " ", html or "", flags=re.DOTALL | re.I
    )
    return _strip_html(cleaned)[:chars].strip()


def fetch_article_text(url: str, *, relaxed: bool = False) -> str:
    """回原文页面抓正文，用于 RSS 只给标题的源（如 Lobsters）。

    Args:
        url: 原文链接。
        relaxed: True 时用完整超时/重试，且只拒绝确定是二进制的内容类型——
            Lobsters 的外链站点五花八门，严格的 content-type 白名单会误杀。

    Returns:
        正文摘录；非文本页面（PDF 等）或抓取失败时返回空字符串。
    """
    if not url.lower().startswith(("http://", "https://")):
        return ""

    response, reason = http_get(
        url,
        headers=PAGE_HEADERS,
        timeout=HTTP_TIMEOUT if relaxed else ENRICH_TIMEOUT,
        attempts=HTTP_MAX_ATTEMPTS if relaxed else ENRICH_ATTEMPTS,
        label="[Step 2] 回源",
    )
    if response is None:
        logger.debug("[Step 2] 回源失败 %s: %s", url, reason)
        return ""

    content_type = response.headers.get("content-type", "").lower()
    if relaxed:
        rejected = any(
            t in content_type
            for t in ("pdf", "image/", "video/", "audio/", "zip", "octet-stream")
        )
    else:
        rejected = bool(content_type) and not any(
            t in content_type for t in ("html", "xml", "text/plain")
        )
    if rejected:
        logger.debug("[Step 2] 回源跳过非文本内容 %s (%s)", url, content_type)
        return ""

    return _extract_page_text(response.text)


def _expand_short_summary(title: str, source_name: str, url: str = "") -> str:
    """回源也失败时的兜底摘要：标题 + 原文站点 + 从标题提取的关键技术词。

    RSS 只给标题时摘要只有 20-40 字，会被 check_quality.py 判低分。这里把标题、
    原文域名与识别出的技术关键词拼起来，保证长度不低于 MIN_SUMMARY_CHARS，
    且带上可检索的技术词与来源信息。

    Args:
        title: 条目标题。
        source_name: 源标识。
        url: 原文链接，用于取域名；缺省时省略该段。

    Returns:
        扩写后的摘要文本，长度 ≥ MIN_SUMMARY_CHARS。
    """
    haystack = title.lower()
    terms: list[str] = []
    for keyword, tag in KEYWORD_TAGS:
        if keyword in haystack and tag not in terms:
            terms.append(tag)

    term_text = "、".join(terms[:3]) if terms else "标题中未出现白名单技术词"
    domain_match = re.match(r"https?://(?:www\.)?([^/]+)", url or "")
    origin = f"，原文站点 {domain_match.group(1)}" if domain_match else ""

    summary = (
        f"{title}。这是 {source_name} 收录的技术条目{origin}；"
        f"该源的 feed 只给出标题、未提供正文摘要，回源抓取正文也未成功，"
        f"以下为基于标题的关键词提取结果：{term_text}。"
    )
    if len(summary) < MIN_SUMMARY_CHARS:
        summary += f"标题原文：{title}。"
    return summary


def fetch_rss(sources: list[dict[str, Any]], limit: int, stats: PipelineStats) -> list[RawItem]:
    """按配置抓取全部 RSS 源。

    单个源失败不影响其他源；失败原因记入 ``stats.rss_failed``。

    Args:
        sources: 已启用的源配置列表。
        limit: 每个源最多采集条数（源自带 ``limit`` 时取两者较小值）。
        stats: 统计对象，就地更新。

    Returns:
        全部源汇总后的 RawItem 列表。
    """
    items: list[RawItem] = []

    for source in sources:
        name = source.get("name", "unknown")
        per_source = min(int(source.get("limit", limit) or limit), limit)
        default_tags = [t for t in (source.get("tags") or []) if t in VALID_TAGS]

        urls = _feed_urls(source, per_source)
        if not urls:
            stats.rss_failed.append((name, "配置缺少 url"))
            continue

        parsed, reason = fetch_feed(name, urls, per_source)
        if not parsed:
            logger.warning("[Step 2] %s 全部地址失败: %s", name, reason)
            stats.rss_failed.append((name, reason))
            continue

        relaxed_enrich = name in RELAXED_ENRICH_SOURCES
        enriched_count = 0
        skipped_enrich = 0
        for title, link, description in parsed:
            # Lobsters 之类的源 feed 里只有标题，摘要 20-40 字，需要回原文页面补正文
            if len(description) < MIN_SUMMARY_CHARS:
                if enriched_count < MAX_ENRICH_PER_SOURCE:
                    enriched_count += 1
                    body = fetch_article_text(link, relaxed=relaxed_enrich)
                    if len(body) > len(description):
                        description = body
                else:
                    skipped_enrich += 1
            if len(description) < MIN_SUMMARY_CHARS:
                description = _expand_short_summary(title, name, link)

            items.append(
                RawItem(
                    source=name,
                    title=title,
                    url=link,
                    raw_text=f"标题: {title}\n来源: {name}\n摘要: {description[:800] or '（无摘要）'}",
                    default_tags=list(default_tags),
                    extra={"description": description[:500]},
                )
            )

        stats.rss_ok.append(name)
        logger.info("[Step 2] %s 采集 %d 条（回源补正文 %d 条）", name, len(parsed), enriched_count)
        if skipped_enrich:
            logger.warning(
                "[Step 2] %s 有 %d 条摘要过短但已达单源回源上限 %d，未补正文",
                name, skipped_enrich, MAX_ENRICH_PER_SOURCE,
            )

    logger.info(
        "[Step 2] RSS 采集完成：成功 %d 源 / 失败 %d 源，共 %d 条",
        len(stats.rss_ok),
        len(stats.rss_failed),
        len(items),
    )
    return items


# ---------------------------------------------------------------------------
# Step 3: AI 分析（计费）
# ---------------------------------------------------------------------------


def _extract_json(text: str) -> dict[str, Any]:
    """从模型输出中抽取 JSON 对象，容忍 markdown 代码块包裹。

    Args:
        text: 模型原始输出。

    Returns:
        解析后的字典。

    Raises:
        ValueError: 找不到或无法解析 JSON。
    """
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.+?)\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()

    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError(f"输出中没有 JSON 对象: {text[:120]!r}")

    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON 解析失败: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError(f"JSON 顶层不是对象: {type(data).__name__}")
    return data


def _normalize_tags(tags: Any, fallback: list[str]) -> list[str]:
    """把模型返回的标签裁剪到白名单内，最多 3 个。

    Args:
        tags: 模型返回的原始标签（任意类型）。
        fallback: 白名单裁剪后为空时使用的兜底标签。

    Returns:
        1-3 个合法标签。
    """
    cleaned: list[str] = []
    if isinstance(tags, list):
        for tag in tags:
            if not isinstance(tag, str):
                continue
            normalized = tag.strip().lower()
            if normalized in VALID_TAGS and normalized not in cleaned:
                cleaned.append(normalized)

    if not cleaned:
        cleaned = [t for t in fallback if t in VALID_TAGS] or ["llm"]
    return cleaned[:3]


def rule_based_analyze(item: RawItem) -> dict[str, Any]:
    """不调 LLM 的降级分析：截取原文 + 关键词映射标签。

    Args:
        item: 待分析的原始条目。

    Returns:
        含 summary / tags / score / audience 的字典。
    """
    description = str(item.extra.get("description") or "").strip()
    body = description or item.raw_text.replace("\n", " ")
    summary = f"{item.title}｜{body}"[:180].strip()
    if len(summary) < 20:
        summary = f"{item.title}（来源 {item.source}）该条目未经 LLM 分析，仅保留原始标题与链接。"

    haystack = f"{item.title} {body}".lower()
    tags = [tag for keyword, tag in KEYWORD_TAGS if keyword in haystack]
    deduped: list[str] = []
    for tag in tags + item.default_tags:
        if tag in VALID_TAGS and tag not in deduped:
            deduped.append(tag)

    stars = int(item.extra.get("stars") or 0)
    score = 6 if stars >= 1000 else 5

    return {
        "summary": summary,
        "tags": (deduped or ["llm"])[:3],
        "score": score,
        "audience": "intermediate",
    }


def analyze_items(
    items: list[RawItem],
    provider_name: str,
    stats: PipelineStats,
    *,
    enabled: bool = True,
) -> list[dict[str, Any]]:
    """对每条原始条目做 AI 分析（失败自动降级为规则分析）。

    Args:
        items: 待分析条目。
        provider_name: LLM 提供商标识。
        stats: 统计对象，就地更新。
        enabled: False 时全部走规则分析，一次 LLM 都不调。

    Returns:
        与 items 等长的分析结果列表。
    """
    if not enabled:
        logger.info("[Step 3] --no-analyze，跳过 LLM，全部使用规则分析")
        results = [rule_based_analyze(item) for item in items]
        stats.analyzed_fallback += len(results)
        return results

    try:
        client = get_provider(provider_name)
    except LLMError as exc:
        logger.warning("[Step 3] 无法初始化 %s（%s），降级为规则分析", provider_name, exc)
        results = [rule_based_analyze(item) for item in items]
        stats.analyzed_fallback += len(results)
        return results

    logger.info("[Step 3] 使用 %s / %s 分析 %d 条", client.name, client.model, len(items))

    results: list[dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        messages = [
            {"role": "system", "content": ANALYZE_SYSTEM_PROMPT},
            {"role": "user", "content": f"请分析以下技术资讯：\n\n{item.raw_text}"},
        ]
        try:
            response = client.chat_with_retry(
                messages, temperature=0.3, max_tokens=500, max_retries=2
            )
            parsed = _extract_json(response.content)
        except (LLMError, ValueError) as exc:
            logger.warning("[Step 3] (%d/%d) %s 分析失败: %s，降级", index, len(items), item.title[:40], exc)
            results.append(rule_based_analyze(item))
            stats.analyzed_fallback += 1
            continue

        summary = str(parsed.get("summary") or "").strip()
        if len(summary) < 20:
            summary = rule_based_analyze(item)["summary"]

        raw_score = parsed.get("score")
        try:
            score = int(round(float(raw_score)))
        except (TypeError, ValueError):
            score = 5
        score = max(1, min(10, score))

        audience = str(parsed.get("audience") or "intermediate").strip().lower()
        if audience not in {"beginner", "intermediate", "advanced"}:
            audience = "intermediate"

        results.append(
            {
                "summary": summary,
                "tags": _normalize_tags(parsed.get("tags"), item.default_tags),
                "score": score,
                "audience": audience,
                "analyzed_by": f"{client.name}/{client.model}",
            }
        )
        stats.analyzed_llm += 1
        logger.info("[Step 3] (%d/%d) ✓ %s → score=%d", index, len(items), item.title[:40], score)

    return results


# ---------------------------------------------------------------------------
# Step 4: 整理入库（免费）
# ---------------------------------------------------------------------------


def _slugify_source(name: str) -> str:
    """把源名规范成 ID 允许的 ``[a-z0-9_]+`` 形式。

    Args:
        name: 原始源名。

    Returns:
        规范化后的短标识。
    """
    slug = re.sub(r"[^a-z0-9_]+", "_", name.lower()).strip("_")
    return slug or "unknown"


def _existing_urls(articles_dir: Path) -> set[str]:
    """收集已入库文章的 source_url，用于去重。

    Args:
        articles_dir: 文章目录。

    Returns:
        已存在的 URL 集合。
    """
    urls: set[str] = set()
    for path in articles_dir.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(data, dict) and isinstance(data.get("source_url"), str):
            urls.add(data["source_url"])
    return urls


def save_articles(
    items: list[RawItem],
    analyses: list[dict[str, Any]],
    stats: PipelineStats,
    *,
    articles_dir: Path = ARTICLES_DIR,
) -> list[Article]:
    """把分析结果写入 knowledge/articles/，一条一个 JSON 文件。

    ID 格式 ``{source}-{YYYYMMDD}-{NNN}``，与 validate_json.py 的正则一致。
    已存在相同 source_url 的条目会被跳过。

    Args:
        items: 原始条目。
        analyses: 与 items 一一对应的分析结果。
        stats: 统计对象，就地更新。
        articles_dir: 输出目录。

    Returns:
        实际写入的 Article 列表。
    """
    articles_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    now_iso = datetime.now(timezone.utc).isoformat()

    seen_urls = _existing_urls(articles_dir)
    counters: dict[str, int] = {}
    saved: list[Article] = []

    for item, analysis in zip(items, analyses):
        if item.url in seen_urls:
            stats.skipped_duplicate += 1
            logger.debug("[Step 4] 跳过重复: %s", item.url)
            continue
        seen_urls.add(item.url)

        slug = _slugify_source(item.source)
        # 序号从目录里已有的同前缀文件之后接着排，避免覆盖当天早些时候的产出
        if slug not in counters:
            existing = list(articles_dir.glob(f"{slug}-{today}-*.json"))
            counters[slug] = len(existing)
        counters[slug] += 1

        article = Article(
            id=f"{slug}-{today}-{counters[slug]:03d}",
            title=item.title[:200],
            source_url=item.url,
            summary=analysis["summary"],
            tags=analysis["tags"],
            status="review",
            score=analysis["score"],
            collected_at=now_iso,
            source=item.source,
            audience=analysis.get("audience", "intermediate"),
            analyzed_by=analysis.get("analyzed_by", "rule-based"),
            extra=item.extra,
        )

        path = articles_dir / f"{article.id}.json"
        path.write_text(
            json.dumps(asdict(article), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        saved.append(article)
        stats.saved += 1
        logger.debug("[Step 4] 写入 %s", path.name)

    logger.info("[Step 4] 入库完成：写入 %d 条，跳过重复 %d 条", stats.saved, stats.skipped_duplicate)
    return saved


def save_raw(items: list[RawItem], *, raw_dir: Path = RAW_DIR) -> Path | None:
    """把本次采集的原始条目落盘，便于复跑分析而不重复抓取。

    Args:
        items: 原始条目。
        raw_dir: 输出目录。

    Returns:
        写入的文件路径；items 为空时返回 None。
    """
    if not items:
        return None
    raw_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = raw_dir / f"raw-{stamp}.json"
    path.write_text(
        json.dumps([asdict(i) for i in items], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    logger.info("[Step 4] 原始数据已保存: %s", path.relative_to(PROJECT_ROOT))
    return path


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """构造命令行解析器。"""
    parser = argparse.ArgumentParser(
        description="四步知识库流水线：采集 → 分析 → 入库",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--sources", default="github,rss", help="数据源，逗号分隔，可选 github / rss"
    )
    parser.add_argument("--limit", type=int, default=10, help="每个数据源最多采集条数")
    parser.add_argument("--provider", default=None, help="LLM 提供商，默认读 LLM_PROVIDER 或 deepseek")
    parser.add_argument("--verbose", action="store_true", help="输出 DEBUG 级日志")
    parser.add_argument(
        "--no-analyze", action="store_true", help="跳过 Step 3（不调 LLM，零成本）"
    )
    parser.add_argument(
        "--articles-dir", type=Path, default=ARTICLES_DIR, help="文章输出目录"
    )
    return parser


def print_summary(stats: PipelineStats, saved: list[Article]) -> None:
    """打印流水线执行汇总。

    Args:
        stats: 统计对象。
        saved: 本次写入的文章。
    """
    print()
    print("=" * 52)
    print("流水线执行汇总")
    print("=" * 52)
    print(f"Step 1 GitHub 采集: {stats.github_fetched} 条")
    print(f"Step 2 RSS 采集:    {stats.rss_fetched} 条"
          f"（成功 {len(stats.rss_ok)} 源 / 失败 {len(stats.rss_failed)} 源）")
    for name, reason in stats.rss_failed:
        print(f"         ✗ {name}: {reason}")
    print(f"Step 3 AI 分析:     LLM {stats.analyzed_llm} 条 / 规则降级 {stats.analyzed_fallback} 条")
    print(f"Step 4 入库:        写入 {stats.saved} 条，跳过重复 {stats.skipped_duplicate} 条")

    if saved:
        scores = [a.score for a in saved]
        print(f"         平均技术深度评分: {sum(scores) / len(scores):.1f}/10")
        print("         样例:")
        for article in saved[:3]:
            print(f"           · [{article.id}] {article.title[:50]}")
            print(f"             {article.summary[:70]}...")
    print("=" * 52)


def main(argv: list[str] | None = None) -> int:
    """脚本入口。

    Args:
        argv: 不含程序名的命令行参数，None 时读 sys.argv。

    Returns:
        进程退出码：正常 0，无任何采集结果 1。
    """
    args = build_parser().parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    requested = {s.strip().lower() for s in args.sources.split(",") if s.strip()}
    unknown = requested - {"github", "rss"}
    if unknown:
        logger.error("未知数据源: %s，可选 github / rss", ", ".join(sorted(unknown)))
        return 1

    stats = PipelineStats()
    items: list[RawItem] = []

    if "github" in requested:
        github_items = fetch_github_trending(args.limit)
        stats.github_fetched = len(github_items)
        items += github_items
    else:
        logger.info("[Step 1] 未请求 github，跳过")

    if "rss" in requested:
        rss_items = fetch_rss(load_rss_config(), args.limit, stats)
        stats.rss_fetched = len(rss_items)
        items += rss_items
    else:
        logger.info("[Step 2] 未请求 rss，跳过")

    if not items:
        logger.error("没有采集到任何条目，流水线终止")
        return 1

    save_raw(items)

    analyses = analyze_items(items, args.provider, stats, enabled=not args.no_analyze)
    saved = save_articles(items, analyses, stats, articles_dir=args.articles_dir)

    print_summary(stats, saved)
    print()
    print(tracker.report())
    return 0


if __name__ == "__main__":
    sys.exit(main())
