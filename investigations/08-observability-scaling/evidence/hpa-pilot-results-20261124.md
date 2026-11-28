# HPA Pilot — 확장·축소 확인과 중단 기록

2026-11-24(KST), STEP08 / 8-D-1. CPU 본실험 원본을 보존하고 기존 b-off/b-on과 k6·수집기만 재사용했다. **1→2→1 확장·축소는 확인했지만, HPA ON 부하는 Probe 경고 중단 기준에 따라 조기에 멈췄다. HPA OFF/ON 성능 개선을 검증한 본실험은 아니다.**

## 고정 조건과 부하 탐색

이미지는 CPU 실험과 같은 digest, W=100000, CPU request=limit500m, memory request/limit128/256Mi다. API는 api 역할 Worker, k6는 support 역할 Worker에 배치했다. HPA OFF·Replica1에서 각60초(warmup0)로 낮은 부하부터 확인했다.

| 목표 RPS | 완료 요청 | 실제 RPS | p95(ms) | CPU(m, 내부 원시 표본) | 오류 / drop |
|---|---:|---:|---:|---:|---:|
| 15 | 901 | 15.0123 | 15.449 | 214.69 | 0 / 0 |
| 20 | 1201 | 19.9981 | 16.839 | 287.20 | 0 / 0 |
| 25 | 1501 | 25.0096 | 15.356 | 358.92 | 0 / 0 |
| 30 | 1801 | 30.0070 | 16.841 | 431.16 | 0 / 0 |

HPA OFF의 네 구간은 모든 요청이 HTTP200이었고, 추가 재시작·새 Probe 경고·노드 압박·발생기 포화 증거가 없었다. CPU 값은60초 전체의 외삽 평균이 아닌 해당 부하 내부 cAdvisor 표본 차이다. 이 짧은 구간들로1Pod의 최대 수용량을 확정하지 않았다.

