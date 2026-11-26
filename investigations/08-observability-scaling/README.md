# HPA가 Pod를 1→2→1로 늘리고 줄였지만 응답은 빨라지지 않았다

<sub>EKS 1.36 · m7i.large Worker 2대 · CPU Limit 6회, HPA OFF/ON 각 3회, 독립 Job OOM 2회 · 2026-11-23–24 (KST)</sub>

Pod에 CPU·메모리 제한을 걸고 HPA를 켰을 때 요청 처리와 종료 상태가 어떻게 달라지는지 비교했습니다. CPU Limit(250m / 1000m), HPA OFF / ON, 독립 Job의 메모리 Limit(128Mi / 256Mi) 세 가지이고, 비교마다 요청률과 작업량을 맞춘 뒤 바꾼 조건만 달리했습니다.

HPA는 세 번 모두 Pod를 1→2→1로 늘리고 줄였고 CPU도 두 Pod로 나뉘었습니다. 그러나 응답 지연이나 처리량이 좋아졌다고는 말할 수 없었습니다. 세 쌍 모두 ON의 p95가 OFF보다 0.439–1.632ms 높았고, Pod 한 개도 30 RPS를 이미 처리하고 있었습니다. 측정 환경에도 문제가 있었는데, 아래 관측기 절에서 설명합니다.

## 핵심 결과

| 실험 | 관측한 결과 | 해석의 범위 |
| --- | --- | --- |
| CPU | 측정 16,204건 모두 HTTP 200. 1000m의 세 실행에서 내부 표본의 API CFS counter 증가는 0 | 지연 차이는 쌍별로 달랐고 처리량 개선은 입증하지 못함 |
| HPA | 측정 43,203건 모두 HTTP 200. 세 번 모두 1→2→1, 확장 후 Pod당 CPU 약 211–224m | 1개 Pod도 30 RPS를 처리함. 지연·처리량 개선 미입증, 관측 환경 한계를 명시한 조건부 PASS |
| OOM | 128Mi Job은 OOMKilled/exit 137, 256Mi는 Completed/exit 0. API 관찰 362건 모두 HTTP 200 | 독립 Job의 종료 결과를 비교함. 정확한 메모리 peak와 API 자체의 OOM 복구는 미검증 |

성공 건수는 정해진 관찰 구간의 결과입니다. 모든 부하에서의 무중단이나 복구 시간을 보장하는 수치로 쓰지 않았습니다.

HPA의 조건부 PASS는 확장·축소 동작과 HTTP 성공은 확인했지만, 사전에 정한 관측기 CFS 기준을 실행 중에 적용하지 못했다는 뜻입니다.

## 예상과 달랐던 부분

### CPU Limit: 차이가 일정하지 않았다

같은 15 RPS에서 250m과 1000m을 세 쌍 비교했습니다. 250m에서는 세 번 모두 CFS 제한이 관측됐지만, 그것이 p95 차이로 일정하게 이어지지는 않았습니다.

| 쌍 | 250m p95 (CFS 제한 기간 비율) | 1000m p95 (CFS 제한 기간 비율) | p95 차이 |
| --- | --- | --- | --- |
| 1 (T1·T2) | 39.028ms (1.392%) | 17.383ms (0%) | 21.644ms |
| 2 (T3·T4) | 31.934ms (51.358%) | 15.671ms (0%) | 16.263ms |
| 3 (T5·T6) | 15.874ms (50.098%) | 15.830ms (0%) | 0.045ms |

표의 p95는 반올림한 값이라 차이와 0.001ms 어긋날 수 있습니다.

- 세 번째 쌍은 사실상 같았습니다.
- 250m의 T4와 T5는 CFS 제한 기간 비율이 비슷했는데(51.358%, 50.098%) p95는 31.934ms와 15.874ms였습니다. 기간 비율 하나로 지연을 설명하거나 일정한 개선율을 만들 수는 없었고, 남은 변동의 원인은 이번 측정으로 특정하지 못했습니다.
- 20 RPS Pilot에서는 Probe 실패와 API 재시작이 생겼습니다. 과부하 사례로 따로 보존하고 6회 비교에서는 뺐습니다.
- T1·T2(11월 23일)와 T3–T6(11월 24일, 모두 KST) 사이에는 약 9.09시간 간격이 있어서, 중단 없는 연속 실험으로 쓰지 않습니다.

