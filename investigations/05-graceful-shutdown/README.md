# Pod가 종료될 때 진행 중인 HTTP 요청은 어떻게 되는가?

## 1. 요청을 처리하던 Pod가 종료된다면

HTTP 요청을 처리하던 Pod가 종료 신호를 받으면, 클라이언트는 응답을 끝까지 받을 수 있을까? Kubernetes에서 노드를 점검하거나 교체할 때 사용하는 `kubectl drain`도 해당 노드의 Pod를 퇴거시킨다.

하지만 다른 노드에 Pod가 다시 생성된다는 사실만으로 기존 요청이 정상적으로 처리된다고 볼 수는 없다. 애플리케이션이 종료 신호를 받았을 때 어떤 동작을 하는지도 중요하다.

먼저 단일 HTTP 요청 처리 도중 SIGTERM을 전달해 즉시 종료하는 v1과 요청 완료를 기다리는 v2를 비교했다. v1은 응답을 받지 못한 채 끝났고, v2는 HTTP 200으로 요청을 마쳤다. 별도의 Worker Drain 실험에서는 Service로 보낸 순차 요청 20건과 Pod 퇴거·재배치를 관찰했다. 두 실험은 요청 경로와 관측 조건이 다르다.

실험은 로컬 kind 환경에서 수행했다. 실제 AWS Spot 인스턴스 중단 이벤트를 재현한 것은 아니다.

## 2. 실험 환경

- 로컬 Kubernetes: kind 기반 클러스터
- 노드: Control Plane 1개, Worker 2개
- 애플리케이션: Python ThreadingHTTPServer
- HTTP 포트: 8080
- 요청 처리 시간: 약 3초
- Deployment: replicas 2개
- Service: ClusterIP
- 종료 유예시간: 30초
- Pod 분산 정책: topologySpreadConstraints / ScheduleAnyway

기존 환경 메모에는 `v1.37.0`이 있으나, 도구·클러스터 버전을 확인할 원본 출력은 보관하지 않았다. kind 버전과 Kubernetes 버전은 구분해 기록해야 하므로 여기서는 확정하지 않았다.

테스트용 HTTP 서버는 요청마다 3초를 기다리도록 구성했다. 종료 신호가 들어오는 시점을 의도적으로 요청 처리 시간과 겹치게 하기 위해서다.

## 3. 첫 번째 실험: 요청 처리 중 즉시 종료

초기 버전(v1)은 SIGTERM을 받으면 프로세스를 즉시 종료하도록 구현했다.

HTTP 요청이 처리되는 도중 SIGTERM을 전달하자 클라이언트에서는 다음 결과가 나타났다.

- curl이 표시한 HTTP 코드: 000 (HTTP 응답을 받지 못했다는 뜻이며, 서버가 반환한 상태 코드가 아님)
- curl 종료 코드: 52
- 오류: Empty reply from server

서버 로그에는 요청 시작과 SIGTERM 수신이 기록됐지만, 요청 완료 기록은 없었다.

즉, 해당 실험에서는 요청을 처리하던 프로세스가 먼저 종료되면서 정상 HTTP 응답을 반환하지 못했다.

증빙:

- [v1 클라이언트 결과](evidence/http-sigterm.txt)
- [v1 서버 로그](evidence/http-sigterm-server.txt)

## 4. 두 번째 실험: Graceful Shutdown 적용

개선 버전(v2)에서는 SIGTERM을 받더라도 즉시 종료하지 않도록 변경했다.

구현한 동작은 다음과 같다.

1. SIGTERM 수신 사실을 기록한다.
2. 요청 처리기가 종료 상태를 확인하면 HTTP 503을 반환하도록 분기한다.
3. HTTP 서버의 요청 수락 루프를 종료한다.
4. 현재 처리 중인 요청 수를 확인하고 완료를 기다린다.
5. 대기가 끝나면 종료 로그를 남기고 서버 소켓을 닫는다.

진행 중인 요청 수는 `active` 변수와 `threading.Condition`으로 관리했다. 수락 루프 종료 후 최대 10초를 기다리며, 이번 증빙에서는 요청 완료 뒤 종료 로그가 남았다. 다만 코드가 대기 결과를 검사하지 않으므로 `graceful shutdown completed` 로그만으로 모든 요청의 완료를 판단해서는 안 된다.

