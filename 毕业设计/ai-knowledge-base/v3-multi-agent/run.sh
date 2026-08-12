#!/bin/bash
# AI 知识库 V3 一键运行
#
#   ./run.sh              跑一次完整工作流（7 节点）
#   ./run.sh check        跑项目完整性检查（12-4 步骤 7）
#   ./run.sh test         跑 pytest + 三个独立模块自测
#   ./run.sh breaker      验证预算熔断（BUDGET_YUAN=0.001）
#   ./run.sh lite|full    切换 Planner 策略档位跑一次
set -euo pipefail

cd "$(dirname "$0")"

PYTHON="${PYTHON:-$HOME/ai-knowledge-base/.venv/bin/python}"
if [ ! -x "$PYTHON" ]; then
    echo "[!!] 找不到 venv Python: $PYTHON"
    echo "     系统 python3 是 3.9，跑不了本项目（PEP 604 语法）。"
    echo "     建环境：/opt/homebrew/opt/python@3.12/bin/python3.12 -m venv ~/ai-knowledge-base/.venv"
    exit 1
fi

case "${1:-run}" in
    run)
        exec "$PYTHON" -m workflows.graph
        ;;
    lite|standard|full)
        PLANNER_TARGET_COUNT="$1" exec "$PYTHON" -m workflows.graph
        ;;
    breaker)
        BUDGET_YUAN=0.001 exec "$PYTHON" -m workflows.graph
        ;;
    check)
        exec bash scripts/check_v3.sh
        ;;
    test)
        "$PYTHON" tests/cost_guard.py
        "$PYTHON" tests/security.py
        exec "$PYTHON" -m pytest tests/
        ;;
    *)
        echo "用法: ./run.sh [run|lite|standard|full|breaker|check|test]"
        exit 1
        ;;
esac
