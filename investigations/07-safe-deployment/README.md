# Healthy인데 업무 API는 503이었다

Green으로 트래픽을 전환한 뒤 업무 API에 장애를 주입했다. `/healthz`와 `/readyz`는 200이고 ALB Target도 Healthy였지만, `/api/info`는 503을 반환했다. Ingress의 가중치를 수동으로 Blue에 되돌리고 외부 업무 API의 정상 응답까지 확인한 실험이다.

06에서 쓴 Terraform 기반 EKS 구성을 다시 만들고, GitHub Actions에서 ECR에 게시한 이미지를 Blue/Green 두 슬롯에 배치했다. 두 슬롯은 같은 이미지 Digest를 사용했으며, 응답의 버전과 슬롯은 환경변수로 구분했다. 서로 다른 앱 이미지 버전 간 Rollback 실험은 아니다.

GitHub에서는 CI와 OIDC 기반 ECR 게시까지 실행했다. EKS 배포·트래픽 전환·복구는 로컬 Mac에서 수동으로 수행했다. 자동 CD나 자동 Rollback을 구현한 것은 아니다. 상세 흐름은 [CI-CD.md](CI-CD.md), 증빙 원본의 선별 기준은 [증빙 안내](evidence/README.md)를 참고한다.

## 헬스 체크와 업무 응답이 달랐다 — 2026-11-22

### 구성과 정상 전환

`GitHub Actions → GitHub OIDC/STS → ECR → Mac 수동 배포 → EKS Blue/Green → ALB Weighted Forward` 구조다. 기존 Terraform 코드로 VPC·Public/Private Subnet·NAT·EKS·2노드 Node Group을 준비했고, AWS Load Balancer Controller Helm Chart/App `3.6.3`을 사용했다. Controller와 애플리케이션은 각각 2개 Pod로 실행했다.

초기 Blue 100 / Green 0에서 두 슬롯의 Target Healthy 2/2와 개별 Pod 응답을 확인했다. Ingress의 Weighted Action 두 가중치만 바꿔 Green 100 / Blue 0으로 전환했다. Kubernetes의 의도한 설정과 AWS 콘솔의 실제 Listener Rule을 따로 확인했다. [Blue 외부 요청](evidence/02-blue-green/normal-blue-http.json)과 [Green 외부 요청](evidence/02-blue-green/normal-green-http.json)은 각 슬롯에서 업무 API 21회(최초 1회 + 추가 20회) 모두 200이었다. [재실험 전 Green 기준선](evidence/02-blue-green/retry-green-baseline.json)도 업무 API 11회 모두 Green 200이었다.

사용한 이미지는 두 슬롯 모두 `aegis-api@sha256:a864b600e8bda071860db5b019b591be7bf45071fcc57c59c32c07fa1ea66ff2`다. 응답의 `version`은 환경변수로 `17ea0b4-blue`, `17ea0b4-green`을 지정했다. 서로 다른 이미지 버전 배포로 해석하면 안 된다.

### 장애 주입과 복구

Green Deployment의 `INJECT_API_FAILURE`만 `0→1`로 바꿨다. 헬스 경로가 그대로 200이므로 Pod Ready와 ALB Healthy가 유지됐지만 업무 요청은 실패했다. 외부 503을 확인한 직후 Ingress의 가중치만 Blue로 되돌렸고, 정상 응답 확인 후 Green 환경변수를 원복했다. Blue Deployment와 이미지는 변경하지 않았다.

