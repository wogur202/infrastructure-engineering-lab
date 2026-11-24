# STEP08 / 8-B-3 앱·관측 환경 배포 검증

검증 시각(UTC): `2026-11-23T12:22:20.404763+00:00`. 앱 소스 기준 Commit: `baf79d3`.
이 문서는 실제 EKS 배포와 기본 검증 결과다. CPU/HPA/OOM 성능 실험 결과는 아직 없다.

## 배포 범위

기존 m7i.large Worker2대와 EKS/VPC/NAT를 재사용했다. API는 2a의 api 역할 노드에1개, Metrics Server·Prometheus·Grafana·Operator·KSM은 2c의 support 역할 노드에 배치했다. node-exporter는 각 노드에1개다.
역할 지정에는 기존 node_labels.py의 읽기 전용 UID/providerID 검토와 원자적 JSON Patch 절차를 사용했다. 새 EC2/NodeGroup/ALB/Ingress/PVC는 만들지 않았다.

| 항목 | 실제 확인 |
| --- | --- |
| Metrics Server | Helm3.14.0 / app0.9.0, Metrics API nodes2/API Pod1 |
| Prometheus/Grafana 등 | kube-prometheus-stack93.8.0, Helm deployed |
| API | Replica1 Ready, request/limit250m, memory128/256Mi, Readiness/Liveness Probe |
| 상태 | Running·Ready Pod14, Pending0, Restart0, Node Pressure없음 |
| 접근 | STEP08 Service9개(Metrics Server·kubelet 조회 Service 포함) 모두 ClusterIP, Grafana는 localhost port-forward |
| 저장소/확장기 | PVC0, HPA0, k6/OOM Job 미배포 |

Metrics APIService는 CA bundle과 TLS 검증을 사용하며 kubelet 인증서 검증도 유지했다. 보안 검증 우회 옵션을 추가하지 않았다. Helm Secret·인증서·원본 manifest는 비공개 보관했다.

## 이미지와 기본 HTTP 검증

- linux/amd64 빌드 및 기존 단위 테스트·로컬 Docker Smoke 통과.
- 새 immutable 태그: `step08-baf79d3-20261123t121448z`
- 실제 ECR Digest: `sha256:18298fbd894be101f2ba8bf16d61c57a02b7e94b0521045f69a67c51fc75731b`
- 기존 STEP07 이미지·태그·보호 Digest는 유지했다. STEP07 CI가 STEP08을 빌드했다고 설명하지 않는다.
- 실제 EKS에서 `/healthz`, `/readyz`, `/api/info`, `/api/cpu-load?iterations=100` 모두 HTTP200. CPU 응답 checksum도 소스의 동일 입력 결과와 일치했다.

배포에는 실제 Digest를 고정했다. render의 rate1은 load.yaml 생성에 필요한 메타데이터일 뿐이며, 해당 부하 Job은 적용하지 않았다. 작은 HTTP Smoke를 성능 결과로 사용하지 않는다.

## 관측 결과

Prometheus Target11/11 Up, 관찰한 target sample age는45초 이내다. API CPU usage와 CFS periods/throttled periods/throttled seconds 네 지표가 모두 존재했다. CFS 누적값은 일부0보다 컸지만 시작·Probe·Smoke가 포함된 카운터여서 통제된 CPU 압박 실험의 결과로 해석하지 않는다.
Pod CPU/Memory requests·limits, Node CPU/Memory/Pressure와 실제 배치도 조회했다. HPA/k6/OOM 관련 시계열 부재는 아직 해당 실험을 실행하지 않았기 때문이며 수집 성공이나 장애 재현으로 보고하지 않는다.

## 실제 요청량 기반 수용량 예상

| 역할 | Allocatable CPU | 향후 요청량 투영 | 남는 CPU | 남는 메모리 |
| --- | --- | --- | --- | --- |
| api | 1930m | 시스템·관측 baseline + API2개 최대 비교 요청량 =1275m | 655m | 약6715.8MiB |
| support | 1930m | 현재 관측기·시스템 + 향후 k6 요청량 =900m | 1030m | 약5427.8MiB |

Pod·init/sidecar·overhead를 반영해 기존 helper로 계산했다. ephemeral-storage 요청량도 Allocatable 안에 들어간다. 이는 예약량 기반 예상이며 실제2Pod 확장·생성기 headroom·지속 디스크 사용을 검증한 것이 아니다.

기존 preflight의 자동 검사는 PASS였지만 `experiment_go=false`를 유지한다. API2개 동시 Ready, 알려진 CPU 작업과 counter 증가의 인과 확인, 생성기 여유/실제 입력률, HPA 안정 상태는 별도 실험 gate다. k6가 없어 실제 API/k6 분리 검증은 아직 NOT_VERIFIED다.

## 보존과 한계

Terraform 관리 리소스26개와 STEP06 State 해시는 유지했다. STEP01~07 코드·State·ECR 이미지를 수정·삭제하지 않았고 IAM을 확대하지 않았다. 인프라 자동 삭제도 구성하지 않았다.
Kubernetes 조회1건이 일시 실패했으나 재조회는 성공했다. 원인을 확정하지 않고 원본/재시도 기록을 비공개 보존했으며 재설치·초기화로 대응하지 않았다.

판정: 앱·관측 배포 검증 PASS, 본실험은 미실행. 다음 CPU 실험 전에 pilot과 비교 조건·관측 유효성을 확정해야 한다. 정확한 지연 개선·HPA 효과·OOM 결과는 아직 주장할 수 없다.
원본은 Git 제외 비공개 경로에 보존하고 이 문서에는 인증정보·계정 ID·노드 IP·Secret을 포함하지 않았다.
