"""Render locally only. Never runs apply or reaches a Kubernetes API."""
import argparse
import json
from pathlib import Path
import re
import subprocess
from yamlutil import documents
import yaml

ROOT = Path(__file__).resolve().parents[1]


def load_job(work, rate, run_id, oom=False):
    load = documents(subprocess.check_output(
        ["kubectl", "kustomize", str(ROOT / "load")], text=True))
    job = next(d for d in load if d["kind"] == "Job")
    job["metadata"]["name"] = "k6-" + run_id
    envs = job["spec"]["template"]["spec"]["containers"][0]["env"]
    for env in envs:
        if env["name"] == "RATE": env["value"] = str(rate)
        if env["name"] == "WORK_ITERATIONS": env["value"] = str(work)
        if env["name"] == "DURATION" and oom: env["value"] = "180s"
        if env["name"] == "WARMUP_SECONDS" and oom: env["value"] = "0"
    envs.append({"name":"ENDPOINT", "value":"info" if oom else "cpu"})
    return load


def render(experiment, image, work, rate, run_id):
    if not re.fullmatch(r"[0-9]{12}\.dkr\.ecr\.ap-northeast-2\.amazonaws\.com/aegis-api@sha256:[0-9a-f]{64}", image):
        raise ValueError("use the new STEP08 ECR immutable digest URI")
    if image.endswith("a864b600e8bda071860db5b019b591be7bf45071fcc57c59c32c07fa1ea66ff2"):
        raise ValueError("the preserved STEP07 image does not implement CPU/OOM work")
    if not 1 <= work <= 2_000_000 or not 1 <= rate <= 1000:
        raise ValueError("work/rate out of bounds; calibrate in pilot before comparison")
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,39}", run_id):
        raise ValueError("run-id must be a short DNS label")
    if experiment in ("a-250", "a-1000", "b-off", "b-on"):
        app = documents(subprocess.check_output(
            ["kubectl", "kustomize", str(ROOT / "k8s/overlays" / experiment)], text=True))
        dep = next(d for d in app if d["kind"] == "Deployment")
        c = dep["spec"]["template"]["spec"]["containers"][0]
        c["image"] = image
        for env in c["env"]:
            if env["name"] == "WORK_ITERATIONS":
                env["value"] = str(work)
            if env["name"] == "APP_VERSION":
                env["value"] = "step08-" + image.rsplit(":", 1)[-1][:12]
        return app, load_job(work, rate, run_id)
    if experiment not in ("oom-128", "oom-256"):
        raise ValueError("unknown experiment")
    if rate != 1:
        raise ValueError("OOM observation load must remain fixed at 1 info request/s")
    app = documents((ROOT / "k8s" / (experiment + ".yaml")).read_text())
    app[0]["metadata"]["name"] = experiment + "-" + run_id
    app[0]["spec"]["template"]["spec"]["containers"][0]["image"] = image
    return app, load_job(work, rate, run_id, oom=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--experiment", required=True, choices=["a-250", "a-1000", "b-off", "b-on", "oom-128", "oom-256"])
    p.add_argument("--image", required=True)
    p.add_argument("--work", required=True, type=int)
    p.add_argument("--rate", required=True, type=int)
    p.add_argument("--run-id", required=True)
    p.add_argument("--out", required=True, type=Path)
    a = p.parse_args()
    app, load = render(a.experiment, a.image, a.work, a.rate, a.run_id)
    output = a.out.resolve()
    if not output.is_relative_to(ROOT / "evidence/private"):
        p.error("output must be under STEP08 evidence/private")
    private = ROOT / "evidence/private"
    private.mkdir(mode=0o700, exist_ok=True)
    private.chmod(0o700)
    if output.parent != private:
        p.error("use a single unique run directory directly under evidence/private")
    output.mkdir(parents=True, mode=0o700, exist_ok=False)
    for name, data in [("app.yaml", app), ("load.yaml", load)]:
        if data:
            path = output / name
            with path.open("x") as f: yaml.safe_dump_all(data, f, sort_keys=False)
            path.chmod(0o600)
    meta = {"experiment": a.experiment, "image": a.image, "iterations": a.work,
            "rate": a.rate, "run_id": a.run_id, "status": "rendered-only; NOT an experiment result"}
    (output / "config.json").write_text(json.dumps(meta, indent=2) + "\n")
    (output / "config.json").chmod(0o600)
