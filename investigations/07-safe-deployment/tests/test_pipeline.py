"""Offline pipeline gates: AWS/kubectl commands are always mocked or prohibited."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / f"scripts/{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PipelineTests(unittest.TestCase):
    def test_workflow_only_manual_main_publish_after_ci(self):
        workflow = json.loads((REPO / ".github/workflows/step07-ci.yaml").read_text())
        self.assertFalse(workflow["on"]["workflow_dispatch"]["inputs"]["publish_ecr"]["default"])
        publish = workflow["jobs"]["publish"]
        self.assertEqual(publish["needs"], ["ci"])
        self.assertIn("workflow_dispatch", publish["if"])
        self.assertIn("inputs.publish_ecr", publish["if"])
        self.assertIn("refs/heads/main", publish["if"])
        self.assertNotIn("environment", publish)
        trust = json.loads((ROOT / "iam/github-trust-policy.json").read_text())
        conditions = trust["Statement"][0]["Condition"]
        self.assertEqual(conditions, {"StringEquals": {
            "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
            "token.actions.githubusercontent.com:sub":
                "repo:wogur202@162789945/infrastructure-engineering-lab@1452771896:ref:refs/heads/main",
        }})
        self.assertNotIn("id-token", workflow["permissions"])
        self.assertEqual(publish["permissions"]["id-token"], "write")
        for job in workflow["jobs"].values():
            self.assertFalse(any(step.get("continue-on-error", False) for step in job["steps"]))
            self.assertFalse(any("kubectl" in step.get("run", "") for step in job["steps"]))

    def test_ci_failure_stops_before_docker(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            python = base / "python3"
            python.write_text("#!/bin/sh\nexit 42\n")
            python.chmod(0o755)
            docker = base / "docker"
            docker.write_text("#!/bin/sh\necho unexpected-docker-invocation\nexit 0\n")
            docker.chmod(0o755)
            import os
            env = dict(os.environ, PATH=directory + os.pathsep + os.environ["PATH"], CI_IMAGE="unused:test")
            result = subprocess.run(["bash", str(ROOT / "scripts/ci.sh")],
                                    env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 42)
            self.assertNotIn("unexpected-docker", result.stdout)

    def test_publish_plan_never_calls_aws_or_docker(self):
        publish = load("publish")
        with patch.object(sys, "argv", ["publish", "--registry",
                "000000000000.dkr.ecr.ap-northeast-2.amazonaws.com", "--commit", "a" * 40,
                "--local-image", "local:test"]), patch.object(publish.subprocess, "run") as run, \
                patch.object(publish.subprocess, "check_output") as output:
            self.assertEqual(publish.main(), 0)
            run.assert_not_called()
            output.assert_not_called()

    def test_lookup_distinguishes_missing_image_from_access_denied(self):
        publish = load("publish")
        with patch.object(publish.subprocess, "run", return_value=subprocess.CompletedProcess(
                [], 1, "", "An error occurred (ImageNotFoundException)")):
            self.assertIsNone(publish.describe("aegis-api", "git-test"))
        with patch.object(publish.subprocess, "run", return_value=subprocess.CompletedProcess(
                [], 1, "", "An error occurred (AccessDeniedException)")):
            with self.assertRaises(RuntimeError):
                publish.describe("aegis-api", "git-test")

    def test_green_plan_never_calls_kubectl(self):
        green = load("prepare_green")
        with patch.object(sys, "argv", ["green", "--context", "not-connected", "--image",
                "000000000000.dkr.ecr.ap-northeast-2.amazonaws.com/aegis-api@sha256:" + "a" * 64,
                "--version", "a" * 40]), patch.object(green.subprocess, "run") as run, \
                patch.object(green.subprocess, "check_output") as output:
            self.assertEqual(green.main(), 0)
            run.assert_not_called()
            output.assert_not_called()

    def test_green_rejects_live_green_traffic_and_legacy_backend(self):
        green = load("prepare_green")
        ingress = json.loads((ROOT / "k8s/ingress.yaml").read_text())
        green.require_blue_only(ingress)
        key = "alb.ingress.kubernetes.io/actions.aegis-api-weighted"
        action = json.loads(ingress["metadata"]["annotations"][key])
        action["forwardConfig"]["targetGroups"][1]["weight"] = 10
        ingress["metadata"]["annotations"][key] = json.dumps(action)
        with self.assertRaises(ValueError):
            green.require_blue_only(ingress)
        ingress = json.loads((ROOT / "k8s/ingress.yaml").read_text())
        ingress["spec"]["rules"][0]["http"]["paths"][0]["backend"]["service"] = {
            "name": "aegis-api", "port": {"number": 8080}}
        with self.assertRaises(ValueError):
            green.require_blue_only(ingress)


if __name__ == "__main__":
    unittest.main()
