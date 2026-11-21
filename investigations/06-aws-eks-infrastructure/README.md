# STEP 06. AWS 네트워크 구축과 EKS 배포 준비

로컬 Kubernetes 실습에서 AWS EKS로 넘어가기 위해 VPC, 서브넷, 라우팅과 IAM 역할을 Terraform으로 구성했다. 이 문서는 **EKS 클러스터는 생성됐지만 Node Group 생성이 권한 오류로 중단된 중간 기록**이다. 워커 노드는 아직 생성하지 못했다.

## 1. 현재 진행 상태

2026-11-21 실습 기준이다.

| 구간 | 결과 | 확인 범위 |
| --- | --- | --- |
| 네트워크 | 15개 리소스 배포 완료 | AWS API로 NAT, 서브넷, 라우팅, EIP 연결 확인 |
| IAM | 역할 2개와 정책 연결 4개 배포 완료 | 역할 및 연결 정책을 AWS API로 조회 |
| 기존 구성 | 네트워크·IAM 21개 유지 | EKS 코드 추가 전 Plan에서 `No changes`, 종료 코드 0 |
| EKS Cluster | 생성 완료 | AWS API에서 `ACTIVE`, Kubernetes `1.36` 확인 |
| Node Group | 생성 실패 | `iam:PassRole` 거부, AWS Node Group 목록은 비어 있음 |
| 애플리케이션 | 미배포 | kubectl 연결, 실제 패킷 통신, API 응답은 미검증 |

현재 State에는 기존 21개와 클러스터 1개가 등록돼 있다. Plan 성공은 실제 생성 권한, EC2 용량 확보나 Kubernetes 워커의 정상 동작까지 보장하지 않는다.

## 2. 네트워크 설계

서울 리전(`ap-northeast-2`)에서 두 AZ에 Public/Private 서브넷을 나눴다. 워커 노드는 Private 서브넷에 두고, 외부 서비스 접근은 NAT Gateway를 사용하도록 계획했다.

| 항목 | 구성 |
| --- | --- |
| VPC | `10.20.0.0/16`, DNS support/hostnames 활성화 |
| Public a / c | `10.20.1.0/24`, `10.20.2.0/24` |
| Private a / c | `10.20.11.0/24`, `10.20.12.0/24` |
| Public 기본 경로 | `0.0.0.0/0` → Internet Gateway |
| Private 기본 경로 | `0.0.0.0/0` → NAT Gateway |
| NAT Gateway | Public a에 1개, Elastic IP 1개 연결 |

두 AZ를 선택해 워커 노드 배치 범위를 확보했다. NAT는 실습 비용을 줄이기 위해 하나만 구성했다. 따라서 NAT가 있는 AZ에 장애가 나면 다른 AZ의 Private 서브넷도 외부 통신에 영향을 받을 수 있다. AZ를 가로지르는 NAT 통신에는 추가 데이터 전송 비용도 고려해야 한다. 이 구성을 고가용성 네트워크로 검증한 것은 아니다.

네트워크 15개는 VPC 1개, 서브넷 4개, IGW 1개, 라우팅 테이블 2개, 서브넷 연결 4개, EIP 1개, NAT Gateway 1개, Private 기본 경로 1개다. VPC 생성 시 AWS가 함께 만드는 기본 리소스까지 센 숫자는 아니다.

## 3. 실제 구축과 검증

AWS API 조회에서 다음을 확인했다.

- NAT Gateway 상태가 `available`이었다.
- Public/Private 서브넷이 각각 2개였고, `ap-northeast-2a`와 `ap-northeast-2c`에 구성됐다.
- Public 서브넷은 자동 공인 IP 할당이 켜져 있고, Private 서브넷은 꺼져 있었다.
- Public/Private 기본 경로가 각각 IGW/NAT를 가리켰고 `active`였다.
- 기존 EIP가 NAT에 연결됐다.

