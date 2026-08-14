"""daily_digest.py — 每日推送入口。

流程：加载全库文章 → 按 `RELEVANCE_THRESHOLD` 过滤低质量条目 → 取最近
`DIGEST_ARTICLE_COUNT` 篇 → 调用 `distribution.publisher.publish_daily_digest()`
并发推送到所有渠道 → 打印汇总。

用法：
    python3 daily_digest.py              # 正常推送（无 token 自动 dry-run）
    python3 daily_digest.py --dry-run    # 强制 dry-run，即便配置了 token
"""

import argparse
import asyncio
import logging

from distribution.formatter import load_articles
from distribution.publisher import publish_daily_digest

logger = logging.getLogger(__name__)

# relevance_score 是 0–1 浮点（AGENTS.md §3.2），本项目一律用这个量纲，
# 不采用课件里 0-100 量纲的旧口径。
RELEVANCE_THRESHOLD = 0.6

# 每次简报取最近入库的文章数量上限。
DIGEST_ARTICLE_COUNT = 10


def _select_digest_articles() -> list[dict]:
    """加载全库文章，过滤低质量条目，取最近 `DIGEST_ARTICLE_COUNT` 篇。

    Returns:
        按 published_at/analyzed_at/fetched_at 降序排列的高质量文章列表。
    """
    articles = load_articles()
    qualified = [a for a in articles if a.get("relevance_score", 0.0) >= RELEVANCE_THRESHOLD]
    qualified.sort(
        key=lambda a: a.get("published_at") or a.get("analyzed_at") or a.get("fetched_at") or "",
        reverse=True,
    )
    return qualified[:DIGEST_ARTICLE_COUNT]


async def main(dry_run: bool) -> None:
    """每日推送主流程。"""
    print("=" * 50)
    print("  AI 知识库 — 每日摘要推送")
    print("=" * 50)

    articles = _select_digest_articles()
    if not articles:
        logger.warning("无 relevance_score >= %.1f 的高质量文章，跳过本次推送", RELEVANCE_THRESHOLD)
        print(f"⚠️  无高质量文章（阈值 {RELEVANCE_THRESHOLD}），跳过本次推送")
        return

    print(f"本次简报文章数：{len(articles)}")
    results = await publish_daily_digest(articles=articles, dry_run=dry_run)

    success = sum(1 for r in results if r.success)
    print(f"\n推送结果: {success}/{len(results)} 个渠道成功")
    for r in results:
        status = "✅" if r.success else "❌"
        print(f"  {status} {r.channel}: {r.message_id or r.error or 'OK'}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    parser = argparse.ArgumentParser(description="AI 知识库每日推送入口")
    parser.add_argument(
        "--dry-run", action="store_true", help="强制 dry-run，不真实发送（即便配置了 token）"
    )
    args = parser.parse_args()

    asyncio.run(main(dry_run=args.dry_run))
