# 대기열을 늘렸는데도 HTTP 타임아웃은 그대로였다

**TCP Listen Queue · Linux · Python socket**  
Ubuntu 24.04 / Multipass (ARM64) · Python 단일 스레드 서버 · macOS `curl`

동시에 들어오는 연결을 서버가 제때 받아들이지 못하면 어떤 현상이 생길까? 처음에는 Listen Queue의 크기를 늘리면 실패도 줄어들 것이라고 생각하기 쉽다. 이번 실험에서는 `backlog`와 연결 수락 지연을 각각 바꿔 보면서, **큐 포화와 HTTP 타임아웃이 같은 문제인지** 확인했다.

이 환경은 실제 운영 장애가 아니라, `accept()` 앞에 의도적으로 지연을 넣은 재현용 서버다.

## 같은 30개 요청인데, 결과가 달랐다

세 조건 모두 **동시 요청 30개**, **요청당 타임아웃 2초**로 테스트했다.

| 조건 | `backlog` | `accept-delay` | HTTP 200 | HTTP 응답 없이 종료 | `ListenOverflows` 증가 |
|:--|--:|--:|--:|--:|--:|
| Trial 2 · 큐가 작고 수락이 느림 | 5 | 0.2초 | 8 | 22 | +92 |
| Trial 3 · 큐만 확장 | 128 | 0.2초 | 8 | 22 | 0 |
| Trial 4 · 인위적 수락 지연 제거 | 128 | 0초 | **30** | **0** | 측정 연속성 미확보 |

![30개 동시 요청의 HTTP 결과 비교](evidence/http-outcomes.png)

눈에 띄는 건 Trial 2와 3이다. `backlog`를 5에서 128로 키우자 커널의 Listen Overflow 증가량은 92에서 0으로 바뀌었다. **하지만 2초 안에 HTTP 응답을 받지 못한 요청은 여전히 22개였다.**

대기열이 버틸 수 있는 연결 수를 늘려도, 애플리케이션이 연결을 받아들이는 속도가 같으면 기다리는 시간이 길어질 수 있다는 뜻이다.

## 서버에서 실제로 지연이 생기는 지점

실험용 서버는 한 번에 하나씩 연결을 처리하며, 다음처럼 `accept()` 호출 전에 멈추도록 만들었다.

```python
while True:
    if args.accept_delay > 0:
        time.sleep(args.accept_delay)
    conn, addr = server.accept()
```

여기서 `--accept-delay 0.2`는 **연결 하나를 받아들이기 전 매번 0.2초 쉬도록 만든 인위적인 장애 조건**이다. 실제 서비스에서 발견된 결함이나 성능 최적화 사례로 소개하려는 것은 아니다.

이때 `backlog`는 수락을 기다리는 연결의 대기 공간에 영향을 주지만, 위 `sleep()`을 없애거나 서버의 처리 속도를 높이지는 않는다.

Trial 4에서는 `backlog=128`을 유지한 채 지연만 0으로 바꿨다. 저장된 클라이언트 로그에서 **30개 모두 HTTP 200**을 받았고, 최대 응답 시간은 **약 21.9ms**였다.

## 커널 카운터와 HTTP 실패 건수는 다르게 읽어야 한다

이번에 함께 관찰한 것은 `ss`의 Listen 소켓 상태와 `/proc/net/netstat`의 `ListenOverflows`, `ListenDrops`다.

- `ListenOverflows` 증가: 대기 중인 연결을 처리하는 과정에서 커널이 큐 포화 관련 이벤트를 기록했다는 근거
- HTTP 200 / 타임아웃: **클라이언트가 정해진 시간 안에 실제 응답을 받았는지**를 보여주는 결과

두 숫자는 일대일로 대응하지 않는다. 따라서 Overflow가 92 증가했다고 HTTP 요청 92개가 실패했다고 해석하면 안 된다.

Trial 3에서는 Overflow가 증가하지 않았지만 클라이언트 타임아웃은 계속됐다. **커널의 큐 지표만 보고 서비스의 응답 상태를 판단하면 놓치는 부분이 있다는 점**이 이번 비교에서 가장 중요했다.

## 다시 재현하려면

서버는 Ubuntu VM에서 실행하고, 부하는 **Mac 터미널**에서 발생시킨다. 서버를 실행한 터미널은 열어 둔다.

Ubuntu VM에서 서버 실행 (조건별로 값을 변경):

```bash
python3 -u server.py --backlog 5 --accept-delay 0.2
# 다른 조건: --backlog 128 --accept-delay 0.2
# 개선 조건: --backlog 128 --accept-delay 0
```

Mac에서 동시 요청 실행 (VM 주소는 자신의 환경에 맞게 변경):

```bash
seq 1 30 | xargs -P30 -I{} curl --max-time 2 -sS -o /dev/null \
  -w '{} HTTP %{http_code} %{time_total}s\n' http://192.168.252.2:8080/
```

부하 전후에는 VM에서 `scripts/check-state.sh`를 실행해 서버 Listen 상태와 커널 카운터를 기록한다. 이전 Trial의 누적 카운터와 섞이지 않도록 **각 Trial의 전후 차이**를 사용해야 한다.

## 기록의 범위와 남은 숙제

이 보고서는 실측된 결과와 그 한계를 구분한다.

- Trial 2·3의 HTTP 성공/실패 건수는 당시 실험 기록에 남아 있지만, **클라이언트 원본 출력 파일은 보존되지 않았다.** 커널 측정 전후 파일은 남아 있다.
- Trial 4의 HTTP 출력 원본은 보존했다. 다만 이후 서버가 종료된 상태에서 커널 카운터를 확인했으므로, **Trial 4의 Overflow 증가량을 확정하지 않는다.**
- 단일 스레드의 인위적인 지연 서버, 동시 요청 30개, 타임아웃 2초에서 얻은 결과다. 반복 측정이나 실제 서비스의 처리량·지연 분포를 검증한 것은 아니다.

이번 실험에서 얻은 결론은 ‘Backlog는 늘릴 필요가 없다’가 아니다. **큐 포화가 원인인지, 연결 수락이나 애플리케이션 처리 속도가 원인인지 먼저 나눠서 관측해야 한다**는 것이다. 대기열을 키우면 포화 이벤트는 줄어들 수 있지만, 그것만으로 응답 지연이 해결됐다고 볼 수는 없다.

## 코드와 측정 자료

- [`server.py`](server.py) — 인위적인 연결 수락 지연을 넣은 HTTP 서버
- [`scripts/check-state.sh`](scripts/check-state.sh) — Listen 소켓 및 커널 카운터 조회
- [`evidence/comparison.csv`](evidence/comparison.csv) — Trial별 비교 데이터
- [`evidence/http-outcomes.png`](evidence/http-outcomes.png) — HTTP 결과 시각화
- `evidence/baseline-*` — 정상 상태 측정
- `evidence/trial2/{before,after}.txt` — 작은 Backlog 조건의 커널 기록
- `evidence/trial3/{before,after}.txt` — Backlog 확장 조건의 커널 기록
- `evidence/trial4/http-results.txt` — 개선 조건의 클라이언트 원본
- `evidence/trial4/{before,after}.txt` — 개선 조건의 커널 기록(측정 시점 주의)
