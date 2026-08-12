"""V3 LangGraph 工作流包：一个 Agent 一个文件。

节点顺序：planner → collector → analyzer → reviewer → (reviser | organizer | human_flag)。
图的组装见 :mod:`workflows.graph`，共享状态定义见 :mod:`workflows.state`。
"""
