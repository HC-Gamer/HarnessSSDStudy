#!/usr/bin/env python3
"""V3 管线 CLI 入口。

用法::

    ./run.sh --topic "AI agent" --limit 5 --verbose
    python -m v3_pipeline.main --topic "LangGraph" --provider deepseek
    python -m v3_pipeline.main --dry-run          # 跑图但不落盘
    python -m v3_pipeline.main --no-strict        # 出口校验失败也照写（不建议）

退出码是给 CI 用的，三档分开，便于在 workflow 里区别对待：

===  ==========================================================
码   含义
===  ==========================================================
0    成功，产出已落盘
1    运行异常（网络、密钥、依赖）
2    schema 校验未通过——**数据坏了，不是程序坏了**，需要人看
===  ==========================================================

把校验失败单独编码成 2，是因为它和「程序崩了」要采取的动作完全不同：
崩了该重试，数据坏了重试一百次也一样。
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from v3_pipeline.graph import REPO_ROOT, PipelineConfig, run_pipeline, tracker

logger = logging.getLogger("v3-pipeline")

#: 校验失败的专用退出码
EXIT_VALIDATION_FAILED = 2


def build_parser() -> argparse.ArgumentParser:
    """构造命令行解析器。

    Returns:
        配置好的 ArgumentParser。
    """
    parser = argparse.ArgumentParser(
        prog="v3-pipeline",
        description="V3 知识管线（LangGraph 图编排 + 段间 schema 校验 + 质量门禁）",
    )
    parser.add_argument("--topic", default="AI agent", help="研究主题（默认 'AI agent'）")
    parser.add_argument("--limit", type=int, default=3, help="每个 RSS 源采集几条（默认 3）")
    parser.add_argument("--provider", choices=["deepseek", "qwen", "openai"], default=None,
                        help="LLM 提供商，默认按 LLM_PROVIDER 环境变量")
    parser.add_argument("--model", default=None, help="模型名覆盖")
    parser.add_argument("--max-rewrites", type=int, default=3, help="重写次数上限（默认 3）")
    parser.add_argument("--output-dir", type=Path, default=REPO_ROOT / "knowledge",
                        help="知识库根目录（默认 <repo>/knowledge）")
    parser.add_argument("--no-real-rss", action="store_true",
                        help="不抓真实 RSS，走 LLM 模拟（离线冒烟用）")
    parser.add_argument("--dry-run", action="store_true", help="跑图但不落盘")
    parser.add_argument("--no-strict", action="store_true",
                        help="出口校验失败也照常落盘（不建议，CI 不要用）")
    parser.add_argument("--report", type=Path, default=None,
                        help="把运行结果 JSON 另存一份到指定路径")
    parser.add_argument("--verbose", action="store_true", help="打印 DEBUG 日志")
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI 入口。

    Args:
        argv: 命令行参数，默认取 ``sys.argv[1:]``。

    Returns:
        退出码，取值见模块 docstring。
    """
    args = build_parser().parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        force=True,  # langgraph_experiment 在 import 时配过一次，这里覆盖掉
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)

    config = PipelineConfig(
        topic=args.topic,
        limit=args.limit,
        provider=args.provider,
        model=args.model,
        max_rewrites=args.max_rewrites,
        use_real_rss=not args.no_real_rss,
        output_dir=args.output_dir,
        dry_run=args.dry_run,
        strict=not args.no_strict,
    )

    try:
        result = run_pipeline(config)
    except KeyboardInterrupt:
        logger.error("被中断")
        return 1
    except Exception as exc:  # noqa: BLE001 - CLI 边界，任何异常都要转成退出码
        logger.exception("运行失败: %s", exc)
        return 1

    payload = result.as_dict()
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("运行报告已保存: %s", args.report)

    tracker.report()  # 内部已经 logger.info 输出，不要再 print 一遍

    if not result.ok:
        print(f"\n❌ 失败：{result.failure_reason}")
        for message in result.validation[1]:
            print(f"   ✗ {message}")
        return EXIT_VALIDATION_FAILED

    print(f"\n✅ 完成 | 质量 {result.quality_score}/100 | "
          f"{result.llm_calls} 次调用 | {result.tokens:,} tokens | ¥{result.cost_cny:.4f}")
    for path in result.written:
        print(f"   → {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
