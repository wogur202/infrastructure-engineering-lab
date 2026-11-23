"""Read-only runtime gates. Run only after a separately reviewed deployment."""
import argparse
from decimal import Decimal
import json
import re
import subprocess
from urllib.parse import urlencode
from urllib.request import urlopen
from datetime import datetime, timezone
from cluster import ROLE_LABEL, add_arguments, client_from_args, node_ready, require
from node_labels import check_placement


MANUAL_GATES = ["two API Pods simultaneously Ready", "known CPU work increases counters",
                "generator headroom and actual offered RPS", "HPA steady Scaling Conditions"]


def quantity(value):
    match = re.fullmatch(r"([0-9.+eE-]+)([a-zA-Z]*)", str(value))
    if not match:
        raise ValueError("unsupported Kubernetes quantity: " + str(value))
    suffix = {"":1, "n":Decimal("1e-9"), "u":Decimal("1e-6"), "m":Decimal(".001"),
              "k":1000, "M":10**6, "G":10**9, "Ki":1024, "Mi":1024**2, "Gi":1024**3}
    return Decimal(match[1]) * suffix[match[2]]


def pod_request(spec, resource):
    def request(container):
        return quantity(container.get("resources", {}).get("requests", {}).get(resource, "0"))
    regular = sum((request(c) for c in spec.get("containers", [])), Decimal(0))
    sidecars, init_peak = Decimal(0), Decimal(0)
    for c in spec.get("initContainers", []):
        if c.get("restartPolicy") == "Always":
            sidecars += request(c)
            init_peak = max(init_peak, sidecars)
        else:
            init_peak = max(init_peak, sidecars + request(c))
    result = max(regular + sidecars, init_peak)
    pod_level = spec.get("resources", {}).get("requests", {}).get(resource)
    if pod_level is not None: result = quantity(pod_level)
    return result + quantity(spec.get("overhead", {}).get(resource, "0"))


