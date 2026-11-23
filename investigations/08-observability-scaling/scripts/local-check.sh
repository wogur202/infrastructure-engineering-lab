#!/usr/bin/env bash
set -euo pipefail
umask 077
STEP08_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$STEP08_ROOT"
mkdir -p .local/charts
if [[ ! -x .local/venv/bin/python ]]; then python3 -m venv .local/venv; fi
.local/venv/bin/python -m pip install -r requirements-local.txt
export HELM_CACHE_HOME="$STEP08_ROOT/.local/helm/cache"
export HELM_CONFIG_HOME="$STEP08_ROOT/.local/helm/config"
export HELM_DATA_HOME="$STEP08_ROOT/.local/helm/data"
if [[ ! -d .local/charts/kube-prometheus-stack ]]; then
  helm pull kube-prometheus-stack --version 93.8.0 --repo https://prometheus-community.github.io/helm-charts --destination .local/charts --untar
fi
if [[ ! -d .local/charts/metrics-server ]]; then
  helm pull metrics-server --version 3.14.0 --repo https://kubernetes-sigs.github.io/metrics-server --destination .local/charts --untar
fi
.local/venv/bin/python -B - <<'PY'
from pathlib import Path
import yaml
for name, version in [('kube-prometheus-stack', '93.8.0'), ('metrics-server', '3.14.0')]:
    actual = yaml.safe_load((Path('.local/charts') / name / 'Chart.yaml').read_text())['version']
    assert actual == version, (name, actual)
PY
.local/venv/bin/python -B -m unittest discover -s tests -v
terraform -chdir=terraform fmt -check
terraform -chdir=terraform init -backend=false -input=false -lockfile=readonly
terraform -chdir=terraform validate -no-color
helm template step08 .local/charts/kube-prometheus-stack --namespace aegis-step08-monitoring --kube-version 1.36.0 --include-crds -f monitoring/values.yaml > .local/rendered-monitoring.yaml
helm template step08-metrics .local/charts/metrics-server --namespace kube-system --kube-version 1.36.0 -f monitoring/metrics-server-values.yaml > .local/rendered-metrics-server.yaml
chmod 700 .local
chmod 600 .local/rendered-monitoring.yaml .local/rendered-metrics-server.yaml
.local/venv/bin/python -B scripts/validate.py
if [[ ${1:-} == --docker ]]; then
  python3 -B scripts/docker-check.py
  python3 -B scripts/k6-check.py
fi
echo 'Local checks finished. No AWS plan/apply, Kubernetes API call, deployment, or push was run.'
