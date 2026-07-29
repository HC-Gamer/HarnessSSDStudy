#!/usr/bin/env python3
"""Wk3 实验：LangGraph 状态图编排 vs 线性管线

对比 V1 (collector→analyzer→organizer 线性管线) 与
LangGraph 状态图方案（共享状态 + 条件路由 + 质量反馈循环）。

实验维度：
1. 状态管理：文件传递 vs StateGraph shared state
2. 条件路由：线性 must-pass vs 图编排 conditional edge
3. 反馈循环：人工重跑 vs 自动 rewrite loop
4. 成本对比：Token 消耗统计
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Literal, Optional
from pathlib import Path

# ── 确保可以引用 model_client ────────────────────────────────────
sys.path.insert(
    0,
    str(
        Path(__file__).parents[3] / "Wk2" / "experiments" / "v2-pipeline"
    ),
)

from dotenv import load_dotenv

load_dotenv()

from pipeline.model_client import quick_chat

# 使用 model_client 的全局 tracker（quick_chat 内部自动记录到此）
import pipeline.model_client as mc

# ── LangGraph ─────────────────────────────────────────────────────
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("langgraph-experiment")

# ═══════════════════════════════════════════════════════════════════
# 1. 状态定义
# ═══════════════════════════════════════════════════════════════════


class PipelineState(TypedDict):
    """LangGraph 共享状态 —— 所有节点共享同一个 dict。

    对比 V1：V1 用文件系统传递（collector → knowledge/raw/xxx.json →
    analyzer → stdout → organizer → knowledge/articles/xxx.json）。
    LangGraph 所有节点直接读写同一份 state dict，不需要 I/O 中介。
    """

    # 输入
    topic: str  # 研究主题

    # Collector 产出
    raw_content: str  # 原始采集内容
    sources: list[str]  # 来源列表

    # Analyzer 产出
    summary: str  # 摘要
    key_points: list[str]  # 关键要点
    quality_score: int  # 质量评分 0-100

    # Organizer 产出
    article_title: str  # 最终文章标题
    article_body: str  # 最终文章正文

    # 路由控制
    rewrite_count: int  # 已重写次数（最大3次）
    should_rewrite: bool  # 是否需要重写

    # 统计
    tokens_used: int  # 累计 Token 消耗
    call_count: int  # LLM 调用次数


def make_initial_state(topic: str) -> PipelineState:
    return PipelineState(
        topic=topic,
        raw_content="",
        sources=[],
        summary="",
        key_points=[],
        quality_score=0,
        article_title="",
        article_body="",
        rewrite_count=0,
        should_rewrite=False,
        tokens_used=0,
        call_count=0,
    )


# ═══════════════════════════════════════════════════════════════════
# 2. LLM 调用包装（带 Token 统计）
# ═══════════════════════════════════════════════════════════════════

# 使用 model_client 模块的全局 tracker（chat 内部自动记录至此）
tracker = mc.tracker


def quick_chat_local(prompt: str, system: str = "") -> str:
    """调用 LLM 并统计消耗。"""
    result = quick_chat(prompt, system=system if system else None)
    return result


# ═══════════════════════════════════════════════════════════════════
# 3. 节点函数
# ═══════════════════════════════════════════════════════════════════


def search_node(state: PipelineState) -> dict[str, Any]:
    """Node 1: 采集 —— 模拟 Collector

    V1 Collector 用 WebFetch 工具爬取 GitHub Trending。
    这里用 LLM 生成模拟采集内容（保持实验可重复）。
    真实场景可替换为 MCP web_fetch tool。
    """
    logger.info(f"[search_node] 采集主题: {state['topic']}")

    prompt = f"""你是一个信息采集 Agent。用户关注的主题是：「{state['topic']}」

请模拟一次 GitHub Trending + RSS 采集的结果。返回 JSON 格式：
{{
  "sources": ["source1", "source2", ...],
  "raw_content": "模拟采集到的原始文本，至少 300 字"
}}

只返回 JSON，不要额外说明。"""

    result = quick_chat_local(prompt)
    try:
        data = json.loads(result)
    except json.JSONDecodeError:
        data = {"sources": ["mock-source"], "raw_content": result}

    return {
        "raw_content": data.get("raw_content", result),
        "sources": data.get("sources", ["mock-source"]),
        "call_count": state.get("call_count", 0) + 1,
    }


def analyze_node(state: PipelineState) -> dict[str, Any]:
    """Node 2: 分析 —— 对标 Analyzer

    V1 Analyzer 从 raw JSON 提取摘要 + 关键点 + 标签。
    """
    logger.info(f"[analyze_node] 分析原始内容 ({len(state['raw_content'])} chars)")

    prompt = f"""分析以下原始内容，提取核心信息：

{state['raw_content'][:2000]}

返回 JSON 格式：
{{
  "summary": "80-120 字中文摘要",
  "key_points": ["要点1", "要点2", "要点3", "要点4", "要点5"]
}}

