import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from render import render
from preflight import pod_request, quantity


IMAGE = "000000000000.dkr.ecr.ap-northeast-2.amazonaws.com/aegis-api@sha256:" + "0" * 64


class ConfigTests(unittest.TestCase):
    def test_overlay_variable_control(self):
        rendered = {}
        for name in ("a-250", "a-1000", "b-off", "b-on"):
            app, load = render(name, IMAGE, 100, 1, "unit")
            dep = next(d for d in app if d["kind"] == "Deployment")
            self.assertEqual(dep["spec"]["replicas"], 1)
            rendered[name] = dep
        low, high = rendered["a-250"], rendered["a-1000"]
        high["spec"]["template"]["spec"]["containers"][0]["resources"]["limits"]["cpu"] = "250m"
        self.assertEqual(low, high)
        self.assertEqual(rendered["b-off"], rendered["b-on"])

    def test_oom_isolated_and_observed(self):
        for name in ("oom-128", "oom-256"):
            app, load = render(name, IMAGE, 100, 1, "unit")
            job = app[0]
            self.assertEqual(job["spec"]["backoffLimit"], 0)
            self.assertEqual(job["spec"]["template"]["spec"]["restartPolicy"], "Never")
            k6 = next(d for d in load if d["kind"] == "Job")
            env = {e["name"]:e["value"] for e in k6["spec"]["template"]["spec"]["containers"][0]["env"]}
            self.assertEqual((env["ENDPOINT"], env["RATE"]), ("info", "1"))
        with self.assertRaises(ValueError): render("oom-128", IMAGE, 100, 2, "unit")

    def test_render_guards(self):
        for image in ("latest", IMAGE.replace("0" * 64, "a864b600e8bda071860db5b019b591be7bf45071fcc57c59c32c07fa1ea66ff2")):
            with self.assertRaises(ValueError): render("b-off", image, 100, 1, "unit")
        for work, rate, run in ((0,1,"ok"),(100,0,"ok"),(100,1,"../../bad")):
            with self.assertRaises(ValueError): render("b-off", IMAGE, work, rate, run)

    def test_scheduler_request_accounting(self):
        spec = {"containers":[{"resources":{"requests":{"cpu":"100m"}}}],
                "initContainers":[{"restartPolicy":"Always","resources":{"requests":{"cpu":"25m"}}},
                                  {"resources":{"requests":{"cpu":"300m"}}}],
                "overhead":{"cpu":"5m"}}
        self.assertEqual(pod_request(spec,"cpu"), quantity("330m"))
        self.assertEqual(quantity("1Gi"), quantity("1024Mi"))


if __name__ == "__main__": unittest.main()
