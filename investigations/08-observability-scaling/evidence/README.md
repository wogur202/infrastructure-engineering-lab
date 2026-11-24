# 증빙 상태와 보관 기준

CPU 본실험6회와 HPA 본실험6회를 완료했다. HPA는 관측 환경의 제한사항을 명시한 조건부 PASS다. 독립 Job OOM 비교는128Mi/256Mi 각1회 완료했다.
[OOM 결과](oom-results-20261124.md), [CPU 결과](cpu-limit-results-20261124.md), [HPA 결과](hpa-results-20261124.md),
[HPA Pilot](hpa-pilot-results-20261124.md), [배포 검증](deployment-verification-20261123.md)에 실제 수치를 정리했다.
로컬 테스트 통과와 실제 AWS 측정은 구분하며, 아래 원본 보관 원칙은 유지한다.

- `local/`: 로컬 테스트·렌더 결과. Git 제외.
- `private/<run-id>/`: 실제 실험 원본. Git 제외. renderer가 새 경로만 생성하며 기존 파일을 덮어쓰지 않는다.
- 공개 자료는 원본 검토 후 별도로 작성한다. 자동 익명화 성공을 가정하거나 원본을 그대로 Git에 추가하지 않는다.

실제 실행 때 보존할 항목: 실험 설정과 이미지 digest, pilot 근거와 고정 W/RPS,
시작/종료 UTC, warm-up/측정/회복 경계, 실제 Node/Pod 배치, k6 원본·summary,
Prometheus query_range JSON, Pod/Job 상태·Events, 실패/무효 판정 사유, 파일 SHA256.
`collect.py`는 읽기 전용이며 결과를 내보낸다. 수집 완료는 실험 성공 판정이 아니다.
수집 실패 시 이미 저장된 원본을 지우지 않고 `--attempt 2`처럼 새 번호로 다시 수집한다.
로그는 컨테이너별 최대10,000줄이므로 누락/절단 여부와 수집 오류도 검토한다.

k6 Job은 실행 종료 후 300초 동안 살아 있어 파일을 읽을 수 있다. 이 시간 안에
`/results/raw.json`, `/results/summary.json`을 수집한다. stdout에도 summary가 남지만
raw 파일을 대신하지는 않는다. Job deadline은 1200초이며 TTL 자동 삭제는 없다.
Job을 너무 늦게 수집하면 결과 파일을 읽을 수 없다. 실패한 실행도 파일/로그/원인을 남긴다.
OOM Job은 Never/backoff0이라 restartcount가 0이어도 OOMKilled일 수 있다.

비공개 원본에는 계정 ID, ARN, IP, hostname, Node providerID, 보안 그룹,
사용자 로컬 경로와 생성된 Helm Secret 등이 들어갈 수 있다. 원본 디렉터리는 0700,
파일은 0600으로 보관한다. Helm 렌더에는 임시 인증서·Grafana 관리자 Secret도
포함되므로 `.local/rendered-*.yaml` 전체를 공개하지 않는다. 인증서 Secret은 실제
클러스터에 배포된 것이 아니어도 비공개로 취급한다.

공개본에서는 credential/token/key/kubeconfig/state/plan은 제외하고 계정·ARN·IP·
로컬 절대경로를 검토·마스킹한다. 실험 시각, CPU/메모리 수치, 실패율, 종료 이유는
분석에 필요한 범위에서 보존한다. 원본 checksum과 공개본 checksum은 별도로 기록한다.
Prometheus ephemeral 데이터와 k6 결과를 내보내고 검증하기 전에 Pod/Helm을 삭제하지 않는다.
