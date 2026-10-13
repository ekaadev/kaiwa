#!/usr/bin/env bash
# First-time setup of a fresh pod on an existing network volume: system packages, backend
# venv (CPU, used by launchers/smoke tests), vLLM venv, and the pinned Qwen download.
# GPU venv: run backend/scripts/install_gpu_trial.sh afterwards.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
ROOT="${KAIWA_ROOT:-/workspace/ai-conversation}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export KAIWA_ROOT="$ROOT"
export UV_CACHE_DIR="$ROOT/cache/uv" UV_LINK_MODE=copy
export HF_HOME="$ROOT/cache/huggingface" HF_HUB_DISABLE_TELEMETRY=1 VLLM_NO_USAGE_STATS=1
apt-get update -qq
apt-get install -y -qq espeak-ng ffmpeg libsndfile1 rsync g++
cd "$ROOT/backend"
uv sync --frozen --no-dev --extra calls --extra tutor --python /usr/bin/python3
"$ROOT/backend/.venv/bin/python" -c 'from misaki.ja import JAG2P; JAG2P(version="pyopenjtalk")("こんにちは")'
uv venv --system-site-packages --python /usr/bin/python3 "$ROOT/llm-venv"
uv pip install --python "$ROOT/llm-venv/bin/python" 'vllm==0.10.2' 'transformers==4.55.2'
"$ROOT/llm-venv/bin/python" "$HERE/download_qwen.py"
mkdir -p "$ROOT/logs"
printf '%s\n' complete > "$ROOT/logs/bootstrap.status"