只返回 JSON。"""

    system = "你是一个技术内容分析 Agent。输出简洁、信息密度高。"

    result = quick_chat_local(prompt, system)
    try:
        data = json.loads(result)
    except json.JSONDecodeError:
        data = {"summary": result[:100], "key_points": []}

    summary = data.get("summary", "")
    key_points = data.get("key_points", [])

    # 取中间质量分数
    quality_score = min(
        100,
        max(0, 60 + len(summary) // 5 - (3 - len(key_points)) * 10),
    )

    return {
        "summary": summary,
        "key_points": key_points,
        "quality_score": quality_score,
        "call_count": state.get("call_count", 0) + 1,
    }


def quality_check_node(state: PipelineState) -> dict[str, bool]:
    """Node 3: 质量门禁 —— 条件路由决策

    这是 LangGraph 独有的能力——V1/V2 没有运行时条件路由。
    质量分 < 60 → 走 rewrite 分支；≥ 60 → 走 organize 分支。
    """
    quality = state.get("quality_score", 0)
    rewrites = state.get("rewrite_count", 0)

    logger.info(
        f"[quality_check_node] 质量评分: {quality}/100, 已重写: {rewrites} 次"
    )

    # 质量控制规则：
    # - 分太低 (< 60) → rewrite
    # - 已重写 3 次 → 强制通过（防止死循环）
    should_rewrite = quality < 60 and rewrites < 3
    return {"should_rewrite": should_rewrite}


def rewrite_node(state: PipelineState) -> dict[str, Any]:
    """Node 4: 修正节点 —— 质量反馈循环

    收到 quality_check 的 low-score 信号后，带着反馈重做分析。
    这是 LangGraph 图编排的核心优势——反馈循环。
    """
    logger.info(f"[rewrite_node] 第 {state['rewrite_count'] + 1} 次重写")

    prompt = f"""上次分析质量不足（评分: {state['quality_score']}/100）。
现有摘要：「{state['summary']}」
要点：{json.dumps(state['key_points'], ensure_ascii=False)}

请重新生成更高质量的分析。要求：
- 摘要 150 字以上，包含具体事实
- 要点至少 5 条，每条带一句话解释
- 避免空洞用词（赋能、抓手、闭环等）

原始内容：
{state['raw_content'][:2000]}