| 관측 지점 | 실제 결과 | 증빙 |
|---|---|---|
| 장애 Green의 개별 Pod 2개 | `/healthz` 200, `/readyz` 200, `/api/info` 503 | [Pod별 응답](evidence/03-failure-rollback/fault-individual-pods.json) |
| Kubernetes | 현재 ReplicaSet의 활성 Pod 2개 Ready, EndpointSlice IP 일치 | [활성 Pod 관측](evidence/03-failure-rollback/fault-active-observations.json) |
| ALB | 신규 Green IP 2개 Healthy, Green 100 / Blue 0 | [콘솔 관측 기록](evidence/03-failure-rollback/console-fault-observation.json) |
| 외부 ALB | Health/Readiness 200, 업무 API 11회 모두 503 | [외부 장애 응답](evidence/03-failure-rollback/fault-external.json) |
| 가중치 복귀 | Blue 100 / Green 0 실제 Rule 확인 | [콘솔 관측 기록](evidence/03-failure-rollback/console-rollback-observation.json) |
| 외부 복구 | 업무 API 최초 1회 + 추가 20회 모두 예상 Blue 버전·200, 연결 오류 없음 | [복구 응답](evidence/03-failure-rollback/rollback-external.json) |
| Green 원복 | `INJECT_API_FAILURE=0`, 개별 Pod 업무 API 200, 원래 Deployment spec과 일치 | [원복 Pod 응답](evidence/04-recovery/restored-individual-pods.json) |
| 최종 상태 | 양쪽 Target Healthy 2/2, Blue 100 / Green 0, 외부 Blue 200 | [Target 콘솔 기록](evidence/04-recovery/console-restored-health-observation.json), [선별 리소스](evidence/04-recovery/final-resources-selected.json), [최종 HTTP](evidence/04-recovery/final-http.json) |

### 첫 시도에서 발견한 관측 오류

첫 시도는 Green RollingUpdate 직후 `len(pods)==2` 검사에서 중단됐다. 라벨 조회에 종료 중인 이전 Pod도 포함됐기 때문이다. 이때는 외부 503과 Target Health를 함께 확인하기 전이므로 완료로 기록하지 않았다. 안전 복구 로직으로 Blue 100과 Green 정상 설정을 복원했다. [오류](evidence/03-failure-rollback/first-attempt-error.json), [첫 시도 타임라인](evidence/03-failure-rollback/first-attempt-timeline.json)을 남겼다.

재실험에서는 Deployment revision과 OwnerReference UID로 현재 ReplicaSet을 찾고, `deletionTimestamp`가 없는 활성 Pod만 셌다. 종료 중인 이전 Pod를 제외한 뒤 다음을 대조했다.

- 활성 Pod의 Ready와 전체 컨테이너 Ready, 이미지 Digest.
- Deployment의 updated/ready/available Replicas와 observedGeneration.
- 활성 Pod IP와 EndpointSlice IP.

안정화 대기는 최대 120초로 제한하고 명백한 실패는 즉시 중단하도록 했다. 이 관측 보완은 실행용 임시 스크립트에 적용했으며 저장소의 앱·Manifest를 변경하지 않았다.

### 관측 타임라인

아래 시각은 모두 2026-11-22이며 [UTC/KST 타임라인 원본 사본](evidence/03-failure-rollback/timeline.json)과 대조했다.

| 이벤트 | UTC | KST |
|---|---|---|
| Green 장애 Patch 수락 | 14:24:46.548 | 23:24:46.548 |
| Green rollout 완료 | 14:24:58.620 | 23:24:58.620 |
| 신규 Target Healthy 확인 게이트 통과 | 14:25:31.642 | 23:25:31.642 |
| 외부 업무 API 503 반복 확인 | 14:25:32.006 | 23:25:32.006 |
| Blue Rollback Patch 수락 | 14:25:32.919 | 23:25:32.919 |
| AWS Rule 반영 확인 게이트 통과 | 14:25:52.985 | 23:25:52.985 |
| 최초 외부 Blue 200 관측 | 14:25:53.016 | 23:25:53.016 |
| Green 원복 rollout 완료 | 14:26:06.716 | 23:26:06.716 |
| 최종 Blue 정상 확인 | 14:26:43.720 | 23:26:43.720 |

Patch 수락부터 최초 Blue 200 관측까지 약 **20.10초**였다. AWS 콘솔 확인 대기가 포함된 관측 간격이다. 연속 부하를 주며 측정한 순수 ALB 전파시간이나 정확한 장애 복구시간은 아니다. 콘솔 관련 게이트 시각도 실제 AWS 상태가 최초 변경된 시각을 의미하지 않는다.

### 판단과 검증 한계

Pod Ready, ALB Target Healthy, 실제 사용자 응답은 별개의 관측 대상이었다. `/healthz`만 확인하면 이번 업무 API 장애를 놓쳤다. 배포 후 업무 경로 Smoke Test가 필요하고, 복구도 설정 변경에서 끝내지 않고 실제 응답까지 확인해야 한다.

