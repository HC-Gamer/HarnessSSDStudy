#!/usr/bin/env python3
"""
V1 管线测试脚本 — 模拟 Collector → Analyzer → Organizer 三步流程
不依赖 OpenCode TUI，直接运行即可验证管线逻辑。

用法: python3 run_v1_pipeline.py
"""

import json
import os
import sys
from datetime import date
from typing import Any, Dict, List


PIPELINE_DIR = os.path.dirname(os.path.abspath(__file__))
RAW_DIR = os.path.join(PIPELINE_DIR, "knowledge", "raw")
ARTICLES_DIR = os.path.join(PIPELINE_DIR, "knowledge", "articles")


def step1_collect() -> Dict[str, Any]:
    """模拟 Collector Agent：输出采集数据格式。"""
    print("=" * 60)
    print("[Collector] 采集 GitHub Trending AI 项目...")
    print("=" * 60)

    # Collector 不自写文件，返回结构化数据
    output = {
        "source": "github-trending",
        "skill": "github-trending",
        "collected_at": f"{date.today().isoformat()}T00:00:00Z",
        "items": [
            {
                "name": "openai/codex",
                "url": "https://github.com/openai/codex",
                "summary": "Codex：OpenAI 的代码生成模型，支持多语言编程任务",
                "stars": 45200,
                "language": "Python",
                "topics": ["ai", "llm", "code-generation"],
            },
            {
                "name": "meta-llama/llama-cookbook",
                "url": "https://github.com/meta-llama/llama-cookbook",
                "summary": "Llama Cookbook：Meta 官方 Llama 模型使用指南和最佳实践集合",
                "stars": 12800,
                "language": "Python",
                "topics": ["llm", "meta", "cookbook"],
            },
            {
                "name": "langchain-ai/langgraph",
                "url": "https://github.com/langchain-ai/langgraph",
                "summary": "LangGraph：构建有状态多 Agent 应用的框架，支持循环和条件分支",
                "stars": 8900,
                "language": "Python",
                "topics": ["agent", "framework", "langchain"],
            },
            {
                "name": "microsoft/autogen",
                "url": "https://github.com/microsoft/autogen",
                "summary": "AutoGen：微软多 Agent 对话框架，支持 LLM 协作完成任务",
                "stars": 34500,
                "language": "Python",
                "topics": ["agent", "multi-agent", "microsoft"],
            },
            {
                "name": "anthropics/claude-code",
                "url": "https://github.com/anthropics/claude-code",
                "summary": "Claude Code：Anthropic 的 AI 编程助手，集成终端和编辑器",
                "stars": 15000,
                "language": "TypeScript",
                "topics": ["ai", "coding", "cli"],
            },
            {
                "name": "n8n-io/n8n",
                "url": "https://github.com/n8n-io/n8n",
                "summary": "n8n：开源工作流自动化工具，支持 AI Agent 节点和 400+ 集成",
                "stars": 56000,
                "language": "TypeScript",
                "topics": ["automation", "workflow", "ai"],
            },
            {
                "name": "crewAIInc/crewAI",
                "url": "https://github.com/crewAIInc/crewAI",
                "summary": "crewAI：多 Agent 协作框架，让 AI Agent 像团队一样分工合作",
                "stars": 28000,
                "language": "Python",
                "topics": ["agent", "multi-agent", "framework"],
            },
            {
                "name": "comfyanonymous/ComfyUI",
                "url": "https://github.com/comfyanonymous/ComfyUI",
                "summary": "ComfyUI：基于节点的 Stable Diffusion 工作流界面",
                "stars": 62000,
                "language": "Python",
                "topics": ["ai", "image-generation", "ui"],
            },
            {
                "name": "ggerganov/llama.cpp",
                "url": "https://github.com/ggerganov/llama.cpp",
                "summary": "llama.cpp：C/C++ 实现的 LLM 推理引擎，支持本地 CPU 运行",
                "stars": 75000,
                "language": "C",
                "topics": ["llm", "inference", "cpp"],
            },
            {
                "name": "hiyouga/LLaMA-Factory",
                "url": "https://github.com/hiyouga/LLaMA-Factory",
                "summary": "LLaMA Factory：高效 Llama 微调框架，支持 LoRA/QLoRA 等多种方法",
                "stars": 42000,
                "language": "Python",
                "topics": ["llm", "fine-tuning", "lora"],
            },
            {
                "name": "apache/airflow",
                "url": "https://github.com/apache/airflow",
                "summary": "Airflow：Apache 工作流调度平台，适合构建数据 pipeline",
                "stars": 38000,
                "language": "Python",
                "topics": ["workflow", "scheduler", "data-pipeline"],
            },
            {
                "name": "pola-rs/polars",
                "url": "https://github.com/pola-rs/polars",
                "summary": "Polars：Rust 实现的 DataFrame 库，比 Pandas 快 10-100 倍",
                "stars": 32000,
                "language": "Rust",
                "topics": ["dataframe", "performance", "rust"],
            },
            {
                "name": "khoj-ai/khoj",
                "url": "https://github.com/khoj-ai/khoj",
                "summary": "Khoj：开源 AI 个人助手，支持本地文档搜索和问答",
                "stars": 18000,
                "language": "Python",
                "topics": ["ai", "search", "assistant"],
            },
            {
                "name": "opentofu/opentofu",
                "url": "https://github.com/opentofu/opentofu",
                "summary": "OpenTofu：Terraform 的开源替代，基础设施即代码工具",
                "stars": 24000,
                "language": "Go",
                "topics": ["infrastructure", "iac", "devops"],
            },
            {
                "name": "stanfordnlp/dspy",
                "url": "https://github.com/stanfordnlp/dspy",
                "summary": "DSPy：斯坦福的编程框架，用编译器范式优化 LLM 提示和管道",
                "stars": 22000,
                "language": "Python",
                "topics": ["llm", "framework", "optimization"],
            },
        ],
    }

    # 写入 knowledge/raw/
    os.makedirs(RAW_DIR, exist_ok=True)
    filename = f"github-trending-{date.today().isoformat()}.json"
    filepath = os.path.join(RAW_DIR, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"  采集完成: {len(output['items'])} 条")
    print(f"  写入: {filepath}")
    print()
    return output


