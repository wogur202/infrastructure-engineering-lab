import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from cluster import Client, NODEGROUP, ROLE_LABEL, node_ready
from node_labels import assignments, label_patch, apply_review, check_placement


def node(name, instance):
    return {"metadata":{"name":name,"uid":"uid-" + name,"resourceVersion":"10",
            "labels":{"eks.amazonaws.com/nodegroup":NODEGROUP}},
            "spec":{"providerID":"aws:///ap-northeast-2a/" + instance},
            "status":{"conditions":[{"type":k,"status":v} for k,v in
                [("Ready","True"),("MemoryPressure","False"),("DiskPressure","False"),("PIDPressure","False")]]}}


class FakeClient:
    def __init__(self, nodes, conflict=None):
        self.nodes = {n["metadata"]["name"]:copy.deepcopy(n) for n in nodes}
        self.patches = []
        self.conflict = conflict

    def verified_nodes(self):
        return copy.deepcopy(list(self.nodes.values()))

    def kube(self, *args):
        name = args[2]
        if args[0] == "get": return copy.deepcopy(self.nodes[name])
        if args[0] != "patch": raise AssertionError("unexpected command")
        self.patches.append(name)
        operations = json.loads(args[args.index("-p") + 1])
        if self.conflict == name: raise RuntimeError("resourceVersion test failed")
        expected_rv = next(x["value"] for x in operations if x["path"] == "/metadata/resourceVersion")
        if self.nodes[name]["metadata"]["resourceVersion"] != expected_rv:
            raise RuntimeError("stale resourceVersion")
        self.nodes[name]["metadata"]["labels"][ROLE_LABEL] = operations[-1]["value"]
        self.nodes[name]["metadata"]["resourceVersion"] = "11"
        return copy.deepcopy(self.nodes[name])


class SafetyTests(unittest.TestCase):
    def setUp(self):
        self.nodes = [node("node-a", "i-aaa"), node("node-b", "i-bbb")]
        self.review = assignments(self.nodes, "node-a", "node-b")

    def test_distinct_nodes_required(self):
        with self.assertRaises(RuntimeError): assignments(self.nodes, "node-a", "node-a")
        same = copy.deepcopy(self.nodes)
        same[1]["spec"]["providerID"] = same[0]["spec"]["providerID"]
        with self.assertRaises(RuntimeError): assignments(same, "node-a", "node-b")

    def test_wrong_existing_label_aborts(self):
        self.nodes[0]["metadata"]["labels"][ROLE_LABEL] = "support"
        with self.assertRaises(RuntimeError): assignments(self.nodes, "node-a", "node-b")

    def test_missing_ready_or_pressure_aborts(self):
        for conditions in ([], [{"type":"Ready","status":"True"}],
                           [{"type":"Ready","status":"False"}]):
            bad = copy.deepcopy(self.nodes[0]);bad["status"]["conditions"] = conditions
            with self.assertRaises(RuntimeError): node_ready(bad)

    def test_replacement_aborts_before_patch(self):
        for field in ("uid", "providerID"):
            bad = copy.deepcopy(self.nodes[0])
            if field == "uid": bad["metadata"][field] = "replacement-uid"
            else: bad["spec"][field] = "aws:///ap-northeast-2a/i-ccc"
            with self.assertRaises(RuntimeError): label_patch(bad, self.review["node-a"])

    def test_atomic_resource_version_and_label_tests(self):
        fresh = copy.deepcopy(self.nodes[0]);fresh["metadata"]["resourceVersion"] = "15"
        operations = label_patch(fresh, self.review["node-a"])
        tests = {x["path"]:x["value"] for x in operations if x["op"] == "test"}
        self.assertEqual(tests["/metadata/resourceVersion"], "15")
        self.assertEqual(tests["/metadata/uid"], "uid-node-a")
        self.assertIn("/metadata/labels", tests)
        self.assertEqual(operations[-1]["path"], "/metadata/labels/aegis.lab~1role")

    def test_partial_failure_has_no_retry_or_rollback(self):
        fake = FakeClient(self.nodes, conflict="node-b")
        with self.assertRaises(RuntimeError): apply_review(fake, self.review)
        self.assertEqual(fake.patches, ["node-a", "node-b"])
        self.assertEqual(fake.nodes["node-a"]["metadata"]["labels"][ROLE_LABEL], "api")
        self.assertNotIn(ROLE_LABEL, fake.nodes["node-b"]["metadata"]["labels"])

    def test_post_write_roles_verified(self):
        fake = FakeClient(self.nodes)
        self.assertEqual(apply_review(fake, self.review), {"node-a":"api","node-b":"support"})

    def test_role_change_since_inventory_aborts(self):
        current = copy.deepcopy(self.nodes[0])
        current["metadata"]["labels"][ROLE_LABEL] = "api"
        with self.assertRaises(RuntimeError): label_patch(current, self.review["node-a"])

    def test_real_membership_check_rejects_different_asg_instances(self):
        client = object.__new__(Client)
        def aws(*args):
            if args[0] == "eks":
                return {"nodegroup":{"status":"ACTIVE","scalingConfig":{"minSize":2,"maxSize":2,"desiredSize":2},
                        "resources":{"autoScalingGroups":[{"name":"mock-asg"}]}}}
            return {"AutoScalingGroups":[{"AutoScalingGroupName":"mock-asg","Instances":[
                {"InstanceId":i,"LifecycleState":"InService","HealthStatus":"Healthy"} for i in ["i-aaa","i-ccc"]]}]}
        client.aws = aws
        client.kube = lambda *_: {"items":copy.deepcopy(self.nodes)}
        with self.assertRaises(RuntimeError): client.verified_nodes()

    def test_membership_change_aborts(self):
        fake = FakeClient([self.nodes[0], node("replacement", "i-ccc")])
        with self.assertRaises(RuntimeError): apply_review(fake, self.review)
        self.assertEqual(fake.patches, [])

    def test_placement_not_verified_when_absent(self):
        result = check_placement([], {"node-a":"api","node-b":"support"})
        self.assertTrue(result["status"].startswith("NOT_VERIFIED"))
        pods = [{"metadata":{"labels":{"app":app}},"status":{"phase":"Running","containerStatuses":[{"ready":True}]},
                 "spec":{"nodeName":"node-a"}} for app in ["aegis-step08-api","step08-k6"]]
        with self.assertRaises(RuntimeError): check_placement(pods, {"node-a":"api","node-b":"support"})

    def test_wrong_account_endpoint_tls_rejected(self):
        ROOT.joinpath(".local").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / ".local") as directory:
            path = Path(directory) / "kubeconfig";path.write_text("mock-only");path.chmod(0o600)
            def aws(_self, *args):
                if args[0] == "sts": return {"Account":"000000000000"}
                return {"cluster":{"arn":"arn:aws:eks:ap-northeast-2:000000000000:cluster/aegis-step08",
                       "endpoint":"https://expected.invalid","status":"ACTIVE"}}
            for server in ({"server":"https://wrong.invalid","certificate-authority-data":"mock"},
                           {"server":"https://expected.invalid","certificate-authority-data":"mock","insecure-skip-tls-verify":True}):
                with patch.object(Client,"aws",aws), patch.object(Client,"kube",return_value={"clusters":[{"cluster":server}]}):
                    with self.assertRaises(RuntimeError): Client(path,"alias","000000000000")
            with patch.object(Client,"aws",aws):
                with self.assertRaises(RuntimeError): Client(path,"alias","111111111111")


if __name__ == "__main__": unittest.main()