- 이번 실험은 **동일 이미지 Digest의 슬롯 전환**이다. 서로 다른 앱 이미지 버전 간 Rollback을 검증하지 않았다.
- ALB Target Health와 Rule은 관리자 AWS 콘솔에서 직접 확인했다. 제출 파일은 당시의 관측 기록이며 `describe-target-health` API 원본이나 화면 캡처가 아니다. CLI 조회 권한은 확대하지 않았다.
- 순차 요청의 관측 결과다. 지속 부하·동시 요청·장기 안정성·무중단 보장은 검증하지 않았다.
- CI/ECR 게시에는 독립 배포 승인자 보호가 없고, 수동 CD 및 수동 Rollback이다.
- [06 구축 기록](../06-aws-eks-infrastructure/README.md)의 인프라 코드를 재사용했다. 재구축으로 새 ALB가 생성됐으며 이전 실험의 ALB 실물을 재사용한 것은 아니다.
- [05 종료 처리 실험](../05-graceful-shutdown/README.md)의 SIGTERM·Drain 검증은 이번 앱에 적용하거나 반복하지 않았고, [02 OOM 실험](../02-linux-oom-cgroup/README.md)의 OOM도 장애 원인으로 사용하지 않았다.

2026-11-22 실험·증빙 정리 당시에는 EKS·노드·NAT·ALB가 실행 중이었다. 이 기록은 이후 삭제 완료를 의미하지 않으며, 현재 리소스 상태와 비용 정리 여부는 별도 확인이 필요하다. 당시 ECR 이미지와 GitHub 게시 인증은 보존 대상으로 두었다.

<details>
<summary>부록 — 초기 로컬 준비, 설계 판단, 재구축 조건</summary>

이 아래는 실험 전에 준비한 로컬 검증과 설계 판단, 재적용 시 필요한 조건이다. 2026-11-22 실제 AWS 검증 결과는 위 내용과 [CI-CD.md](CI-CD.md)에 정리했다.


## 파일 구성과 기존 환경 보존

| 경로 | 역할 |
|---|---|
| `app/server.py`, `app/Dockerfile` | 07 전용 표준 라이브러리 API와 Non-root 이미지 |
| `scripts/smoke.py` | GET 상태·JSON·버전·슬롯 검사. 실패 시 종료 코드 1 |
| `scripts/render.py` | 저장된 Terraform Output JSON과 이미지 Digest로 로컬 Manifest 생성 |
| `k8s/blue.yaml`, `k8s/green.yaml` | 슬롯별 Deployment와 ClusterIP Service를 담은 Kubernetes List |
| `k8s/ingress.yaml` | 기존 이름의 Ingress에 적용할 Weighted Forward Action 템플릿 |
| `tests/test_local.py` | 루프백 HTTP 테스트와 렌더링·선택자·가중치 검사 |

07 작업 당시 기존 01~06의 파일·증빙은 수정하지 않았다. 시작 시 06 `terraform/outputs.tf`가 미추적 사용자 파일로 존재했으며 그대로 보존했다(이후 저장소에 포함했다). Namespace 이름 `aegis`를 유지하며 별도 Namespace Manifest는 만들지 않았다. 실제 재구축 시에는 Namespace가 없어 `aegis`를 먼저 생성했다.

새 Pod의 공통 라벨은 `app: aegis-api-step07`이고 슬롯은 `slot: blue|green`이다. 06 Service의 기존 선택자 `app: aegis-api`가 새 Pod까지 선택하는 일을 막는다. Deployment 선택자, Pod 라벨, Service 선택자, Topology Spread 선택자를 슬롯별로 맞췄다. 기존 Deployment의 불변 selector는 변경하지 않는다.

## API와 로컬 Smoke Test

| 환경변수 | 기본값 | 의미 |
|---|---|---|
| `APP_VERSION` | `1.0.0` | 응답에 표시할 애플리케이션 버전 |
| `APP_SLOT` | `local` | 응답에 표시할 슬롯 |
| `INJECT_API_FAILURE` | `0` | 정확히 `1`일 때 `/api/info`만 HTTP 503 |
| `PORT` | `8080` | 수신 포트 |
| `BIND_ADDRESS` | `0.0.0.0` | 컨테이너 수신 주소. 로컬 실행은 `127.0.0.1` 권장 |

