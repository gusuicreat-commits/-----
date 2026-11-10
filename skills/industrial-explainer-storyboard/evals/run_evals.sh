#!/usr/bin/env bash
# 真实模型对照评测；只由验收方主动运行。
set -euo pipefail
EVAL_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$EVAL_DIR/run_evals.py" "$@"
