"""Start vLLM serving Qwen3-1.7B on loopback; the API key stays out of process arguments."""

import os

from _paths import ROOT, load_runtime_env

os.environ["VLLM_API_KEY"] = load_runtime_env()["TUTOR_LLM_API_KEY"]
vllm = str(ROOT / "llm-venv/bin/vllm")
os.execv(vllm, [
    vllm, "serve", str(ROOT / "models/qwen3-1.7b"),
    "--served-model-name", "Qwen/Qwen3-1.7B",
    "--host", "127.0.0.1", "--port", os.environ.get("KAIWA_LLM_PORT", "18001"),
    "--dtype", "bfloat16", "--max-model-len", "32768", "--max-num-seqs", "2",
    "--gpu-memory-utilization", os.environ.get("KAIWA_VLLM_GPU_UTILIZATION", "0.75"),
    "--enforce-eager", "--disable-log-requests",
])
