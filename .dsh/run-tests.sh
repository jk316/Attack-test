#!/usr/bin/env bash
# SDD 监督测试入口：剥离宿主代理变量后运行 pytest，保证基线可复现。
# 用法: bash .dsh/run-tests.sh [pytest 参数...]
set -euo pipefail
# 无真实密钥时注入占位密钥（graph 构建只校验存在性；真实 LLM 调用测试一律 mock）
if [ -z "${DEEPSEEK_API_KEY:-}" ] && [ -z "${OPENAI_API_KEY:-}" ]; then
  export DEEPSEEK_API_KEY="sk-baseline-dummy-key"
fi
env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u all_proxy -u NO_PROXY -u no_proxy \
  uv run pytest "$@"
