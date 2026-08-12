"""Reviser Agent —— 定向修改节点（V3 流水线节点 ⑤，课件 11-2）。

核心原则：**只修改不评估（Revise, don't judge）**。
Reviser 读 ``review_feedback`` 去改 ``analyses``，**不给自己打分** ——
改完必须回到 Reviewer 再评一次，形成 ``review → revise → review`` 闭环。

Reviewer 与 Reviser 拆成两个 Agent，就是为了让「评」和「改」互相制衡：
同一个 Agent 既改又评，等于让它给自己的作业打分。

``temperature=0.4`` —— 比审核（0.1）高，允许创造性改写；比自由生成低，
避免改着改着跑题（「定向修改，不要过度发散」）。
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests.cost_guard import BudgetExceededError  # noqa: E402
from workflows.model_client import accumulate_usage, chat_json  # noqa: E402
from workflows.state import KBState  # noqa: E402

logger = logging.getLogger(__name__)

#: 本节点在成本报告里的名字
NODE_NAME = "revise"

#: 修订温度：允许改写，但不放飞
REVISER_TEMPERATURE = 0.4

#: 一次最多送多少条给 LLM 改（与 Reviewer 的采样窗口对齐，避免超长上下文）
REVISE_BATCH_SIZE = 5

#: 修订输出的 token 上限。比默认值大 —— 5 条改写稿的 JSON 很容易超过 2000，
#: 一旦被截断就是「模型返回了半个数组」，解析必失败、修订必空转。
REVISE_MAX_TOKENS = 4000

#: 只把内容字段交给 LLM 改写。url / stars / collected_at 等溯源字段不进 prompt：
#: 既省 token，也堵死「模型顺手把 url 改了」这类事故。
CONTENT_FIELDS = ("summary", "key_insight", "tags", "category", "relevance_score")

REVISER_SYSTEM = "你是经验丰富的知识库编辑。根据反馈定向修改，不要过度发散。只返回 JSON 数组。"

REVISE_PROMPT = """你是知识库编辑。以下是审核员的反馈，请据此修改这些分析结果。

【审核反馈】
{feedback}

【当前分析结果】（共 {count} 条，按顺序）
{analyses}

【修改要求】
- 重点改进反馈中提到的弱项维度
- 保留已经不错的部分，不要推倒重来
- 每条只返回这 5 个字段：summary / key_insight / tags / category / relevance_score
- relevance_score 保持 0-1 浮点
- 返回的数组长度必须是 {count}，顺序与输入一致
- 只返回 JSON 数组，不要额外说明"""


def _merge_revision(original: list[dict], improved: list[Any]) -> list[dict]:
    """把 LLM 改过的字段合回原条目，保留 url / stars 等采集元数据。

    LLM 常常「顺手」丢掉它认为不重要的字段（url、stars、collected_at），
    直接用返回值替换会让下游丢溯源信息，所以只合并内容字段。

    Args:
        original: 修改前的 analyses。
        improved: LLM 返回的数组。

    Returns:
        合并后的 analyses，长度与 ``original`` 一致。

    Examples:
        >>> _merge_revision([{"url": "u", "summary": "old"}], [{"summary": "new"}])
        [{'url': 'u', 'summary': 'new'}]
    """
    merged: list[dict] = []
    for index, item in enumerate(original):
        record = dict(item)
        if index < len(improved) and isinstance(improved[index], dict):
            for field in CONTENT_FIELDS:
                if field in improved[index]:
                    record[field] = improved[index][field]
        merged.append(record)
    return merged


def revise_node(state: KBState) -> dict:
    """LangGraph 节点 ⑤：根据 Reviewer 反馈定向修改 analyses。

    Args:
        state: 当前 KBState，读 ``analyses`` / ``review_feedback``。

    Returns:
        ``{"analyses": [...], "cost_tracker": {...}}``；无可改内容时只回
        ``cost_tracker``（LangGraph 要求至少更新一个字段）。

    Raises:
        BudgetExceededError: 预算熔断时向上抛，中断流水线。
    """
    analyses = state.get("analyses", []) or []
    feedback = state.get("review_feedback", "")
    iteration = state.get("iteration", 0)
    tracker = state.get("cost_tracker", {})

    if not analyses or not feedback:
        logger.info("[Reviser] 无可修改内容，跳过")
        return {"cost_tracker": tracker}

    batch = analyses[:REVISE_BATCH_SIZE]
    payload = [{field: item.get(field) for field in CONTENT_FIELDS} for item in batch]
    prompt = REVISE_PROMPT.format(
        feedback=feedback,
        count=len(payload),
        analyses=json.dumps(payload, ensure_ascii=False, indent=2),
    )

    try:
        improved, usage = chat_json(
            prompt,
            system=REVISER_SYSTEM,
            temperature=REVISER_TEMPERATURE,
            max_tokens=REVISE_MAX_TOKENS,
            node_name=NODE_NAME,
        )
        tracker = accumulate_usage(tracker, usage)
    except BudgetExceededError:
        logger.error("[Reviser] 预算熔断，修订中断")
        raise
    except Exception as exc:  # noqa: BLE001 - 改不动就把原稿交回，让循环自然走到兜底
        logger.warning("[Reviser] 修改失败：%s", exc)
        return {"cost_tracker": tracker}

    if isinstance(improved, list) and improved:
        merged = _merge_revision(batch, improved) + analyses[REVISE_BATCH_SIZE:]
        logger.info("[Reviser] 定向修改 %d 条 analyses (迭代 %d)", len(batch), iteration)
        return {"analyses": merged, "cost_tracker": tracker}

    logger.warning("[Reviser] LLM 未返回可用数组，保留原稿")
    return {"cost_tracker": tracker}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    print("=== _merge_revision 自测（不调 LLM）===")
    before = [{"url": "https://x", "stars": 1, "summary": "旧摘要", "tags": ["a"]}]
    after = _merge_revision(before, [{"summary": "新摘要", "tags": ["a", "b"]}])
    print(f"  合并结果: {after}")
    assert after[0]["url"] == "https://x", "采集元数据必须保留"
    assert after[0]["summary"] == "新摘要"
    assert after[0]["tags"] == ["a", "b"]
    print("  OK：内容字段被替换，url / stars 等元数据保留")
