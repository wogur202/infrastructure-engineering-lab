# STEP 08 — CPU Limit, HPA, OOM 관측

## 실험을 진행한 이유

Pod에 CPU·메모리 제한을 걸었을 때 요청 처리와 종료 상태가 어떻게 달라지는지 확인했다.
같은 작업량에서 CPU Limit만 바꾸고, HPA를 켜고 끄고, 독립 Job의 메모리 Limit을 바꿔 실제 지표와 종료 상태를 비교했다.
예상과 다른 지연, 중단한 실행, 수집하지 못한 값도 결과와 함께 남겼다.

CPU 비교 6회, HPA OFF/ON 각 3회, 독립 Job OOM 비교 각 1회를 완료했다.
HPA의 확장·축소와 CPU 분산은 확인했지만 응답 지연이나 처리량 개선은 입증하지 못했다.
관측기에도 CFS 제한이 있었으므로, 실험 환경의 품질 기준을 모두 통과했다고 표현하지 않는다.

## AWS EKS 환경과 비교 조건

서울 리전의 EKS 1.36과 m7i.large ON_DEMAND Worker 2대를 사용했다.
한 Worker에는 API를, 다른 Worker에는 k6와 Prometheus·Grafana·Metrics Server 등을 배치했다.
HPA로 늘어난 API 두 Pod도 같은 API Worker에서 실행했다. 노드 자동 확장이나 다중 노드 고가용성을 검증한 구성은 아니다.

| 항목 | 실제 구성 |
| --- | --- |
| 네트워크 | VPC, public subnet 1개, private subnet 2개(2a/2c), NAT Gateway 1개 |
| API | Python 3.12 표준 라이브러리 HTTP 서버, 고정 횟수 정수 연산 |
| 관측 | kubelet cAdvisor의 CPU/CFS, Prometheus, kube-state-metrics, 별도 Metrics API |
| 통제 | 같은 STEP08 이미지 digest, 같은 Node UID/providerID, API·발생기 역할별 배치 |
| 제외한 구성 | ALB·Ingress·별도 EC2 발생기·PVC 없음 |

| 비교 | 변경 변수 | 고정한 조건 |
| --- | --- | --- |
| CPU | limit 250m / 1000m | request 250m, replica 1, HPA OFF, W=100000, 15 RPS |
| HPA | OFF / ON | request=limit 500m, 시작 replica 1, W=100000, 30 RPS |
| OOM Job | memory limit 128Mi / 256Mi | request 64Mi, CPU 50m/100m, 192Mi 할당·페이지 쓰기, API info 관찰 1 RPS |

API memory request/limit은 모든 비교에서 128/256Mi로 유지했다.
HPA는 min 1/max 2, CPU 목표 70%(request 500m의 350m), 축소 안정화 300초였다.
API 부하 비교는 HTTP/1.0 연결 종료와 k6 연결 재사용 금지를 같은 조건으로 적용했다.
구체적인 구간·표본·변경 변수는 각 결과 문서에 기록했다.

## 핵심 결과

| 실험 | 관측한 결과 | 해석의 범위 |
| --- | --- | --- |
| CPU | 측정 16,204건 모두 HTTP 200. 1000m의 세 실행에서 내부 표본의 API CFS counter 증가는 0 | 지연 차이는 쌍별로 달랐고 처리량 개선은 입증하지 못함 |
| HPA | 측정 43,203건 모두 HTTP 200. 세 번 모두 1→2→1, 확장 후 Pod당 CPU 약 211~224m | 1개 Pod도 30 RPS를 처리함. 지연·처리량 개선 미입증, 관측 환경 한계를 명시한 조건부 PASS |
| OOM | 128Mi Job은 OOMKilled/exit 137, 256Mi는 Completed/exit 0. API 관찰 362건 모두 HTTP 200 | 독립 Job의 종료 결과를 비교함. 정확한 메모리 peak와 API 자체의 OOM 복구는 미검증 |

성공 건수는 정해진 관찰 구간의 결과다. 모든 부하에서의 무중단이나 복구 시간을 보장하는 수치로 사용하지 않았다.

## 예상과 달랐던 현상과 판단