보존한 원본 증빙은 [NAT 조회 결과](evidence/network/nat-status.json)와 [네트워크 배포 후 No changes 결과](evidence/network/terraform-no-drift.txt)다. 두 파일은 네트워크 배포 당시의 기록이며 이후 IAM/EKS 코드까지 포함한 최신 실행 로그는 아니다. 원본에는 당시 리소스 ID가 남아 있지만 인증정보는 포함하지 않는다.

IAM 역할은 다음과 같이 구성하고 실제 연결 상태까지 조회했다.

| 역할 | 신뢰하는 서비스 | 연결 정책 |
| --- | --- | --- |
| `aegis-eks-cluster-role` | `eks.amazonaws.com` | `AmazonEKSClusterPolicy` |
| `aegis-eks-node-role` | `ec2.amazonaws.com` | `AmazonEKSWorkerNodePolicy`, `AmazonEC2ContainerRegistryPullOnly`, `AmazonEKS_CNI_Policy` |

CNI 정책은 초기 실습 구성을 단순하게 유지하려고 Node Role에 연결했다. 워크로드별 최소 권한을 분리하는 구성은 아직 적용하지 않았다.

## 4. EIP 조회 권한 오류와 부분 배포 복구

첫 네트워크 배포는 EIP를 할당한 뒤 `ec2:DescribeAddressesAttribute` 권한 오류로 중단됐다. `DescribeAddresses`와 별개의 API 권한이었다. VPC와 서브넷 등은 이미 생성됐기 때문에 전체 배포가 실패했다고 보고 처음부터 다시 실행하면 안 되는 상황이었다.

복구는 다음 순서로 진행했다.

1. 실패 메시지에서 부족한 API를 확인하고 기존 네트워크 정책에 해당 조회 권한을 추가했다.
2. `terraform state list`와 AWS EIP 조회를 대조했다. EIP가 State에 등록돼 있고 AWS에도 존재했다. 속성 조회 API는 종료 코드 0으로 바뀌었지만 `Addresses: []`를 반환해, 속성 데이터가 확인됐다고 기록하지 않았다.
3. 새 Plan에서 EIP가 `tainted`로 표시되고 `3 to add, 0 to change, 1 to destroy`가 나왔다. 이 계획은 적용하지 않았다.
4. State를 로컬 파일로 백업한 뒤 `terraform untaint aws_eip.nat`으로 교체 표시를 해제했다. 실제 EIP를 삭제하거나 State 내용을 직접 편집하지 않았다.
5. 새 복구 Plan에서 NAT Gateway와 Private 경로만 생성하는 `2 to add, 0 to change, 0 to destroy`를 확인했다.
6. 복구 계획을 적용해 `2 added, 0 changed, 0 destroyed`를 확인했다. 이후 NAT `available`, EIP 연결 및 `No changes`를 검증했다.

위 내용은 이번 작업 세션의 실행 결과를 정리한 것이다. 실패 당시 전체 터미널 로그를 별도의 원본 파일로 보관한 것은 아니므로, 재구성한 로그를 원본 증빙처럼 만들지는 않았다. State 백업과 이전 계획 파일은 로컬에 보존하고 Git에서 제외했다.

이번 실습에서 배운 점은 생성 실패 후에는 **오류 메시지, 실제 AWS 리소스, Terraform State와 새 Plan을 함께 확인해야 한다**는 것이다. `untaint`는 실패 이력만 보고 항상 적용하는 해결책이 아니다. 이번에는 실제 EIP 존재와 조회 권한 복구를 먼저 확인한 뒤 사용했다.

## 5. IAM 권한 구성에서 겪은 추가 이슈

Terraform 실행 사용자의 네트워크 권한과 EKS 관리 권한을 분리했다. 역할 관리 권한은 지정한 Cluster/Node Role 2개로 제한하고, 연결할 관리형 정책 4개와 `iam:PassRole`의 대상 서비스를 조건으로 지정했다. EKS 서비스 연결 역할 생성 권한도 별도로 정의했다.

