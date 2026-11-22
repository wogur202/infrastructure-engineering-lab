import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from urllib.request import ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("aegis_step07_server", ROOT / "app/server.py")
api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(api)


class SmokeTests(unittest.TestCase):
    def check_smoke(self, fail_api=False, expected_version="test-green", slot="green"):
        server = api.create_server("127.0.0.1", 0, "test-green", "green", fail_api)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            opener = build_opener(ProxyHandler({}))
            for path in ("/healthz", "/readyz"):
                with opener.open(base + path, timeout=2) as response:
                    self.assertEqual(response.status, 200)
            return subprocess.run(
                [sys.executable, str(ROOT / "scripts/smoke.py"), base,
                 "--expected-version", expected_version, "--expected-slot", slot],
                capture_output=True, text=True, timeout=10,
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    def test_normal(self):
        self.assertEqual(self.check_smoke().returncode, 0)

    def test_api_failure_preserves_health_but_blocks_smoke(self):
        result = self.check_smoke(fail_api=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("503", result.stderr)

    def test_wrong_version_blocks_smoke(self):
        self.assertNotEqual(self.check_smoke(expected_version="old").returncode, 0)

    def test_wrong_slot_blocks_smoke(self):
        self.assertNotEqual(self.check_smoke(slot="blue").returncode, 0)


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        outputs = self.base / "outputs.json"
        outputs.write_text(json.dumps({"public_subnet_ids": {"value": [
            "subnet-00000000000000001", "subnet-00000000000000002"
        ]}}))
        self.command = [sys.executable, str(ROOT / "scripts/render.py"),
            "--outputs-json", str(outputs),
            "--blue-image", "000000000000.dkr.ecr.ap-northeast-2.amazonaws.com/aegis-api@sha256:" + "a" * 64,
            "--green-image", "000000000000.dkr.ecr.ap-northeast-2.amazonaws.com/aegis-api@sha256:" + "b" * 64,
            "--blue-version", "1.0.0", "--green-version", "1.1.0",
            "--allowed-cidr", "192.0.2.1/32", "--output-dir", str(self.base / "rendered")]

    def run_render(self, command=None):
        return subprocess.run(command or self.command, capture_output=True, text=True, timeout=10)

    def test_render_selectors_probes_images_and_weighted_action(self):
        result = self.run_render()
        self.assertEqual(result.returncode, 0, result.stderr)
        selectors = []
        for slot in ("blue", "green"):
            document = json.loads((self.base / f"rendered/{slot}.yaml").read_text())
            deployment, service = document["items"]
            selector = deployment["spec"]["selector"]["matchLabels"]
            self.assertEqual(selector, {"app": "aegis-api-step07", "slot": slot})
            self.assertEqual(selector, service["spec"]["selector"])
            self.assertEqual(selector, deployment["spec"]["template"]["metadata"]["labels"])
            selectors.append(selector)
            container = deployment["spec"]["template"]["spec"]["containers"][0]
            self.assertIn("@sha256:", container["image"])
            self.assertEqual(container["readinessProbe"]["httpGet"]["path"], "/readyz")
            self.assertEqual(container["livenessProbe"]["httpGet"]["path"], "/healthz")
            self.assertTrue(container["securityContext"]["runAsNonRoot"])
            self.assertEqual(container["env"][2]["value"], "0")
        self.assertNotEqual(*selectors)
        ingress = json.loads((self.base / "rendered/ingress.yaml").read_text())
        self.assertEqual(ingress["metadata"]["name"], "aegis-api")
        action = json.loads(ingress["metadata"]["annotations"]["alb.ingress.kubernetes.io/actions.aegis-api-weighted"])
        self.assertEqual(action["type"], "forward")
        self.assertEqual(action["forwardConfig"]["targetGroups"], [
            {"serviceName": "aegis-api-blue", "servicePort": 8080, "weight": 100},
            {"serviceName": "aegis-api-green", "servicePort": 8080, "weight": 0},
        ])
        backend = ingress["spec"]["rules"][0]["http"]["paths"][0]["backend"]["service"]
        self.assertEqual(backend, {"name": "aegis-api-weighted", "port": {"name": "use-annotation"}})

    def test_refuses_to_overwrite_previous_render(self):
        self.assertEqual(self.run_render().returncode, 0)
        self.assertNotEqual(self.run_render().returncode, 0)

    def test_mutable_image_rejected(self):
        command = self.command.copy()
        command[command.index("--blue-image") + 1] = "aegis-api:latest"
        self.assertNotEqual(self.run_render(command).returncode, 0)

    def test_public_cidr_rejected(self):
        command = self.command.copy()
        command[command.index("--allowed-cidr") + 1] = "0.0.0.0/0"
        self.assertNotEqual(self.run_render(command).returncode, 0)

    def test_green_failure_is_explicit(self):
        self.assertEqual(self.run_render(self.command + ["--green-failure", "1"]).returncode, 0)
        document = json.loads((self.base / "rendered/green.yaml").read_text())
        container = document["items"][0]["spec"]["template"]["spec"]["containers"][0]
        self.assertEqual(container["env"][2]["value"], "1")


if __name__ == "__main__":
    unittest.main()
