"""Move the template's JupyterLab to another loopback port, freeing its public port.

Use when the proxy must listen on a port the pod already exposes (e.g. 8888). Reuses the
running server's exact arguments (including its token) and only changes --port and --ip.
JupyterLab is then reachable through an SSH tunnel to the new port.

Usage: python3 move_jupyter.py [new_port]   (default 8889)
"""

import os
import subprocess
import sys
import time
from pathlib import Path

new_port = sys.argv[1] if len(sys.argv) > 1 else "8889"
for proc in Path("/proc").glob("[0-9]*"):
    try:
        args = proc.joinpath("cmdline").read_bytes().decode().split("\0")[:-1]
    except OSError:
        continue
    if any(a.endswith("jupyter-lab") for a in args[:2]) and any(a.startswith("--port=") for a in args):
        break
else:
    raise SystemExit("No running jupyter-lab found (already moved?)")

pid = int(proc.name)
cwd = os.readlink(f"/proc/{pid}/cwd")  # root_dir defaults to cwd; preferred_dir must be inside
new_args = [f"--port={new_port}" if a.startswith("--port=") else
            "--ip=127.0.0.1" if a.startswith("--ip=") else a for a in args]
log = open("/tmp/jupyter-moved.log", "ab")
os.kill(pid, 15)
time.sleep(2)
subprocess.Popen(new_args, stdout=log, stderr=log, stdin=subprocess.DEVNULL, start_new_session=True, cwd=cwd)
print(f"JupyterLab restarted on 127.0.0.1:{new_port}")
