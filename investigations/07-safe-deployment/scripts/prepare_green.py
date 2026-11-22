"""Opt-in local CD for an existing Green slot. Never writes an Ingress or Blue."""
import argparse
import json
from pathlib import Path
import re
import selectors
import subprocess
import sys
import time

IMAGE = re.compile(r"[0-9]{12}\.dkr\.ecr\.ap-northeast-2\.amazonaws\.com/aegis-api@sha256:[0-9a-f]{64}")


def require_blue_only(ingress):
    action = json.loads(ingress["metadata"]["annotations"][
        "alb.ingress.kubernetes.io/actions.aegis-api-weighted"])
    backend = ingress["spec"]["rules"][0]["http"]["paths"][0]["backend"]["service"]
    if len(ingress["spec"]["rules"]) != 1 or len(ingress["spec"]["rules"][0]["http"]["paths"]) != 1:
        raise ValueError("unexpected extra routing rules")
    if action["type"] != "forward" or backend != {
        "name": "aegis-api-weighted", "port": {"name": "use-annotation"}
    }:
        raise ValueError("existing weighted Ingress bootstrap is required")
    targets = action["forwardConfig"]["targetGroups"]
    if len(targets) != 2 or {(item["serviceName"], item["servicePort"], item["weight"]) for item in targets} != {
        ("aegis-api-blue", 8080, 100), ("aegis-api-green", 8080, 0)
    }:
        raise ValueError("refusing Green update: expected Blue 100 / Green 0")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--context", required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    forwarding = None
    try:
        if not IMAGE.fullmatch(args.image) or not re.fullmatch(r"[0-9a-f]{40}", args.version):
            raise ValueError("expected immutable ECR digest and full commit SHA version")
        if not args.execute:
            print("PLAN only: read existing slots and Blue-only routing; patch Green; rollout; local port-forward smoke")
            print("No Kubernetes/AWS calls. Bootstrap slots/weighted Ingress is a separate operation.")
            return 0
        command = ["kubectl", "--context", args.context, "--namespace", "aegis"]

        def get(kind, name):
            return json.loads(subprocess.check_output(command + ["get", kind, name, "-o", "json"], timeout=30))

        require_blue_only(get("ingress", "aegis-api"))
        blue_spec = get("deployment", "aegis-api-blue")["spec"]
        green = get("deployment", "aegis-api-green")
        expected = {"app": "aegis-api-step07", "slot": "green"}
        if (green["spec"]["selector"]["matchLabels"] != expected
                or green["spec"]["template"]["metadata"]["labels"] != expected
                or get("service", "aegis-api-green")["spec"]["selector"] != expected):
            raise ValueError("unexpected Green selectors")
        patch = {"spec": {"template": {"spec": {"containers": [{
            "name": "api", "image": args.image, "env": [
                {"name": "APP_VERSION", "value": args.version},
                {"name": "APP_SLOT", "value": "green"},
                {"name": "INJECT_API_FAILURE", "value": "0"},
            ],
        }]}}}}
        subprocess.run(command + ["patch", "deployment", "aegis-api-green", "--type", "strategic",
                                  "--patch", json.dumps(patch)], check=True, timeout=30)
        subprocess.run(command + ["rollout", "status", "deployment/aegis-api-green", "--timeout=180s"],
                       check=True, timeout=200)
        forwarding = subprocess.Popen(command + ["port-forward", "--address", "127.0.0.1",
                                                  "service/aegis-api-green", ":8080"],
                                      stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        with selectors.DefaultSelector() as ready:
            ready.register(forwarding.stdout, selectors.EVENT_READ)
            deadline = time.monotonic() + 20
            port = None
            while time.monotonic() < deadline:
                if forwarding.poll() is not None:
                    raise RuntimeError("Green port-forward exited")
                if ready.select(timeout=0.5):
                    line = forwarding.stdout.readline()
                    match = re.search(r"Forwarding from 127\.0\.0\.1:([0-9]+)", line)
                    if match:
                        port = match.group(1)
                        break
            if port is None:
                raise RuntimeError("Green port-forward timeout")
        subprocess.run([sys.executable, str(Path(__file__).with_name("smoke.py")),
                        f"http://127.0.0.1:{port}", "--expected-version", args.version,
                        "--expected-slot", "green"], check=True, timeout=15)
        require_blue_only(get("ingress", "aegis-api"))
        if get("deployment", "aegis-api-blue")["spec"] != blue_spec:
            raise ValueError("Blue spec changed during preparation")
        print("PASS Green rollout and one port-forwarded Pod smoke; Blue desired weight remains 100")
        print("ALB target health/effective routing are not verified; no traffic switch or rollback performed")
        return 0
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"FAIL Green preparation: {error}", file=sys.stderr)
        return 1
    finally:
        if forwarding is not None:
            forwarding.terminate()
            try:
                forwarding.wait(timeout=5)
            except subprocess.TimeoutExpired:
                forwarding.kill()
                forwarding.wait()


if __name__ == "__main__":
    sys.exit(main())
