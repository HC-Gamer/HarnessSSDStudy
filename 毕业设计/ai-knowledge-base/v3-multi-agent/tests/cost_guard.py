"""CostGuard —— 多 Agent 预算守卫（课件 12-1）。

三重保护：

1. **成本追踪** —— :meth:`CostGuard.record` 记录每次 LLM 调用的 token 与费用；
2. **预警提醒** —— :meth:`CostGuard.check` 在用量达到 ``alert_threshold`` 时返回
   ``status="warning"``；
3. **预算熔断** —— 超出预算时 :meth:`CostGuard.check` 抛出
   :class:`BudgetExceededError`，让调用链**立刻中断**而不是继续烧钱。

设计要点：``record()`` 是仪表盘，预警是黄灯，``BudgetExceededError`` 是保险丝。
超预算是严重事件，抛异常比返回 ``False`` 更难被调用方忽略。

本模块**不依赖** workflows 包，可以单独 ``python3 tests/cost_guard.py`` 运行。
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: 项目根目录（tests/ 的上一级）
PROJECT_ROOT = Path(__file__).resolve().parent.parent

#: 默认成本报告落盘位置（课件 12-4 步骤 6 会检查该文件存在）
DEFAULT_REPORT_PATH = PROJECT_ROOT / "knowledge" / "cost-report.json"

#: DeepSeek 官方价格（元 / 百万 token），与 pipeline/model_client.py 的 PROVIDERS 一致
DEFAULT_INPUT_PRICE_PER_MILLION = 1.0
DEFAULT_OUTPUT_PRICE_PER_MILLION = 2.0

#: 默认预算（元）与预警比例
DEFAULT_BUDGET_YUAN = 1.0
DEFAULT_ALERT_THRESHOLD = 0.8


@dataclass
class CostRecord:
    """单次 LLM 调用的成本记录。

    Attributes:
        timestamp: Unix 时间戳。
        node_name: 调用发生在哪个工作流节点（plan / collect / analyze / ...）。
        prompt_tokens: 输入 token 数。
        completion_tokens: 输出 token 数。
        cost_yuan: 本次调用的估算成本（元）。
        model: 实际使用的模型名。
    """

    timestamp: float
    node_name: str
    prompt_tokens: int
    completion_tokens: int
    cost_yuan: float
    model: str = ""


class BudgetExceededError(Exception):
    """预算超标异常 —— 触发熔断，中断整条 LLM 调用链。"""


class CostGuard:
    """成本守卫：追踪 + 预警 + 熔断。

    典型用法::

        guard = CostGuard(budget_yuan=1.0)
        guard.record("analyze", usage, model="deepseek-chat")
        guard.check()          # 超预算时抛 BudgetExceededError
        guard.save_report()

    Attributes:
        budget_yuan: 单次运行的预算上限（元）。
        alert_threshold: 预警比例，0.8 表示用到 80% 时黄灯。
        records: 全部调用记录。
    """

    def __init__(
        self,
        budget_yuan: float = DEFAULT_BUDGET_YUAN,
        alert_threshold: float = DEFAULT_ALERT_THRESHOLD,
        input_price_per_million: float = DEFAULT_INPUT_PRICE_PER_MILLION,
        output_price_per_million: float = DEFAULT_OUTPUT_PRICE_PER_MILLION,
    ) -> None:
        """初始化守卫。

        Args:
            budget_yuan: 预算上限（元）。
            alert_threshold: 预警触发比例（0-1）。
            input_price_per_million: 输入单价（元 / 百万 token）。
            output_price_per_million: 输出单价（元 / 百万 token）。
        """
        self.budget_yuan = budget_yuan
        self.alert_threshold = alert_threshold
        self.input_price = input_price_per_million
        self.output_price = output_price_per_million

        self.records: list[CostRecord] = []
        self.total_prompt_tokens: int = 0
        self.total_completion_tokens: int = 0
        self.total_cost_yuan: float = 0.0
        self._alert_fired: bool = False

    def record(self, node_name: str, usage: dict, model: str = "") -> CostRecord:
        """记录一次 LLM 调用的 token 用量。

        Args:
            node_name: 节点名，用于按节点分组统计。
            usage: ``{"prompt_tokens": int, "completion_tokens": int}``。
            model: 模型名（可选）。

        Returns:
            本次生成的 :class:`CostRecord`。

        Examples:
            >>> g = CostGuard(budget_yuan=1.0)
            >>> r = g.record("analyze", {"prompt_tokens": 1000, "completion_tokens": 500})
            >>> round(r.cost_yuan, 6)
            0.002
        """
        prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
        completion_tokens = int(usage.get("completion_tokens", 0) or 0)
        cost = (
            prompt_tokens * self.input_price + completion_tokens * self.output_price
        ) / 1_000_000

        rec = CostRecord(
            timestamp=time.time(),
            node_name=node_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_yuan=cost,
            model=model,
        )
        self.records.append(rec)
        self.total_prompt_tokens += prompt_tokens
        self.total_completion_tokens += completion_tokens
        self.total_cost_yuan += cost
        logger.debug(
            "[CostGuard] record node=%s tokens=%d/%d cost=%.6f",
            node_name, prompt_tokens, completion_tokens, cost,
        )
        return rec

    def check(self) -> dict[str, Any]:
        """检查预算状态。

        Returns:
            ``{"status": "ok"|"warning", "total_cost": float, "budget": float,
            "usage_ratio": float, "message": str}``。

        Raises:
            BudgetExceededError: 累计成本已达到或超过预算。
        """
        ratio = self.total_cost_yuan / self.budget_yuan if self.budget_yuan > 0 else 0.0

        if self.total_cost_yuan >= self.budget_yuan:
            raise BudgetExceededError(
                f"成本已超出预算！当前: ¥{self.total_cost_yuan:.4f}, "
                f"预算: ¥{self.budget_yuan:.4f}"
            )

        if ratio >= self.alert_threshold and not self._alert_fired:
            self._alert_fired = True
            status = "warning"
            message = f"[预警] 成本已达预算的 {ratio:.0%}！"
            logger.warning("[CostGuard] %s", message)
        else:
            status = "ok"
            message = f"成本正常: ¥{self.total_cost_yuan:.4f} / ¥{self.budget_yuan:.4f}"

        return {
            "status": status,
            "total_cost": round(self.total_cost_yuan, 6),
            "budget": self.budget_yuan,
            "usage_ratio": round(ratio, 4),
            "message": message,
        }

    def get_report(self) -> dict[str, Any]:
        """生成成本报告（按节点分组）。

        Returns:
            含 ``cost_by_node`` / ``calls_by_node`` / ``tokens_by_node`` 的报告字典。
        """
        cost_by_node: dict[str, float] = {}
        calls_by_node: dict[str, int] = {}
        tokens_by_node: dict[str, int] = {}

        for rec in self.records:
            cost_by_node[rec.node_name] = cost_by_node.get(rec.node_name, 0.0) + rec.cost_yuan
            calls_by_node[rec.node_name] = calls_by_node.get(rec.node_name, 0) + 1
            tokens_by_node[rec.node_name] = (
                tokens_by_node.get(rec.node_name, 0)
                + rec.prompt_tokens
                + rec.completion_tokens
            )

        return {
            "total_cost_yuan": round(self.total_cost_yuan, 6),
            "total_prompt_tokens": self.total_prompt_tokens,
            "total_completion_tokens": self.total_completion_tokens,
            "total_calls": len(self.records),
            "budget_yuan": self.budget_yuan,
            "usage_ratio": round(
                self.total_cost_yuan / self.budget_yuan if self.budget_yuan > 0 else 0.0, 4
            ),
            "cost_by_node": {k: round(v, 6) for k, v in cost_by_node.items()},
            "calls_by_node": calls_by_node,
            "tokens_by_node": tokens_by_node,
        }

    def save_report(self, path: str | os.PathLike[str] | None = None) -> Path:
        """把成本报告写到 JSON 文件。

        Args:
            path: 目标路径；默认 ``knowledge/cost-report.json``。

        Returns:
            实际写入的路径。
        """
        target = Path(path) if path is not None else DEFAULT_REPORT_PATH
        target.parent.mkdir(parents=True, exist_ok=True)
        report = self.get_report()
        report["generated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        with open(target, "w", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2)
        logger.info("[CostGuard] 成本报告已写入 %s", target)
        return target

    def reset(self) -> None:
        """清空全部记录（测试用）。"""
        self.records.clear()
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_cost_yuan = 0.0
        self._alert_fired = False


def _self_test() -> int:
    """模块自测：追踪 / 熔断 / 预警三条路径。

    Returns:
        0 表示全部通过。
    """
    print("=== 测试 1：成本追踪 ===")
    guard = CostGuard(budget_yuan=1.0)
    guard.record("collect", {"prompt_tokens": 100, "completion_tokens": 50})
    guard.record("analyze", {"prompt_tokens": 2000, "completion_tokens": 1000})
    guard.record("review", {"prompt_tokens": 2500, "completion_tokens": 800})
    report = guard.get_report()
    assert report["total_calls"] == 3
    assert report["total_prompt_tokens"] == 4600
    assert abs(report["total_cost_yuan"] - 0.0083) < 1e-6, report["total_cost_yuan"]
    print(f"  调用次数: {report['total_calls']}")
    print(f"  总成本: ¥{report['total_cost_yuan']}")
    print(f"  按节点: {report['cost_by_node']}")
    status = guard.check()
    assert status["status"] == "ok"
    print(f"  预算状态: {status['status']}\n")

    print("=== 测试 2：预算超限（熔断）===")
    guard2 = CostGuard(budget_yuan=0.001)
    guard2.record("analyze", {"prompt_tokens": 100000, "completion_tokens": 100000})
    try:
        guard2.check()
    except BudgetExceededError as exc:
        print(f"  预算超限检测通过: {exc}\n")
    else:  # pragma: no cover - 断言失败路径
        raise AssertionError("应该抛出 BudgetExceededError！")

    print("=== 测试 3：预警阈值 ===")
    guard3 = CostGuard(budget_yuan=0.01, alert_threshold=0.5)
    guard3.record("analyze", {"prompt_tokens": 5000, "completion_tokens": 2000})
    result3 = guard3.check()
    assert result3["status"] == "warning", result3
    print(f"  预警状态: {result3['status']} — {result3['message']}\n")

    print("=== 测试 4：报告落盘 ===")
    tmp = PROJECT_ROOT / "knowledge" / "cost-report.selftest.json"
    written = guard.save_report(tmp)
    assert written.exists()
    payload = json.loads(written.read_text(encoding="utf-8"))
    assert "cost_by_node" in payload
    written.unlink()
    print(f"  报告结构正确（cost_by_node 含 {len(payload['cost_by_node'])} 个节点）\n")

    print("所有测试通过！")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    raise SystemExit(_self_test())
