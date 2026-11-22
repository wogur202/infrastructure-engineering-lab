#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONDONTWRITEBYTECODE=1
python3 -m compileall -q app scripts tests
python3 -m unittest discover -s tests -v
: "${CI_IMAGE:?Set a unique local CI_IMAGE tag}"
docker build --platform linux/amd64 --tag "$CI_IMAGE" app
python3 scripts/container_smoke.py --image "$CI_IMAGE"
