"""Three-second local integration check, not an AWS load experiment."""
import json
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
server = subprocess.check_output(["docker", "run", "-d", "--platform", "linux/amd64",
    "--read-only", "--cap-drop", "ALL", "aegis-step08-local:verification"], text=True).strip()
try:
    for attempt in range(30):
        ready = subprocess.run(["docker", "exec", server, "python", "-c",
            "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/readyz', timeout=2).read()"],
            capture_output=True, timeout=5)
        if ready.returncode == 0: break
        if attempt == 29: raise RuntimeError("local API never became Ready")
        time.sleep(.2)
    result = subprocess.run(["docker", "run", "--rm", "--platform", "linux/amd64",
        "--network", "container:" + server, "--read-only", "--user", "10001:10001",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--tmpfs", "/results:rw,size=32m,uid=10001,gid=10001", "--tmpfs", "/tmp:rw,size=16m",
        "--mount", "type=bind,src=" + str(ROOT / "load") + ",dst=/scripts,readonly",
        "-e", "RATE=2", "-e", "WORK_ITERATIONS=1000", "-e", "PRE_VUS=2", "-e", "MAX_VUS=2",
        "-e", "BASE_URL=http://127.0.0.1:8080", "-e", "DURATION=2s", "-e", "WARMUP_SECONDS=1",
        "-e", "K6_NO_USAGE_REPORT=true",
        "grafana/k6:1.0.0@sha256:f21270290d702cbf0a7d6ba5d7ed100b63bcb233b558b885ed787547b3488279",
        "run", "--out", "json=/results/raw.json", "/scripts/cpu.js"],
        capture_output=True, text=True, timeout=45)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    with (ROOT / (".local/k6-check-" + stamp + ".log")).open("x") as log:
        log.write(result.stdout + "\n" + result.stderr)
    assert result.returncode == 0, result.stderr
    line = next(x.split("STEP08_SUMMARY ", 1)[1] for x in result.stdout.splitlines() if "STEP08_SUMMARY " in x)
    data = json.loads(line)
    assert data["metrics"]["api_errors"]["values"]["rate"] == 0
    assert data["metrics"]["http_reqs{phase:measure}"]["values"]["count"] > 0
    print("Local k6 -> amd64 API, bounded VUs, phase metrics, raw/summary export: PASS")
finally:
    subprocess.run(["docker", "rm", "-f", server], check=True, stdout=subprocess.DEVNULL)
