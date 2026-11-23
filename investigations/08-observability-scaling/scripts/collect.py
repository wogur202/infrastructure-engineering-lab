"""Read-only evidence export. Never installs, deletes, scales, or changes AWS."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import urlencode, urlsplit
from urllib.request import urlopen
from cluster import add_arguments, client_from_args

ROOT = Path(__file__).resolve().parents[1]


def export_k6(client, config, out):
    job = "k6-" + config["run_id"]
    for filename in ("raw.json", "summary.json"):
        payload = subprocess.check_output(client.command("-n", "aegis-step08", "exec", "job/" + job,
            "-c", "k6", "--", "cat", "/results/" + filename), timeout=60)
        path = out / ("k6-" + filename)
        with path.open("xb") as f: f.write(payload)
        path.chmod(0o600)


def save(directory, name, value):
    path = directory / name
    with path.open("x") as out:
        json.dump(value, out, indent=2)
        out.write("\n")
    path.chmod(0o600)


def timestamp(text):
    if not text.endswith("Z"):
        raise ValueError("timestamps must be UTC with Z suffix")
    return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    add_arguments(parser)
    parser.add_argument("--phase", choices=["before", "after"], required=True)
    parser.add_argument("--attempt", type=int, default=1)
    parser.add_argument("--prom-url", default="http://127.0.0.1:9090")
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--invalid-reason", default="")
    args = parser.parse_args()
    run = args.run_dir.resolve()
    if not run.is_relative_to(ROOT / "evidence/private"):
        parser.error("run_dir must be STEP08 evidence/private output")
    parsed = urlsplit(args.prom_url)
    if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or parsed.path:
        parser.error("Prometheus must use a loopback-only port-forward")
    if args.phase == "after":
        if not args.start or not args.end:
            parser.error("after export requires actual --start/--end UTC timestamps")
        start, end = timestamp(args.start), timestamp(args.end)
        if not 0 < end - start <= 7200:
            parser.error("invalid or excessive query window")
    config = json.loads((run / "config.json").read_text())
    if not 1 <= args.attempt <= 99:
        parser.error("attempt must be 1..99; preserve incomplete prior exports")
    out = run / (args.phase + "-" + str(args.attempt))
    client = client_from_args(args)
    out.mkdir(mode=0o700, exist_ok=False)
    # Export short-lived k6 files FIRST, before slower log/Prometheus queries.
    if args.phase == "after":
        export_k6(client, config, out)
    commands = {
        "pods": ["-n", "aegis-step08", "get", "pods", "-o", "json"],
        "workloads": ["-n", "aegis-step08", "get", "deployment,hpa,job,service", "-o", "json"],
        "events": ["-n", "aegis-step08", "get", "events", "-o", "json"],
        "monitoring-pods": ["-n", "aegis-step08-monitoring", "get", "pods", "-o", "json"],
        "system-pods": ["-n", "kube-system", "get", "pods", "-o", "json"],
        "nodes": ["get", "nodes", "-o", "json"],
    }
    for name, command in commands.items():
        save(out, name + ".json", client.kube(*command))
    if args.phase == "after":
        pods = json.loads((out / "pods.json").read_text())["items"]
        for pod in pods:
            name = pod["metadata"]["name"]
            for container in pod["spec"].get("containers", []):
                result = subprocess.run(client.command("-n", "aegis-step08", "logs", name,
                    "-c", container["name"], "--timestamps", "--tail=10000"),
                    capture_output=True, text=True, timeout=30)
                save(out, "logs-" + name + "-" + container["name"] + ".json",
                     {"returncode":result.returncode,"stdout":result.stdout,"stderr":result.stderr})
    if args.phase == "after":
        queries = json.loads((ROOT / "monitoring/queries.json").read_text())
        required = {"cpu_cores", "cfs_period_fraction", "cfs_seconds_rate", "up",
                    "k6_cpu_cores", "k6_cfs_period_fraction", "monitoring_cpu_cores",
                    "monitoring_cfs_period_fraction", "node_memory_available", "node_memory_total",
                    "node_allocatable", "all_pod_requests", "api_placement", "k6_placement",
                    "target_sample_age", "api_cpu_sample_age", "k6_cpu_sample_age", "monitoring_cpu_sample_age"}
        if config["experiment"] == "b-on": required |= {"hpa_current", "hpa_desired", "hpa_conditions"}
        for name, query in queries.items():
            parameters = urlencode({"query": query, "start": start, "end": end, "step": "15s"})
            with urlopen(args.prom_url + "/api/v1/query_range?" + parameters, timeout=30) as response:
                data = json.load(response)
            save(out, "prom-" + name + ".json", data)
            if data.get("status") != "success":
                raise RuntimeError("Prometheus query failed: " + name)
            if name in required and not data.get("data", {}).get("result"):
                raise RuntimeError("required metric is absent: " + name)
    save(out, "collection.json", {"collected_utc": datetime.now(timezone.utc).isoformat(),
        "start_utc": args.start, "end_utc": args.end, "invalid_reason": args.invalid_reason,
        "config": config, "notice": "export complete does NOT mean the experiment passed"})
    index = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in out.iterdir() if p.is_file()}
    save(out, "SHA256.json", index)
    print("Private export complete:", out, "Review coverage, failures and hashes before cleanup.")


if __name__ == "__main__":
    main()
