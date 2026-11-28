# 실험 전 설계 기록

<sub>08번 실험을 시작하기 전에 작성한 비교 프로토콜과 구축·IAM·노드 검토 기록입니다. 결과는 [README](README.md)에 있습니다.</sub>

아래는 실험 전에 작성한 비교 프로토콜과 구축 과정의 기록이다. 절 번호는 당시 문서의 번호 체계를 유지했다.
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
구축 전 검토 당시 기존 정책10개로는 새 역할 관리와 EC2/EBS/ASG/LT 조회가 거부됐다.
이후 보완안을 검토하고 승인 후 `AegisStep08Supplement` 하나를 `terraform-lab`에
연결했다. 기존 정책10개와 Boundary 미설정 상태를 유지했고, 누락됐던 조회 API는 실제로
성공했다. 대표 Simulator 평가도 통과했지만, 이 권한 검토 시점에 실제 생성·삭제 성공까지 검증한 것은 아니다.
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
OIDC/Publisher Role 보존도 마지막에 확인한다. 이 구축 전 기록 단계에서는 삭제 명령을 실행하지 않았다.

## 8. 구축 전 검증 범위

로컬 앱·HTTP·amd64 이미지, 단위 테스트, Terraform fmt/validate, Helm template,
YAML/JSON 및 Kubernetes OpenAPI/CRD 구조를 검증한다. 상세 로컬 결과는 이후 검증 보고에
실제 통과/실패로 적는 계획이었다. 당시 AWS 생성·삭제 권한 전체, 네트워크 연결, addon/runtime
호환성, 실제 allocatable, 메트릭 수집, pilot W/RPS, HPA 안정시간, OOMKilled, 비용 청구는
미검증이었다. 당시 권한이 부족했던 사실과 아직 실행하지 않은 AWS 성공 여부를 구별했다.
기존 07 workflow는 경로 필터가07 전용이므로08 CI가 이미 동작한다고
설명하지 않는다. 이 구축 전 검토 단계에서는 실제 배포를 하지 않았다.

## 9. 노드 라벨 절차와 자동/수동 gate (구축 전 초안 기록)

`scripts/node_labels.py`의 기본 모드는 읽기 전용 inventory다. kubeconfig·context·
예상 AWS 계정을 명시해야 하며 kubeconfig는600 권한으로 비공개 경로에 보관한다.
이 초안을 작성한 구축 전 시점에는 이번 실험의 클러스터가 없어 아래 절차를 실행하지 않았다.

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
두 Node가 ASG의 실제 인스턴스와 일치하지 않으면 중단한다. 초안 작성 당시에는 ASG 조회 권한이
거부돼 권한 보완 전까지 이 inventory도 실제 환경에서 통과할 수 없는 상태였다.

검토된 inventory에만 `--review`와 명시적인 `--write-labels`를 함께 사용하도록 구현했다.
이 모드는 두 노드를 변경하므로 별도 승인된 실행 범위에서만 사용한다. 초안 작성 당시에는 모의
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
이 구축 전 초안 시점에는 정상상태 성능·HPA·OOM 검증이 미완료였다.

수집기는 종료 후300초 안에 읽어야 하는 k6 raw/summary를 먼저 저장한 뒤 Pod/Event/log와
Prometheus 범위 쿼리를 처리한다. 수집이 실패하면 기존 파일을 지우지 않고 새 attempt로 보존한다.
Git ignore 패턴은 kubeconfig/state/plan/Secret 이름/token과 private 디렉터리를 보완했지만
어떤 이름의 Secret도 모두 검출하는 기능은 아니다. 공개 후보는 별도로 검사해야 한다.

참고: [HPA](https://kubernetes.io/docs/concepts/workloads/autoscaling/horizontal-pod-autoscale/),
[Python GIL](https://docs.python.org/3.12/library/threading.html),
[Metrics Server](https://github.com/kubernetes-sigs/metrics-server),
[k6 constant arrival rate](https://grafana.com/docs/k6/latest/using-k6/scenarios/executors/constant-arrival-rate/),
[관측 차트 고정 Values](https://github.com/prometheus-community/helm-charts/blob/4db9f9b11ed00838051066cff4e06c3c500e1560/charts/kube-prometheus-stack/values.yaml).