### HPA: 동작했지만 빨라지지는 않았다

부하는 30 RPS로 정했습니다. HPA OFF에서 15·20·25·30 RPS를 짧게 확인했는데, 25 RPS는 CPU가 약 359m로 HPA 목표(request 500m의 70%인 350m)와 가까웠습니다. 30 RPS는 약 431m였고 오류가 없어서 이 값을 ON 후보로 삼았습니다.

결과: 세 번 모두 1→2→1로 동작하고 CPU도 나뉘었지만 지연은 줄지 않았습니다.

- 짝별 ON−OFF p95는 +0.439 / +1.632 / +1.158ms였습니다. 이 차이의 원인을 HPA로 확정하지는 않습니다.
- 확장 후 CPU는 Pod당 약 211–224m였고, OFF의 Pod 한 개는 약 430m였습니다.
- Pod 한 개도 30 RPS를 처리하고 있어서 처리량 개선도 확인할 수 없었습니다.

![HPA OFF/ON의 p95 응답 시간과 Pod당 CPU](images/hpa-vs-latency.png)

예상과 달랐던 점: 확장하는 순간에는 일시적으로 지연이 늘었습니다.

| ON 실행 | 확장 결정 → 새 Pod Ready | 확장 전환 중 요청 / p95 | Ready 전 Readiness 경고 | 부하 종료 후 축소까지 |
| --- | ---: | --- | ---: | ---: |
| 2 | 1초 | 30건 / 82.679ms | 1건 | 314.6초 |
| 3 | 5초 | 150건 / 166.161ms | 2건 | 301.3초 |
| 6 | 1초 | 30건 / 172.429ms | 1건 | 314.5초 |

전환 구간의 표본이 작아서 일반적인 전환 지연으로 말하지는 않습니다. 축소 안정화 시간은 300초로 설정했습니다. 새 Pod가 처음 Ready가 되기 전의 경고와 이미 서비스 중이던 Pod의 문제는 구분해 적었고, 기존 Pod가 Ready를 잃거나 재시작한 기록은 없었습니다.

실행 과정에서 두 가지 일이 있었습니다.

- 첫 HPA Pilot은 새 Pod의 Readiness 경고를 중단 기준으로 보고 약 67초 만에 멈췄습니다. 1→2→1 동작은 확인했지만 성능 비교는 되지 않았습니다.
- 본실험의 첫 OFF 실행에서는 k6 컨테이너 안에서 raw 파일을 `grep`/`wc`로 읽어 추가 CPU 작업이 생겼고, 그 시점이 CFS counter 증가와 겹쳤습니다. 인과관계는 확정하지 못했습니다. 이후 실행과 조건이 달라졌으므로 이 실행은 참고용으로 분리하고 같은 조건의 OFF를 한 번 다시 측정했습니다. 첫 실행은 측정 7,202건이 모두 200이었고 p95는 15.728ms였습니다. 원본, 정상 결과, 제외 사유를 모두 남겼습니다.

### 관측기: 사전 기준을 실행 중에 적용하지 못했다

실험 전 계획의 중단·무효 기준에는 "생성기/관측기 지속 CFS"가 들어 있었습니다([DESIGN.md](DESIGN.md) 4절). 그런데 실행 중에는 이 항목을 판정하지 못했고, 최종 검토에서 Prometheus 데이터를 다시 보다가 node-exporter 컨테이너(CPU limit 50m)에 CFS 제한이 지속적으로 걸려 있었던 것을 발견했습니다.

| 실험 | 실행 수 | node-exporter CFS 기간 비율 (실행별 최댓값) |
| --- | ---: | --- |
| CPU | 6회 | 37.50–46.67% |
| HPA | 6회 | 41.94–47.06% |
| OOM | 2회 | 43.75%, 46.15% |

