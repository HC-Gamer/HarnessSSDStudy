"""Eval 评估测试 —— AI 知识库质量验证（课件 12-2）。

AI 系统的输出是不确定的：同一个输入两次调用结果不同，``assert output ==
expected`` 根本不成立。Eval 测试换一个思路：**不测精确内容，测行为边界**。

* 用 ``>=`` / ``<=`` / ``in`` 代替 ``==``；
* 测「有没有摘要」而不是「摘要写了什么」；
* 正面 + 负面 + 边界 = 最小 Eval 集；
* LLM-as-Judge 补上规则断言测不了的「质量」维度。

运行::

    pytest tests/eval_test.py -v          # 只跑不花钱的本地断言
    pytest tests/eval_test.py -m slow -v  # 跑真实 LLM 用例（消耗 token）

文件名注意：官方叫 ``eval_test.py``，不符合 pytest 默认的 ``test_*.py``
发现规则，已在 ``pytest.ini`` 里配 ``python_files``；``tests/test_eval.py``
再做一层别名兜底。
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 加载 .env，让 pytest 也能读到 DEEPSEEK_API_KEY
load_dotenv(PROJECT_ROOT / ".env")

from workflows.analyzer import _normalize_category, _normalize_score  # noqa: E402
from workflows.model_client import chat  # noqa: E402
from workflows.reviewer import (  # noqa: E402
    REVIEWER_PASS_THRESHOLD,
    REVIEWER_WEIGHTS,
    compute_weighted_score,
)

#: 本文件在成本报告里的节点名
NODE_NAME = "eval"

#: LLM-as-Judge 的及格线
JUDGE_MIN_SCORE = 5


# ── 评估用例定义 ──────────────────────────────────────────

EVAL_CASES = [
    {
        "name": "正面案例 — 技术项目分析",
        "input": "LangGraph 是一个基于有向图的多 Agent 工作流编排框架，支持条件分支和循环。",
        "expected": {
            "min_length": 50,
            "max_length": 2000,
            "must_contain_any": ["LangGraph", "工作流", "Agent", "图", "编排"],
        },
    },
    {
        "name": "负面案例 — 无关内容",
        "input": "今天天气真好，适合出去野餐，带上三明治和果汁。",
        "expected": {
            "max_length": 1000,
            "must_contain_any": ["不相关", "无关", "不属于", "并非", "没有关系"],
        },
    },
    {
        "name": "边界案例 — 极短输入",
        "input": "AI",
        "expected": {"min_length": 1, "no_crash": True},
    },
    {
        "name": "正面案例 — 英文技术内容",
        "input": "OpenAI released a model with a 1M token context window and native tool use.",
        "expected": {
            "min_length": 30,
            "must_contain_any": ["OpenAI", "token", "context", "上下文", "工具"],
        },
    },
]


# ── 本地验证（不调 LLM，不花钱）──────────────────────────


def test_eval_cases_structure():
    """EVAL_CASES 结构完整性：三类场景齐全、字段不缺。"""
    assert len(EVAL_CASES) >= 3, "至少需要 3 个评估用例"

    names = [case["name"] for case in EVAL_CASES]
    assert any("正面" in name for name in names), "缺少正面案例"
    assert any("负面" in name for name in names), "缺少负面案例"
    assert any("边界" in name for name in names), "缺少边界案例"

    for case in EVAL_CASES:
        assert "name" in case
        assert case.get("input"), f"用例 {case.get('name')} 缺少 input"
        assert case.get("expected"), f"用例 {case.get('name')} 缺少 expected"


def test_reviewer_weights_sum_to_one():
    """5 维权重必须合计为 1.00，否则加权总分的量纲会漂。"""
    assert abs(sum(REVIEWER_WEIGHTS.values()) - 1.0) < 1e-9
    assert len(REVIEWER_WEIGHTS) == 5


@pytest.mark.parametrize(
    ("scores", "expected"),
    [
        ({d: 10 for d in REVIEWER_WEIGHTS}, 10.0),
        ({d: 0 for d in REVIEWER_WEIGHTS}, 0.0),
        ({d: 7 for d in REVIEWER_WEIGHTS}, 7.0),
        ({"summary_quality": 10, "technical_depth": 10, "relevance": 10,
          "originality": 0, "formatting": 0}, 7.0),
        ({}, 0.0),
    ],
)
def test_weighted_score_recomputed_in_python(scores, expected):
    """加权总分由 Python 重算，不采信模型算术 —— 这里钉死算式。"""
    assert compute_weighted_score(scores) == pytest.approx(expected)


def test_pass_threshold_boundary():
    """通过线是 >= 7.0，边界上下各测一次。"""
    just_pass = {d: 7 for d in REVIEWER_WEIGHTS}
    just_fail = {"summary_quality": 7, "technical_depth": 7, "relevance": 7,
                 "originality": 7, "formatting": 6}
    assert compute_weighted_score(just_pass) >= REVIEWER_PASS_THRESHOLD
    assert compute_weighted_score(just_fail) < REVIEWER_PASS_THRESHOLD


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(0.85, 0.85), (8, 0.8), (85, 0.85), (-1, 0.0), ("bad", 0.0), (None, 0.0)],
)
def test_relevance_score_normalized_to_unit_range(raw, expected):
    """relevance_score 一律归一到 0-1（PLANNING §8.2 的量纲决策）。"""
    assert _normalize_score(raw) == pytest.approx(expected)


def test_category_falls_back_to_whitelist():
    """分类必须落在白名单里，模型乱答也不能污染知识库 schema。"""
    assert _normalize_category("Agent") == "agent"
    assert _normalize_category("多模态 multimodal") == "multimodal"
    assert _normalize_category("外星科技") == "industry"


# ── LLM 评估测试（消耗 token，默认跑，可用 -m "not slow" 跳过）────


@pytest.mark.slow
def test_eval_positive():
    """正面案例：技术内容应生成有意义的分析。"""
    case = EVAL_CASES[0]
    result, _ = chat(
        f"请分析以下技术内容，输出 200 字以内的中文摘要：\n{case['input']}",
        system="你是技术分析师。",
        node_name=NODE_NAME,
    )
    expected = case["expected"]
    assert len(result) >= expected["min_length"], f"输出太短: {len(result)}"
    assert len(result) <= expected["max_length"], f"输出太长: {len(result)}"
    assert any(keyword in result for keyword in expected["must_contain_any"]), (
        f"输出应包含 {expected['must_contain_any']} 之一，实际: {result[:120]}"
    )


@pytest.mark.slow
def test_eval_negative():
    """负面案例：无关内容应被识别为不相关。"""
    case = EVAL_CASES[1]
    result, _ = chat(
        f"请判断以下内容是否与 AI 技术相关，如果不相关请明确说明：\n{case['input']}",
        system="你是技术内容筛选器。",
        node_name=NODE_NAME,
    )
    assert result and len(result) <= case["expected"]["max_length"]
    assert any(word in result for word in case["expected"]["must_contain_any"]), (
        f"应识别为不相关，实际: {result[:120]}"
    )


@pytest.mark.slow
def test_eval_boundary():
    """边界案例：极短输入不应崩溃。"""
    case = EVAL_CASES[2]
    try:
        result, _ = chat(f"请分析：{case['input']}", system="你是技术分析师。",
                         node_name=NODE_NAME)
    except Exception as exc:  # noqa: BLE001 - 这里就是要把崩溃变成失败断言
        pytest.fail(f"边界输入不应导致崩溃: {exc}")
    assert result and len(result) >= case["expected"]["min_length"]


@pytest.mark.slow
def test_llm_as_judge():
    """LLM-as-Judge：让另一次 LLM 调用给分析质量打分，断言 >= 5。"""
    analysis, _ = chat(
        "请分析 LangGraph 框架的核心优势和适用场景",
        system="你是技术分析师。输出 Markdown 格式。",
        node_name=NODE_NAME,
    )

    judge_prompt = f"""请对以下技术分析的质量打分（1-10 分）。

