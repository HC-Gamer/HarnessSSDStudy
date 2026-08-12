#!/bin/bash
# V3 知识管线一键启动。
#
# 用法:
#   ./run.sh --topic "AI agent" --limit 5 --verbose
#   ./run.sh --dry-run
#   ./run.sh --help
#
# 对标 Wk2 v2-pipeline 的交付标准。venv 位置按 Wk3 约定（每周一个 .venv）。

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WK3_ROOT="$(cd "${HERE}/../.." && pwd)"
VENV="${WK3_ROOT}/.venv"

if [[ ! -d "${VENV}" ]]; then
  echo "错误: 找不到虚拟环境 ${VENV}" >&2
  echo "请先创建: /opt/homebrew/bin/python3 -m venv ${VENV} && ${VENV}/bin/pip install -r ${HERE}/requirements.txt" >&2
  exit 1
fi

# shellcheck source=/dev/null
source "${VENV}/bin/activate"

cd "${HERE}"
exec python -m v3_pipeline.main "$@"