모두 2분 rate의 조회 표본 최댓값입니다. 이 값은 API 컨테이너의 CFS와는 별개이고, CPU 사용률이나 손실된 CPU 시간의 비율도 아닙니다. HPA 실행에서 node-exporter의 평균 CPU는 약 0.6–1m로 낮았지만, 제한이 실제로 걸렸다는 사실은 남깁니다.

그래서 HPA 판정을 조건부 PASS로 남겼습니다.

- 확인한 것: HPA의 1→2→1 동작, 측정 구간 HTTP 200, 두 Pod로의 CPU 분산. 이 근거는 node-exporter가 아니라 kubelet cAdvisor counter이고, Prometheus target 11개는 수집 구간 내내 Up이었습니다. 다만 Up은 수집 연결이 유지됐다는 뜻이지 관측 정확도를 보장하지는 않습니다.
- 통과하지 못한 것: 사전에 정한 관측기 CFS 기준을 실행 중에 적용하지 못했습니다. 그래서 지연의 미세한 차이는 제한적으로 해석합니다.

결과를 본 뒤 기준을 완화하지 않고, 기준과 실제 적용의 차이를 그대로 남겼습니다. 추가 실험이나 node-exporter 자원 변경은 하지 않았습니다.

### OOM: 종료 결과만 비교했다

128Mi Job은 OOMKilled/exit 137로, 256Mi Job은 Completed/exit 0으로 끝났습니다. exit 137만 보고 판단하지 않고 컨테이너의 `state.terminated.reason`이 OOMKilled인 것을 확인했습니다.

그러나 메모리 최고값은 잡지 못했습니다.

- 128Mi의 마지막 할당 로그 112Mi는 실제 컨테이너 peak가 아닙니다.
- cAdvisor working_set 표본은 128Mi에서 약 3.88MiB 하나뿐이었고, 256Mi는 시계열이 아예 수집되지 않았습니다. Job이 15초 scrape 간격보다 짧게 실행되어 할당 과정을 놓쳤을 수 있습니다.
- 그래서 정확한 peak는 미확인으로 남겼습니다. 시계열이 없는 것을 정상 사용의 증거로 보지 않았고, 종료 판정은 Kubernetes 종료 상태와 작업 로그로 했습니다.

같은 시간 API info 관찰 362건은 모두 200이었습니다. 다만 Job 실행 중의 요청은 128Mi에서 3건, 256Mi에서 14건뿐이라 API의 OOM 복구나 무중단의 근거로는 쓰지 않습니다.

## 남은 한계

- API 두 Pod가 같은 Worker에서 실행됐습니다. 노드 자동 확장이나 다중 노드 고가용성은 검증하지 않았습니다.
- HPA 축소는 부하를 끈 뒤 관찰했습니다. 축소 중의 무중단 처리는 검증하지 않았습니다. Pod별 요청 수도 계측하지 않아 두 Pod의 정확한 트래픽 비율은 모릅니다.
- OOM 비교는 각 조건 1회라 반복 재현성은 검증하지 않았고, API 자체의 OOM 복구도 검증하지 않았습니다.
- 실험 종료 당시 AWS 리소스를 보존했습니다. 실행 전 비용 추정은 [DESIGN.md](DESIGN.md)에 있지만 실제 청구액이 아닙니다.

## 증빙

- [CPU Limit 비교 — 6회 결과와 세션 분리·변동](evidence/cpu-limit-results-20261124.md)
- [HPA OFF/ON — 3쌍 결과, 전환 지연, 관측 품질과 제외 실행](evidence/hpa-results-20261124.md)
- [독립 Job OOM — 두 종료 결과와 메모리 관측 한계](evidence/oom-results-20261124.md)
- [HPA Pilot — 최초 중단과 1→2→1 확인 기록](evidence/hpa-pilot-results-20261124.md)
- [배포 검증 — 이미지·Pod·메트릭 연결 확인](evidence/deployment-verification-20261123.md)

