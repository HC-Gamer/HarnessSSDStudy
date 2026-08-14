"""向后兼容 re-export —— 第 10 节的 ``workflows/nodes.py`` 单文件形态。

课件 10-2 把 5 个节点函数全写在 ``nodes.py`` 里；11-2/11-3 重构成
「一个 Agent 一个文件」后，节点搬进了各自的模块。老代码、老笔记、
以及 V4 的完整性检查脚本仍然会 ``from workflows.nodes import ...``，
所以这里保留一层薄薄的转发，**不写任何业务逻辑**。

新代码请直接从各自模块导入，例如
``from workflows.reviewer import review_node``。
"""

from __future__ import annotations

from workflows.analyzer import analyze_node
from workflows.collector import collect_node
from workflows.human_flag import human_flag_node
from workflows.organizer import organize_node
from workflows.planner import plan_strategy, planner_node
from workflows.reviewer import review_node
from workflows.reviser import revise_node

#: 10-2 的 save_node 已被合并进 organize_node（11-2 重构删掉了 save 节点），
#: 老代码若还在调 save_node，转发到 organize_node 语义等价（都是「整理后落盘」）。
save_node = organize_node

__all__ = [
    "analyze_node",
    "collect_node",
    "human_flag_node",
    "organize_node",
    "plan_strategy",
    "planner_node",
    "review_node",
    "revise_node",
    "save_node",
]
