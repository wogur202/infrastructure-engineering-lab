# 독립 Job 메모리 Limit 비교 — 2026-11-24

8-E에서는 기존 OOM Job을128Mi와256Mi에서 각각 한 번씩 실행했다.
128Mi는 Kubernetes 종료 사유 OOMKilled,256Mi는 Completed/exit0으로 확인했다.
API 자체를 죽이거나 복구시키는 실험이 아니라 같은 Worker의 독립 Job 두 조건을 비교한 결과다.

## 1. 고정 조건과 범위

- 같은 기존 STEP08 이미지 digest와 memory_job.py를 사용했다. 이미지·코드·Manifest 소스는 바꾸지 않았다.
- memory request64Mi, CPU request/limit50/100m, ephemeral-storage request/limit16/32Mi로 고정했다.
- 작업은192Mi를16Mi씩 할당하고4KiB 페이지마다 쓴 뒤 최대10초 유지한다. 내부 제한50초, Job activeDeadline60초다.
- restartPolicy Never, backoffLimit0, 비root·읽기 전용 파일시스템·ServiceAccount token 미마운트다.
- 두 Manifest는 생성된 Job 이름과 memory limit 외에는 동일함을 대조했다.
- API는 CPU request=limit500m·memory128/256Mi·replica1, HPA OFF였다. 기존 노드 UID/providerID와 배치를 유지했다.
- 각 조건의 API info 관찰은 기존 k6로1RPS·180초, Job 실행 전60초 이상·종료 후60초 이상을 확보했다.
- README의 교차3쌍은 후보였으며, 실행 전 검토로 각 조건1회·총2회로 확정했다. 반복 재현성은 검증하지 않았다.
- 실행 중 k6 컨테이너 내부 진단을 하지 않았고, 종료 후 기존 collect.py로 원본을 내보냈다.

## 2. Job 종료 결과

| 메모리 Limit | 실행 시각 UTC | 종료 시각 UTC | 종료 사유 | exit | 마지막 작업 로그 | 실행 Pod / 재시작 |
| --- | --- | --- | --- | ---: | --- | --- |
| 128Mi | 2026-11-24T05:35:35Z | 2026-11-24T05:35:38Z | OOMKilled | 137 | allocated_mib112; 완료 로그 없음 | 1 / 0 |
| 256Mi | 2026-11-24T05:40:51Z | 2026-11-24T05:41:05Z | Completed | 0 | allocated_mib192 → completed_mib192 | 1 / 0 |

128Mi는 Failed나 exit137만으로 판단하지 않고 Pod container state.terminated.reason이 OOMKilled임을 확인했다.
Job은 backoffLimit0으로 실패 처리됐으며 BackoffLimitExceeded 이벤트1건이 남았다. 두 번째 Pod나 자동 재시도는 없었다.
256Mi는 모든192Mi 할당 로그와 completed_mib192, Pod Completed/exit0, Job Complete를 함께 확인했다.
메모리 페이지 접근은 같은 이미지의 구현과 단계별 로그를 근거로 확인했으며, 별도의 커널 메모리 추적은 하지 않았다.

## 3. API 전·중·후 관찰

| Limit | 전 / 중 / 후 HTTP 200 건수 | 전체 성공 / 오류 / Drop | 실제 RPS | 전 / 후 관찰 시간 |
| --- | --- | --- | ---: | --- |
| 128Mi | 68 / 3 / 110 | 181 / 0 / 0 | 1.00556 | 67.81s / 109.19s |
| 256Mi | 68 / 14 / 99 | 181 / 0 / 0 | 1.00556 | 67.55s / 98.44s |

총362건이 모두 HTTP200이었고 k6는 두 번 모두 exit0이었다.
API Ready 상실·재시작·예상 밖 API Probe 경고와 Node MemoryPressure는 관측되지 않았다.
Job 실행 시간은 Kubernetes startedAt~finishedAt으로 구분했다. 해당 timestamp는 초 단위이며,
HTTP 시작 시각도 duration 종료 timestamp에서 duration을 빼 근사했으므로 경계에는 오차가 있다.
짧은128Mi Job 실행 중 요청은3건,256Mi는14건뿐이다. 이 표본으로 모든 부하의 무중단이나
API OOM 복구·고가용성을 보장했다고 주장하지 않는다.