def main():
    require(__debug__, "do not run safety checks with Python -O/PYTHONOPTIMIZE")
    p = argparse.ArgumentParser(description=__doc__)
    add_arguments(p)
    p.add_argument("--expect-hpa", choices=["off", "on"], required=True)
    p.add_argument("--prom-url", default="http://127.0.0.1:9090")
    args = p.parse_args()
    if not re.fullmatch(r"http://127\.0\.0\.1:[0-9]+", args.prom_url):
        p.error("use localhost-only Prometheus forwarding")
    client = client_from_args(args)
    get = client.kube
    nodes = client.verified_nodes()
    pods = get("get", "pods", "--all-namespaces", "-o", "json")["items"]
    assert len(nodes) == 2, "expected exactly two nodes"
    roles = [n["metadata"]["labels"].get("aegis.lab/role") for n in nodes]
    assert sorted(roles) == ["api", "support"], "assign one stable label per node before experiments"
    for node in nodes:
        node_ready(node)
        name = node["metadata"]["name"]
        role = node["metadata"]["labels"]["aegis.lab/role"]
        current = [x for x in pods if x["spec"].get("nodeName") == name and x["status"].get("phase") not in ("Succeeded", "Failed")]
        baseline = [x for x in current if x["metadata"].get("labels", {}).get("app") not in ("aegis-step08-api", "step08-k6")]
        cpu = sum((pod_request(x["spec"], "cpu") for x in baseline), Decimal(0))
        mem = sum((pod_request(x["spec"], "memory") for x in baseline), Decimal(0))
        # Reserve the actual comparison peak, irrespective of current replicas.
        cpu += Decimal("1") if role == "api" else Decimal(".25")
        mem += quantity("256Mi")
        alloc = node["status"]["allocatable"]
        assert quantity(alloc["cpu"]) - cpu >= Decimal(".2"), "insufficient projected CPU headroom"
        assert quantity(alloc["memory"]) - mem >= quantity("512Mi"), "insufficient memory headroom"
        assert int(alloc["pods"]) >= len(baseline) + (2 if role == "api" else 1) + 2
        print(json.dumps({"node":name,"role":role,"providerID":node["spec"].get("providerID"),
              "allocatable":alloc,"projected_cpu_request_cores":str(cpu),"projected_memory_bytes":str(mem)}))
    relevant = [x for x in pods if x["metadata"]["namespace"] in ("aegis-step08", "aegis-step08-monitoring", "kube-system")]
    api = [x for x in relevant if x["metadata"].get("labels", {}).get("app") == "aegis-step08-api"]
    assert api, "API must be deployed and Ready before the gate"
    role_by_node = {n["metadata"]["name"]: n["metadata"]["labels"]["aegis.lab/role"] for n in nodes}
    for pod in api:
        assert pod["status"].get("phase") == "Running", "API is not running"
        assert pod["status"].get("containerStatuses"), "missing API readiness status"
        assert all(c.get("ready") for c in pod["status"]["containerStatuses"]), "API is not Ready"
        assert role_by_node.get(pod["spec"].get("nodeName")) == "api", "wrong API placement"
        assert all("@sha256:" in c["image"] for c in pod["spec"]["containers"]), "pin API digest"
    for pod in relevant:
        phase = pod["status"].get("phase")
        assert phase != "Pending", "Pending pod: " + pod["metadata"]["name"]
        if phase == "Running":
            statuses = pod["status"].get("containerStatuses", [])
            require(bool(statuses) and all(c.get("ready") for c in statuses), "unready container")
        require(pod["status"].get("reason") != "Evicted", "pod was evicted; preserve evidence and investigate")
    # This API is independent of Prometheus and must work for HPA.
    require(bool(get("get", "--raw", "/apis/metrics.k8s.io/v1beta1/nodes")["items"]), "node metrics absent")
    pod_metrics = get("get", "--raw", "/apis/metrics.k8s.io/v1beta1/namespaces/aegis-step08/pods")["items"]
    by_name = {m["metadata"]["name"]: m for m in pod_metrics}
    for pod in api:
        require(pod["metadata"]["name"] in by_name, "API resource metrics absent")
        metric = by_name[pod["metadata"]["name"]]
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(metric["timestamp"].replace("Z", "+00:00"))).total_seconds()
        require(-5 <= age <= 60, "API resource metrics stale")
        require(any(c["name"] == "api" and quantity(c["usage"]["cpu"]) >= 0 for c in metric["containers"]), "API CPU metric invalid")
    api_resources = get("get", "--raw", "/apis/autoscaling/v2")["resources"]
    require(any(x["kind"] == "HorizontalPodAutoscaler" for x in api_resources), "HPA API missing")
    hpas = get("-n", "aegis-step08", "get", "hpa", "-o", "json")["items"]
    require(bool(hpas) == (args.expect_hpa == "on"), "unexpected HPA presence/absence")
    if args.expect_hpa == "on":
        require(len(hpas) == 1 and hpas[0]["metadata"]["name"] == "aegis-step08-api", "unexpected HPA")
        hpa = hpas[0]
        require(hpa["spec"]["minReplicas"] == 1 and hpa["spec"]["maxReplicas"] == 2, "HPA bounds changed")
        require(hpa["spec"]["metrics"][0]["resource"]["target"]["averageUtilization"] == 70, "HPA target changed")
        conditions = {c["type"]:c["status"] for c in hpa.get("status", {}).get("conditions", [])}
        require(conditions.get("AbleToScale") == "True" and conditions.get("ScalingActive") == "True", "HPA not able/active")
        require(bool(hpa.get("status", {}).get("currentMetrics")), "HPA current metrics absent")
        print(json.dumps({"HPA_conditions":hpa["status"]["conditions"], "steady_state":"NOT_VERIFIED"}))
    for metric in ("container_cpu_usage_seconds_total", "container_cpu_cfs_periods_total",
                   "container_cpu_cfs_throttled_periods_total", "container_cpu_cfs_throttled_seconds_total"):
        query = metric + '{namespace="aegis-step08",container="api"}'
        with urlopen(args.prom_url + "/api/v1/query?" + urlencode({"query":"time() - timestamp(" + query + ")"}), timeout=10) as response:
            data = json.load(response)
        assert data.get("status") == "success" and data["data"]["result"], "missing metric: " + metric
        assert all(0 <= float(x["value"][1]) <= 45 for x in data["data"]["result"]), "stale metric: " + metric
    with urlopen(args.prom_url + "/api/v1/query?" + urlencode({"query":"up"}), timeout=10) as response:
        targets = json.load(response)
    require(targets.get("status") == "success" and bool(targets["data"]["result"]), "no Prometheus targets")
    require(all(float(x["value"][1]) == 1 for x in targets["data"]["result"]), "one or more scrape targets are down")
    with urlopen(args.prom_url + "/api/v1/query?" + urlencode({"query":"time() - timestamp(up)"}), timeout=10) as response:
        ages = json.load(response)
    require(ages.get("status") == "success" and bool(ages["data"]["result"]), "target freshness missing")
    require(all(0 <= float(x["value"][1]) <= 45 for x in ages["data"]["result"]), "scrape target samples stale")
    placement = check_placement(relevant, role_by_node)
    print(json.dumps({"automatic_checks":"PASS", "placement":placement,
                      "manual_gates_not_passed_by_this_script":MANUAL_GATES,
                      "experiment_go":False}))


if __name__ == "__main__":
    main()
