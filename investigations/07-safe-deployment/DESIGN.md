# 설계와 재구축 메모

[07 README](README.md)의 실험을 준비하면서 정리한 로컬 검증, 설계 판단, 재구축 조건입니다. 2026-11-22에 실제 AWS에서 확인한 결과는 README와 [CI-CD.md](CI-CD.md)에 있습니다.

## 파일 구성과 기존 환경 보존

| 경로 | 역할 |
|---|---|
| `app/server.py`, `app/Dockerfile` | 07 전용 표준 라이브러리 API와 Non-root 이미지 |
| `scripts/smoke.py` | GET 상태·JSON·버전·슬롯 검사. 실패 시 종료 코드 1 |
| `scripts/render.py` | 저장된 Terraform Output JSON과 이미지 Digest로 로컬 Manifest 생성 |
| `k8s/blue.yaml`, `k8s/green.yaml` | 슬롯별 Deployment와 ClusterIP Service를 담은 Kubernetes List |
| `k8s/ingress.yaml` | 기존 이름의 Ingress에 적용할 Weighted Forward Action 템플릿 |
| `tests/test_local.py` | 루프백 HTTP 테스트와 렌더링·선택자·가중치 검사 |

Namespace 이름 `aegis`를 유지하며 별도 Namespace Manifest는 만들지 않았다. 실제 재구축 시에는 Namespace가 없어 `aegis`를 먼저 생성했다.

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
