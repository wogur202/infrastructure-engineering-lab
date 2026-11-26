# 로컬에서 재현하기

[05 README](README.md)의 실험을 저장된 코드로 다시 해 보기 위한 절차입니다.

아래는 저장된 코드로 다시 실험하기 위한 명령이다. 문서를 정리할 때는 실행 중인 환경을 바꾸지 않기 위해 클러스터 생성·이미지 빌드·배포·Drain을 다시 실행하지 않았다. 명령어의 셸 구문과 코드·설정의 일치 여부를 확인했으며, `spot-http.yaml`은 Kubernetes v1.34.0 공식 OpenAPI 스키마로 정적 검증했다. 실제 클러스터 버전의 API 서버 검증과 전체 재실행 검증은 하지 않았다. 기존 `evidence/`는 원본 기록으로 두고, 재현 결과는 Git에서 제외한 `.local/`에 저장한다.

### 준비와 클러스터 생성

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

### 이미지 빌드와 kind 로드

현재 [Dockerfile](app/Dockerfile)은 빌드 컨텍스트의 `server.py`만 복사하므로, 컨텍스트는 저장소 루트가 아닌 `./app`이어야 한다. 이 이미지는 v2 서버를 실행한다.

```bash
docker build -t spot-http:v2 ./app
kind load docker-image spot-http:v2 --name spot-lab
```

Manifest의 이미지 이름도 `spot-http:v2`이며, `imagePullPolicy: IfNotPresent`로 로드한 이미지를 사용한다. 같은 태그로 코드를 바꾸어 다시 빌드하는 경우에는 이미지 재로드와 기존 Pod 교체가 추가로 필요하다. 아래 절차는 새 실험 환경에 최초 배포하는 경우를 기준으로 한다.

### 단일 요청 중 SIGTERM 비교

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

### Manifest 적용과 정상 상태 HTTP 테스트

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

### Cordon / Drain 중 순차 HTTP 요청

Drain 전에 서버 Pod가 두 Worker에 하나씩 있는지 확인한다. `ScheduleAnyway`는 분산을 보장하지 않으므로, 두 Pod가 모두 같은 Worker에 있다면 기존 실험과 동일한 배치 조건이 아니다. 이 경우 결과를 같은 조건의 비교로 기록하지 않는다.

터미널 A에서 다음을 실행한다. `request_batch` 함수는 위 'Manifest 적용과 정상 상태 HTTP 테스트'에서 정의한 것을 사용한다. 이 측정이 끝나기 전에 터미널 B에서 Drain을 시작해야 한다.

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

### Uncordon과 클라이언트 정리

요청 측정과 Pod 상태 확인을 마친 뒤, 터미널 B에서 노드를 다시 스케줄 가능한 상태로 바꾼다.

```bash
kubectl --context kind-spot-lab uncordon spot-lab-worker
kubectl --context kind-spot-lab get nodes
kubectl --context kind-spot-lab -n default delete pod step05-http-client
```

Uncordon은 새 Pod를 배치할 수 있게 할 뿐, 이미 다른 Worker에서 실행 중인 Pod를 자동으로 다시 분산하지는 않는다. 클러스터나 서버 Deployment를 삭제하는 명령은 이 절차에 포함하지 않았다.
