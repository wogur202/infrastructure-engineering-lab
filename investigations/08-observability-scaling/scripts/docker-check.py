"""Local amd64 build/smoke only; no ECR auth, tag, or push."""
import json
from pathlib import Path
import subprocess
import sys
import time
from smoke import smoke

ROOT = Path(__file__).resolve().parents[1]
tag = "aegis-step08-local:verification"
subprocess.run(["docker", "build", "--platform", "linux/amd64", "-t", tag, str(ROOT / "app")], check=True)
arch = subprocess.check_output(["docker", "image", "inspect", tag, "--format", "{{.Architecture}}"], text=True).strip()
assert arch == "amd64", arch
container = subprocess.check_output(["docker", "run", "-d", "--platform", "linux/amd64", "--read-only",
    "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "-p", "127.0.0.1::8080", tag], text=True).strip()
try:
    mapping = json.loads(subprocess.check_output(["docker", "inspect", container], text=True))[0]
    port = mapping["NetworkSettings"]["Ports"]["8080/tcp"][0]["HostPort"]
    for attempt in range(30):
        try:
            smoke("http://127.0.0.1:" + port)
            break
        except Exception:
            if attempt == 29: raise
            time.sleep(.5)
    subprocess.run(["docker", "exec", container, "python", "memory_job.py", "--safe", "--mib", "2",
                    "--step-mib", "1", "--hold-seconds", "0", "--max-seconds", "2"], check=True)
finally:
    subprocess.run(["docker", "rm", "-f", container], check=True, stdout=subprocess.DEVNULL)
print("linux/amd64 image, read-only nonroot HTTP smoke and safe 2Mi allocation PASS")
