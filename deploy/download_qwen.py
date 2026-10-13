"""Download Qwen3-1.7B at the current Hub revision and record that revision."""

import json

from huggingface_hub import HfApi, snapshot_download

from _paths import ROOT

revision = HfApi().model_info("Qwen/Qwen3-1.7B").sha
snapshot_download("Qwen/Qwen3-1.7B", revision=revision, local_dir=ROOT / "models/qwen3-1.7b",
                  allow_patterns=["*.json", "*.safetensors", "*.txt"])
(ROOT / "models/qwen-revision.json").write_text(
    json.dumps({"repository": "Qwen/Qwen3-1.7B", "revision": revision}))
print("Qwen downloaded at pinned revision", revision)
