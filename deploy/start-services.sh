#!/usr/bin/env bash
# Start Qwen (vLLM) and the API in the background, then configure the HTTPS proxy.
# Does not wait for models to finish loading: check /health afterwards.
set -euo pipefail
umask 077
ROOT="${KAIWA_ROOT:-/workspace/ai-conversation}"
CONFIG="${KAIWA_CONFIG_DIR:-/root/.config/ai-conversation}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export KAIWA_ROOT="$ROOT" KAIWA_CONFIG_DIR="$CONFIG"
export HF_HOME="$ROOT/cache/huggingface" HF_HUB_DISABLE_TELEMETRY=1 VLLM_NO_USAGE_STATS=1
mkdir -p "$ROOT/logs" "$CONFIG"

start_service() {
    local name="$1" port="$2" launcher="$3"
    local pidfile="$CONFIG/$name.pid"
    if curl -fsS "http://127.0.0.1:$port/health" >/dev/null 2>&1; then
        return
    fi
    if [ -f "$pidfile" ] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
        return
    fi
    setsid "$ROOT/backend/.venv/bin/python" "$launcher" >> "$ROOT/logs/$name.log" 2>&1 < /dev/null &
    printf '%s\n' "$!" > "$pidfile"
}
start_service llm "${KAIWA_LLM_PORT:-18001}" "$HERE/launch_llm.py"
start_service api "${KAIWA_API_PORT:-8002}" "$HERE/launch_api.py"
"$ROOT/backend/.venv/bin/python" "$HERE/configure_proxy.py"