def step2_analyze(raw_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """模拟 Analyzer Agent：给每条数据打分、写摘要。"""
    print("=" * 60)
    print("[Analyzer] 深度分析采集数据...")
    print("=" * 60)

    # Analyzer 不自写文件，只返回结果
    results = []
    for item in raw_data["items"]:
        # 模拟评分逻辑（根据 stars 和 topics 综合判断）
        stars = item["stars"]
        if stars >= 40000 and "ai" in str(item["topics"]):
            score = 9
            reason = "超高星数 + AI 核心领域，行业标杆项目"
        elif stars >= 20000:
            score = 8
            reason = "高星数，社区活跃，技术价值显著"
        elif stars >= 10000:
            score = 7
            reason = "中等星数，有明确技术亮点和应用场景"
        else:
            score = 6
            reason = "值得关注，但影响力有限"

        # 强制 9 分不超 2 个
        if score == 9 and len([r for r in results if r.get("relevance_score") == 9]) >= 2:
            score = 8
            reason = "高星数 AI 项目，评分已饱和"

        results.append(
            {
                "name": item["name"],
                "summary": item["summary"][:50],
                "highlights": [
                    f"{item['language']} 实现，{stars:,} stars",
                    f"主要领域: {', '.join(item['topics'][:2])}",
                ],
                "relevance_score": score,
                "score_reason": reason,
                "tags": item["topics"][:3],
            }
        )

    print(f"  分析完成: {len(results)} 条")
    scores = [r["relevance_score"] for r in results]
    print(f"  评分范围: {min(scores)}-{max(scores)}")
    print(f"  9 分数量: {scores.count(9)}（约束 ≤ 2）")
    print()
    return results


def step3_organize(
    raw_data: Dict[str, Any], analyzed: List[Dict[str, Any]]
) -> List[str]:
    """模拟 Organizer Agent：格式化为知识条目，写入 knowledge/articles/。"""
    print("=" * 60)
    print("[Organizer] 整理归档知识条目...")
    print("=" * 60)

    os.makedirs(ARTICLES_DIR, exist_ok=True)
    created_files = []

    # 简单去重：检查已有文件的 source_url
    existing_urls = set()
    if os.listdir(ARTICLES_DIR):
        for fname in os.listdir(ARTICLES_DIR):
            if fname.endswith(".json"):
                try:
                    with open(os.path.join(ARTICLES_DIR, fname), "r") as f:
                        existing = json.load(f)
                        existing_urls.add(existing.get("source_url", ""))
                except (json.JSONDecodeError, FileNotFoundError):
                    pass

    for raw_item, analyzed_item in zip(raw_data["items"], analyzed):
        source_url = raw_item["url"]
        if source_url in existing_urls:
            print(f"  ⏭ 跳过（已存在）: {raw_item['name']}")
            continue

        slug = raw_item["name"].replace("/", "-").lower()
        entry = {
            "id": f'{date.today().isoformat()}-github-{slug}',
            "title": raw_item["name"],
            "source": "github-trending",
            "source_url": source_url,
            "collected_at": raw_data["collected_at"],
            "summary": analyzed_item["summary"],
            "analysis": {
                "tech_highlights": analyzed_item["highlights"],
                "relevance_score": analyzed_item["relevance_score"],
                "score_reason": analyzed_item["score_reason"],
            },
            "tags": analyzed_item["tags"],
            "status": "draft",
        }

        filename = f'{date.today().isoformat()}-github-{slug}.json'
        filepath = os.path.join(ARTICLES_DIR, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(entry, f, ensure_ascii=False, indent=2)
        created_files.append(filepath)

    print(f"  新建条目: {len(created_files)} 个")
    if existing_urls:
        print(f"  去重跳过: {len(raw_data['items']) - len(created_files)} 个（基于 URL hash）")
    print()
    return created_files


def main():
    print()
    print("🚀 V1 Pipeline — Collector → Analyzer → Organizer")
    print(f"   日期: {date.today().isoformat()}")
    print(f"   工作目录: {PIPELINE_DIR}")
    print()

    # Step 1: Collect
    raw_data = step1_collect()

    # Step 2: Analyze
    analyzed = step2_analyze(raw_data)

    # Step 3: Organize
    created = step3_organize(raw_data, analyzed)

    print("=" * 60)
    print(f"✅ V1 管线完成")
    print(f"   采集: {len(raw_data['items'])} 条")
    print(f"   分析: {len(analyzed)} 条")
    print(f"   归档: {len(created)} 个新条目")
    print("=" * 60)


if __name__ == "__main__":
    main()
