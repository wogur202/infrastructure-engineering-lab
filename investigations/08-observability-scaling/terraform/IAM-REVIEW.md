# AWS 구축 전에 확인할 권한

2026-11-23 후속 상태: 8-A-6 검토와 사용자 승인 후 고객 관리형 `AegisStep08Supplement`
하나를 `terraform-lab` 한 명에게 연결했다. 생성된 JSON 전체가 검증본과 의미상 일치했고,
기존 정책10개는 유지되어 총11개다. Boundary 미설정도 유지했다. EC2/EBS/LT/ASG 조회와
Add-on 설정 조회는 실제 API 호출에 성공했다. 실제 인프라 생성·삭제는 아직 하지 않았다.
콘솔 요약의 일부 작업·리소스·조건 관련 안내 원인은 확정하지 않았으며, 이를 없애기 위해
조건을 제거하거나 권한을 확대하지 않았다. Simulator 허용을 실제 구축 성공으로 간주하지 않는다.
최종 정책·적용 확인 원본은 Git 제외 비공개 경로에 보관한다.

아래는 8-A-4 실제 권한 조사와 8-A-5 로컬 보완 당시의 기록이다. 당시에는 정책을 생성하거나 연결하지 않았다.
`terraform-lab` CLI의 `iam:ListAttachedUserPolicies`, `iam:ListUserPolicies`는 거부됐지만,
기존 관리자 콘솔에서 상속 정책까지 10개 JSON을 읽었다. Boundary는 미설정이고
SCP 화면은 계정이 Organizations 멤버가 아니라고 반환했다. 아래 API 표는 검토 범주이며
모두 허용됐다는 뜻이 아니다.

## 실제 확인된 부족 권한

새 `aegis-step08-cluster` 역할의 CreateRole/DeleteRole/PassRole은 10개 정책을 포함한
AWS Simulator에서 암시적 거부였다. 서울 리전과 EKS 전달 조건을 지정했다.
기존 역할 관리·PassRole·instance profile 조회는 예전 역할 ARN에만 한정된다.
네트워크/Cluster/NodeGroup/SG 관리는 서울 조건으로 허용하지만 Launch Template,
RunInstances, managed Add-on 생성·수정·삭제는 기존 열거 목록에 없다.
DescribeInstances/Volumes/LaunchTemplates와 DescribeAutoScalingGroups는 실제 API도 거부됐다.
EIP 분리는 과거 EIP/ENI 식별자만 허용해 새 자원에 그대로 적용할 수 없다.

기존 ECR 정책은 repo 조회뿐 아니라 삭제도 허용한다. 따라서 ECR 보존은 새 root의
data 참조와 명령 범위 관리에 근거하며, 사용자 IAM이 삭제를 금지한다고 설명하지 않는다.
기존 정책을 수정하거나 이 삭제 권한을 새 초안에 복제하지 않았다.

| 실행 주체/대상 | 생성·조회·삭제 과정의 주요 동작 |
| --- | --- |
| Terraform 사용자 / 신규 네트워크 | EC2 Create/Describe/DeleteVpc·Subnet·RouteTable·Route·InternetGateway, ModifyVpcAttribute, Attach/DetachInternetGateway, Associate/DisassociateRouteTable, Allocate/Describe/ReleaseAddress, Create/Describe/DeleteNatGateway, 필요한 Create/DeleteTags |
| Terraform 사용자 / 신규 Launch Template | Create/Describe/DeleteLaunchTemplate, Create/Delete/DescribeLaunchTemplateVersions, 필요한 ModifyLaunchTemplate·CreateTags |
| Terraform 사용자 / EKS | Create/Describe/DeleteCluster, UpdateClusterConfig/Version, DescribeUpdate, Create/Describe/DeleteNodegroup, UpdateNodegroupConfig/Version, List/Describe/Tag/UntagResource, Create/Describe/Update/DeleteAddon, DescribeAddonVersions/Configuration |
| Terraform 사용자 / 신규 IAM 역할 | Create/Get/DeleteRole, UpdateAssumeRolePolicy, Attach/Detach/ListAttachedRolePolicies, ListRolePolicies, Tag/Untag/ListRoleTags, 역할을 EKS/EC2에 전달하는 제한된 PassRole |
| AWS 서비스 연결 역할 | 계정에 없는 경우에만 제한된 CreateServiceLinkedRole이 필요할 수 있다. EKS/Node Group/Auto Scaling에 필요한 서비스 이름 조건을 검토한다. |
| EKS·Node Group 서비스 역할 | EC2/ASG/SG/ENI/인스턴스 프로파일 등은 서비스가 만들기도 한다. 사용자와 서비스 역할이 필요한 동작을 구분한다. Custom Launch Template의 RunInstances/CreateTags/PassRole 요구사항도 별도로 확인한다. |
| 노드 역할 | AmazonEKSWorkerNodePolicy, AmazonEC2ContainerRegistryPullOnly, AmazonEKS_CNI_Policy. CNI 권한이 노드 역할에 있는 작은 실험실 구성이다. 운영 환경의 Pod 단위 권한 분리를 구현한 것은 아니다. |
| 기존 ECR | DescribeRepositories 등 data source 조회와 노드 Pull만 필요. 새 Terraform에 ECR 생성/삭제 또는 기존 이미지 삭제 권한을 추가할 이유가 없다. |
| 잔여 리소스 확인 | DescribeInstances/Volumes/Addresses/NatGateways/NetworkInterfaces/SecurityGroups/Subnets/RouteTables/Vpcs, EKS 조회, autoscaling:DescribeAutoScalingGroups 등. 실제 정리 과정에서 필요한 DisassociateAddress/ReleaseAddress 권한과 최신 대상 식별자도 확인한다. |

