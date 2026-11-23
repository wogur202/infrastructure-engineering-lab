"""Explicit kubeconfig + live AWS cluster identity checks for STEP08 tools."""
import json
from pathlib import Path
import re
import subprocess

CLUSTER = "aegis-step08"
NODEGROUP = "aegis-step08-workers"
REGION = "ap-northeast-2"
ROLE_LABEL = "aegis.lab/role"


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def node_ready(node):
    conditions = {x["type"]: x["status"] for x in node.get("status", {}).get("conditions", [])}
    require(conditions.get("Ready") == "True", "node must explicitly report Ready=True")
    for key in ("MemoryPressure", "DiskPressure", "PIDPressure"):
        require(conditions.get(key) == "False", "node pressure is missing/active: " + key)
    require(not node["spec"].get("unschedulable", False), "node is cordoned")


def node_identity(node):
    metadata = node["metadata"]
    identity = {"name": metadata["name"], "uid": metadata["uid"],
                "resourceVersion": metadata["resourceVersion"], "providerID": node["spec"]["providerID"]}
    require(bool(re.fullmatch(r"aws:///ap-northeast-2[ac]/i-[0-9a-f]+", identity["providerID"])),
            "unexpected providerID/AZ")
    return identity


def add_arguments(parser):
    parser.add_argument("--kubeconfig", type=Path, required=True)
    parser.add_argument("--context", required=True)
    parser.add_argument("--expected-account", required=True)
    parser.add_argument("--aws-profile", default="terraform-lab")


class Client:
    def __init__(self, kubeconfig, context, expected_account, profile="terraform-lab"):
        require(bool(re.fullmatch(r"[0-9]{12}", expected_account)), "invalid expected account")
        self.account, self.profile = expected_account, profile
        self.kubeconfig = kubeconfig.resolve(strict=True)
        require(self.kubeconfig.is_file(), "kubeconfig must be a file")
        require(self.kubeconfig.stat().st_mode & 0o077 == 0, "kubeconfig must not be group/world readable")
        self.context = context
        self.aws_identity = self.aws("sts", "get-caller-identity")
        require(self.aws_identity["Account"] == expected_account, "AWS account mismatch")
        self.cluster = self.aws("eks", "describe-cluster", "--name", CLUSTER)["cluster"]
        expected_arn = f"arn:aws:eks:{REGION}:{expected_account}:cluster/{CLUSTER}"
        require(self.cluster["arn"] == expected_arn and self.cluster["status"] == "ACTIVE", "wrong/inactive EKS cluster")
        config = self.kube("config", "view", "--minify", "-o", "json")
        server = config["clusters"][0]["cluster"]
        require(server["server"] == self.cluster["endpoint"], "kubeconfig endpoint does not match AWS EKS")
        require(not server.get("insecure-skip-tls-verify", False), "kubeconfig TLS verification must remain enabled")
        require(bool(server.get("certificate-authority") or server.get("certificate-authority-data")), "cluster CA missing")

    def aws(self, *args):
        return json.loads(subprocess.check_output(["aws", "--profile", self.profile, "--region", REGION,
            "--output", "json", *args], text=True, timeout=30))

    def command(self, *args):
        return ["kubectl", "--kubeconfig", str(self.kubeconfig), "--context", self.context, *args]

    def kube(self, *args):
        return json.loads(subprocess.check_output(self.command(*args), text=True, timeout=30))

    def verified_nodes(self):
        group = self.aws("eks", "describe-nodegroup", "--cluster-name", CLUSTER,
                         "--nodegroup-name", NODEGROUP)["nodegroup"]
        require(group["status"] == "ACTIVE" and all(group["scalingConfig"].get(k) == 2 for k in ("desiredSize", "minSize", "maxSize")), "unexpected node group state")
        groups = [g["name"] for g in group["resources"]["autoScalingGroups"]]
        require(bool(groups), "node group ASG missing")
        asgs = self.aws("autoscaling", "describe-auto-scaling-groups", "--auto-scaling-group-names", *groups)["AutoScalingGroups"]
        require({g["AutoScalingGroupName"] for g in asgs} == set(groups), "ASG membership incomplete")
        instances = [x for g in asgs for x in g["Instances"]]
        require(len(instances) == 2 and all(x["LifecycleState"] == "InService" and x["HealthStatus"] == "Healthy" for x in instances),
                "expected exactly two healthy ASG instances")
        nodes = self.kube("get", "nodes", "-o", "json")["items"]
        require(len(nodes) == 2, "cluster must contain exactly two nodes")
        for node in nodes:
            require(node["metadata"].get("labels", {}).get("eks.amazonaws.com/nodegroup") == NODEGROUP,
                    "wrong node group label")
            node_ready(node)
        identities = [node_identity(n) for n in nodes]
        for key in ("name", "uid", "providerID"):
            require(len({n[key] for n in identities}) == 2, "duplicate node identity: " + key)
        require({n["providerID"].rsplit("/", 1)[-1] for n in identities} == {i["InstanceId"] for i in instances},
                "Kubernetes nodes do not match EKS/ASG instances")
        return nodes


def client_from_args(args):
    return Client(args.kubeconfig, args.context, args.expected_account, args.aws_profile)
