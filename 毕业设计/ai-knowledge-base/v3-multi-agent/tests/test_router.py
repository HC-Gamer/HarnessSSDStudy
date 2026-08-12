"""Router / Supervisor 两个设计模式的单元测试（课件第 9 节，不调 LLM）。

Router 的核心承诺是「关键词命中就不花钱」，Supervisor 的核心承诺是
「最多 3 轮一定退出」。这两条都用不着真实 LLM 就能验证 —— Supervisor
用假的 Worker/Supervisor 替身即可。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from patterns import router as router_module  # noqa: E402
from patterns import supervisor as supervisor_module  # noqa: E402


# ── Router：两层分类 ────────────────────────────────────────


@pytest.mark.parametrize(
    ("query", "intent"),
    [
        ("搜索最近的 AI Agent 框架仓库", "github_search"),
        ("GitHub 上 star 最多的 LLM 项目", "github_search"),
        ("知识库里有什么关于 RAG 的内容", "knowledge_query"),
        ("我们已收录哪些 multimodal 文章", "knowledge_query"),
    ],
)
def test_keyword_layer_hits_without_llm(query, intent, monkeypatch):
    """关键词命中的查询必须零成本 —— 一旦调 LLM 就让测试失败。"""

    def _boom(*args, **kwargs):
        raise AssertionError("关键词已命中，不应该再调 LLM")

    monkeypatch.setattr(router_module, "chat", _boom)
    got_intent, used_llm = router_module.classify_intent(query)
    assert got_intent == intent
    assert used_llm is False


def test_llm_layer_is_the_fallback(monkeypatch):
    """关键词没命中时才走 LLM，且返回值要能收敛到已注册意图。"""
    monkeypatch.setattr(
        router_module, "chat", lambda *a, **k: ("  General_Chat.  ", {})
    )
    intent, used_llm = router_module.classify_intent("LangGraph 和 CrewAI 有什么区别")
    assert intent == "general_chat"
    assert used_llm is True


def test_llm_failure_degrades_not_raises(monkeypatch):
    """分类调用挂了要降级到 general_chat，不能把异常抛给用户。"""

    def _fail(*args, **kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr(router_module, "chat", _fail)
    intent, used_llm = router_module.classify_intent("随便问点什么")
    assert intent == router_module.FALLBACK_INTENT
    assert used_llm is True


def test_every_intent_has_a_handler():
    """新增意图必须同时注册处理器，否则 route() 会 KeyError。"""
    registered = set(router_module.HANDLERS)
    from_rules = {intent for _, intent in router_module.KEYWORD_RULES}
    assert from_rules <= registered
    assert router_module.FALLBACK_INTENT in registered
    assert registered == {"github_search", "knowledge_query", "general_chat"}


def test_knowledge_handler_survives_missing_index(monkeypatch, tmp_path):
    """索引不存在时给出可操作提示，而不是抛 FileNotFoundError。"""
    monkeypatch.setattr(router_module, "INDEX_PATH", tmp_path / "nope.json")
    assert "请先运行采集工作流" in router_module.knowledge_query_handler("rag")


def test_route_dispatches_to_matching_handler(monkeypatch):
    """route() 只做分发，处理器可替换 —— 这是 Router 模式的可扩展点。"""
    monkeypatch.setitem(router_module.HANDLERS, "knowledge_query", lambda q: f"HIT:{q}")
    assert router_module.route("知识库里有什么") == "HIT:知识库里有什么"


# ── Supervisor：审核循环 ───────────────────────────────────


def _fake_reviews(scores):
    """构造一个按次序返回指定分数的假 Supervisor。

    Args:
        scores: 每轮返回的分数序列。

    Returns:
        可替换 ``_run_supervisor`` 的函数。
    """
    calls = iter(scores)

    def _review(_output):
        score = next(calls)
        return {"passed": score >= supervisor_module.PASS_SCORE, "score": score,
                "feedback": f"第 {score} 分的反馈"}

    return _review


def test_supervisor_returns_early_when_passed(monkeypatch):
    """一次过就立刻返回，不多跑一轮浪费 token。"""
    monkeypatch.setattr(supervisor_module, "_run_worker", lambda *a, **k: '{"summary": "ok"}')
    monkeypatch.setattr(supervisor_module, "_run_supervisor", _fake_reviews([9]))
    result = supervisor_module.supervisor("分析 LangGraph")
    assert result["attempts"] == 1
    assert result["final_score"] == 9
    assert result["warning"] is None


def test_supervisor_loops_with_feedback_then_passes(monkeypatch):
    """不通过时带反馈重做，第二轮通过就退出。"""
    seen: list[str] = []

    def _worker(task, previous, feedback):
        seen.append(feedback)
        return '{"summary": "v"}'

    monkeypatch.setattr(supervisor_module, "_run_worker", _worker)
    monkeypatch.setattr(supervisor_module, "_run_supervisor", _fake_reviews([4, 8]))
    result = supervisor_module.supervisor("分析 LangGraph")
    assert result["attempts"] == 2
    assert seen[1], "第二轮必须带着上一轮的反馈重做，不能盲目重试"


def test_supervisor_stops_at_three_rounds(monkeypatch):
    """一直不通过也必须在 3 轮退出，并带 warning 标记。"""
    monkeypatch.setattr(supervisor_module, "_run_worker", lambda *a, **k: '{"summary": "v"}')
    monkeypatch.setattr(supervisor_module, "_run_supervisor", _fake_reviews([2, 3, 4]))
    result = supervisor_module.supervisor("分析 LangGraph")
    assert result["attempts"] == supervisor_module.DEFAULT_MAX_RETRIES == 3
    assert result["warning"]
    assert len(result["history"]) == 3


@pytest.mark.parametrize(
    ("review", "expected"),
    [
        ({"score": 26, "dimension_scores": {"accuracy": 9, "depth": 7, "format": 10}}, 9),
        ({"score": 8}, 8),
        ({"score": 26}, 10),
        ({"score": 0}, 0),
        ({"score": 5, "dimension_scores": {"accuracy": 10, "depth": 10, "format": 10}}, 10),
    ],
)
def test_supervisor_score_recomputed_in_python(review, expected):
    """实测坑：模型会把三个维度加起来返回 26/10 —— 总分必须由代码算。"""
    assert supervisor_module.normalize_score(review) == expected


def test_supervisor_survives_review_failure(monkeypatch):
    """审核调用挂掉不能丢掉 Worker 的产出。"""

    def _fail(_output):
        raise RuntimeError("judge down")

    monkeypatch.setattr(supervisor_module, "_run_worker", lambda *a, **k: '{"summary": "v"}')
    monkeypatch.setattr(supervisor_module, "_run_supervisor", _fail)
    result = supervisor_module.supervisor("分析 LangGraph", max_retries=2)
    assert result["output"] == '{"summary": "v"}'
    assert result["attempts"] == 2