`GET /healthz`와 `GET /readyz`는 장애 주입 중에도 `200 {"status":"ok"}`를 반환한다. `/api/info`는 `service`, `version`, `slot`, `hostname`을 반환하고, 주입된 장애에서는 여기에 `error`를 추가한다. 다른 경로는 404다. 장애 제어용 공개 HTTP 엔드포인트는 없다. HEAD 지원은 추가하지 않았으므로 Smoke Test는 GET으로 실행한다.

```bash
cd ~/infrastructure-engineering-lab/investigations/07-safe-deployment
python3 -m unittest discover -s tests -v
```

테스트는 `127.0.0.1`의 임시 포트만 사용한다. 정상 응답에서는 Smoke Test 종료 코드 0, 업무 API 503·잘못된 버전·잘못된 슬롯에서는 비정상 종료를 확인한다. 장애 시에도 두 Health 경로가 200인지를 별도로 확인한다. 테스트가 끝나면 테스트 서버를 종료한다.

직접 확인하려면 첫 번째 터미널에서 실행한다.

```bash
BIND_ADDRESS=127.0.0.1 APP_VERSION=1.1.0 APP_SLOT=green \
  python3 app/server.py
```

다른 터미널에서 실행한다.

```bash
python3 scripts/smoke.py http://127.0.0.1:8080 \
  --expected-version 1.1.0 --expected-slot green
```

첫 번째 서버를 Ctrl-C로 종료한 뒤 `INJECT_API_FAILURE=1`을 추가해 다시 실행하면 같은 Smoke Test는 HTTP 503을 감지하고 종료 코드 1을 반환해야 한다. 장애를 감지한 Smoke Test의 실패는 이 시나리오에서 의도한 결과다.

## Manifest 렌더링과 오프라인 검증

추가 YAML 패키지 없이 파싱하도록 Manifest는 **YAML의 부분집합인 JSON 문법**으로 작성했다. `.yaml` 파일을 `json.loads`로 읽을 수 있으며, Kubernetes 리소스 형식으로 사용할 수 있다. 원본은 `${...}`가 남은 템플릿이므로 직접 적용하지 않는다.

입력값은 다음과 같다.

- `public_subnet_ids`가 포함된 **미리 저장한** Terraform Output JSON. 06 `terraform/outputs.tf`의 이름과 동일하다. 이 스크립트는 Terraform을 호출하지 않는다.
- Blue/Green의 전체 ECR 이미지 URI. 서울 리전 `aegis-api@sha256:<64자리 해시>`만 허용한다.
- 슬롯별 버전, 접근을 허용할 IPv4 `/32`, 새 출력 디렉터리.

저장된 Output JSON의 형태는 다음과 같다. 아래 값은 테스트용 가상 식별자이며 AWS에 존재하는 리소스를 의미하지 않는다.

```json
{
  "public_subnet_ids": {
    "value": ["subnet-00000000000000001", "subnet-00000000000000002"]
  }
}
```

아래 명령은 입력값을 미리 준비한 뒤 **로컬 렌더링만** 수행하는 예다. 이 단계에서 Output을 얻으려고 AWS나 Terraform을 실행하지 않는다.

```bash
python3 scripts/render.py \
  --outputs-json "$TF_OUTPUTS_JSON" \
  --blue-image "$BLUE_IMAGE" --green-image "$GREEN_IMAGE" \
  --blue-version "$BLUE_VERSION" --green-version "$GREEN_VERSION" \
  --allowed-cidr "$ALLOWED_CIDR" \
  --output-dir rendered/run-001
```

출력 경로가 존재하면 실패하므로 이전 결과를 덮어쓰지 않는다. `rendered/`와 `local-inputs/`는 Git 제외 대상이다. 두 슬롯의 장애 주입 기본값은 모두 `0`이며, Green 장애 실험용 렌더링은 별도 출력 경로에 `--green-failure 1`을 명시한다.