分析内容：
{analysis}

评分标准：
- 准确性：信息是否正确
- 深度：是否有洞察
- 实用性：读者能否据此行动

只返回一个数字（1-10），不要解释。"""

    score_text, _ = chat(
        judge_prompt, system="你是质量评审。只返回数字。", max_tokens=10, node_name=NODE_NAME
    )

    match = re.search(r"\d+", score_text)
    score = int(match.group()) if match else 0

    assert 1 <= score <= 10, f"评分应在 1-10，实际: {score_text!r}"
    assert score >= JUDGE_MIN_SCORE, f"分析质量评分过低: {score}/10"


if __name__ == "__main__":
    print("=== 本地验证（不消耗 token）===")
    test_eval_cases_structure()
    print(f"[OK] EVAL_CASES 结构验证通过，共 {len(EVAL_CASES)} 个用例")
    for eval_case in EVAL_CASES:
        print(f"  - {eval_case['name']}")
    test_reviewer_weights_sum_to_one()
    print("[OK] 5 维权重合计 1.00")
    test_pass_threshold_boundary()
    print(f"[OK] 通过线边界正确（>= {REVIEWER_PASS_THRESHOLD}）")
    print("\n提示：跑 LLM 用例请用 pytest tests/eval_test.py -m slow -v")