503은 코드에 있는 분기이며, 종료 후 새 요청이 이 분기에 도달해 503을 받는지는 이번 증빙으로 확인하지 못했다. SIGTERM을 받으면 수락 루프도 종료하므로 모든 새 요청이 503을 받는다고 보장할 수는 없다.

동일하게 HTTP 요청 처리 중 SIGTERM을 전달한 결과:

- HTTP 코드: 200
- curl 종료 코드: 0
- 서버 로그에서 요청 완료 확인
- 이후 Graceful Shutdown 완료 로그 확인

v1에서는 중단됐던 요청이 v2에서는 정상적으로 완료됐다.

다만 단일 요청을 대상으로 확인한 결과이며, 모든 동시 요청에서 성공을 보장하는 검증은 아니다.

증빙:

- [v2 클라이언트 결과](evidence/http-graceful.txt)
- [v2 서버 로그](evidence/http-graceful-server.txt)

## 5. 세 번째 실험: Worker Cordon / Drain

애플리케이션의 종료 동작을 확인한 다음, Kubernetes 노드 퇴거 상황을 실험했다.

서버 Pod 2개와 ClusterIP Service를 사용하고, 별도의 클라이언트 Pod에서 HTTP 요청을 보냈다. 초기 Drain 전후 목록에는 두 Worker에 나뉘어 있던 Pod가 한 Worker로 옮겨진 모습이 남아 있다. v2 실험의 Drain 직전 Pod 목록은 별도로 보관하지 않았다.

실험 당시 클라이언트는 Drain 대상이 아닌 `spot-lab-worker2`에 배치했다. 다만 클라이언트 Pod 설정을 저장한 증빙은 없으며, 9절의 재현 명령에서는 이를 명시한다.

실험 당시 진행한 순서는 다음과 같다. 요청 로그와 Drain 로그에 공통 타임스탬프가 없어, 아래의 약 5초 간격을 저장된 증빙만으로 다시 확인할 수는 없다.

1. Service로 순차 HTTP 요청 시작
2. 약 5초 뒤 `spot-lab-worker` Drain 실행
3. 기존 서버 Pod 퇴거 확인
4. HTTP 응답 결과 확인
5. 다른 Worker에서 대체 Pod 실행 확인

Drain 과정에서 `spot-lab-worker`에 있던 서버 Pod가 퇴거됐고, 대체 Pod는 `spot-lab-worker2`에서 실행됐다.

증빙:

- [Drain 실행 로그](evidence/drain-v2.txt)
- [Drain 이후 Pod 상태](evidence/pods-after-drain-v2.txt)
- [초기 Drain 전 Pod 상태](evidence/pods-before-drain.txt)
- [초기 Drain 후 Pod 상태](evidence/pods-after-drain.txt)

초기 목록의 ReplicaSet 해시는 `79b4b8cdb4`, v2 Drain 로그의 해시는 `644dfc7c8`이다. 초기 목록을 v2 실험 직전 상태로 해석하지 않았다. v2 로그에서 퇴거된 `r759l` Pod는 이후 목록에 없고, 다른 Worker에 `mrh4s`와 기존 `w6mlk` Pod가 실행 중이다.

## 6. HTTP 측정 결과

| 측정 조건 | 전체 요청 | HTTP 200 | 관측된 실패 |
|---|---:|---:|---:|
| 정상 상태 | 20 | 20 | 0 |
| Worker Drain 중 | 20 | 20 | 0 |

정상 상태와 Drain 상황 모두 HTTP 요청 20건이 성공했다. 두 순차 요청 측정 파일의 응답 시간은 약 3초였다. 4절의 단일 SIGTERM 실험에서 클라이언트가 측정한 시간은 약 4.01초로, 서버 로그의 요청 처리 시간 약 3초와 구분한다.

이번 결과는 해당 트래픽 조건에서 관측된 HTTP 실패가 없었다는 의미다.

