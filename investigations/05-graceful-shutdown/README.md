# SIGTERM에 끊기던 요청이 종료 처리 후 완료됐다

<sub>Kubernetes · Graceful Shutdown · kind(Control Plane 1, Worker 2) · Python ThreadingHTTPServer</sub>

처리 중인 요청에 SIGTERM을 보내자 기존 서버는 응답을 마치지 못하고 종료됐습니다. 종료 신호를 받은 뒤 진행 중인 요청을 기다리도록 바꾸자, 같은 방식으로 진행한 테스트에서는 HTTP 200이 돌아왔습니다.

이후 로컬 kind 클러스터에서 Worker Drain 중 순차 요청 20건을 확인했습니다. 두 실험은 요청 경로와 조건이 다르며, 실제 AWS Spot 중단을 재현한 것은 아닙니다.

## 컨테이너에 직접 보낸 SIGTERM, v1과 v2

이 비교는 Kubernetes를 거치지 않고 Docker 컨테이너에 직접 요청해서 했습니다. 테스트 서버는 요청마다 3초를 기다립니다. 종료 신호가 요청 처리 시간과 겹치도록 일부러 그렇게 만들었습니다.

![요청 처리 중 SIGTERM이 들어왔을 때 v1은 응답 없이 끊기고 v2는 요청 완료 후 종료되는 타임라인](evidence/graceful-sigterm-timeline.png)

| | v1 (SIGTERM에 즉시 종료) | v2 (요청 완료 후 종료) |
|---|---|---|
| curl HTTP 코드 | 000 | 200 |
| curl 종료 코드 | 52 (`Empty reply from server`) | 0 |
| 서버 로그 | 요청 시작, SIGTERM 수신. 완료 기록 없음 | 요청 완료, 그 뒤 `graceful shutdown completed` |
| 증빙 | [클라이언트](evidence/http-sigterm.txt) · [서버 로그](evidence/http-sigterm-server.txt) | [클라이언트](evidence/http-graceful.txt) · [서버 로그](evidence/http-graceful-server.txt) |

v1에서는 요청 처리 중 프로세스가 종료돼 curl이 `Empty reply from server`를 반환했습니다. 여기서 HTTP 000은 서버가 보낸 상태 코드가 아니라 응답을 받지 못했다는 표시입니다.

v2는 SIGTERM 이후 새 요청 수락을 멈추고 진행 중인 요청을 최대 10초 기다리도록 구현했습니다. 이번 요청 한 건에서는 HTTP 200을 받았고, 요청 완료 로그도 종료 완료 로그보다 먼저 남았습니다.

## Worker Drain 중 순차 요청 20건

다음은 Kubernetes의 노드 퇴거 상황입니다. 서버 Pod 2개와 ClusterIP Service를 두고, Drain 대상이 아닌 `spot-lab-worker2`의 클라이언트 Pod에서 순차 요청을 보냈습니다. 당시 순서는 요청을 시작하고 약 5초 뒤에 `spot-lab-worker`를 Drain하는 것이었습니다. 요청 로그와 Drain 로그에 공통 타임스탬프가 없어서, 이 간격은 저장된 기록으로 다시 확인할 수 없습니다.

| 측정 조건 | 전체 요청 | HTTP 200 | 관측된 실패 |
|---|---:|---:|---:|
| 정상 상태 | 20 | 20 | 0 |
| Worker Drain 중 | 20 | 20 | 0 |

Drain 로그에는 `spot-lab-worker`의 서버 Pod가 퇴거된 기록이 있고, Drain 이후 Pod 목록에는 `spot-lab-worker2`에서 실행 중인 Pod 2개가 남아 있습니다. 두 측정 모두 응답 시간은 약 3초였습니다.

이 결과가 Graceful Shutdown 덕분이라고 단정할 수는 없습니다. 요청이 순차적이었고, 다른 Worker에서 이미 실행 중이던 서버 Pod가 요청을 받을 수 있었기 때문입니다. Pod 상태는 Drain이 끝난 뒤에 확인했기 때문에 재배치에 걸린 시간이나 서비스 복구 시간도 측정하지 못했습니다. 이번 결과는 해당 조건에서 관측된 HTTP 실패가 없었다는 데까지입니다.

## 남은 한계

운영 환경에서 무중단을 말하려면 이번에 다루지 않은 것들이 남아 있습니다.

