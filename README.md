# 인프라 구축과 장애 실험 기록

Linux와 Kubernetes에서 장애 조건을 만들고, AWS에 API를 배포해 요청과 상태가 어떻게 달라지는지 확인했습니다.
설정을 바꾸기 전후의 응답, 로그, 지표를 비교한 기록입니다.

AWS 배포·운영 실험인 **Project Aegis**와 개별 현상을 다룬 **Engineering Lab**으로 구성했습니다.

## Project Aegis

AWS에 API를 배포하고, Pod 삭제나 배포 대상의 장애가 외부 요청에 어떤 영향을 주는지 확인했습니다.
이후 별도 EKS 환경에서 CPU 제한과 HPA 동작도 비교했습니다.
인프라는 Terraform으로 VPC·EKS를 구축하고, ECR의 Python API를 ALB에 연결했습니다.

GitHub Actions에서 실행한 범위는 CI와 OIDC 기반 ECR 게시까지입니다.
EKS 배포와 Rollback은 수동으로 진행했으며, Blue/Green에는 같은 이미지 digest를 사용해 슬롯을 구분했습니다.

배포 실험은 기존 인프라 코드를 재사용해 환경을 다시 구축했습니다.
CPU Limit·HPA·OOM 실험은 기존 ECR을 참조하는 별도 EKS·Terraform State 환경에서 수행했습니다.

- [EKS 인프라와 Pod 복구](investigations/06-aws-eks-infrastructure/README.md)
- [Blue/Green 업무 API 장애](investigations/07-safe-deployment/README.md)
- [CPU 제한과 HPA 관측](investigations/08-observability-scaling/README.md)

## Engineering Lab

TCP 연결 지연, Linux 메모리 제한, Kubernetes Service 연결 실패, Terraform 설정 변경, 종료 중인 요청 처리를 다룬 다섯 가지 독립 실험입니다.
조건을 바꿔 증상을 만들고 응답·로그·상태를 비교했습니다.

종료 실험에서는 진행 중인 요청의 종료 방식 비교와 Worker Drain 관찰을 나눠 진행했습니다.
로컬 kind 실험이며 실제 AWS Spot 중단을 재현한 것은 아닙니다.

## 대표 관측 사례

### [Healthy인데 업무 API는 503이었다](investigations/07-safe-deployment/README.md)

헬스 체크가 정상이어도 업무 API는 실패했습니다. Green에 장애를 주입하고 Ingress의 가중치를 Blue로 되돌린 뒤, 실제 API 응답이 정상으로 돌아오는 과정을 따라갔습니다.

### [대기열을 늘렸는데도 HTTP 타임아웃은 그대로였다](investigations/01-tcp-listen-queue/README.md)

동시 요청 30개 중 22개가 시간 안에 응답을 받지 못했습니다. 대기열을 늘리자 Overflow 증가는 사라졌지만 실패 건수는 같았습니다. 연결을 받아들이는 지연을 없앤 조건에서는 30개 모두 성공했습니다.

### [CPU 제한을 풀고 Pod를 늘리면 성능도 좋아질까?](investigations/08-observability-scaling/README.md)

CPU Limit을 바꾸고 HPA를 켜고 끄며 요청 처리 결과를 비교했습니다.
HPA는 1→2→1로 동작했고 CPU 부하는 분산됐지만, 응답 지연이나 처리량 개선을 입증하지는 못했습니다.

## 전체 실험 보기

각 README에서 코드·설정·결과 자료와 재현 조건을 확인할 수 있습니다.
번호는 기존 실험을 찾기 위한 구분이며, 아래 두 영역이 하나의 통합 시스템으로 구현된 것은 아닙니다.

<details>
<summary>Project Aegis · 구축, 배포와 복구, 자원 관측</summary>

- [AWS EKS 구축과 Pod 복구 · 06](investigations/06-aws-eks-infrastructure/README.md)
- [ALB Blue/Green과 업무 API 장애 · 07](investigations/07-safe-deployment/README.md)
- [CPU Limit·HPA·독립 Job OOM · 08](investigations/08-observability-scaling/README.md)

</details>

<details>
<summary>Engineering Lab · 다섯 가지 장애 조사</summary>

- [TCP 대기열과 연결 수락 지연 · 01](investigations/01-tcp-listen-queue/README.md)
- [시스템 여유 메모리와 cgroup OOM · 02](investigations/02-linux-oom-cgroup/README.md)
- [Service selector 장애의 DNS·HTTP 응답 · 03](investigations/03-kubernetes-dns/README.md)
- [Terraform Drift 탐지와 복구 · 04](investigations/04-terraform-drift/README.md)
- [종료 중 요청과 Worker Drain · 05](investigations/05-spot-graceful-shutdown/README.md)

</details>
