"""LangGraph 状态定义 —— AI 知识库 V3 工作流的核心数据契约。

所有节点共享同一个 :class:`KBState`，用 ``TypedDict`` 保证类型安全。
每个节点只写自己负责的字段，实现职责隔离（报告式通信：字段是结构化摘要，
不是原始 HTML / 原始响应）。

数据流向（V3 完整 · 7 节点）::

    plan → sources → analyses → review ─[pass]→ organize → END
                                  │
                                  ├─[fail < max]→ revise → review（闭环）
                                  │
                                  └─[>= max]────→ human_flag → END

字段演进（对应课件 10-1 / 11-2 / 11-3）：

===========  ======  ==========================================
阶段          字段数  新增字段
===========  ======  ==========================================
10-1          7       sources / analyses / articles /
                      review_feedback / review_passed /
                      iteration / cost_tracker
11-2          8       + needs_human_review
11-3          9       + plan
===========  ======  ==========================================
"""

from __future__ import annotations

from typing import TypedDict


class KBState(TypedDict):
    """知识库工作流的全局状态（课件 11-3 最终版 · 9 字段）。

    Attributes:
        plan: Planner 输出的策略字典，含 strategy / per_source_limit /
            relevance_threshold / max_iterations / rationale。
            下游 collector / organizer / reviewer 共同消费。
        sources: 采集到的原始数据，每条含 source / title / url /
            description / stars / collected_at。
        analyses: LLM 分析后的结构化结果，每条含 summary / tags /
            relevance_score / category / key_insight。
        articles: 过滤、去重、PII 掩码后的最终知识条目。
        review_feedback: Reviewer 的反馈意见（中文，非空表示需修改）。
        review_passed: 审核是否通过（3 路条件边的判断依据之一）。
        iteration: 已完成的审核轮次，在 reviewer 内 +1。
        needs_human_review: HumanFlag 兜底标记，True 表示已落盘待人工处理。
        cost_tracker: token 用量累计 {prompt_tokens, completion_tokens,
            total_tokens, calls}。
    """

    plan: dict                  # 11-3 新增 · Planner 输出策略
    sources: list[dict]         # 采集结果（报告式：结构化摘要而非原始 HTML）
    analyses: list[dict]        # 分析结果（每条含 summary / tags / relevance_score）
    articles: list[dict]        # 知识条目（过滤 + 去重 + PII 掩码后的最终格式）
    review_feedback: str        # 审核反馈（具体改进建议，非空表示需修改）
    review_passed: bool         # 审核是否通过（条件边判断依据）
    iteration: int              # 审核迭代次数（>= plan.max_iterations 触发兜底）
    needs_human_review: bool    # 11-2 新增 · HumanFlag 节点设为 True
    cost_tracker: dict          # token 统计 {prompt_tokens, completion_tokens, ...}


def make_initial_state(**overrides: object) -> KBState:
    """构造一个字段齐全的初始 state。

    图的入口节点是 planner，但 LangGraph 不会自动补齐 TypedDict 缺失的键，
    下游节点若用 ``state["x"]`` 直接取会 KeyError。统一从这里构造可避免。

    Args:
        **overrides: 需要覆盖的字段，如 ``sources=[...]``。

    Returns:
        字段齐全的 KBState。

    Examples:
        >>> s = make_initial_state()
        >>> len(s) == len(KBState.__annotations__)
        True
        >>> make_initial_state(iteration=2)["iteration"]
        2
    """
    state: KBState = {
        "plan": {},
        "sources": [],
        "analyses": [],
        "articles": [],
        "review_feedback": "",
        "review_passed": False,
        "iteration": 0,
        "needs_human_review": False,
        "cost_tracker": {},
    }
    state.update(overrides)  # type: ignore[typeddict-item]
    return state


if __name__ == "__main__":
    annotations = KBState.__annotations__
    print("KBState 字段：")
    for name, type_hint in annotations.items():
        print(f"  {name}: {type_hint}")
    print(f"\n共 {len(annotations)} 个字段")
    print(f"初始 state 构造成功，iteration = {make_initial_state()['iteration']}")