返回 JSON：{{"summary": "...", "key_points": [...]}}"""

    result = quick_chat_local(prompt)
    try:
        data = json.loads(result)
    except json.JSONDecodeError:
        data = {"summary": result[:150], "key_points": []}

    new_summary = data.get("summary", state["summary"])
    new_points = data.get("key_points", state["key_points"])
    new_quality = min(100, state["quality_score"] + 20)  # 每次重写+20分

    return {
        "summary": new_summary,
        "key_points": new_points,
        "quality_score": new_quality,
        "rewrite_count": state["rewrite_count"] + 1,
        "call_count": state["call_count"] + 1,
    }


def organize_node(state: PipelineState) -> dict[str, Any]:
    """Node 5: 组织输出 —— 对标 Organizer

    V1 Organizer 格式化输出到 knowledge/articles/*.json。
    LangGraph 版本直接写入共享 state 并返回结构化结果。
    """
    logger.info("[organize_node] 生成最终文章")

    kp_bullets = "\n".join(
        f"- {kp}" for kp in state["key_points"]
    )

    prompt = f"""基于以下分析，写一篇 300-500 字的技术文章。

主题：{state['topic']}
摘要：{state['summary']}
关键要点：
{kp_bullets}
质量评分：{state['quality_score']}/100

风格：技术专栏风格，面向 AI 开发者。
要求：有观点、有深度、有人味儿。"""

    system = "你是一个技术文章写手。输出工整的 Markdown。"

    body = quick_chat_local(prompt, system)

    return {
        "article_title": f"LangGraph 实验报告：{state['topic']}",
        "article_body": body,
        "call_count": state["call_count"] + 1,
    }


def decide_route(
    state: PipelineState,
) -> Literal["rewrite", "organize"]:
    """条件边 —— 根据 quality_check 的结果选择路径。

    这是 LangGraph 的 Conditional Edge，V1 管线做不到。
    函数签名由 LangGraph 约定：接收 state，返回下一节点的名称。
    """
    if state.get("should_rewrite", False):
        logger.info("→ 路由到 rewrite 节点（质量修正循环）")
        return "rewrite"
    logger.info("→ 路由到 organize 节点（通过质量门禁）")
    return "organize"


# ═══════════════════════════════════════════════════════════════════
# 4. 图构建
# ═══════════════════════════════════════════════════════════════════


def build_pipeline_graph() -> StateGraph:
    """构建 LangGraph StateGraph。

    图结构：
        START → search → analyze → quality_check
                                    ├─ (低质量) → rewrite → analyze (循环)
                                    └─ (高质量) → organize → END

    对比 V1 线性结构：
        START → collector → analyzer → organizer → END
    """
    builder = StateGraph(PipelineState)

    # 注册节点
    builder.add_node("search", search_node)
    builder.add_node("analyze", analyze_node)
    builder.add_node("quality_check", quality_check_node)
    builder.add_node("rewrite", rewrite_node)
    builder.add_node("organize", organize_node)

    # 边定义
    builder.add_edge(START, "search")
    builder.add_edge("search", "analyze")
    builder.add_edge("analyze", "quality_check")

    # 条件边 —— LangGraph 独有
    builder.add_conditional_edges(
        "quality_check",
        decide_route,
        {
            "rewrite": "rewrite",
            "organize": "organize",
        },
    )

    # rewrite → analyze：反馈循环
    builder.add_edge("rewrite", "analyze")

    builder.add_edge("organize", END)

    return builder


# ═══════════════════════════════════════════════════════════════════
# 5. 运行实验
# ═══════════════════════════════════════════════════════════════════


def run_experiment(
    topic: str, max_rewrites: int = 3
) -> tuple[dict[str, Any], float]:
    """运行一次完整的 LangGraph 实验。

    Args:
        topic: 研究主题
        max_rewrites: 最大重写次数

    Returns:
        (最终状态, 耗时秒数)
    """
    graph = build_pipeline_graph()
    # 启用内存检查点 —— LangGraph 的 Trajectory 记录
    app = graph.compile(checkpointer=MemorySaver())

    initial = make_initial_state(topic)
    initial["rewrite_count"] = 0
    initial["call_count"] = 0

    # 生成唯一 thread_id（用于 checkpointer）
    thread_id = f"experiment-{int(time.time())}"

    logger.info(f"=" * 60)
    logger.info(f"实验主题: {topic}")
    logger.info(f"Max rewrites: {max_rewrites}")
    logger.info(f"Thread ID: {thread_id}")
    logger.info(f"=" * 60)

    start_time = time.time()

    config = {
        "configurable": {"thread_id": thread_id},
    }

    # 运行图 —— LangGraph 自动处理状态流转 + 条件路由 + 循环
    final_state = app.invoke(initial, config=config)

    elapsed = time.time() - start_time

    logger.info(f"=" * 60)
    logger.info(f"实验完成 | 耗时: {elapsed:.1f}s")
    logger.info(f"LLM 调用: {final_state.get('call_count', 0)} 次")
    logger.info(f"最终质量分: {final_state.get('quality_score', 0)}/100")
    logger.info(f"=" * 60)

    return final_state, elapsed


def run_all_experiments():
    """运行多个实验主题，对比不同场景。"""
    results_dir = Path(__file__).parent / "results"
    results_dir.mkdir(parents=True, exist_ok=True)

    topics = [
        "LangGraph StateGraph vs 线性 Harness 管线架构对比",
        "AI Agent 中的条件路由与反馈循环设计模式",
        "多 Agent 协作中的状态共享机制",
    ]

    all_results = []

    for i, topic in enumerate(topics, 1):
        print(f"\n")
        print(f"{'=' * 70}")
        print(f"  实验 {i}/3: {topic}")
        print(f"{'=' * 70}")

        state, elapsed = run_experiment(topic)

        result = {
            "experiment": i,
            "topic": topic,
            "elapsed_seconds": round(elapsed, 2),
            "llm_calls": state["call_count"],
            "quality_score": state["quality_score"],
            "rewrite_count": state["rewrite_count"],
            "summary": state["summary"],
            "key_points": state["key_points"],
            "article_title": state["article_title"],
            "cost_total_cny": tracker.estimated_cost(),
            "cost_total_usd": tracker.estimated_cost_usd(),
            "total_tokens": tracker.total_tokens,
        }
        all_results.append(result)

        # 保存每次实验的完整文章
        article_path = (
            results_dir / f"experiment_{i}_article.md"
        )
        article_content = f"""# {state['article_title']}

> 主题: {topic}
> 质量评分: {state['quality_score']}/100 | LLM 调用: {state['call_count']} 次
> 重写次数: {state['rewrite_count']}

## 摘要

{state['summary']}

## 关键要点

{chr(10).join(f'- {kp}' for kp in state['key_points'])}

## 正文

{state['article_body']}
"""
        article_path.write_text(article_content)
        logger.info(f"文章已保存: {article_path}")

    return all_results


# ═══════════════════════════════════════════════════════════════════
# 6. 入口
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    results = run_all_experiments()

    # 打印汇总
    print(f"\n")
    print(f"{'=' * 70}")
    print(f"  Wk3 LangGraph 实验汇总")
    print(f"{'=' * 70}")
    for r in results:
        print(f"  [{r['experiment']}] {r['topic'][:40]}...")
        print(f"      调用: {r['llm_calls']} 次 | 质量: {r['quality_score']}/100 "
              f"| 重写: {r['rewrite_count']}x | 耗时: {r['elapsed_seconds']}s")
    print(f"{'=' * 70}")
    print(f"  成本: ¥{tracker.estimated_cost():.4f} / ${tracker.estimated_cost_usd():.4f}")
    print(f"  Token: {tracker.total_tokens:,} | 调用: {tracker.total_calls} 次")
    print(f"{'=' * 70}")
