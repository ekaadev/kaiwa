"""Start the single-worker FastAPI process with runtime.env loaded."""

import os

from _paths import BACKEND, HF_HOME, cuda_library_path, load_runtime_env

settings = load_runtime_env()
os.environ.update(settings)
os.environ.update({
    "LD_LIBRARY_PATH": cuda_library_path(),
    "HF_HOME": str(HF_HOME),
    "HF_HUB_DISABLE_TELEMETRY": "1",
    "LOGURU_LEVEL": "INFO",
    "OMP_NUM_THREADS": "2",
    "OPENBLAS_NUM_THREADS": "2",
})
os.chdir(BACKEND)
python = settings.get("CONVERSATION_API_PYTHON", str(BACKEND / ".venv-gpu/bin/python"))
os.execv(python, [python, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
                  "--port", os.environ.get("KAIWA_API_PORT", "8002"),
                  "--workers", "1", "--no-access-log"])
