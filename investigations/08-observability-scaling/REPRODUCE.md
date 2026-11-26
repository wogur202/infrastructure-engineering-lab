# 재현 범위와 코드 구조

<sub>08번 실험의 코드 위치와 실행 절차, 재현의 한계입니다. 결과는 [README](README.md)에 있습니다.</sub>

## 코드 구조

| 경로 | 역할 |
| --- | --- |
| [app/](app/) | HTTP API, 유한 메모리 Job, Dockerfile |
| [k8s/](k8s/) | 공통 Deployment, CPU/HPA overlay, 독립 OOM Job |
| [load/](load/) | 고정 입력률 k6 시나리오, 원본·summary 출력 |
| [monitoring/](monitoring/) | 고정 Helm Values와 수집 쿼리. dashboard는 수동 import용 선택 자료 |
| [terraform/](terraform/) | 별도 EKS 실험 환경과 기존 ECR data 참조 |
| [scripts/](scripts/), [tests/](tests/) | 렌더·계정/노드 확인·사전 점검·수집·로컬 검증 |

## 로컬 검증

Python3, Docker, Terraform 1.17+, Helm4, kubectl을 준비한 뒤 로컬 검증은 다음 진입점으로 실행할 수 있다.

```bash
cd "$(git rev-parse --show-toplevel)/investigations/08-observability-scaling"
bash scripts/local-check.sh --docker
```

이 검사는 앱·이미지·설정·스키마를 확인한다. backend 없는 Terraform init/validate도 포함하지만 AWS apply나 실험 부하는 실행하지 않는다.
실제 AWS 측정의 성공 여부는 위 결과 문서와 구분해야 한다. 당시 범위는 [로컬 검증 기록](LOCAL-VALIDATION.md)에 남겼다.

## 실제 측정 절차

소스 Manifest의 image는 의도적으로 실행할 수 없는 placeholder다.
실제 실험에는 새로 게시한 ECR digest와 W/RPS/run-id를 [render.py](scripts/render.py)에 명시해 private 경로에 렌더했다.
계정·kubeconfig/context·노드 역할·Metrics API·Prometheus를 확인한 뒤 수동으로 배포와 부하 순서를 진행했다.
[preflight.py](scripts/preflight.py)의 사전 검사를 통과해도 실제 부하 중 입력률·배치·지표와 실험 진행 조건은 별도로 확인해야 한다.
HPA OFF 전환에는 기존 HPA 제거와 replica 1 Ready 확인이 별도로 필요하며, OOM은 관찰 부하를 먼저 시작해 전·후 60초를 확보했다.
[collect.py](scripts/collect.py)는 k6 종료 후 300초의 원본 수집 대기 구간 안에 raw/summary를 먼저 내보낸다.

## 재현의 한계

현재 공개 절차는 로컬 검증과 실험 구성·수집 방법을 제공한다.
이미지 게시, 환경별 입력, 각 Trial의 시작·회복·수집 순서를 모두 자동화한 원클릭 재현을 제공하는 것은 아니다.
스키마 검증도 실제 admission·IAM 권한·런타임 성능 검증을 대신하지 않는다.
