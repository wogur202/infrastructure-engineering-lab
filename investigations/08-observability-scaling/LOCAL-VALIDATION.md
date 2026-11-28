# 로컬 검증 기록 — AWS 구축 전

이 문서는 2026-11-23의 로컬 검증 단계(8-A-3 / 8-A-5)를 기록한다. 아래의 미검증 항목과
종료 상태는 AWS 구축 전 시점의 것이다. 이후 IAM 보완 정책을 연결하고 실제 EKS·CPU/HPA/OOM
실험을 진행했다. 최종 실험 결과와 환경 정리 상태는 [README](README.md), 권한 보완 과정은
[IAM 검토 이력](terraform/IAM-REVIEW.md)에 구분해 정리했다.

2026-11-23 실행. 실제 AWS 리소스 생성, Terraform plan/apply/destroy, ECR push,
Kubernetes 배포는 하지 않았다. 로컬 검증과 AWS 조회 권한의 제한을 구분한다.

| 검사 | 실제 결과 |
| --- | --- |
| 앱·설정 단위 테스트 | 8-A-3에서 12건 통과. 노드 안전 검사와 클라이언트 검증을 추가한 8-A-5에서는 24건 통과. |
| Python3.12 amd64 컨테이너 앱 테스트 | 8건 통과 |
| amd64 Docker build | 성공. Python base image digest 고정 |
| nonroot·read-only 컨테이너 HTTP smoke | 4개 endpoint200 및 응답 확인 |
| 안전 메모리 모드 | 2Mi 할당·페이지 접근 후 정상 종료. 실제 OOM 테스트 아님 |
| k6 inspect | 고정1.0.0 이미지에서 constant-arrival-rate 및 VU 상한 확인 |
| k6 로컬 연결 | Ready 확인 후 3초 연동 통과. HTTP 오류0, measure 하위 지표와 raw/summary 출력. 성능 비교 아님 |
| Terraform | 새08 root에서 backend=false init, fmt check, validate 통과. AWS API plan 없음 |
| Helm | stack93.8.0/metrics-server3.14.0, Kubernetes1.36 대상으로 template 성공 |
| 스키마 | Kubernetes v1.36.0 공식 OpenAPI와 렌더된 CRD schema 검증 통과. optional null/IntOrString 호환 처리 |
| 구성·문법 | Python AST, JSON/YAML, Bash, JS 문법 검사 통과 |
| 기존 환경 확인 | 06 outputs.tf·06 State의 SHA256 불변 확인 |
| 공개 파일 검색 | 알려진 AWS/GitHub key 패턴, 개인 로컬 절대경로, private key 본문 검색에서 발견 없음. 자동 검색이 모든 유출을 보장하지는 않음 |

도구: host Python3.15.2, container Python3.12.16, Terraform1.17.2,
Helm4.3.2, kubectl1.37.2/Kustomize5.8.1. 실제 EKS 대상은1.36이며
kubectl client minor 차이는1이다. 테스트 원본과 Secret을 포함한 렌더 결과는
Git 제외 `.local/`에 보관한다.

Helm stack 렌더는 CRD10, Service5, Deployment3, DaemonSet1, Prometheus1,
ServiceMonitor6, 인증서 hook Job2를 포함했다. PVC0/Ingress0/LoadBalancer0이다.
Prometheus Pod/StatefulSet은 Operator가 이후 생성하므로 렌더 성공으로 Pod 스케줄링을
검증했다고 할 수 없다. Grafana sidecar/test Pod는 끄고 reloader 자원은 Operator args에서
10m/50m·32Mi/64Mi가 전달되는 것을 확인했다. admission hook Job도 자원을 지정했지만
실제 실행은 하지 않았다. Metrics Server는 Deployment1/APIService1/Service1이다.

CFS usage/periods/throttled periods/throttled seconds 네 지표가 렌더된 metric relabel
규칙을 통과하는 것을 검사했다. Prometheus emptyDir2Gi 및 replica1을 확인했고,
Metrics Server APIService는 검증 우회 없이 CA bundle을 포함한다. 이 로컬 검증 시점에는 실제 EKS kubelet
인증서/SAN/메트릭 수집 성공을 확인하지 못했다.

처음 k6 inspect에서는 Docker 환경변수가 inspect에 전달되지 않아 입력 검증이 거부했다.
inspect의 명시적 --env로 고쳤다. 첫 연결 테스트에서는 서버 준비 전 첫 요청이
connection refused였고, Ready 확인 후 시작하도록 수정해 재검증했다. 실패 로그도
남겨두었다. 테스트 코드의 시작 순서를 고친 것이며 AWS 성능 실패를 감춘 것이 아니다.

8-A-4에서는 관리자 콘솔의 실제 정책10개를 읽었고 새 역할의 생성/삭제/PassRole이
Simulator에서 거부됐다. EC2/EBS/ASG/LT 조회도 실제 거부였다. Boundary 미설정·
Organizations 비멤버를 확인했다. 이 권한 조사 시점에는 보완 정책을 적용하지 않았으며,
이후 적용 결과는 [IAM 검토](terraform/IAM-REVIEW.md)에 있다.
AWS 실제 allocatable, 두 API Ready, Add-on/메트릭 연결, pilot W/RPS, CPU/HPA/OOM 결과와
청구액은 이 단계의 검증 범위에 포함되지 않았다. **로컬 구현 통과만으로 실제 AWS 구축이나 실험 성공을 판단하지 않았다.**

