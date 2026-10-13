#!/usr/bin/env bash
# Linux NVIDIA trial: retain the CPU venv and use one ONNX distribution in a separate venv.
set -euo pipefail
cd "$(dirname "$0")/.."
export UV_LINK_MODE=copy
if ! test -f .venv-gpu/pyvenv.cfg; then
    uv venv --python "${CONVERSATION_GPU_PYTHON:-python3}" .venv-gpu
fi
uv export --frozen --extra calls --extra tutor --no-dev --no-emit-project --no-hashes \
    -o .venv-gpu/requirements-cpu.txt
python3 - <<'PY'
from pathlib import Path

source = Path('.venv-gpu/requirements-cpu.txt').read_text()
if 'onnxruntime==1.23.2' not in source:
    raise SystemExit('Review the ONNX Runtime GPU pin when updating uv.lock')
Path('.venv-gpu/requirements-gpu.txt').write_text(
    source.replace('onnxruntime==1.23.2', 'onnxruntime-gpu==1.23.2')
)
PY
# The frozen export already includes all transitive dependencies. Re-resolving
# would reintroduce the CPU onnxruntime distribution required by Pipecat metadata.
uv pip install --python .venv-gpu/bin/python --no-deps -r .venv-gpu/requirements-gpu.txt
.venv-gpu/bin/python -c 'import onnxruntime; print(onnxruntime.get_available_providers())'