역할 관리 정책을 사용자 인라인 정책으로 추가하려다 기존 인라인 정책과 합산한 2,048자 제한에 걸렸다. JSON 문법 오류는 아니었다. 기존 정책을 삭제하거나 관리자 권한으로 바꾸는 대신, 같은 JSON을 고객 관리형 `AegisEKSIAMRoleAccess` 정책으로 생성해 연결했다.

정책 시뮬레이터에서는 지정한 역할 ARN을 사용해 `CreateRole`, `AttachRolePolicy`, `DeleteRole`의 허용을 확인했다. 정책 연결 검사에는 `iam:PolicyARN` 조건도 입력했다. 이후 실제 역할 2개와 정책 연결 4개를 배포하고 AWS API로 조회했다. `PassRole`과 서비스 연결 역할을 이용한 실제 EKS 생성은 아직 검증하지 않았다.

현재 EC2/EKS 관리 정책에는 서울 리전 조건이 있지만 일부 작업의 리소스 범위가 `*`다. 모든 권한이 리소스 단위 최소 권한으로 완성됐다고 설명하지 않는다. 사용자 정책은 콘솔에서 준비했으며 [iam.tf](terraform/iam.tf)가 관리하는 대상은 서비스 역할과 정책 연결이다.

## 6. EKS 배포 계획

| 항목 | 코드에 정의한 값 |
| --- | --- |
| 클러스터 | `aegis-eks`, Kubernetes `1.36` |
| 노드 그룹 | `aegis-workers`, Managed Node Group |
| 노드 사양 | `t3.medium`, On-Demand, 디스크 20 GiB |
| 노드 수 | desired 2, min 1, max 2 |
| 서브넷 | 기존 Private a/c |
| API endpoint | Public + Private, Public 접근은 로컬에서 확인한 IPv4 `/32` |
| 인증 | `API` 모드, 생성자 초기 관리자 권한 활성화 |
| 지원 정책 | `STANDARD` |

[eks.tf](terraform/eks.tf), [nodegroup.tf](terraform/nodegroup.tf), [variables.tf](terraform/variables.tf)에 정의했다. 별도의 `aws_eks_access_entry` 리소스를 작성한 것은 아니며, 클러스터 생성 시 부여되는 생성자 관리자 접근을 사용할 계획이다. 실제 kubectl 인증·권한은 배포 후 확인해야 한다.

버전 조회가 처음 비어 있었던 원인은 JMESPath 필터였다. 응답의 `clusterVersion`은 문자열인데 백틱으로 쓴 `1.36`과 `1.37`을 숫자로 비교했다. 원본 응답을 문자열로 비교하니 두 버전 모두 `STANDARD_SUPPORT`였다. 조회 시점의 1.36 표준 지원 종료일은 2027-08-02였으며 이후에도 배포 직전에 다시 확인해야 한다.

`ec2:DescribeInstanceTypeOfferings`는 권한 부족으로 거부됐다. 따라서 두 AZ에서 `t3.medium`이 제공되는지는 미확인이다. 두 서브넷을 지정했다고 노드가 각 AZ에 정확히 하나씩 배치되는 것도 보장하지 않는다.

## 7. 로컬에서 계획 검증하기

Terraform 1.17.2, AWS Provider 6.73.0을 사용했다. AWS CLI의 `terraform-lab` 프로필과 해당 리소스 조회 권한이 준비돼 있어야 한다. 아래 명령은 형식·구조와 배포 계획을 확인한다.

```bash
cd ~/infrastructure-engineering-lab/investigations/06-aws-eks-infrastructure/terraform
terraform init
```

실제 접속 위치의 공인 IPv4를 확인해 Git에서 제외되는 `terraform.tfvars`를 로컬에 작성한다. 다음 주소는 문서용 예시이므로 그대로 사용하지 않는다.

```hcl
eks_public_access_cidrs = ["203.0.113.10/32"]
```