**CPU Limit을 높였다고 지연 차이가 일정하지는 않았다.**
세 쌍의 p95 차이는 약 21.644ms, 16.263ms, 0.045ms였다.
250m에서 CFS 기간 비율이 비슷했던 두 실행도 p95가 달랐다.
제한된 기간의 비율 하나로 지연을 설명하거나 일정한 성능 개선율을 만들지 않았다.
20 RPS Pilot에서는 Probe 실패와 API 재시작도 발생해, 정상 비교 조건과 구분해 보존했다.

**HPA가 동작한 것과 성능이 좋아진 것은 다른 결과였다.**
CPU는 두 Pod로 분산됐지만 세 쌍의 ON p95는 OFF보다 약 0.439~1.632ms 높았다.
확장 전환의 짧은 구간에는 일시적인 지연 증가도 있었다.
새 Pod의 최초 Ready 이전 경고와 이미 서비스를 제공하던 Pod의 장애를 구분했다.
초기 Pilot 중단, 최초 OFF의 k6 내부 진단 간섭과 대체 측정도 [HPA 결과](evidence/hpa-results-20261124.md)에 남겼다.

**관측 환경에도 제한이 있었다.**
후속 원본 재검토에서 CPU 6회 모두 node-exporter CFS가 확인됐다. 각 실행의 조회 표본 최대값은 약 37.50~46.67%였다.
HPA와 OOM에서도 같은 관측기 제한을 기록했다. 이는 API 컨테이너의 CFS와 별개의 값이며, CPU 사용률이나 손실 CPU 시간의 비율도 아니다.
API·k6 CPU 분석은 node-exporter가 아닌 kubelet cAdvisor counter를 사용했고, Prometheus target은 수집 구간에서 Up이었다.
다만 Up은 수집 연결이 유지됐다는 뜻이며 관측 정확도를 완전히 보장하지 않는다.
관측기 CFS를 실행 중 즉시 판정하지 못했으므로, 부록의 원래 중단 기준을 모두 충족했다고 할 수 없다.
기존 측정값은 보존하되 CPU·HPA·OOM에 공통으로 적용되는 환경 한계로 설명하고 미세한 지연 차이는 제한적으로 해석한다.

**짧게 실행된 Job의 메모리 최고값은 잡지 못했다.**
128Mi의 마지막 할당 로그 112Mi는 실제 컨테이너 peak가 아니다.
128Mi에서는 기동 초기 working_set 표본 1개만 있었고, 256Mi는 해당 Job의 시계열이 수집되지 않았다.
15초 scrape와 cAdvisor 갱신 간격의 영향을 고려해 정확한 peak는 미확인으로 남겼다.
종료 판정은 Kubernetes terminated reason과 작업 완료 로그를 함께 확인했다.

## 실제 결과와 증빙

- [CPU Limit 비교 — 6회 결과와 세션 분리·변동](evidence/cpu-limit-results-20261124.md)
- [HPA OFF/ON — 3쌍 결과, 전환 지연, 관측 품질과 제외 실행](evidence/hpa-results-20261124.md)
- [독립 Job OOM — 두 종료 결과와 메모리 관측 한계](evidence/oom-results-20261124.md)
- [HPA Pilot — 최초 중단과 1→2→1 확인 기록](evidence/hpa-pilot-results-20261124.md)
- [배포 검증 — 이미지·Pod·메트릭 연결 확인](evidence/deployment-verification-20261123.md)

원본 k6 raw/summary, Kubernetes 상태·Events·로그, Prometheus 쿼리와 SHA256 목록은 Git 제외 경로에 보존했다.
계정·네트워크·노드 식별자가 포함될 수 있어 공개 요약과 분리했다.
[증빙 보관 기준](evidence/README.md)에 원본 범위와 공개 시 주의점을 정리했다.

## 코드 구조와 재현 범위

| 경로 | 역할 |
| --- | --- |
| [app/](app/) | HTTP API, 유한 메모리 Job, Dockerfile |
| [k8s/](k8s/) | 공통 Deployment, CPU/HPA overlay, 독립 OOM Job |
| [load/](load/) | 고정 입력률 k6 시나리오, 원본·summary 출력 |
| [monitoring/](monitoring/) | 고정 Helm Values와 수집 쿼리. dashboard는 수동 import용 선택 자료 |
| [terraform/](terraform/) | 별도 EKS 실험 환경과 기존 ECR data 참조 |
| [scripts/](scripts/), [tests/](tests/) | 렌더·계정/노드 확인·사전 점검·수집·로컬 검증 |