- Readiness Probe와 `preStop` Hook은 구현하지 않았습니다. 종료 중인 Pod의 EndpointSlice 엔드포인트는 종료 절차에서 `ready: false`가 되어 일반 트래픽 대상에서 빠지지만, 그 전파 시점과 실제 요청 유입 사이의 경합은 측정하지 않았습니다. ([Kubernetes Pod 종료 절차](https://kubernetes.io/docs/concepts/workloads/pods/pod-termination/) 참고)
- Deployment의 `terminationGracePeriodSeconds`는 30초이고, 앱은 처리 중인 요청을 최대 10초 기다리게 했습니다. 이것이 종료 시간을 엄격히 보장하는 것은 아닙니다.
- Pod 분산은 처음 `DoNotSchedule`로 두었다가 RollingUpdate 중 추가 Pod가 Pending에 머물러서 `ScheduleAnyway`로 바꿨습니다. 이때의 Pending 출력은 보관하지 않아서 원인을 증빙으로 확정하지는 못합니다. `ScheduleAnyway`가 두 Worker에 하나씩 배치되는 것을 보장하지도 않습니다. [저장된 Deployment](evidence/deployment-v2.yaml)에서 설정을 볼 수 있습니다.
- v2의 503 분기는 코드에만 있고, 종료 후 새 요청이 실제로 503을 받는지는 확인하지 못했습니다. 대기 결과를 검사하는 코드도 없어서 `graceful shutdown completed` 로그만으로 모든 요청이 끝났다고 볼 수 없습니다. 동시 요청은 시험하지 않았습니다.
- `kubectl drain`은 계획된 퇴거를 관찰한 것입니다. Spot 중단 알림 수신, 노드 종료까지의 제한 시간, 자동 Drain은 포함하지 않았습니다.

이번 실험은 kind 환경의 종료 처리와 Worker Drain에 한정됩니다. 실제 Spot 중단 처리와 Kubernetes의 트래픽 제외·종료 절차를 연결하는 AWS/EKS 검증은 후속 과제로 남겼습니다.

## 증빙

| 경로 | 기록 내용 |
|---|---|
| [`http-sigterm.txt`](evidence/http-sigterm.txt) · [`http-sigterm-server.txt`](evidence/http-sigterm-server.txt) | v1 클라이언트 결과와 서버 로그 |
| [`http-graceful.txt`](evidence/http-graceful.txt) · [`http-graceful-server.txt`](evidence/http-graceful-server.txt) | v2 클라이언트 결과와 서버 로그 |
| [`http-drain-v2.txt`](evidence/http-drain-v2.txt) | 정상 상태 순차 요청 20건 |
| [`http-during-drain-v2.txt`](evidence/http-during-drain-v2.txt) | Drain 중 순차 요청 20건 |
| [`drain-v2.txt`](evidence/drain-v2.txt) · [`pods-after-drain-v2.txt`](evidence/pods-after-drain-v2.txt) | Drain 실행 로그와 이후 Pod 상태 |
| [`pods-before-drain.txt`](evidence/pods-before-drain.txt) · [`pods-after-drain.txt`](evidence/pods-after-drain.txt) | 초기 Drain 전후 Pod 상태 |
| [`deployment-v2.yaml`](evidence/deployment-v2.yaml) | 실험 당시 Deployment 조회 기록 |

재현 명령은 [REPRODUCE.md](REPRODUCE.md)에 따로 두었습니다.

<details>
<summary>실험 환경과 기록에 없는 것</summary>

### 실험 환경

- 로컬 Kubernetes: kind 기반 클러스터, Control Plane 1개와 Worker 2개
- 애플리케이션: Python ThreadingHTTPServer, 포트 8080, 요청 처리 시간 약 3초
- Deployment: replicas 2개, Service는 ClusterIP, 종료 유예시간 30초
- Pod 분산 정책: topologySpreadConstraints / ScheduleAnyway

기존 환경 메모에는 `v1.37.0`이 있지만 도구·클러스터 버전을 확인할 원본 출력은 보관하지 않았습니다. kind 버전과 Kubernetes 버전은 구분해서 적어야 하므로 확정하지 않았습니다.

### 기록에 없는 것

- 클라이언트 Pod 설정은 저장하지 않았습니다. 실험 당시 클라이언트는 `spot-lab-worker2`에 두었고, [재현 명령](REPRODUCE.md)에는 이를 명시했습니다.
- Drain을 요청 시작 약 5초 뒤에 실행했다는 순서는 당시 실행 기록이며, 로그에 공통 타임스탬프가 없습니다.
- v2 실험의 Drain 직전 Pod 목록은 보관하지 않았습니다. 초기 Drain 전후 목록은 ReplicaSet 해시가 `79b4b8cdb4`이고 v2 Drain 로그는 `644dfc7c8`이라서, 초기 목록을 v2 실험 직전 상태로 해석하지 않았습니다. v2 로그에서 퇴거된 `r759l` Pod는 이후 목록에 없고, `spot-lab-worker2`에 `mrh4s`와 기존 `w6mlk` Pod가 실행 중입니다.
- 단일 SIGTERM 실험에서 클라이언트가 잰 약 4.01초와 서버 로그의 요청 처리 시간 약 3초는 측정 지점이 다릅니다.

</details>