## 4. 메모리 관측의 한계

128Mi의 cAdvisor working_set 원시 표본은1개,약3.88MiB(4,071,424bytes)였다.
256Mi Job은 working_set 시계열이 수집되지 않았다.15초 Prometheus scrape와 cAdvisor 내부 갱신 간격보다
실행 시간이 짧아 실제 할당 과정을 놓칠 수 있다. 따라서 **두 조건 모두 정확한 메모리 peak는 미확인**이다.
128Mi의3.88MiB 표본이나 마지막 할당 로그112Mi를 OOM 발생 시 실제 사용량으로 쓰지 않았다.
256Mi의 작업 로그192Mi도 Python 런타임 등을 포함한 컨테이너 전체 사용량과는 다르다.
시계열 부재를 정상 메모리 사용의 증거로 보지 않으며, 이번 종료 판정의 주 근거는 Kubernetes 종료 상태와 작업 로그다.
128Mi OOM은 kube-state-metrics current terminated reason에도 기록됐지만, 해당 지표와 실제 메모리 peak는 별개다.

관측기 CFS 한계도 유지됐다. node-exporter의2분 rate CFS period 비율 표본 최대값은128Mi 관찰에서46.15%,
256Mi에서43.75%였다. 전체 target은11/11 Up, target sample age 최대값은 각각14.46/13.12초였다.
CFS period 비율은 CPU 사용률이나 손실 CPU 시간 비율이 아니다. 관측 환경이 완전하다고 표현하지 않으며
[HPA 결과에 기록한 품질 기준과 한계](hpa-results-20261124.md)를 그대로 유지한다. 추가 튜닝·새 수집 구현·재실험은 하지 않았다.

## 5. 판정과 종료 상태

독립 Job의 메모리 Limit에 따른 종료 결과와 관찰 범위의 API 응답은 **PASS**다.
정확한 메모리 peak, 반복 재현성, API 자체의 OOM 복구는 검증하지 않았다.
의도한128Mi 실패를 장애 복구 성공으로 바꾸어 해석하지 않는다.

최종 상태 snapshot은 2026-11-24T05:44:19.121854+00:00 UTC에 저장했다.
API1개 Ready/restart0, HPA OFF, 기존 Worker2개 Ready, Prometheus11/11 Up·Metrics API 정상이었다.
healthz/readyz/api/info도200이며 활성 HTTP 부하는0이다.128Mi Failed/OOMKilled Pod와256Mi Succeeded Pod는 증빙으로 보존했다.
해당 시점에는 두 번째 k6 컨테이너만 원본 수집용300초 sleep 구간이어서 Job Running으로 남아 있었다.
k6 프로세스의 exit0과 부하 종료는 확인했으며, Job 자체의 자연 완료와 구분해 기록했다.
이 OOM 실험에서는 기존 CPU/HPA 원본·결과와 Terraform/IAM/AWS 인프라를 변경하거나 삭제하지 않았다.
이후 환경 정리 상태는 [README](../README.md)에 있다.

## 6. 증빙 경로

공개본에는 계정·IP·노드 식별자·인증정보를 넣지 않았다. 다음 원본은 Git 제외 경로에 보관했다.

- evidence/private/oom-t1-128-053302/
- evidence/private/oom-t2-256-053302/
- 각 실행의 app.yaml/load.yaml, termination-evidence/, termination-review.json, after-1/, raw-memory-matrix.json, trial-review.json
- .local/e-1/: 실행 범위·HPA OFF 전환 기록·native watch·results.json·final-state/·SHA256 목록

STEP08의 CPU·HPA·독립 Job OOM 비교 결과는 [README](../README.md)에 모아 두었다.