Python3, Docker, Terraform 1.17+, Helm4, kubectl을 준비한 뒤 로컬 검증은 다음 진입점으로 실행할 수 있다.

```bash
cd "$(git rev-parse --show-toplevel)/investigations/08-observability-scaling"
bash scripts/local-check.sh --docker
```

이 검사는 앱·이미지·설정·스키마를 확인한다. backend 없는 Terraform init/validate도 포함하지만 AWS apply나 실험 부하는 실행하지 않는다.
실제 AWS 측정의 성공 여부는 위 결과 문서와 구분해야 한다. 당시 범위는 [로컬 검증 기록](LOCAL-VALIDATION.md)에 남겼다.

소스 Manifest의 image는 의도적으로 실행할 수 없는 placeholder다.
실제 실험에는 새 STEP08 ECR digest와 W/RPS/run-id를 [render.py](scripts/render.py)에 명시해 private 경로에 렌더했다.
계정·kubeconfig/context·노드 역할·Metrics API·Prometheus를 확인한 뒤 수동으로 배포와 부하 순서를 진행했다.
[preflight.py](scripts/preflight.py)의 자동 검사 통과가 전체 실험 GO를 뜻하지는 않는다.
HPA OFF 전환에는 기존 HPA 제거와 replica 1 Ready 확인이 별도로 필요하며, OOM은 관찰 부하를 먼저 시작해 전·후 60초를 확보했다.
[collect.py](scripts/collect.py)는 k6 종료 후 300초의 원본 수집 대기 구간 안에 raw/summary를 먼저 내보낸다.

현재 공개 절차는 로컬 검증과 실험 구성·수집 방법을 제공한다.
이미지 게시, 환경별 입력, 각 Trial의 시작·회복·수집 순서를 모두 자동화한 원클릭 재현을 제공하는 것은 아니다.
스키마 검증도 실제 admission·IAM 권한·런타임 성능 검증을 대신하지 않는다.

## STEP 06·07과의 관계

STEP 06·07의 EKS/API 패턴을 참고하되 STEP08 관측을 위한 별도 코드를 작성했다.
기존 `aegis-api` ECR은 Terraform data로 참조하고, 새 환경의 State는 `terraform/.state/terraform.tfstate`로 분리했다.
기존 State·ECR 이미지·GitHub OIDC/Publisher Role은 보존했다.
STEP07 Workflow가 STEP08을 자동 빌드·배포한 구조는 아니며, STEP08 이미지는 별도로 게시해 digest로 고정했다.

실험 종료 후 마지막 k6 Job까지 자연 완료됐고 API 1개 Ready, HPA OFF, Worker 2개 Ready, Prometheus 11/11 Up을 확인했다.
AWS 리소스는 보존 중이며 예산 변수는 자동 과금 차단이나 삭제 타이머가 아니다.
구축 시의 [IAM 검토 기록](terraform/IAM-REVIEW.md)과 아래 부록은 현재 실험 결과와 구분해 읽는다.

<details>
<summary>부록 — 기존 비교 기준과 구축·IAM·노드 검토 기록</summary>

아래는 실험 전에 작성한 비교 프로토콜과 구축 과정의 기록이다.
후보 부하·반복 횟수·과거 미완료 상태·당시 가격과 예산은 작성 시점의 판단이며, 현재 실험 결과나 실제 청구액이 아니다.
OOM 반복 후보는 실행 전 검토로 각 조건 1회로 확정했다.
원래 관측기 중단 기준은 그대로 보존하며, 실제 적용의 미흡함과 측정 한계는 본문에서 설명했다.

## 4. 비교 조건

| 실험 | 변경 변수 | 고정 조건 |
| --- | --- | --- |
| A | CPU Limit 250m / 1000m | request250m, replica1, HPA 없음, memory128/256Mi, W·입력률·배치 |
| B | HPA OFF / ON | request=limit500m, 시작1개, memory128/256Mi, W·입력률·배치 |
| C | 별도 Job memory limit128/256Mi | allocation192Mi, req50m/64Mi·limit100m, API1개·HPA 없음, info 1RPS |

