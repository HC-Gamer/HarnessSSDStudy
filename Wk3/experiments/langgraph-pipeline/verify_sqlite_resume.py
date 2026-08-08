#!/usr/bin/env python3
"""独立进程读取 SQLite checkpoint —— 「跨进程恢复」的硬证据。

``exp_sqlite_checkpointer`` 用两个 SqliteSaver 实例模拟换进程，但那毕竟还在
同一个 Python 进程里。本脚本由主实验用 ``subprocess`` 拉起，是一个**真正独立
的进程**：它只拿到 ``(db_path, thread_id)``，没有任何内存里的 state，能读出
next 节点和质量分就证明 checkpoint 确实落在了磁盘上。

用法::

    python verify_sqlite_resume.py <db_path> <thread_id>

输出一行 JSON 到 stdout，供父进程解析。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def main(argv: list[str]) -> int:
    """读取指定 thread 的 checkpoint 并打印 JSON。

    Args:
        argv: ``[db_path, thread_id]``。

    Returns:
        退出码：读到 state 返回 0，否则 1。
    """
    if len(argv) != 2:
        print(json.dumps({"error": "usage: verify_sqlite_resume.py <db_path> <thread_id>"}))
        return 2

    db_path, thread_id = argv

    from langgraph.checkpoint.sqlite import SqliteSaver

    # 只导入图定义，不跑任何节点
    from langgraph_experiment import build_pipeline_graph

    config = {"configurable": {"thread_id": thread_id}}

    with SqliteSaver.from_conn_string(db_path) as saver:
        app = build_pipeline_graph().compile(checkpointer=saver)
        snapshot = app.get_state(config)
        values = snapshot.values or {}
        payload = {
            "pid": __import__("os").getpid(),
            "db_path": db_path,
            "thread_id": thread_id,
            "saw_state": bool(values),
            "next": list(snapshot.next),
            "quality_score": values.get("quality_score"),
            "path": values.get("path", []),
            "summary_chars": len(values.get("summary", "")),
            "article_body_chars": len(values.get("article_body", "")),
        }

    print(json.dumps(payload, ensure_ascii=False))
    return 0 if payload["saw_state"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