```bash
terraform fmt -check -diff
terraform validate
terraform plan -input=false -out=eks-build.tfplan
terraform show -json eks-build.tfplan | jq -r '
  .resource_changes[] |
  select(.change.actions != ["no-op"]) |
  "\(.change.actions | join(",")) | \(.address)"'
git check-ignore -v terraform.tfvars eks-build.tfplan terraform.tfstate
```

이번 로컬 State에는 기존 21개 리소스가 등록돼 있어 EKS Cluster와 Node Group 2개만 추가 예정이었다. State가 없는 새 체크아웃에서는 네트워크와 IAM도 새로 만드는 계획이 나온다. 같은 결과를 얻으려고 기존 State를 삭제하거나 다른 사람에게 공유하면 안 된다.

배포 전 Plan의 공개용 요약과 이후 부분 배포 상태는 [계획 검증 결과](evidence/validation/eks-plan-review.json)에 저장했다. 원본 Plan이나 State 내용은 포함하지 않았다. 위 검증 명령에는 apply/destroy를 넣지 않았다. 부분 배포 후에는 이전 계획 파일을 다시 적용하지 않고 현재 State를 반영한 복구 계획을 새로 확인해야 한다.

### Node Group의 PassRole 조건 불일치

최종 사전 점검 후 `eks-preflight.tfplan`을 적용했다. 클러스터는 7분 33초 후 생성됐지만 Node Group의 `CreateNodegroup` 호출은 `iam:PassRole` 거부로 중단됐다. 이후 읽기 전용 조회에서 클러스터 `ACTIVE`, Node Group 목록 `[]`, State의 클러스터 등록을 확인했다. 재실행이나 삭제는 하지 않았다.