A는 정상 부하와 압박 부하를 구분한다. 정상 부하는 저Limit에서도 처리 가능해야 하며,
압박 부하는 pilot에서 `C250 < 입력률 < C1000`인 구간을 확인한다. 각 수준에서 두
Limit에 **같은 입력률**을 준다. 해당 구간이 없으면 조건을 다시 검토하고 차이가 없는
결과도 보존한다. 후보 프로토콜은 warm-up60초, 측정180~240초, 회복60초,
Low/High → High/Low → Low/High의 3쌍이다.

B는 pilot에서 1Pod 수용량 초과·2Pod 수용량 이내의 입력률을 찾는다. HPA 목표70%는
request500m의 350m다. HPA는 min1/max2, downscale stabilization300초다.
Off/On → On/Off → Off/On의 3쌍으로 시작하며, 같은 replica1 Ready 상태로 초기화한다.
HPA 구간은 desired=current=Ready2와 유효 metrics가120초 유지된 구간까지 관측하되
측정상한8분을 넘으면 미수렴으로 종료한다. 부하 제거 후 실제1개 복귀를 최대6분 관찰한다.
단순히 3~4분 부하를 줬다고 HPA 안정화를 검증했다고 적지 않는다.

C는 낮음/높음 교차3쌍 후보다. info 1RPS를 전60초·Job최대60초·후60초 관찰한다.
실제 실행할 때는 load Job을 먼저 시작하고 60초 뒤 OOM Job을 시작해야 한다.
두 manifest를 동시에 적용하면 전60초 관찰 조건을 만족하지 않는다.
128Mi OOMKilled/256Mi exit0은 가설이다. terminated reason·exitCode·Event·로그·할당량을
함께 확인한다. exit137만으로 OOMKilled라고 단정하지 않고 MemoryError·Eviction·Probe 종료와
구별한다. Never Job은 restartcount0일 수 있다. 별도 Job의 API 영향 관측을 API OOM 복구
실험으로 확대하지 않는다.

k6는 1iteration=1HTTP 요청의 constant-arrival-rate를 쓴다. p95/p99, 오류율,
실제 http_reqs/s, dropped_iterations, CPU/CFS, Pod 수와 배치를 함께 본다.
k6 Job은 warm-up60초+측정240초를 기본 후보로 두고 phase 태그를 남긴다.
전체 summary와 measure 하위 지표를 구분한다. HPA 정상상태 구간은 실제 replica·metrics
이력을 기준으로 다시 잘라 분석한다. warm-up 종료가 HPA 안정화를 뜻하지는 않는다.
이때 k6 filtered counter의 기본 rate 분모도 전체 실행시간이므로 측정 RPS로 바로 쓰지 않는다.
별도 normalizedRps는 측정 구간 시작 요청의 완료 건수/계획 구간 초다. 중단된 실행과
응답 drain 구간은 원본 timestamp로 다시 분석한다.
실패한 요청을 빼고 좋아진 p95만 보고하지 않는다. 생성기 자체 포화와 서버 지연에 따른
VU 소진을 구별한다. 생성기/관측기 지속 CFS, scrape 누락, node pressure, Pending,
예상 밖 restart, 비용·시간 초과가 있으면 중단·무효 사유를 기록한다.

## 7. Terraform 소유권·비용·삭제

새 root의 backend 경로는 `terraform/.state/terraform.tfstate`다. 기존06 State를 복사하거나
다른 root에서 공유하지 않는다. 기존 ECR은 data 참조뿐이며 GitHub IAM/OIDC도 관리하지 않는다.
계정 ID는 필수 입력·provider allowed_account_ids로 확인하고 리전은 서울로 고정했다.
VPC-CNI/CoreDNS/kube-proxy는1.36 호환 목록에서 조회한 managed Add-on 버전을 고정했다.
노드 CNI 권한은 실험실 단순화를 위해 노드 역할에 남겨 두었다.
8-A-4·5 당시 기존 정책10개로는 새 역할 관리와 EC2/EBS/ASG/LT 조회가 거부됐다.
8-A-6에서 보완안을 검토하고 승인 후 `AegisStep08Supplement` 하나를 `terraform-lab`에
연결했다. 기존 정책10개와 Boundary 미설정 상태를 유지했고, 누락됐던 조회 API는 실제로
성공했다. 대표 Simulator 평가도 통과했지만 실제 생성·삭제 성공을 검증한 것은 아니다.
콘솔 요약에는 일부 작업·리소스·조건이 권한을 제공하지 않는다는 안내가 남아 있다.
정책 원문은 검증본과 일치하며, 이 안내를 없애려고 권한을 확대하지 않았다.
검토 이력과 한계는 [IAM-REVIEW.md](terraform/IAM-REVIEW.md)에 정리했다. 정책 JSON과
계정별 원본은 비공개로 보관한다.

