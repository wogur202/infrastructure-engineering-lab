"""Draft node labeling procedure. Default: read-only inventory. Not run on AWS yet."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
from cluster import ROLE_LABEL, NODEGROUP, add_arguments, client_from_args, node_identity, node_ready, require

ROOT = Path(__file__).resolve().parents[1]


def assignments(nodes, api_name, support_name):
    require(api_name != support_name, "API and support must name different nodes")
    require({api_name, support_name} == {n["metadata"]["name"] for n in nodes}, "unexpected/missing node selection")
    result = {}
    for node in nodes:
        node_ready(node)
        identity = node_identity(node)
        role = "api" if identity["name"] == api_name else "support"
        current = node["metadata"].get("labels", {}).get(ROLE_LABEL)
        require(current in (None, role), "unexpected existing role; never overwrite automatically")
        result[identity["name"]] = {**identity, "role": role, "previousRole": current}
    for key in ("uid", "providerID"):
        require(len({x[key] for x in result.values()}) == 2, "duplicate physical node identity")
    return result


def label_patch(node, reviewed):
    current = node_identity(node)
    require(all(current[k] == reviewed[k] for k in ("name", "uid", "providerID")), "node was replaced; stop the experiment")
    node_ready(node)
    label = node["metadata"].get("labels", {}).get(ROLE_LABEL)
    require(label == reviewed["previousRole"], "node role changed since review")
    require(node["metadata"].get("labels", {}).get("eks.amazonaws.com/nodegroup") == NODEGROUP, "node left the expected group")
    if label == reviewed["role"]:
        return []
    return [{"op":"test", "path":"/metadata/uid", "value":current["uid"]},
            {"op":"test", "path":"/metadata/resourceVersion", "value":current["resourceVersion"]},
            {"op":"test", "path":"/spec/providerID", "value":current["providerID"]},
            {"op":"test", "path":"/metadata/labels", "value":node["metadata"].get("labels", {})},
            {"op":"add", "path":"/metadata/labels/aegis.lab~1role", "value":reviewed["role"]}]


def check_placement(pods, roles):
    counts = {"api":0, "support":0}
    for pod in pods:
        if pod["status"].get("phase") in ("Succeeded", "Failed"): continue
        app = pod["metadata"].get("labels", {}).get("app")
        expected = {"aegis-step08-api":"api", "step08-k6":"support"}.get(app)
        if not expected: continue
        require(pod["status"].get("phase") == "Running", "API/k6 pod is not running")
        require(roles.get(pod["spec"].get("nodeName")) == expected, "API/k6 placement is wrong")
        statuses = pod["status"].get("containerStatuses", [])
        require(bool(statuses) and all(c.get("ready") for c in statuses), "API/k6 is not Ready")
        counts[expected] += 1
    return {"counts":counts, "status":"VERIFIED" if all(counts.values()) else "NOT_VERIFIED_WORKLOAD_NOT_RUNNING"}


def apply_review(client, reviewed):
    # Revalidate the complete group, then re-read each node immediately before
    # an atomic JSON Patch with UID/resourceVersion tests. There is no retry.
    nodes = client.verified_nodes()
    require({n["metadata"]["name"] for n in nodes} == set(reviewed), "node membership changed")
    for name, expected in reviewed.items():
        node = client.kube("get", "node", name, "-o", "json")
        patch = label_patch(node, expected)
        if patch:
            client.kube("patch", "node", name, "--type=json", "-p", json.dumps(patch), "-o", "json")
    after = client.verified_nodes()
    roles = {n["metadata"]["name"]: n["metadata"].get("labels", {}).get(ROLE_LABEL) for n in after}
    require(sorted(roles.values()) == ["api", "support"], "post-label role counts are wrong")
    for node in after:
        identity = node_identity(node)
        require(all(identity[k] == reviewed[identity["name"]][k] for k in ("uid", "providerID")), "node changed during labeling")
        require(roles[identity["name"]] == reviewed[identity["name"]]["role"], "role assignment changed")
    return roles


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    add_arguments(parser)
    parser.add_argument("--api-node", required=True)
    parser.add_argument("--support-node", required=True)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--review", type=Path)
    parser.add_argument("--write-labels", action="store_true", help="mutates two nodes; requires separate execution approval")
    args = parser.parse_args()
    require(bool(args.review) == args.write_labels, "review and explicit write-labels must be used together")
    out = args.out.resolve()
    require(out.is_relative_to(ROOT / "evidence/private") or out.is_relative_to(ROOT / ".local"), "output must stay private")
    require(not out.exists() and out.parent.is_dir(), "use a new file inside an existing private directory")
    client = client_from_args(args)
    nodes = client.verified_nodes()
    selected = assignments(nodes, args.api_node, args.support_node)
    identity = {"cluster_arn": client.cluster["arn"], "endpoint": client.cluster["endpoint"], "context":args.context}
    result = {**identity, "nodes": selected, "utc":datetime.now(timezone.utc).isoformat(), "mode":"read-only inventory"}
    if args.write_labels:
        review = json.loads(args.review.read_text())
        require(all(review.get(k) == v for k,v in identity.items()), "review targets a different cluster/context")
        require({k:v["role"] for k,v in review["nodes"].items()} == {k:v["role"] for k,v in selected.items()}, "review selection changed")
        # Preserve the before snapshot even if the second node fails. No rollback.
        with out.open("x") as f: json.dump(result, f, indent=2)
        out.chmod(0o600)
        roles = apply_review(client, review["nodes"])
        namespaces = client.kube("get", "namespaces", "-o", "json")["items"]
        pods = client.kube("-n", "aegis-step08", "get", "pods", "-o", "json")["items"] if any(n["metadata"]["name"] == "aegis-step08" for n in namespaces) else []
        print(json.dumps({"node_labels":"VERIFIED", "placement":check_placement(pods, roles)}))
    else:
        with out.open("x") as f: json.dump(result, f, indent=2)
        out.chmod(0o600)
        print("Read-only inventory written. No labels changed. Review UID/providerID before any separately approved write.")


if __name__ == "__main__":
    main()
