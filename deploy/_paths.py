"""Shared locations and runtime.env loader for the deployment launchers."""

import os
from pathlib import Path

ROOT = Path(os.environ.get("KAIWA_ROOT", "/workspace/ai-conversation"))
CONFIG = Path(os.environ.get("KAIWA_CONFIG_DIR", "/root/.config/ai-conversation"))
BACKEND = ROOT / "backend"
LOGS = ROOT / "logs"
HF_HOME = ROOT / "cache" / "huggingface"


def load_runtime_env() -> dict[str, str]:
    """Parse NAME=value lines from runtime.env (no quotes, no `export`)."""
    lines = (CONFIG / "runtime.env").read_text().splitlines()
    return dict(line.split("=", 1) for line in lines if "=" in line and not line.startswith("#"))


def cuda_library_path() -> str:
    """LD_LIBRARY_PATH covering pip-installed NVIDIA libraries (cuDNN, cuBLAS) and the toolkit."""
    libraries = sorted(Path("/usr/local/lib").glob("python3*/dist-packages/nvidia/*/lib"))
    return ":".join([*map(str, libraries), "/usr/local/cuda/lib64"])
