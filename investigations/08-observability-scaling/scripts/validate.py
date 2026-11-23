"""Offline shape + upstream OpenAPI checks; not server-side dry-run/admission."""
import collections
import json
from pathlib import Path
import re
import subprocess
import sys
import urllib.request
import jsonschema
from yamlutil import documents

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / ".local"


def omit_null_fields(value):
    # Kubernetes accepts null optional map fields from Helm. OpenAPI v2 omits
    # nullable semantics; validate their absent equivalent without altering YAML.
    if isinstance(value, dict):
        return {k: omit_null_fields(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [omit_null_fields(v) for v in value]
    return value


def int_or_string_schema(value):
    # OpenAPI v2 spells Kubernetes IntOrString as type:string + a custom format.
    # A generic JSON Schema engine needs the actual two accepted JSON types.
    if isinstance(value, dict):
        result = {k: int_or_string_schema(v) for k, v in value.items()}
        if result.get("format") == "int-or-string":
            result["type"] = ["integer", "string"]
        return result
    if isinstance(value, list):
        return [int_or_string_schema(v) for v in value]
    return value


def main():
    LOCAL.mkdir(exist_ok=True)
    specs = []
    for name in ("a-250", "a-1000", "b-off", "b-on"):
        text = subprocess.check_output(["kubectl", "kustomize", str(ROOT / "k8s/overlays" / name)], text=True)
        docs = documents(text)
        (LOCAL / (name + ".yaml")).write_text(text)
        dep = next(d for d in docs if d["kind"] == "Deployment")
        c = dep["spec"]["template"]["spec"]["containers"][0]
        assert c["resources"]["limits"]["cpu"] == {"a-250":"250m", "a-1000":"1000m", "b-off":"500m", "b-on":"500m"}[name]
        assert sum(d["kind"] == "HorizontalPodAutoscaler" for d in docs) == (name == "b-on")
        assert dep["spec"]["template"]["spec"]["nodeSelector"] == {"aegis.lab/role":"api"}
        specs.extend(docs)
    specs.extend(documents(subprocess.check_output(["kubectl", "kustomize", str(ROOT / "load")], text=True)))
    for path in ROOT.glob("k8s/oom-*.yaml"): specs.extend(documents(path.read_text()))
    mon = documents((LOCAL / "rendered-monitoring.yaml").read_text())
    metrics = documents((LOCAL / "rendered-metrics-server.yaml").read_text())
    specs.extend(mon + metrics)
    assert not any(d["kind"] == "PersistentVolumeClaim" for d in specs)
    assert not any(d["kind"] == "Ingress" for d in specs)
    for d in specs:
        if d["kind"] == "Service": assert d["spec"].get("type", "ClusterIP") == "ClusterIP"
    crds = {d["spec"]["names"]["kind"]: d for d in mon if d["kind"] == "CustomResourceDefinition"}
    prom = next(d for d in mon if d["kind"] == "Prometheus")
    assert prom["spec"]["storage"] == {"emptyDir":{"sizeLimit":"2Gi"}}
    assert prom["spec"]["replicas"] == 1
    cadvisor = [e for d in mon if d["kind"] == "ServiceMonitor" for e in d["spec"]["endpoints"] if e.get("path") == "/metrics/cadvisor"]
    assert len(cadvisor) == 1
    for name in ("container_cpu_usage_seconds_total", "container_cpu_cfs_periods_total",
                 "container_cpu_cfs_throttled_periods_total", "container_cpu_cfs_throttled_seconds_total"):
        for rule in cadvisor[0].get("metricRelabelings", []):
            if rule.get("sourceLabels") == ["__name__"]:
                match = bool(re.fullmatch(rule["regex"], name))
                assert (match if rule["action"] == "keep" else not match), name
    api = next(d for d in metrics if d["kind"] == "APIService")
    assert not api["spec"].get("insecureSkipTLSVerify", False) and api["spec"].get("caBundle")
    schemafile = LOCAL / "kubernetes-v1.36.0-openapi.json"
    if not schemafile.exists():
        with urllib.request.urlopen("https://raw.githubusercontent.com/kubernetes/kubernetes/v1.36.0/api/openapi-spec/swagger.json", timeout=60) as response:
            schemafile.write_bytes(response.read())
    definitions = int_or_string_schema(json.loads(schemafile.read_text())["definitions"])
    index = {}
    for key, definition in definitions.items():
        for gvk in definition.get("x-kubernetes-group-version-kind", []):
            api_version = (gvk["group"] + "/" if gvk["group"] else "") + gvk["version"]
            index[(api_version, gvk["kind"])] = key
    validated = collections.Counter()
    for doc in specs:
        kind = doc["kind"]
        key = index.get((doc["apiVersion"], kind))
        if key:
            schema = {"$ref":"#/definitions/" + key, "definitions": definitions}
        elif kind in crds:
            crd = crds[kind]
            version = doc["apiVersion"].split("/")[-1]
            schema = next(v["schema"]["openAPIV3Schema"] for v in crd["spec"]["versions"] if v["name"] == version)
        else:
            raise RuntimeError("schema unavailable: " + doc["apiVersion"] + " " + kind)
        try:
            jsonschema.Draft4Validator(schema).validate(omit_null_fields(doc))
        except jsonschema.ValidationError as exc:
            raise RuntimeError(f"{kind}/{doc['metadata']['name']}: {exc.message}") from None
        validated[kind] += 1
    inventory = {"objects": dict(validated), "monitoring_objects": dict(collections.Counter(d["kind"] for d in mon)),
        "metrics_server_objects": dict(collections.Counter(d["kind"] for d in metrics)),
        "limits": "Offline OpenAPI only; CEL/admission/runtime/controller reconciliation not verified"}
    (LOCAL / "validation.json").write_text(json.dumps(inventory, indent=2) + "\n")
    print(json.dumps(inventory, indent=2))


if __name__ == "__main__":
    main()
