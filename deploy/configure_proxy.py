"""Expose the API on port 8000 behind a private random path prefix via the template's nginx.

The prefix is generated once and kept in access.json on the container disk. The public
base URL is recomputed from the pod ID (RUNPOD_POD_ID, KAIWA_POD_ID, or /proc/1/environ) on every run, so a new pod only needs this script.
"""

import json
import os
import secrets
import subprocess
from pathlib import Path

from _paths import CONFIG

record = CONFIG / "access.json"
if record.exists():
    prefix = json.loads(record.read_text())["prefix"]
else:
    prefix = "/pilot/" + secrets.token_hex(32)


def find_pod_id() -> str:
    """RUNPOD_POD_ID is set for the container's main process but not for SSH sessions."""
    for name in ("KAIWA_POD_ID", "RUNPOD_POD_ID"):
        if os.environ.get(name):
            return os.environ[name]
    for entry in Path("/proc/1/environ").read_bytes().split(b"\0"):
        if entry.startswith(b"RUNPOD_POD_ID="):
            return entry.split(b"=", 1)[1].decode()
    raise SystemExit("Set KAIWA_POD_ID: RUNPOD_POD_ID was not found")


pod_id = find_pod_id()
access = {"prefix": prefix, "base_url": f"https://{pod_id}-8000.proxy.runpod.net{prefix}"}
CONFIG.mkdir(parents=True, exist_ok=True)
record.write_text(json.dumps(access, indent=2))
record.chmod(0o600)

api_port = os.environ.get("KAIWA_API_PORT", "8002")
config = """server {
    listen 8000;
    server_name _;
    access_log off;
    error_log /var/log/nginx/conversation-error.log warn;
    client_max_body_size 64k;
    location / { return 404; }
    location ^~ PREFIX/ {
        proxy_pass http://127.0.0.1:API_PORT/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto https;
        proxy_read_timeout 90s;
    }
}
""".replace("PREFIX", prefix).replace("API_PORT", api_port)
Path("/etc/nginx/conf.d").mkdir(exist_ok=True)
Path("/etc/nginx/conf.d/conversation.conf").write_text(config)
main = Path("/etc/nginx/nginx.conf")
text = main.read_text()
if "include /etc/nginx/conf.d/conversation.conf;" not in text:
    main.write_text(text.replace("http {", "http {\n    include /etc/nginx/conf.d/conversation.conf;", 1))
subprocess.run(["nginx", "-t"], check=True)
subprocess.run(["nginx", "-s", "reload"], check=True)
print("HTTPS proxy configured with private access path (see access.json for the base URL)")