오프라인 테스트는 JSON/YAML 파싱, 슬롯 선택자, 이미지 Digest, Probe, Non-root 설정, 초기 가중치, Action 이름과 `use-annotation` 연결을 검사한다. 변환되지 않은 변수·가변 이미지 태그·전체 공개 CIDR·기존 출력 경로를 거부한다. **Kubernetes OpenAPI 스키마, Admission, Controller 실행, 이미지 존재 여부는 검증하지 않는다.** API Server 연결을 시도할 수 있는 kubectl 검증은 이 단계에서 실행하지 않는다.

## ALB 설계와 재적용 전 확인 사항

초기 가중치는 Blue 100 / Green 0이다. `alb.ingress.kubernetes.io/actions.aegis-api-weighted`의 `forwardConfig.targetGroups`에서 두 Service의 8080 포트를 참조한다. Ingress Backend는 Action 이름과 `port.name: use-annotation`을 사용한다. Target은 Pod IP이며 Health Check는 기존 `/healthz`를 유지하고 Target Group Stickiness는 비활성화했다.

문법 근거: [AWS Load Balancer Controller의 Custom Action 문서](https://kubernetes-sigs.github.io/aws-load-balancer-controller/latest/guide/ingress/annotations/), [ALB Forward Action 문서](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/rule-action-types.html).

**Ingress 이름은 06과 같은 `aegis-api`다.** 기존 클러스터라면 이 파일이 같은 이름의 Ingress Backend를 변경하므로 관리 이력과 Annotation을 먼저 확인해야 한다. 이번 재구축에서는 기존 Ingress가 없어 새로 생성했다. 이후 Blue/Green 전환과 복구에서는 이 Ingress와 ALB를 그대로 유지하고 가중치만 바꿨다. 기존 단일 Service로 되돌리는 복원과 두 슬롯 사이의 가중치 Rollback은 구분한다.

다음은 초기 설계에서 정리한 적용 전 확인 사항이다. 환경을 다시 구성하거나 기존 Ingress에 적용할 때도 실제 상태와 대조해야 한다.

1. Namespace, Controller/IRSA 상태, 이미지 Digest와 `linux/amd64` 빌드 여부, 실제 Public Subnet, 허용 CIDR.
2. 두 슬롯 Deployment/Service 준비, Green 업무 API Smoke Test. `rollout` 성공과 ALB Target Healthy는 따로 확인.
3. 이전 Ingress 사본·Backend·가중치와 슬롯별 이미지 Digest 보관. 출력 디렉터리 하나를 통째로 적용하지 않고 리소스별 적용 순서 검토.
4. 최초 Ingress 변경에서 Target Group 생성·등록·Healthy 전환 지연 측정. Blue 100이라는 설정만으로 최초 변경의 무중단을 보장하지 않음.
5. 두 슬롯 운영 이후에는 Ingress Action 가중치를 변경하고, 실패 시 이전 정상 슬롯 가중치와 업무 응답을 복원·검증. ALB 직접 수정과 Controller의 조정을 혼용하지 않음.

ALB는 가중치가 있는 그룹이 비정상이거나 비어 있어도 다른 그룹으로 자동 Failover하지 않는다. 이 실험에서는 Health Check가 정상이면서 API가 실패하므로 업무 Smoke Test가 필수다. 2026-11-22 실험에서 실제 가중치 전환과 외부 응답을 검증했다. 순수 전파 지연, 연결 배제 시간과 정확한 복구 시간은 측정하지 않았다.

기존 Probe·Requests/Limits·보안 설정은 재사용했다. SIGTERM 요청 완료 대기, preStop, 명시적 종료 유예, Pod Readiness Gate, HPA는 추가하지 않았다. 05 종료 실험이나 06 Pod 삭제 실험은 반복하지 않았다. 향후 활성 슬롯 종료를 검증하려면 종료 처리와 ALB 등록 해제 지연을 별도로 검토해야 한다.

## 코드에 근거한 재구축 순서

| 순서 | 관리 주체와 준비 항목 |
|---|---|
| 1 | 기존 Terraform State 보관·실행자 권한·서울 리전 Profile·`eks_public_access_cidrs` 준비. 새 Checkout만으로 기존 리소스를 관리할 수 없음 |
| 2 | 06 Terraform: VPC/Subnet/IGW/NAT/Route, EKS/Node Group, ECR, EKS OIDC, Controller IAM 역할·정책 생성 |
| 3 | Kubernetes/Helm: Namespace, Controller ServiceAccount의 IRSA Annotation, 버전과 Values를 고정한 Controller 설치. IAM 역할은 2번 Terraform에 있으므로 중복 생성하지 않음 |
| 4 | 이미지: 기존 Dockerfile로 `linux/amd64` Build, 로컬 컨테이너 검증, ECR Push, 슬롯별 Digest 확보 |
| 5 | Output JSON의 Public Subnet ID와 이미지·버전·허용 CIDR로 07 Manifest 렌더링 |
| 6 | 배포 권한과 네트워크 경로 확인 후 슬롯 Deployment/Service 준비, 업무 검증, 기존 Ingress 전환 검토 |

이 표는 절차 설명이며 AWS/Helm/Terraform 실행 스크립트가 아니다. 실제 배포에서 사용한 Chart 3.6.3 Values는 저장소 밖의 비공개 보관소에 남겼다. 실제 환경값의 주입과 수동 설치가 필요해 완전 자동 재구축은 아니다. Controller가 만드는 ALB/Target Group/Listener/관련 SG는 Terraform 직접 관리 리소스와 구분한다. 추후 삭제할 때도 Controller가 동작하는 동안 Ingress와 AWS 부속 리소스 정리를 확인해야 한다.

## 초기 보안 확인과 CI 설계 조건

초기 보안 점검에서는 Git 추적 파일명에서 `terraform.tfvars`, `*.tfvars.json`, `*.tfplan`, `*.tfstate*`, AWS 자격 증명 경로, `.env*`, 개인 키 파일을 확인했다. 새 07 파일에서는 자격 증명 형식과 로컬 절대경로 패턴도 검사했다. 민감 파일의 원문을 출력하거나 기존 파일을 임의 삭제하고 Git 기록을 변경하지는 않았다. 이 점검은 전체 Git 이력과 모든 종류의 비밀값 부재를 보장하는 검사가 아니다.

CI/ECR 게시 단계에서 Workflow·GitHub OIDC 게시 역할·실패 차단·동시 실행 제어를 구성했다. EKS는 기존 Mac에서 배포했으며 GitHub Runner의 EKS 접근은 구성하지 않았다. EKS OIDC는 Pod IRSA용이며 GitHub 인증을 대신하지 않는다. ECR은 Immutable 태그이므로 Commit 태그 재실행 처리도 필요하다.

2026-11-22까지 로컬 검증, CI/ECR 게시, 수동 배포·가중치 전환·업무 API 장애 복구를 확인했다. 독립 승인자 보호와 자동 CD는 구현하지 않았다. 증빙은 위 링크에 정리했으며, 이 문서는 AWS 유료 리소스 정리 완료를 증명하지 않는다.

## 초기 로컬 검증 기록

2026-11-22 초기 로컬 준비 단계에서 다음을 확인했다. 아래 항목은 이후 AWS 실험에 앞서 수행한 검증 기록이다.

- Python 소스 문법 검사 통과, `unittest` 9개 모두 통과.
- 정상 API는 Smoke Test 종료 코드 0. 업무 API 503, 버전 불일치, 슬롯 불일치는 비정상 종료.
- 실제 `server.py` 실행 진입점에서도 환경변수로 버전·슬롯·장애 주입이 반영됨. Health/Readiness 200, 업무 API 503 확인 후 테스트 프로세스 종료.
- Manifest 렌더링·구조 검사 통과. Weighted Action의 숫자 Service Port `8080`과 Service Port 설정 일치.
- 기존 06 Terraform의 `fmt -check -recursive` 통과. 초기화·Plan·Apply는 실행하지 않음.
- 01~06의 기존 파일 145개를 작업 전후 SHA-256으로 비교해 변경 없음 확인. `.terraform` 내부는 비교 대상에서 제외.
- 민감 파일명 검사에서 추적 중인 대상 없음. 새 07 파일의 자격 증명 형식·로컬 절대경로 패턴 검사에서 일치 없음. 전체 Git 이력과 모든 종류의 비밀값을 검사한 결과는 아님.
- 위 목록은 초기 로컬 준비 시점의 검증 범위다. 이후 Docker/CI/OIDC/ECR/Controller/ALB 실제 검증 결과는 문서 앞부분과 CI-CD 문서에 정리했다.

</details>