Node Role의 신뢰 정책과 실행 사용자에게 부여한 PassRole 조건을 구분해야 했다. 노드를 실행하는 EC2의 신뢰 서비스는 `ec2.amazonaws.com`이지만, Node Group 생성 API로 역할을 전달받는 서비스는 `eks.amazonaws.com`이다. [AWS EKS 권한 참조](https://docs.aws.amazon.com/service-authorization/latest/reference/list_eks.html)의 `CreateNodegroup` 매핑에서도 이 조건을 확인했다. 사전 시뮬레이션은 잘못된 EC2 서비스 조건을 넣고 허용을 확인했기 때문에 실제 요청을 검증하지 못했다.

현재는 Node Role의 `iam:PassedToService`를 `ec2.amazonaws.com`에서 `eks.amazonaws.com`으로 교체하는 정책 수정안을 저장 직전까지 준비한 상태다. 아직 저장하거나 수정 후 시뮬레이션·복구 Plan을 실행하지 않았다. 다른 역할·정책 권한과 Node Role의 신뢰 정책은 변경 대상이 아니다. 실제 Node Group 생성과 최종 성공 여부는 후속 복구 후 기록한다.

## 8. 배포 전 남은 확인과 비용

- 배포 직전 시뮬레이터에서 서울 리전의 `CreateCluster`·`CreateNodegroup`, 각 역할과 대상 서비스를 지정한 `PassRole`, EKS/Node Group 서비스 연결 역할 ARN의 `CreateServiceLinkedRole`이 허용됐다. 실제 생성 시 연관 API와 권한 전파까지 검증한 것은 아니다.
- AZ별 인스턴스 제공 여부와 실제 EC2 용량은 미확인이다.
- 현재 CIDR 변수 검증은 유효한 CIDR인지와 `0.0.0.0/0` 제외만 검사한다. 모든 입력을 IPv4 `/32`로 강제하는 검증은 아니다. 이번 로컬 변수는 실제 IPv4 `/32`인지 별도로 확인했다.
- Public IP가 바뀌면 허용 CIDR을 갱신해야 한다. Node Group 배치, CNI, DNS, ECR 이미지 가져오기와 실제 인터넷 통신은 배포 후 검증한다.
- 단일 NAT의 가용성 한계, CNI 정책의 Node Role 공유, 클러스터 생성자 관리자 권한은 실습 편의를 고려한 선택이다.
- 현재 NAT Gateway와 공인 IPv4 유지 비용이 발생한다. 실제 사용 시간과 청구액은 아직 확정하지 않았다.

### 배포 전 비용 시나리오

2026-11-21에 확인한 공개 단가 기준이며 USD, 할인·크레딧·세금 적용 전 추정이다. EC2/NAT/EBS는 [AWS 서울 리전 공개 가격표](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonEC2/current/ap-northeast-2/index.csv)의 On-Demand 단가(적용일 2026-11-01)를 사용했다. [EKS 요금](https://aws.amazon.com/eks/pricing/)과 [VPC 공인 IPv4 요금](https://aws.amazon.com/vpc/pricing/)도 확인했다.

| 구성 | 계산 | 시간당 비용 |
| --- | --- | --- |
| EKS 표준 지원 | 1 × $0.10 | $0.100 |
| Linux t3.medium | 2 × $0.052 | $0.104 |
| NAT Gateway | 1 × $0.059 | $0.059 |
| 공인 IPv4 | NAT용 1개 × $0.005 | $0.005 |
| EBS | 노드당 20 GiB, 총 40 GiB | 아래 범위로 추정 |

현재 Node Group 코드에서 볼륨 종류는 명시하지 않았다. gp3 단가 $0.0912/GB-month와 gp2 단가 $0.114/GB-month로 계산하면, 월 730시간 환산 시 40 GiB의 시간당 비용은 약 $0.0050~$0.0062다. 실제 생성된 볼륨 종류와 청구 시간으로 다시 계산해야 한다.

따라서 워커 2개까지 생성한 경우의 기본 유지비는 **약 $0.273~$0.274/시간**이다. 실습 시간을 2시간으로 가정하면 약 $0.55, 4시간이면 약 $1.09~$1.10이다. 이는 사용 시간별 비교 시나리오이며 사용자가 정한 작업 시간이나 지출 한도는 아니다. 배포 준비·생성·삭제 대기 시간도 비용에 영향을 준다. 현재는 EKS 클러스터와 NAT+공인 IPv4가 남아 있어 기본 비용이 약 $0.164/시간 발생하는 상태다. Node Group 생성은 거부됐고 목록은 비어 있다.

위 합계에는 NAT 처리량($0.059/GB), AZ 간 전송, 인터넷 송신, T3 CPU 추가 크레딧, 추가 EBS 성능·스냅샷, 이후 ALB·로그 비용을 포함하지 않았다. 실제 전체 청구액의 상한으로 보면 안 된다. 부분 배포 상태에서도 생성된 유료 리소스의 비용은 계속 발생한다.

## 9. GitHub 업로드 전 점검

로컬 검증에서 `.terraform/`, `*.tfstate`, State 백업, `*.tfplan`, `*.tfvars`가 Git에서 제외되는지 확인했다. Provider 버전 재현을 위해 `.terraform.lock.hcl`은 포함한다. 현재 `.tf` 파일, README와 증빙을 대상으로 인증정보·개인 로컬 절대경로·실제 접속 IP의 포함 여부를 검사했다.

기존 네트워크 증빙은 변경하지 않았다. 공개 후보 파일에는 AWS 리소스 ID와 사설 CIDR이 포함되지만 계정 번호, 실제 공인 IP, 토큰이나 액세스 키는 넣지 않았다. 개인 접속 IP가 들어간 로컬 변수와 전체 State/Plan은 공개 후보에서 제외했다.

Git 추가 후보는 README, `terraform/*.tf`, `terraform/.gitignore`, `terraform/.terraform.lock.hcl`, 기존 `evidence/network/` 2개 파일과 `evidence/validation/eks-plan-review.json`이다. 아직 stage, commit, push하지 않았다.
