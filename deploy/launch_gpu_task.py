"""Run a backend script (e.g. a benchmark) in the GPU venv with CUDA libraries and runtime.env.

Usage (script paths resolve against the current directory, then backend/):
    python launch_gpu_task.py smoke_models.py
    python launch_gpu_task.py scripts/benchmark_speech.py --output /path/out.json
"""

import os
import sys
from pathlib import Path

from _paths import BACKEND, HF_HOME, cuda_library_path, load_runtime_env

os.environ.update(load_runtime_env())
os.environ.update({
    "LD_LIBRARY_PATH": cuda_library_path(),
    "HF_HOME": str(HF_HOME),
    "HF_HUB_DISABLE_TELEMETRY": "1",
    "LOGURU_LEVEL": "INFO",
    "OMP_NUM_THREADS": "2",
    "OPENBLAS_NUM_THREADS": "2",
    "ONNX_PROVIDER": "CPUExecutionProvider",
    "TUTOR_WHISPER_DEVICE": "cuda",
    "TUTOR_WHISPER_COMPUTE_TYPE": "float16",
    "TUTOR_KOKORO_EXECUTION_PROVIDER": "CUDAExecutionProvider",
    "PYTHONPATH": str(BACKEND),
})
args = sys.argv[1:]
if args and Path(args[0]).is_file():
    args[0] = str(Path(args[0]).resolve())
os.chdir(BACKEND)
python = str(BACKEND / ".venv-gpu/bin/python")
os.execv(python, [python, *args])