다만 요청은 순차적으로 전송했고, 다른 Worker에서 이미 실행 중이던 서버 Pod가 요청을 처리할 수 있었다. 따라서 실패가 발생하지 않은 원인을 Graceful Shutdown 하나로 단정할 수 없다.

또한 Pod 상태는 Drain 이후 확인했으므로, 정확한 재배치 소요 시간이나 서비스 복구 시간을 측정했다고 볼 수 없다.

증빙:

- [정상 상태 HTTP 결과](evidence/http-drain-v2.txt)
- [Drain 중 HTTP 결과](evidence/http-during-drain-v2.txt)

## 7. 운영 환경 적용 시 고려할 점

이번 v2 서버는 종료 중인 요청을 기다리도록 구현했지만, Kubernetes 운영 환경에서 무중단을 보장하려면 추가적인 설정과 검증이 필요하다.

**Readiness Probe와 preStop Hook**

현재 Deployment에는 `readinessProbe`와 `preStop` Hook을 구현하지 않았다. 종료 중인 Pod에 해당하는 EndpointSlice의 엔드포인트는 Kubernetes 종료 절차에서 `ready: false`로 표시돼 일반 트래픽 대상에서 제외되지만, 그 전파 시점과 실제 요청 유입 사이의 경합은 이번에 측정하지 않았다. Readiness Probe를 추가한다면 준비 상태 판정도 별도로 검증해야 한다. [Kubernetes Pod 종료 절차](https://kubernetes.io/docs/concepts/workloads/pods/pod-termination/)를 참고했다.

**종료 유예시간**

Deployment에는 `terminationGracePeriodSeconds: 30`이 설정돼 있다. 애플리케이션 내부에서는 진행 중인 요청을 최대 10초 기다리도록 작성했으나, 이것이 프로세스 종료 시간을 엄격히 보장하는 것은 아니다.

**Pod 분산**

처음 사용한 `DoNotSchedule` 조건에서는 RollingUpdate 중 추가 Pod가 Pending 상태에 머무는 상황이 발생했다.

이후 `ScheduleAnyway`로 변경해 분산을 선호하면서도, 한 Worker가 스케줄 불가 상태일 때 다른 Worker에 Pod를 배치할 수 있도록 했다. 현재 코드와 [저장된 Deployment](evidence/deployment-v2.yaml)에서 이 설정을 확인할 수 있다. 다만 앞선 Pending 상태의 출력은 보관하지 않아, 원인을 증빙으로 확정하지는 못한다. `ScheduleAnyway`는 두 Worker에 하나씩 배치되는 것을 보장하지 않는다.

**실제 Spot 중단과의 차이**

`kubectl drain`은 계획된 Pod 퇴거 동작을 관찰하기 위한 실험이다. AWS Spot 중단 알림 수신, 노드 종료까지의 제한시간, 자동 Drain 및 실제 인스턴스 중단 과정은 이번 실험에 포함하지 않았다.

## 8. 종료 방식과 Drain에서 확인한 것

이번 실험을 통해 Pod가 다른 노드에 다시 생성되는 것과, 기존 HTTP 요청이 정상적으로 마무리되는 것은 별도의 문제라는 점을 확인했다.

SIGTERM에 즉시 종료하는 v1에서는 진행 중인 요청이 실패했지만, Graceful Shutdown을 적용한 v2에서는 동일한 유형의 요청을 정상적으로 마무리했다.

별도의 Worker Drain 실험에서는 Pod 퇴거 및 재배치가 이루어졌고, 관측한 HTTP 요청 20건은 모두 성공했다.

이 실험을 마쳤을 때는 실제 Spot 중단 처리와 Kubernetes 트래픽 제외·종료 절차를 연결하는 AWS/EKS 검증을 후속 계획으로 남겼다. 이 문서는 그 계획의 수행 여부나 06~08에 같은 종료 처리가 적용됐음을 증명하지 않는다.

## 9. 로컬 환경에서 재현하기

아래는 저장된 코드로 다시 실험하기 위한 명령이다. 문서를 정리할 때는 실행 중인 환경을 바꾸지 않기 위해 클러스터 생성·이미지 빌드·배포·Drain을 다시 실행하지 않았다. 명령어의 셸 구문과 코드·설정의 일치 여부를 확인했으며, `spot-http.yaml`은 Kubernetes v1.34.0 공식 OpenAPI 스키마로 정적 검증했다. 실제 클러스터 버전의 API 서버 검증과 전체 재실행 검증은 하지 않았다. 기존 `evidence/`는 원본 기록으로 두고, 재현 결과는 Git에서 제외한 `.local/`에 저장한다.

### 9.1 준비 및 3노드 클러스터 생성

Docker 엔진이 실행 중이어야 하며, `kind`, `kubectl`, `curl`, Bash가 필요하다. 저장소를 받은 뒤 05 디렉터리로 이동한다. 아래의 `~/infrastructure-engineering-lab`은 예시 체크아웃 위치이며, 실제 저장소 위치에 맞춰 이동하면 된다.

```bash
cd ~/infrastructure-engineering-lab/investigations/05-graceful-shutdown
bash
mkdir -p .local
export KUBECONFIG="$PWD/.local/kubeconfig"
kind version
kubectl version --client
kind get clusters
```

`spot-lab`이라는 클러스터가 없을 때만 다음 생성 명령을 실행한다. 같은 이름의 클러스터가 이미 있다면 이 절차를 멈추고 기존 환경의 용도를 확인한다. 기존 클러스터를 삭제하거나 재생성하지 않는다. 별도 kubeconfig를 사용하므로 기본 kubeconfig의 현재 컨텍스트도 바꾸지 않는다.

```bash
kind create cluster --name spot-lab --config manifests/kind.yaml \
  --kubeconfig "$KUBECONFIG"
kubectl --context kind-spot-lab get nodes -o wide
```

[클러스터 설정](manifests/kind.yaml)은 Control Plane 1개와 Worker 2개를 생성한다. 노드 이름은 `spot-lab-control-plane`, `spot-lab-worker`, `spot-lab-worker2`가 된다. 노드 이미지 버전은 고정하지 않았으므로 설치된 kind의 기본값을 사용한다. `get nodes` 출력으로 실제 Kubernetes 버전을 기록한다. 설정과 이미지 로드 방식은 [kind 공식 안내](https://kind.sigs.k8s.io/docs/user/quick-start/)를 따랐다.

### 9.2 이미지 빌드 및 kind 로드

현재 [Dockerfile](app/Dockerfile)은 빌드 컨텍스트의 `server.py`만 복사하므로, 컨텍스트는 저장소 루트가 아닌 `./app`이어야 한다. 이 이미지는 v2 서버를 실행한다.

```bash
docker build -t spot-http:v2 ./app
kind load docker-image spot-http:v2 --name spot-lab
```

Manifest의 이미지 이름도 `spot-http:v2`이며, `imagePullPolicy: IfNotPresent`로 로드한 이미지를 사용한다. 같은 태그로 코드를 바꾸어 다시 빌드하는 경우에는 이미지 재로드와 기존 Pod 교체가 추가로 필요하다. 아래 절차는 새 실험 환경에 최초 배포하는 경우를 기준으로 한다.

### 9.3 단일 요청 중 SIGTERM 비교

이 비교는 Service를 거치지 않고 Docker 컨테이너에 직접 요청한다. v1은 [즉시 종료 코드](app/server_immediate.py)를 같은 베이스 이미지 위에서 실행한다. v2 이미지를 만드는 Dockerfile이 v1 파일까지 포함하는 것은 아니므로, v1 파일은 읽기 전용으로 마운트한다.

호스트의 `18080` 포트와 `step05-sigterm-v1`, `step05-sigterm-v2` 컨테이너 이름이 비어 있는 환경에서 실행한다. 이미 사용 중이라면 해당 자원을 지우지 말고 이 절차의 이름과 포트를 바꾼다. 다음 함수는 Bash에서 실행하며, 요청 시작 로그를 확인한 뒤 SIGTERM을 전달한다.

```bash
compare_shutdown() {
  local version="$1"
  local name="step05-sigterm-$version"
  local request_pid rc started

  if [ "$version" = v1 ]; then
    docker run -d --name "$name" -p 127.0.0.1:18080:8080 \
      -v "$PWD/app/server_immediate.py:/app/server_immediate.py:ro" \
      spot-http:v2 python -u server_immediate.py || return 1
  else
    docker run -d --name "$name" -p 127.0.0.1:18080:8080 \
      spot-http:v2 || return 1
  fi

  started=0
  for i in {1..100}; do
    if docker logs "$name" 2>&1 | grep -q 'HTTP server started'; then
      started=1
      break
    fi
    sleep 0.1
  done
  if [ "$started" -ne 1 ]; then
    echo "서버 시작 실패: docker logs $name 으로 확인"
    return 1
  fi

  curl --max-time 15 -sS -w '\nHTTP %{http_code} | %{time_total}s\n' \
    http://127.0.0.1:18080/ > ".local/http-$version.txt" 2>&1 &
  request_pid=$!

  started=0
  for i in {1..100}; do
    if docker logs "$name" 2>&1 | grep -q 'request started'; then
      started=1
      break
    fi
    sleep 0.1
  done
  if [ "$started" -ne 1 ]; then
    wait "$request_pid"
    echo "요청 시작을 확인하지 못함: 종료 비교를 중단"
    return 1
  fi

  sleep 1
  docker kill --signal=TERM "$name"
  if wait "$request_pid"; then rc=0; else rc=$?; fi
  printf 'curl exit: %s\n' "$rc" >> ".local/http-$version.txt"
  docker wait "$name"
  docker logs "$name" > ".local/server-$version.txt" 2>&1
  cat ".local/http-$version.txt" ".local/server-$version.txt"
  docker rm "$name"
}

compare_shutdown v1
compare_shutdown v2
```

v1에서는 `HTTP 000`과 `curl exit: 52`, v2에서는 `HTTP 200`과 `curl exit: 0`을 예상한다. v2는 `request completed`가 `graceful shutdown completed`보다 먼저 남는지도 확인한다. 요청 시작 확인이 늦어져 SIGTERM 전에 응답이 끝났다면 유효한 비교가 아니므로 로그 시각을 보고 판단한다. 함수가 중간에 실패하면 컨테이너는 진단을 위해 남는다.

### 9.4 Kubernetes Manifest 적용 및 정상 상태 HTTP 테스트

적용 대상은 [배포 Manifest](manifests/spot-http.yaml)다. 이 파일에는 조회 결과의 `status`, `generation`, revision annotation 등이 없다. `evidence/deployment-v2.yaml`에 남은 메타데이터와 상태값은 실험 당시 조회 기록이므로 그대로 보존했으며, 배포 입력으로 사용하지 않는다.

```bash
kubectl --context kind-spot-lab apply -f manifests/spot-http.yaml
kubectl --context kind-spot-lab -n default rollout status deployment/spot-http --timeout=120s
kubectl --context kind-spot-lab -n default get pods -l app=spot-http -o wide
kubectl --context kind-spot-lab -n default get service spot-http-svc
```

`rollout status`의 성공은 이번 설정에서 애플리케이션 Readiness Probe 통과를 의미하지 않는다. Probe 자체가 없기 때문이다. 실제 HTTP 응답은 아래 클라이언트로 확인한다.

클라이언트 Pod는 Drain 대상이 아닌 `spot-lab-worker2`에 고정하고, 실험 사이에도 유지한다. 이름이 이미 사용 중이라면 먼저 용도를 확인한다.

```bash
kubectl --context kind-spot-lab -n default run step05-http-client \
  --image=curlimages/curl:8.12.1 --restart=Never \
  --overrides='{"spec":{"nodeSelector":{"kubernetes.io/hostname":"spot-lab-worker2"}}}' \
  --command -- sleep 3600
kubectl --context kind-spot-lab -n default wait --for=condition=Ready \
  pod/step05-http-client --timeout=120s

request_batch() {
  kubectl --context kind-spot-lab -n default exec step05-http-client -- sh -c '
    i=1
    while [ "$i" -le 20 ]; do
      printf "request=%s " "$i"
      curl --max-time 10 -sS -o /dev/null \
        -w "HTTP=%{http_code} time=%{time_total}s" \
        http://spot-http-svc:8080/
      rc=$?
      printf " curl_exit=%s\n" "$rc"
      i=$((i + 1))
    done
  '
}

request_batch > .local/http-baseline-repro.txt 2>&1
cat .local/http-baseline-repro.txt
```

각 행의 `HTTP=200`과 `curl_exit=0`을 확인한다.

### 9.5 Cordon / Drain 중 순차 HTTP 요청

Drain 전에 서버 Pod가 두 Worker에 하나씩 있는지 확인한다. `ScheduleAnyway`는 분산을 보장하지 않으므로, 두 Pod가 모두 같은 Worker에 있다면 기존 실험과 동일한 배치 조건이 아니다. 이 경우 결과를 같은 조건의 비교로 기록하지 않는다.

터미널 A에서 다음을 실행한다. `request_batch` 함수는 9.4에서 정의한 것을 사용한다. 이 측정이 끝나기 전에 터미널 B에서 Drain을 시작해야 한다.

```bash
kubectl --context kind-spot-lab -n default get pods -l app=spot-http -o wide \
  > .local/pods-before-drain-repro.txt
cat .local/pods-before-drain-repro.txt
request_batch > .local/http-during-drain-repro.txt 2>&1
cat .local/http-during-drain-repro.txt
```

터미널 B도 Bash에서 같은 디렉터리와 kubeconfig를 사용한다. A에서 측정을 시작한 뒤 약 5초 후 Cordon/Drain을 수행한다. Drain 자체도 노드를 스케줄 불가 상태로 만들지만, 여기서는 Cordon을 별도로 실행해 단계를 구분한다.

```bash
cd ~/infrastructure-engineering-lab/investigations/05-graceful-shutdown
export KUBECONFIG="$PWD/.local/kubeconfig"
sleep 5
kubectl --context kind-spot-lab cordon spot-lab-worker
kubectl --context kind-spot-lab drain spot-lab-worker \
  --ignore-daemonsets --timeout=120s > .local/drain-repro.txt 2>&1
cat .local/drain-repro.txt
kubectl --context kind-spot-lab -n default rollout status deployment/spot-http --timeout=120s
kubectl --context kind-spot-lab -n default get pods -l app=spot-http -o wide \
  > .local/pods-after-drain-repro.txt
cat .local/pods-after-drain-repro.txt
```

이 Manifest는 `emptyDir`를 사용하지 않으므로 `--delete-emptydir-data`를 붙이지 않았다. 다른 워크로드 때문에 Drain이 거부되면 실패 원인을 확인하고 중단한다.

확인할 항목은 다음과 같다.

- A의 결과에 순차 요청 20건이 있고, 각 행이 `HTTP=200`, `curl_exit=0`인지 확인한다. curl은 HTTP 503에서도 종료 코드 0을 반환할 수 있으므로 두 값을 함께 본다.
- Drain 로그에 기존 Pod의 퇴거가 기록됐는지 확인한다.
- 전후 목록에서 기존 Pod 이름이 사라지고, 다른 Worker에 새 이름의 Pod가 실행되는지 확인한다.
- 실제 요청·Drain 시점, 노드 배치가 예상과 다르면 그 조건도 함께 기록한다. 이번 확인만으로 정확한 복구 시간이나 무중단을 보장하지 않는다.

DaemonSet Pod는 `--ignore-daemonsets`로 제외한다. Drain 동작과 옵션은 [kubectl drain 공식 문서](https://kubernetes.io/docs/reference/kubectl/generated/kubectl_drain/)를 참고했다.

### 9.6 Uncordon 및 클라이언트 정리

요청 측정과 Pod 상태 확인을 마친 뒤, 터미널 B에서 노드를 다시 스케줄 가능한 상태로 바꾼다.

```bash
kubectl --context kind-spot-lab uncordon spot-lab-worker
kubectl --context kind-spot-lab get nodes
kubectl --context kind-spot-lab -n default delete pod step05-http-client
```

Uncordon은 새 Pod를 배치할 수 있게 할 뿐, 이미 다른 Worker에서 실행 중인 Pod를 자동으로 다시 분산하지는 않는다. 클러스터나 서버 Deployment를 삭제하는 명령은 이 절차에 포함하지 않았다.
