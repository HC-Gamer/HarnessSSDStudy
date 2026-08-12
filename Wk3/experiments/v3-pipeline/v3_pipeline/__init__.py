"""V3 知识管线 —— LangGraph 图编排的可交付形态。

对标 Wk2 的 ``v2-pipeline/pipeline/``：那边是线性四步流水线，这边是状态图。
两者共用 ``Wk2/experiments/v2-pipeline/pipeline/model_client.py`` 的 LLM 客户端
与 ``rss_sources.yaml`` 的源列表——V3 换的是编排层，不是数据层。

模块::

    graph   图定义（节点 / 条件边 / 段间校验 / 质量门禁 / 反馈回路）
    main    CLI 入口，负责参数、落盘、成本报告、退出码

用法见 ``README.md`` 或 ``./run.sh --help``。
"""

from __future__ import annotations

__all__ = ["__version__"]

#: 版本号。V3 的第一个可交付版本。
__version__ = "3.0.0"
