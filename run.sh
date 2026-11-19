#!/usr/bin/env bash
# One-click runner for the closed-loop experiment agent.
#   ./run.sh            -> bare-run experiment (params from experiment.json)
#   ./run.sh web        -> start the web console
#   ./run.sh explore    -> TRex attack catalog exploration
#   ./run.sh test       -> run unit tests
set -euo pipefail
cd "$(dirname "$0")"

case "${1:-}" in
  web)
    echo "启动 Web 控制台: http://localhost:8000"
    exec uv run uvicorn backend.server:app --host 0.0.0.0 --port 8000 --reload
    ;;
  test)
    exec uv run pytest tests/unit/ -q
    ;;
  explore)
    shift
    exec uv run python src/main.py --trex-explore "$@"
    ;;
  *)
    echo "============================================"
    echo "  闭环实验（参数来自 experiment.json）"
    echo "============================================"
    exec uv run python src/main.py "$@"
    ;;
esac
