#!/usr/bin/env python3
"""真实 RSS / Atom 采集 —— Wk3 实验 Bug #3 的修复。

旧实现的 ``search_node`` 用 LLM 生成「模拟 GitHub Trending / RSS 结果」，
好处是可重复、零外部依赖，坏处是产出文章里的 star 数、论文结论、性能百分比
全是模型编的（详见 EXPERIMENT_REPORT.md「已知问题 #3」）。

本模块复用 Wk2 v2-pipeline 的 ``pipeline/rss_sources.yaml`` 源列表，用 httpx
直接抓真实 feed，标准库 ``xml.etree`` 解析 Atom 与 RSS 2.0 两种格式。

设计取舍：
* 只取前 N 个 **enabled** 源、每源前 M 条，够做采集验证就行，不追求覆盖
* 抓不动就降级 —— 返回空列表，由调用方决定是回退到 LLM 模拟还是直接失败
* 不落盘、不去重 —— 这两件事是 Wk2 pipeline 的职责，这里只负责「拿到真东西」
"""

from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

import httpx
import yaml

logger = logging.getLogger("rss-collector")

#: Wk2 v2-pipeline 的 RSS 源配置，本模块直接复用，不再维护第二份源列表。
DEFAULT_SOURCES_YAML = (
    Path(__file__).parents[3]
    / "Wk2"
    / "experiments"
    / "v2-pipeline"
    / "pipeline"
    / "rss_sources.yaml"
)

ATOM_NS = "{http://www.w3.org/2005/Atom}"
DEFAULT_TIMEOUT = 20.0
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "HarnessSSDStudy-Wk3/1.0 (+https://github.com/HC-Gamer/HarnessSSDStudy)"
    ),
    "Accept": "application/atom+xml, application/rss+xml, application/xml, text/xml, */*",
}

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


@dataclass
class FeedEntry:
    """一条真实采集到的 feed 条目。

    Attributes:
        source: 源标识（对应 rss_sources.yaml 的 name）。
        title: 条目标题。
        url: 条目链接。
        summary: 条目摘要 / 描述，已去 HTML 标签并截断。
    """

    source: str
    title: str
    url: str
    summary: str

    def as_text(self) -> str:
        """渲染为供 LLM 分析的纯文本块。"""
        return f"[{self.source}] {self.title}\n{self.url}\n{self.summary}"


def _clean(text: str | None, limit: int = 600) -> str:
    """去 HTML 标签、反转义实体、压缩空白并截断。

    Args:
        text: 原始文本，可能含 HTML。
        limit: 截断长度上限。

    Returns:
        清洗后的纯文本。
    """
    if not text:
        return ""
    plain = _TAG_RE.sub(" ", text)
    plain = html.unescape(plain)
    plain = _WS_RE.sub(" ", plain).strip()
    return plain[:limit]


def load_sources(path: Path | None = None) -> list[dict[str, object]]:
    """读取 rss_sources.yaml 中启用的源。

    Args:
        path: 配置文件路径，默认用 Wk2 v2-pipeline 的那份。

    Returns:
        enabled 为 true 的源配置列表；文件不存在时返回空列表。
    """
    path = path or DEFAULT_SOURCES_YAML
    if not path.exists():
        logger.warning("RSS 源配置不存在: %s", path)
        return []

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    sources = [s for s in data.get("sources", []) if s.get("enabled")]
    logger.info("从 %s 载入 %d 个启用的 RSS 源", path.name, len(sources))
    return sources


