#!/bin/bash
set -euo pipefail

CONTEXT="aegis-eks"
NS="aegis"
mkdir -p evidence/recovery

ALB_DNS=$(kubectl --context "$CONTEXT" -n "$NS" \
  get ingress aegis-api \
  -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')

TARGET=$(kubectl --context "$CONTEXT" -n "$NS" \
  get pods -l app=aegis-api \
  -o jsonpath='{.items[0].metadata.name}')

if [[ -z "$ALB_DNS" || -z "$TARGET" ]]; then
  echo "ALB DNS 또는 삭제 대상 Pod 확인 실패"
  exit 1
fi

echo "ALB: $ALB_DNS"
echo "삭제 대상: $TARGET"

# 실험 전 Pod 2개 Ready 확인
kubectl --context "$CONTEXT" -n "$NS" \
  wait --for=condition=Ready pod \
  -l app=aegis-api --timeout=30s

echo "=== HTTP 모니터링 시작 ==="

(
  for i in $(seq 1 90); do
    BODY=$(mktemp)
    STATUS=$(curl --noproxy '*' -s \
      --max-time 3 \
      -o "$BODY" \
      -w '%{http_code}' \
      "http://$ALB_DNS/api/info" || true)

    HOST=$(jq -r '.hostname // "-"' "$BODY" \
      2>/dev/null || echo "-")

    printf '%s request=%02d http=%s pod=%s\n' \
      "$(date '+%H:%M:%S')" "$i" "$STATUS" "$HOST"

    rm -f "$BODY"
    sleep 1
  done
) > evidence/recovery/http-during-failure.txt &

MONITOR_PID=$!

# 요청 기록 시작 후 장애 주입
sleep 5

echo "=== 장애 주입 ==="
date '+%Y-%m-%d %H:%M:%S %z' \
  | tee evidence/recovery/deletion-time.txt

kubectl --context "$CONTEXT" -n "$NS" \
  delete pod "$TARGET" --wait=false

echo "=== Deployment 복구 확인 ==="
kubectl --context "$CONTEXT" -n "$NS" \
  rollout status deployment/aegis-api \
  --timeout=180s

date '+%Y-%m-%d %H:%M:%S %z' \
  | tee evidence/recovery/rollout-time.txt

# HTTP 모니터링 종료까지 수집
wait "$MONITOR_PID"

kubectl --context "$CONTEXT" -n "$NS" \
  get pods -o wide \
  > evidence/recovery/after-pods.txt

kubectl --context "$CONTEXT" -n "$NS" \
  get deployment aegis-api \
  > evidence/recovery/after-deployment.txt

echo "=== HTTP 결과 집계 ==="
awk '{
  for(i=1;i<=NF;i++)
    if($i ~ /^http=/) count[$i]++
}
END {
  for(k in count) print k, count[k]
}' evidence/recovery/http-during-failure.txt

echo "=== 복구 후 Pod ==="
cat evidence/recovery/after-pods.txt