표의 Create/Describe/Delete 표기는 동작 범주를 축약했다. 이 문서를 그대로 IAM JSON
Action으로 복사하지 않는다. Terraform provider가 사용하는 정확한 API, 리소스 ARN,
조건 키, 적용 가능한 리소스 범위를 검토해 정책을 구성해야 한다. 일부 Describe 동작은
Resource `*`가 필요하지만 Create/Delete/PassRole까지 넓힐 근거가 되지는 않는다.

DescribeAddonVersions와 EC2 DescribeInstanceTypeOfferings는 성공했다.
DescribeAddonConfiguration과 Pricing GetProducts는 거부되었다. 가격은 공식 Price List로
확인했다. AWSServiceRoleForAmazonEKS/AmazonEKSNodegroup은 GetRole 조회로 존재를 확인했다.
Auto Scaling 서비스 연결 역할의 존재는 아직 확인하지 못했다. 공유 역할을 지우지 않는다.

## 비공개 부분 초안

`.local/iam-review/supplement-partial-draft.json`은 11개 Statement의 검토용 부분 초안이다.
새 역할 2개의 정확한 ARN, 역할별 managed policy 제한, EKS 대상 PassRole, 빠진 조회,
Scope 태그가 있는 LT, 신규 클러스터의 태그가 있는 Add-on 생성과 기존 3개 Add-on ARN의
수정·삭제 범위를 담았다. CreateAddon은 cluster ARN으로 제한되며, 지원하지 않는 addonName
조건을 만들어 이름까지 제한됐다고 주장하지 않는다. 이미 허용된 네트워크·
EKS 기본 관리·CreateTags·ECR 동작은 다시 추가하지 않았다. 같은 Action이어도 새 역할 ARN의
허용은 기존 허용과 다르므로 새 ARN에 필요한 권한은 초안에 포함했다.

공식 SAR JSON과 Action 표로 Action/리소스 종류/조건 키를 검토했다. EC2 LT 생성은
RequestTag, 기존 LT 변경·삭제는 ResourceTag를 구분했다. Add-on의 생성 대상 cluster ARN과
수정·삭제 대상 addon ARN도 구분했다. 이 검사는 AWS 유효 권한 시뮬레이션이 아니다.

`unresolved.json`에는 RunInstances 다중 리소스, CreateAccessEntry 간접 호출 문맥,
새 NAT EIP/ENI 분리 범위, 공유 서비스 역할 및 실제 AWS 검증의 미해결 항목을 분리했다.
RunInstances의 AMI/instance/volume/ENI/subnet/SG/LT에 같은 태그 조건을 무조건 붙이지 않는다.
현재 LT에는 instance/volume 태그가 있지만 ENI 태그는 없고 EKS 자동 SG의 태그도 미확인이다.
정확히 검증하지 못한 이 쓰기 권한은 부분 초안에 넣지 않았다. CreateAccessEntry도
creator bootstrap의 principal/type 조건이 실제 평가되는지 확인하기 전에는 허용문을 만들지 않는다.
따라서 이 부분 초안을 적용해도 전체 구축이 가능하다는 결론을 내릴 수 없다.

기존 임시 OIDC 정리 정책을 재연결하거나 기존 GitHub OIDC/Publisher Role을 변경하지 않는다.
이번 Terraform에는 IAM OIDC Provider가 없다. Metrics Server/Prometheus도 추가 AWS API 권한을
사용하지 않는다. 최초 클러스터 생성자의 Kubernetes 관리자 접근은 실험실 관리용이다.
GitHub Actions의 EKS 배포 권한까지 구성한 것은 아니다.

다음에는 미해결 문맥과 AWS 정책 검증·시뮬레이션을 검토하고, 승인된 정확한 범위만 적용해야 한다.
Terraform validate나 부분 IAM 초안의 문법 통과는 생성·삭제 권한 검증이 아니다.
AdministratorAccess 추가를 해결책으로 삼지 않는다.

근거: [EKS Node IAM role](https://docs.aws.amazon.com/eks/latest/userguide/create-node-role.html),
[EKS launch templates](https://docs.aws.amazon.com/eks/latest/userguide/launch-templates.html),
[EKS IAM actions](https://docs.aws.amazon.com/service-authorization/latest/reference/list_eks.html).