원본 k6 raw/summary, Kubernetes 상태·Events·로그, Prometheus 쿼리와 SHA256 목록은 계정·네트워크·노드 식별자가 있어 Git 제외 경로에 따로 보관했습니다. 원본 범위와 공개 시 주의점은 [증빙 보관 기준](evidence/README.md)에 정리했습니다.

<details>
<summary>실험 환경과 비교 조건</summary>

서울 리전의 EKS 1.36과 m7i.large ON_DEMAND Worker 2대를 사용했습니다. 한 Worker에는 API를, 다른 Worker에는 k6와 Prometheus·Grafana·Metrics Server 등을 배치했습니다. HPA로 늘어난 API 두 Pod도 같은 API Worker에서 실행했습니다.

| 항목 | 실제 구성 |
| --- | --- |
| 네트워크 | VPC, public subnet 1개, private subnet 2개(2a/2c), NAT Gateway 1개 |
| API | Python 3.12 표준 라이브러리 HTTP 서버, 고정 횟수 정수 연산 |
| 관측 | kubelet cAdvisor의 CPU/CFS, Prometheus, kube-state-metrics, 별도 Metrics API |
| 통제 | 같은 측정용 이미지 digest, 같은 Node UID/providerID, API·발생기 역할별 배치 |
| 제외한 구성 | ALB·Ingress·별도 EC2 발생기·PVC 없음 |

| 비교 | 변경 변수 | 고정한 조건 |
| --- | --- | --- |
| CPU | limit 250m / 1000m | request 250m, replica 1, HPA OFF, W=100000, 15 RPS |
| HPA | OFF / ON | request=limit 500m, 시작 replica 1, W=100000, 30 RPS |
| OOM Job | memory limit 128Mi / 256Mi | request 64Mi, CPU 50m/100m, 192Mi 할당·페이지 쓰기, API info 관찰 1 RPS |

- API memory request/limit은 모든 비교에서 128/256Mi로 유지했습니다.
- HPA는 min 1/max 2, CPU 목표 70%(request 500m의 350m), 축소 안정화 300초였습니다.
- API 부하 비교는 HTTP/1.0 연결 종료와 k6 연결 재사용 금지를 같은 조건으로 적용했습니다.
- 구체적인 구간·표본·변경 변수는 각 결과 문서에 기록했습니다.

</details>

<details>
<summary>앞선 구축·배포 기록과의 관계, 종료 상태</summary>

- 06·07에서 쓴 EKS/API 구성을 참고하되, 이번 관측을 위한 별도 코드를 작성했습니다.
- 기존 `aegis-api` ECR은 Terraform data로 참조하고, 새 환경의 State는 `terraform/.state/terraform.tfstate`로 분리했습니다.
- 기존 State·ECR 이미지·GitHub OIDC/Publisher Role은 보존했습니다.
- 07의 Workflow가 이번 실험 이미지를 자동 빌드·배포한 구조는 아닙니다. 이 이미지는 별도로 게시해 digest로 고정했습니다.
- 실험 종료 후 API 1개 Ready, HPA OFF, Worker 2개 Ready, Prometheus 11/11 Up을 확인했습니다. 마지막 OOM 비교의 최종 상태 기록 시점에는 두 번째 k6 Job이 원본 수집 대기 구간이었고, k6 프로세스는 exit 0으로 끝났습니다.
- 실험 종료 당시 AWS 리소스는 보존했습니다. 예산 변수는 자동 과금 차단이나 삭제 타이머가 아닙니다.
- 구축 시의 [IAM 검토 기록](terraform/IAM-REVIEW.md)은 현재 실험 결과와 구분해 읽어야 합니다.

</details>

## 함께 보는 문서

- [DESIGN.md](DESIGN.md): 실험 전에 작성한 비교 프로토콜, 비용 추정, 삭제 순서, 노드 라벨 절차
- [REPRODUCE.md](REPRODUCE.md): 코드 구조, 로컬 검증, 실제 측정 절차, 재현의 한계
- [LOCAL-VALIDATION.md](LOCAL-VALIDATION.md): 로컬 검증 기록