## 8-A-5 추가 검증 범위

Node Label 스크립트는 모의 Client로만 시험한다. UID/providerID 교체, 기존 role 변경,
Ready 조건 누락, 잘못된 계정/endpoint/TLS 우회, 실제 ASG membership 불일치, 한 노드
라벨 변경 후 두 번째 노드의 resourceVersion 충돌에서 중단하는지 검사한다.
두 노드를 한 번에 원자적으로 바꾸는 API는 아니므로 부분 실패 시 자동 rollback/재시도하지 않는다.
실제 노드 라벨 변경이나 클러스터 연결 성공으로 기록하지 않는다.

노드/API/생성기·관측기의 CPU/CFS, Node 메모리·allocatable, Pod requests/placement,
target up/freshness 쿼리를 추가했다. 실제 시계열 존재는 여전히 미검증이다.
Preflight 자동 검사 통과와 별도 실험 gate를 구분하며 자동 출력의 experiment_go는 false다.
비공개 IAM 부분 초안은 SAR 정적 검토만 했고 RunInstances/CreateAccessEntry/NAT 분리 등은
미해결로 남겼다. AWS에 실제 정책이 적용됐다고 기록하지 않는다.

## 8-A-5 최종 결과

2026-11-23 최종 `bash scripts/local-check.sh --docker`는 exit0이었다.

1. **IAM 부분 초안:** 비공개 `.local/iam-review/`에 정확한 새 역할2개, 역할별 policy 제한,
   EKS PassRole, 부족한 조회, Scope 태그 LT, 신규 클러스터 Add-on 범위를11개 Statement로
   정리했다. 26개 Action 항목을 SAR와 대조했으며 중복 Action이라도 기존 ARN에서
   새 ARN으로 범위가 달라지는 경우는 별도 허용이 필요함을 구별했다. ECR 삭제/
   GitHub IAM/OIDC 관리 권한은 추가하지 않았다.
2. **미해결 IAM:** RunInstances의 다중 리소스 문맥, 간접 CreateAccessEntry 조건,
   새 NAT EIP/ENI 분리 범위, Auto Scaling 공유 역할 확인은 미완료다. EKS/NodeGroup
   서비스 연결 역할2개는 GetRole로 존재를 확인했다. Access Analyzer ValidatePolicy는
   실제 AccessDenied였고 권한을 확대하지 않았다. AWS 유효 권한 검증 통과가 아니다.
3. **라벨 안전성:** 기본 inventory는 읽기 전용이다. 명시적 kubeconfig/context/account,
   AWS EKS endpoint, NodeGroup·ASG membership, Node UID/providerID·Ready/pressure를
   확인한다. 검토 후 쓰기 모드도 직전 재조회와 JSON Patch test를 사용하며 예상 외
   변경·부분 실패 시 중단한다. 실제 라벨링은 미실행이다.
4. **관측 증빙:** queries33개로 API·k6·관측기 CPU/CFS, Node memory/allocatable,
   Pod requests/placement와 target up/freshness를 함께 내보내도록 했다. 실제 시계열은
   아직 없다. 짧은 export 대기시간을 고려해 collect는 k6 raw/summary부터 저장한다.
5. **자동/수동 gate:** 자동 검사는 실제 계정/클러스터·노드·자원·Ready·digest·CFS·
   Metrics API·HPA API/조건·up/freshness다. 두 API 동시 Ready, counter 증가,
   실제 입력률/생성기 headroom, HPA 정상상태는 별도로 확인한다. workload가 없으면
   배치는 NOT_VERIFIED이며 자동 출력은 experiment_go=false다.
6. **공개 범위 검사:** private 정책/증빙/렌더·kubeconfig·State/Plan/backup·Secret 이름/token
   패턴을 확인했다. 공개 대상 파일에서 알려진 key 패턴, 개인 절대경로,
   실제 계정 ID를 검색해 발견하지 못했다.
   파일명·정규식만으로 모든 민감정보를 탐지한다고 보장하지 않는다.
7. **로컬 검사:** 단위24건 통과, Python3.12 amd64 앱8건은8-A-3에서 통과했다.
   8-A-5에서도 amd64 build/4endpoint smoke/safe2Mi/k6로컬3초 연동, Terraform fmt/
   backend=false init/validate, Helm2개 template, YAML/JSON·공식 OpenAPI/CRD,
   Python/Bash/JS 문법, runtime helper의 help 검사를 통과했다. 실제 AWS 연결 테스트나
   OOMKilled/성능 비교는 아니다.
8. **실환경 미검증 범위:** 이 로컬 검증 시점에는 08 State가 없었다. 실제 kubelet TLS,
   Add-on/Operator Pod 기동, allocatable, pilot·CPU/HPA/OOM 및 청구액은 미검증이었다.
9. **검증 한계:** 부분 IAM 초안의 정적 검토와 로컬 검사 통과만으로 전체 생성·삭제 권한이나
   AWS 구축 성공을 확인할 수는 없었다. 후속 권한 보완은 [IAM 검토 이력](terraform/IAM-REVIEW.md),
   실제 구축 이후 결과는 [README](README.md)에서 확인할 수 있다.