HPA target70%는 request500m의350m다. 25RPS는 약359m로 목표와 가까워, 지시된 추가 탐색 범위에서30RPS를1회 더 확인했다. 약431m와 오류0을 확인한 뒤 같은30RPS를 HPA ON 후보로 삼았다. target이나 Probe를 바꾸지 않았다. [Kubernetes1.36 API 문서](https://v1-36.docs.kubernetes.io/docs/reference/kubernetes-api/autoscaling/horizontal-pod-autoscaler-v2/)는 전역 기본 tolerance10%를 설명하지만 이EKS의 전역 override는 조회하지 않았다. 목표를 조금 넘었다는 이유만으로 확장을 단정하지 않고 실제 HPA 상태를 확인했다. **HPA ON25RPS를 실행한 것은 아니다.**

## HPA ON에서 실제 관측한 것

기존 [HPA](../k8s/overlays/b-on/hpa.yaml)의 min1/max2·target70%·scaleDown stabilization300초를 유지했다. 부하가 없는 상태에서 Desired/Current1, API1 Ready, HPA AbleToScale/ScalingActive와 Metrics를 확인하고 시작했다. HPA 최초 생성 직후 준비 검사는 첫 계산 전이라 통과하지 못했고, 첫 ValidMetricFound 이후 같은 검사로 통과했다. 설정을 고쳐 통과시킨 것은 아니다.

| UTC | 관측 |
|---|---|
| 2026-11-23T22:58:37Z | HPA SuccessfulRescale:1→2, CPU target 초과. 상태에서84%/421m 관측 |
| 2026-11-23T22:58:37Z | 새 Pod의 초기 readiness connection refused, 집계 Event1개·count2 |
| 2026-11-23T22:58:42Z | 두 Pod Ready, 같은 api 역할 Worker에 배치 |
| 2026-11-23T22:59:12.791858419Z | 경고 확인 후 운영자 SIGINT로 k6 종료, exit105 |
| 2026-11-23T23:04:07Z | HPA SuccessfulRescale:2→1, metrics가 target 아래. 종료되는 새 Pod에 readiness connection reset Event1개·count1 |
| 2026-11-23T23:04:26Z | 조회에서 Desired/Current1, API1 Ready 확인 |

부하 종료 로그부터 축소 결정까지 294.208초(약4분54초)였다. 수동 scale이나 HPA target 변경 없이 축소됐다. 새 Pod의 기동 전·종료 중 readiness 경고를 기존 Pod의 장애와 구분한다. 기존 Pod의 Ready 상실 기록과 API 컨테이너 재시작은 없었지만, Probe 경고가 있었으므로 지시된 중단 기준대로 부하를 멈췄다.

k6 Job은 종료 후300초 보존 대기 뒤 exit105로 끝나 Failed/BackoffLimitExceeded가 됐다. 이는 운영자 중단의 결과이며 API OOM이나 Job 자동 재시도 성공으로 해석하지 않는다. 원본·실패 상태를 삭제하지 않았다.

## 중단된 요청 구간과 해석 한계

계획240초 중 실제 실행은 67.398초였다. 완료된2022건은 모두 HTTP200, 실제 약30.0009RPS, 오류·drop0이었다. `summary.measurement.normalizedRps=8.425`는 완료 건수를 계획240초로 나눈 값이므로 이번 중단 실행의 실제RPS로 사용하지 않았다. 실제 실행시간과 원본 timestamp를 함께 확인했다.

| 응답 완료 시각 기준 | 건수 | p50(ms) | p95(ms) | p99(ms) |
|---|---:|---:|---:|---:|
| 두 Pod Ready 이전 | 1098 | 14.986 | 20.710 | 131.983 |
| 두 Pod Ready 이후 | 924 | 15.048 | 15.483 | 20.527 |

이 표는 짧은 실행의 관측값이다. 시작·확장 전환이 포함되고 두 Pod Ready 이후는 약30초에 불과하다. 충분한 정상상태 유지, 동일 조건 교차 반복, HPA OFF/ON 성능 효과를 확정한 결과로 사용하지 않는다.

k6는46.018초의 내부 표본에서 약23.12m, 메모리 최대약16.27MiB, CFS throttled periods 증가0이었다. 첫 표본의 누적 throttled periods에는 이미1이 있어 전체67초가 무CFS였다고 주장하지 않는다. 입력률을 달성했고 지속적인 발생기 포화 증거는 없었다. 노드 Pressure0, 수집 구간의 Prometheus Target Up을 확인했다. 두 Pod Ready로 배치·기동은 확인했으나 이를 노드의 최대 수용량 검증으로 확대하지 않는다.

축소는 부하를 끈 뒤 관찰했다. 따라서 축소 중 연속 HTTP 요청의 무중단 여부나 정확한 서비스 복구시간은 검증하지 않았다. 또한30RPS는1Pod도 처리했으므로 처리량 개선이나1Pod 용량 초과·2Pod 수용량 이하 구간을 입증하지 않았다.

## 판정과 종료 상태

- HPA1→2확장·두 Pod Ready·부하 종료 후2→1축소: 실제 관측했다.
- 성능 Pilot: Probe 경고에 따라 중단한 불완전 실행이다. 이 시점에는 HPA OFF/ON 성능 비교용 본실험을 보류했다.
- W100000/30RPS는 확장 관찰 후보이며, 기동 전 readiness와 기존 Ready Pod의 Probe 실패를 구분하는 유효성 기준은 후속 검토 대상이다. 경고를 없애기 위한 코드·Probe 변경은 하지 않았다.

최종 확인 UTC2026-11-23T23:06:36.943161+00:00: API request=limit500m·Replica1 Ready·재시작0, HPA ON(min1/max2/target70%)·Desired/Current1이다. 부하0, Worker2대 Ready, healthz/readyz/info HTTP200이다. HPA를 임의 삭제하거나 수동 축소하지 않았다.

원본은 Git 제외 `evidence/private/hpa-off-*`, `evidence/private/hpa-on-*`에 분리 보존했다. k6 raw/summary, HPA·Pod·Event watch 원본, Prometheus 부하·회복 구간, 설정·최종 상태와 SHA256을 보관했다. CPU 본실험 원본·Terraform/IAM·AWS 인프라·STEP01~07·기존 ECR은 변경하지 않았다. 이 Pilot 단계에서는 OOM과 HPA OFF/ON 본실험을 실행하지 않았다.

이 종료 상태는 Pilot 당시의 기록이다. 후속 [HPA OFF/ON 본실험](hpa-results-20261124.md)과
[OOM 비교](oom-results-20261124.md), 최종 환경 정리 상태는 [README](../README.md)에 있다.