def _parse_feed(xml_text: str, source_name: str, limit: int) -> list[FeedEntry]:
    """解析 Atom 或 RSS 2.0 文本。

    Args:
        xml_text: feed 的原始 XML 文本。
        source_name: 源标识，写进 FeedEntry.source。
        limit: 最多返回条数。

    Returns:
        解析出的条目列表；XML 非法时返回空列表。
    """
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError as exc:
        logger.warning("[%s] XML 解析失败: %s", source_name, exc)
        return []

    entries: list[FeedEntry] = []

    # Atom: <feed><entry><title/><link href/><summary|content/>
    for node in root.findall(f"{ATOM_NS}entry")[:limit]:
        title = _clean(node.findtext(f"{ATOM_NS}title"), 200)
        link_node = node.find(f"{ATOM_NS}link")
        url = link_node.get("href", "") if link_node is not None else ""
        body = node.findtext(f"{ATOM_NS}summary") or node.findtext(f"{ATOM_NS}content") or ""
        entries.append(FeedEntry(source_name, title, url, _clean(body)))

    # RSS 2.0: <rss><channel><item><title/><link/><description/>
    if not entries:
        for node in root.findall(".//item")[:limit]:
            title = _clean(node.findtext("title"), 200)
            url = _clean(node.findtext("link"), 300)
            body = node.findtext("description") or node.findtext("content:encoded") or ""
            entries.append(FeedEntry(source_name, title, url, _clean(body)))

    return [e for e in entries if e.title]


def fetch_source(source: dict[str, object], limit: int = 2) -> list[FeedEntry]:
    """抓取单个源（含 fallback_urls 依次重试）。

    Args:
        source: rss_sources.yaml 中的一个源配置。
        limit: 该源最多取几条。

    Returns:
        采集到的条目；全部地址都失败时返回空列表。
    """
    name = str(source.get("name", "unknown"))
    urls = [str(source["url"])] + [str(u) for u in (source.get("fallback_urls") or [])]

    for url in urls:
        try:
            response = httpx.get(
                url,
                headers=DEFAULT_HEADERS,
                timeout=DEFAULT_TIMEOUT,
                follow_redirects=True,
            )
        except httpx.HTTPError as exc:
            logger.warning("[%s] 请求失败 %s: %s", name, url, exc)
            continue

        if response.status_code != 200:
            logger.warning("[%s] HTTP %d %s", name, response.status_code, url)
            continue

        entries = _parse_feed(response.text, name, limit)
        if entries:
            logger.info("[%s] 采集成功 %d 条 ← %s", name, len(entries), url)
            return entries
        logger.warning("[%s] 解析到 0 条: %s", name, url)

    return []


def collect(
    max_sources: int = 2,
    per_source: int = 2,
    sources_path: Path | None = None,
) -> list[FeedEntry]:
    """按顺序尝试多个源，凑够条目就返回。

    Args:
        max_sources: 最多成功采集几个源。
        per_source: 每个源取几条。
        sources_path: 源配置路径。

    Returns:
        真实采集到的条目列表，可能为空（调用方需处理降级）。
    """
    collected: list[FeedEntry] = []
    ok_sources = 0

    for source in load_sources(sources_path):
        if ok_sources >= max_sources:
            break
        entries = fetch_source(source, per_source)
        if entries:
            collected.extend(entries)
            ok_sources += 1

    logger.info("真实采集合计 %d 条，来自 %d 个源", len(collected), ok_sources)
    return collected


def entries_to_raw_content(entries: list[FeedEntry], topic: str) -> tuple[str, list[str]]:
    """把条目列表渲染成 ``(raw_content, sources)``。

    Args:
        entries: 采集到的条目。
        topic: 本次实验主题，写进 raw_content 头部作为分析上下文。

    Returns:
        (拼接后的原始文本, 来源 URL 列表)。
    """
    header = f"# 研究主题: {topic}\n# 采集方式: 真实 RSS/Atom feed ({len(entries)} 条)\n"
    body = "\n\n".join(e.as_text() for e in entries)
    sources = [e.url or f"{e.source} (无链接)" for e in entries]
    return header + "\n" + body, sources


def _self_test() -> int:
    """抓一次真实 feed 并打印结果，用于验证网络与解析都通。

    Returns:
        退出码：一条都没抓到时返回 1。
    """
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    entries = collect(max_sources=2, per_source=2)
    for entry in entries:
        print("-" * 70)
        print(f"source : {entry.source}")
        print(f"title  : {entry.title}")
        print(f"url    : {entry.url}")
        print(f"summary: {entry.summary[:120]}...")
    print("-" * 70)
    print(f"合计 {len(entries)} 条")
    return 0 if entries else 1


if __name__ == "__main__":
    raise SystemExit(_self_test())
