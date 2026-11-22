# STEP 07-B — GitHub CI·OIDC·ECR 게시와 수동 CD

[실제 Publish 성공 실행 45006939590](https://github.com/wogur202/infrastructure-engineering-lab/actions/runs/45006939590)에서 Commit `17ea0b4eeb2c2e4409636264c5307dd33f3edf6c`의 CI와 Publish가 모두 성공했다. Python 테스트 15개, amd64 Build, 컨테이너 Smoke Test를 통과한 뒤 GitHub OIDC로 STS 역할을 받아 ECR에 게시했고, 반환된 Digest를 다시 Pull해 검사했다. [Run 메타데이터](evidence/01-ci-ecr/run.json)와 [로그 발췌](evidence/01-ci-ecr/publish-excerpt.json)에 근거를 남겼다.

배포한 Digest는 `sha256:a864b600e8bda071860db5b019b591be7bf45071fcc57c59c32c07fa1ea66ff2`다. 게시 후 `ECR_PUBLISH_ENABLED=false`로 되돌렸다. CI/ECR 게시 이후 EKS 배포와 ALB 전환은 Mac에서 수동 실행했으며, 실제 결과는 [README](README.md)에 정리했다. 완전 자동 CD와 자동 Rollback은 구현하지 않았다.

## 1. CI 실행 흐름

저장소 루트 `.github/workflows/step07-ci.yaml`을 사용한다. Manifest와 같은 JSON 문법의 YAML이며 추가 Python YAML 패키지가 필요 없다. STEP 07 또는 Workflow 변경의 Pull Request, main Push, 수동 실행에서 CI가 동작하도록 작성했다. `pull_request_target`은 사용하지 않는다.

`scripts/ci.sh`의 순서는 다음과 같다.

1. Python 문법 검사.
2. 기존 9개를 포함한 전체 로컬 단위·통합 테스트. 정상 API, 업무 장애 감지, 버전·슬롯 불일치, 렌더링 검증 포함.
3. `linux/amd64` Docker Build.
4. 격리된 컨테이너 실행 후 GET Smoke Test. 호스트는 `127.0.0.1`의 임시 포트만 사용.
5. 테스트 컨테이너 제거. 기존 실행 중인 컨테이너와 이미지는 삭제하지 않음.

`set -euo pipefail`, Python의 비정상 종료 코드와 Job의 `needs`를 사용한다. `continue-on-error`로 실패를 무시하지 않는다. 문법·테스트·Build·Smoke 중 하나라도 실패하면 그 뒤 단계와 Publish가 차단된다. Workflow 단위 동시 실행은 같은 Ref에서 직렬화하며 실행 중인 Publish를 새 실행이 취소하지 않는다.

로컬에서는 다음과 같이 실행한다. Docker가 실행 중이어야 하고 Base Image를 내려받을 수 있어야 한다.

```bash
cd ~/infrastructure-engineering-lab
CI_IMAGE=aegis-step07-ci:local-review \
  bash investigations/07-safe-deployment/scripts/ci.sh
```

GitHub의 PR 검사는 AWS 인증 권한 없이 `contents: read`만 사용한다. 외부 Actions는 공식 Checkout, Setup Python, AWS Credentials 세 가지이며, 코드 작성 시 공식 저장소의 태그가 가리키는 Commit SHA를 확인해 고정했다. 이후 업데이트는 별도 검토한다.

## 2. ECR Publish — 실제 실행 완료

Publish Job은 아래 조건에서만 시작하도록 작성했다.

- `workflow_dispatch`에서 `publish_ecr=true`를 명시.
- 실행 Ref가 `main`이고 CI Job 성공.
- Repository Variables에 `ECR_PUBLISH_ENABLED=true`, `ECR_REGISTRY`, `AWS_PUBLISH_ROLE_ARN` 설정. 미설정이면 인증 전에 실패.
- Publish Job은 Environment를 참조하지 않는다. OIDC Subject가 Environment 형식으로 바뀌는 것을 피하고 IAM에서 `main` Ref를 정확히 제한한다.

현재 Private 저장소의 개인 실습에서는 Environment Required Reviewers에 의존하지 않는다. 게시자는 수동 실행과 기본 비활성화 설정으로 실행 의사를 표시하고, Workflow는 이벤트·입력·Branch를 검사한다. **독립적인 다른 사람의 승인 절차는 없다.** 이는 보호된 Environment 승인과 동등하지 않다. 저장소 공개 전환이나 요금제 변경은 하지 않았다. 실제 IAM 역할과 Repository Variables를 확인한 뒤 한 번 게시했고, 이후 기본 비활성 상태로 복원했다.

수동 실행 후의 코드 흐름은 로컬 이미지 재빌드·검증 → GitHub OIDC 임시 인증 → 기존 Commit 태그 조회 → ECR 로그인 → 필요 시 Push → 실제 Digest 조회 → 해당 Digest Pull·컨테이너 Smoke → Job Output과 Summary에 이미지 URI·버전 기록이다. Job 간에 로컬 Docker 이미지는 공유되지 않으므로 Publish Job 안에서 검사한 이미지를 Push한다.

`scripts/publish.py`는 기본적으로 Plan 모드다. `--execute`가 없으면 AWS/Docker 명령을 실행하지 않는다. 실행 모드에서는 다음을 처리한다.

- 태그는 전체 Commit SHA의 `git-<SHA>`이며 `latest`를 사용하지 않는다.
- 태그가 이미 있으면 원래 Digest를 재사용한다. Base Image 변경으로 재빌드 결과가 달라져도 기존 Immutable 태그를 덮어쓰지 않는다.
- `ImageNotFoundException`만 신규 Push 대상으로 취급한다. 접근 거부·저장소 누락 등은 실패 처리한다.
- 동시 Push 충돌은 태그가 실제 존재하는 경우에만 재사용한다.
- 신규/기존 이미지 모두 레지스트리의 실제 Digest를 Pull해 Smoke Test한 뒤 Output으로 전달한다. 실패하면 후속 인계도 실패한다. 이미 Push된 이미지를 자동 삭제하지는 않는다.
- Docker 로그인 정보는 임시 디렉터리를 사용해 사용자 Docker 설정을 덮어쓰지 않는다.

Commit 태그는 소스 식별자다. 현재 Base Image는 가변 태그이므로 동일 소스의 새 Build가 항상 같은 Digest가 되는 것은 아니다. 재빌드 아티팩트가 필요하면 새 Commit/버전 정책을 정해야 하며, 기존 Commit 태그를 삭제해 덮어쓰는 방식은 사용하지 않는다. ECR Scan 결과에 따른 취약점 차단은 아직 구현하지 않았다.

## 3. Green 준비 — Mac에서 수동 실행하는 코드

추천 경로는 **GitHub에서 CI/이미지 Push까지, 기존에 접근을 허용한 Mac에서 명시적 수동 CD**다. Workflow에는 EKS 배포 Job을 넣지 않았다. GitHub 호스팅 Runner가 제한된 EKS API에 접근한다고 가정하지 않는다.

`scripts/prepare_green.py`는 기본 Plan 모드이고 `--execute`가 없으면 kubectl/AWS 명령을 실행하지 않는다. 향후 승인된 배포에서 명시적 Context, ECR Digest URI, 전체 Commit SHA를 전달한다. 이 스크립트는 AWS CLI나 kubeconfig 갱신을 수행하지 않으므로, 허용된 네트워크와 적절한 기존 인증 설정이 먼저 필요하다.

실행 모드의 순서:

1. 기존 Weighted Ingress Backend가 예상한 Action이며, 설정 가중치가 정확히 Blue 100 / Green 0인지 검사.
2. 기존 Blue Deployment spec 보관, 기존 Green Deployment/Service 선택자 검사.
3. **Green Deployment만** 이미지·버전·슬롯·장애 비활성 값으로 Strategic Merge Patch.
4. Green rollout 완료 대기.
5. Green Service를 루프백 임시 포트로 Port-forward하고 업무 API Smoke Test.
6. Ingress의 Blue 100 / Green 0과 Blue spec 불변을 다시 확인. Port-forward 종료.

이 스크립트는 슬롯/Ingress를 처음 만들지 않는다. STEP 06의 단일 Backend 상태라면 실패하고, STEP 07-C의 최초 전환 검토가 먼저 필요하다. 7-C에서 초기 슬롯 배치와 Ingress 구성을 별도 수동 절차로 실행했다. 이 스크립트가 초기 배치를 수행한 것은 아니다. 자동 트래픽 전환·자동 Rollback도 구현하지 않았다.

여기서 확인하는 가중치는 Kubernetes의 **의도한 설정**이다. ALB에 실제 반영된 가중치·Target Healthy는 AWS 통합 검증이 필요하다. Service Port-forward는 선택된 Pod 하나의 요청만 확인하므로 모든 Green Pod나 ALB 경유 요청을 검증한 것으로 해석하면 안 된다. 다른 실행자가 동시에 Ingress를 변경하는 상황을 완전히 잠그는 구조도 아니므로 수동 배포는 직렬 실행해야 한다. 중간 실패 시 Green 변경이 남을 수 있으며, Blue를 보존하고 오류를 보고한다.

## 4. EKS 접근 방식 비교

| 방식 | 보안·비용·복잡도 | 포트폴리오에서의 의미 |
|---|---|---|
| A. GitHub CI/Push + Mac 수동 CD | EKS CIDR를 넓히지 않고 추가 AWS Runner 비용 없음. Mac 인증·실행자 관리는 필요 | 가장 단순한 현 단계 추천. 완전 자동 CD라고 표현하지 않음 |
| B. EKS 접근 가능한 전용 Runner | 고정 출구 IP 또는 VPC 내부 경로, Runner 패치·격리·비용 관리 필요. PR 코드를 특권 Runner에서 실행하지 않도록 분리 필요 | 자동 배포에는 적합하지만 이번 실험에 운영 요소가 추가됨 |
| C. Mac을 Self-hosted Runner로 등록 | 추가 AWS 인프라는 없어도 개인 Mac의 저장소·인증정보·환경이 Workflow 코드에 노출될 위험과 상시 실행 부담 | A보다 보안·운영 부담이 커 현 단계에서 권장하지 않음 |

실제 실험에서는 EKS/ALB를 실습자 공인 IPv4 `/32`로 제한했다. GitHub Runner를 위해 CIDR를 넓히거나 Self-hosted Runner를 등록하지 않았다. OIDC 인증 성공과 Kubernetes API 도달 가능성은 별개다.

## 5. IAM·OIDC·RBAC 요구사항

`iam/` 파일은 **미치환 템플릿**이며 바로 적용할 파일이 아니다. 실제 ECR 전용 게시 역할은 계정값을 주입한 정책으로 별도 생성해 사용했다. EKS 배포용 Access Entry와 여기의 제한 RBAC를 새로 구성한 것은 아니다.

| 파일 | 요구사항 |
|---|---|
| `ecr-push-policy.json` | 인증 Token만 Resource `*`. Push/Pull/Digest 조회는 서울 `aegis-api` 저장소 ARN으로 제한 |
| `github-trust-policy.json` | GitHub 전용 Provider, `aud=sts.amazonaws.com`, 확인한 저장소 OIDC 설정과 `main` Ref에서 도출한 예상 Subject에 정확히 일치. 실제 OIDC/STS 인증 성공 |
| `eks-describe-policy.json` | `aegis-eks`의 `eks:DescribeCluster`만. GitHub ECR 전용 역할에 추가할 필요 없음 |
| `green-rbac.yaml` | `aegis` Namespace의 Green Patch/Watch, Blue·Ingress 읽기, Service/Pod 조회·Port-forward. Ingress 변경·Blue Patch 권한 없음 |

AWS 장기 Access Key는 사용하지 않는다. `id-token: write`는 OIDC Token 발급 권한이며 AWS 권한은 IAM 역할 정책으로 따로 제한한다. EKS의 기존 OIDC/IRSA Provider를 GitHub용으로 재사용할 수는 없다.

**OIDC Subject는 저장소 이름만 보고 정하지 않는다.** 저장소의 읽기 전용 OIDC 설정 조회에서 `use_default=true`, `use_immutable_subject=true`, 아래 Prefix를 확인했다. 공식 문서의 Immutable Subject와 Branch 규칙에 따라, Environment를 제거한 Publish Job의 예상 Subject는 다음과 같다.

```text
repo:wogur202@162789945/infrastructure-engineering-lab@1452771896:ref:refs/heads/main
```

신뢰 정책은 `StringEquals`로 이 Subject와 `aud=sts.amazonaws.com`을 모두 검사하고 와일드카드를 사용하지 않는다. Provider ARN의 AWS 계정 ID만 `${AWS_ACCOUNT_ID}`로 남겼다. 이 신뢰 조건의 역할로 실제 OIDC/STS 인증이 성공했다. JWT 원문을 저장하거나 직접 해독해 Subject를 수집하지는 않았다. JWT 원문이나 Token은 로그·채팅·저장소에 남기지 않는다.

IAM의 Branch 신뢰 조건은 `workflow_dispatch` 여부나 특정 Workflow 파일까지 제한하는 조건은 아니다. 같은 저장소 `main`의 다른 OIDC 권한 Workflow도 역할을 요청할 수 있다는 한계가 있다. 수동 실행 조건은 현재 Workflow가 검사하며, `main`에 대한 코드 변경 권한도 신뢰 범위에 포함된다.

Mac CD의 별도 실행자 역할에는 EKS API 인증 모드의 Access Entry와 Kubernetes Group `aegis-green-deployers` 연결이 필요하다. 위 RoleBinding이 해당 그룹을 Namespace Role에 연결한다. 이는 IAM의 `DescribeCluster`와 별개다. 자동 인증을 위해 kubeconfig의 AWS CLI exec가 사용될 수 있으므로 실제 CD 실행은 AWS 인증을 포함한 클라우드 작업으로 취급한다. Role의 Pod Port-forward 권한은 Namespace 내 Pod에 적용되므로 범위와 실행자를 검토해야 한다.

참고한 공식 문서:

- [GitHub AWS OIDC 설정과 subject 조건](https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-aws)
- [GitHub Workflow 문법·권한·Environment](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax)
- [ECR Push 최소 권한](https://docs.aws.amazon.com/AmazonECR/latest/userguide/image-push-iam.html)
- [EKS Access Entry와 Kubernetes Group 연결](https://docs.aws.amazon.com/eks/latest/userguide/access-entries.html)

## 6. 완료 범위와 남은 검증

7-B CI/OIDC/ECR 게시와 7-C/7-D 수동 배포·트래픽 전환·장애 복구를 실제 검증했다. GitHub Workflow는 EKS에 연결하지 않는다. `prepare_green.py`를 실제 초기 배포나 장애 관측 도구로 사용했다고 주장하지 않으며, Mac의 별도 실행 절차로 검증했다.

- 실제 Run에서 CI/Publish 모두 성공, 테스트 15개 통과, `linux/amd64` Build 및 컨테이너 Smoke 성공, OIDC/STS 인증과 Digest 기반 Pull/Smoke 성공.
- 실제 이미지 게시 태그는 전체 Commit SHA의 `git-17ea0b4eeb2c2e4409636264c5307dd33f3edf6c`다. Immutable 태그의 재실행 충돌 경로는 로컬 테스트 범위이며 실제 중복 게시 실험은 추가하지 않았다.
- 업무 503은 두 헬스 경로의 정상 응답과 별도로 관측했다. 이 장애를 로컬 Smoke Test가 실패로 판정하는 동작은 테스트에 포함돼 있다. 실운영 자동 배포 차단·자동 복구까지 실증한 것은 아니다.
- ECR Scan 결과 기반 차단, 독립 승인자, GitHub Runner의 EKS 접근, 제한 RBAC로 실제 배포, 다른 이미지 버전 간 Rollback은 미검증이다.
- 이번 증빙 정리에서는 앱·Workflow·Manifest·IAM 템플릿을 수정하지 않았다. STEP 01~06 추적 파일과 기존 사용자 `outputs.tf`도 보존했다. Commit/Push는 별도 검토 대상이다.