2026-11-23 확인한 서울 Linux OnDemand 단가: m7i.large$0.12390/대·h,
Flex$0.11771/대·h, EKSStandard$0.10/h, NAT$0.059/h+$0.059/GB,
publicIPv4$0.005/h, gp3$0.0912/GB-month. 40GB/730h로 환산하면 고정분은
약$0.41680/h(4h$1.667,6h$2.501,8h$3.334). 6h+정리1h+NAT5GB는 약$3.213이다.
세금·환율·cross-AZ/인터넷 전송·ECR 저장·선택한 로그·삭제 지연은 별도다.
공식 근거: [EC2 서울 Price List](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonEC2/current/ap-northeast-2/index.csv),
[VPC 서울 Price List](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonVPC/current/ap-northeast-2/index.csv),
[EKS 요금](https://aws.amazon.com/eks/pricing/).

증분 예산 목표$5, 첫 유료 리소스 생성 후6h에 새 실험 중단·정리1h 확보를 후보로 둔다.
예상 지출80% 또는 초과 전망이면 내보내고 정리한다. 변수 validation은 자동 과금 차단이나
자동 삭제 기능이 아니다. 실제 리소스가 없어질 때까지 과금될 수 있다.

삭제 순서는 부하 중단→증빙 내보내기·해시 검증→App/HPA/Job→Helm 관측 도구→외부
LB/PVC 유무 확인→새08 root의 최신 삭제 plan 검토→승인된 삭제→AWS 실제 조회다.
EKS/NodeGroup/ASG/EC2/EBS/NAT/EIP/ENI/SG/Subnet/RT/VPC/신규IAM까지 확인한다.
NAT/EIP association이 오래된 값인지, 삭제 권한이 새 대상에도 적용되는지 확인한다.
State가 비었다는 이유만으로 정리 완료라고 적지 않는다. 기존 ECR digest와 GitHub
OIDC/Publisher Role 보존도 마지막에 확인한다. 이번 단계에서는 삭제 명령을 실행하지 않았다.

## 8. 구축 전 검증 범위 (8-A-5 기록)

로컬 앱·HTTP·amd64 이미지, 단위 테스트, Terraform fmt/validate, Helm template,
YAML/JSON 및 Kubernetes OpenAPI/CRD 구조를 검증한다. 상세 로컬 결과는 이후 검증 보고에
실제 통과/실패로 적는다. 현재 AWS 생성·삭제 권한 전체, 네트워크 연결, addon/runtime
호환성, 실제 allocatable, 메트릭 수집, pilot W/RPS, HPA 안정시간, OOMKilled, 비용 청구는
미검증이다. 현재 권한이 부족하다는 사실과 아직 실행하지 않은 AWS 성공 여부를 구별한다.
기존 STEP07 workflow는 경로 필터가07 전용이므로08 CI가 이미 동작한다고
설명하지 않는다. Commit/Push 및 실제 배포는 하지 않았다.

## 9. 노드 라벨 절차와 자동/수동 gate (구축 전 초안 기록)

`scripts/node_labels.py`의 기본 모드는 읽기 전용 inventory다. kubeconfig·context·
예상 AWS 계정을 명시해야 하며 kubeconfig는600 권한으로 비공개 경로에 보관한다.
현재 STEP08 클러스터는 없으므로 아래 절차는 실행하지 않았다.

별도 구축·검토 후 기본 inventory는 다음과 같이 수집한다. 노드 이름은 실제 조회 후
서로 다른 두 이름을 선택해야 하며 임의로 만들어 넣지 않는다.

```bash
python3 -B scripts/node_labels.py \
  --kubeconfig .local/kubeconfig --context aegis-step08 \
  --expected-account "${STEP08_ACCOUNT_ID:?}" \
  --api-node "${STEP08_API_NODE:?}" --support-node "${STEP08_SUPPORT_NODE:?}" \
  --out .local/nodes-review-unique.json
```

스크립트는 AWS 계정·실제 EKS ARN/endpoint와 kubeconfig의 endpoint/TLS를 대조한다.
NodeGroup ACTIVE·min/desired/max2, ASG의 Healthy/InService 인스턴스2개,
Kubernetes 노드2개의 NodeGroup 라벨·UID/providerID·Ready·pressure·cordon 여부를 확인한다.
두 Node가 ASG의 실제 인스턴스와 일치하지 않으면 중단한다. 현재 ASG 조회 권한이
거부되므로 권한 보완 전에는 이 inventory도 실제 환경에서 통과할 수 없다.

검토된 inventory에만 `--review`와 명시적인 `--write-labels`를 함께 사용하도록 구현했다.
이 모드는 두 노드를 변경하므로 별도 승인된 실행 범위에서만 사용한다. 이번에는 모의
Client 테스트만 했고 실제 label/patch 명령은 실행하지 않았다. 쓰기 직전에 각 Node를
다시 읽고 UID/providerID·기존 라벨을 대조한 뒤 JSON Patch의 UID/resourceVersion/
providerID/기존 labels test로 경쟁 변경을 거부한다. 두 Node 전체가 하나의 트랜잭션은 아니다.
첫 Node 성공 후 두 번째가 실패하면 즉시 중단하고 자동 rollback·재시도하지 않는다.
노드 교체 후 role을 자동으로 재할당하지 않으며 새 검토와 실험 무효 기록이 필요하다.

후검증은 api1/support1, 같은 실제 노드인지, 실행 중인 API/k6의 분리와 Ready를 확인한다.
아직 workload가 없으면 placement는 NOT_VERIFIED로 남긴다. 실험 전체 PASS로 표시하지 않는다.

`preflight.py`와 `collect.py`도 같은 `--kubeconfig`, `--context`, `--expected-account`를
필수로 받는다. preflight는 추가로 `--expect-hpa off|on`을 요구한다. 자동 검사 범위는
실제2Node/ASG membership/Ready/pressure/role, requests 대 allocatable, digest/Pod Ready,
CFS4지표 신선도45초, Metrics API의 API Pod CPU/시각, HPA API와 예상 HPA 유무,
활성 HPA의 AbleToScale/ScalingActive/currentMetrics, Prom up/freshness다.
ScalingLimited는 저부하에서 min1 때문에 True일 수 있어 이유를 따로 검토한다.

두 API 동시 Ready, 알려진 CPU 작업의 counter 증가, 생성기 headroom·실제 입력률 달성,
HPA 정상상태와120초 유지 판정은 별도 실험 gate다. 자동 출력은 이들을 통과시키지 않으며
`experiment_go: false`를 유지한다. 배치 검사는 실제 k6/API가 실행 중일 때만 VERIFIED다.
정상상태 성능·HPA·OOM 검증은 그대로 미완료다.

수집기는 종료 후300초 안에 읽어야 하는 k6 raw/summary를 먼저 저장한 뒤 Pod/Event/log와
Prometheus 범위 쿼리를 처리한다. 수집이 실패하면 기존 파일을 지우지 않고 새 attempt로 보존한다.
Git ignore 패턴은 kubeconfig/state/plan/Secret 이름/token과 private 디렉터리를 보완했지만
어떤 이름의 Secret도 모두 검출하는 기능은 아니다. 공개 후보는 별도로 검사해야 한다.

참고: [HPA](https://kubernetes.io/docs/concepts/workloads/autoscaling/horizontal-pod-autoscale/),
[Python GIL](https://docs.python.org/3.12/library/threading.html),
[Metrics Server](https://github.com/kubernetes-sigs/metrics-server),
[k6 constant arrival rate](https://grafana.com/docs/k6/latest/using-k6/scenarios/executors/constant-arrival-rate/),
[관측 차트 고정 Values](https://github.com/prometheus-community/helm-charts/blob/4db9f9b11ed00838051066cff4e06c3c500e1560/charts/kube-prometheus-stack/values.yaml).

</details>
