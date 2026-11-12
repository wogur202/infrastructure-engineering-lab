# 메모리는 남아 있는데, 왜 프로세스가 죽었을까?

**Linux OOM Killer · cgroup v2 · systemd**  
Ubuntu 24.04 / Multipass / 2 vCPU / RAM 약 1.9GiB / Swap 없음

> 시스템의 여유 메모리만으로 OOM을 판단할 수 있을까?  
> 이번 실험에서는 프로세스별 메모리 한도를 따로 설정한 뒤, 실제 종료 기록과 메모리 사용량을 비교했다.

## 여유 메모리 1.7GiB, 그런데 OOM

장애를 만들기 전 VM의 사용 가능 메모리는 약 **1.7GiB**였다. 이 상태에서 Python 프로그램이 메모리 128MiB를 조금씩 확보하도록 만들고, 프로그램이 속한 systemd 서비스에 **64MiB 제한**을 걸었다.

결과는 다음과 같았다.

- 할당 로그는 **48MiB**까지 출력됐다.
- 이후 서비스가 `oom-kill`로 끝났다.
- systemd가 보고한 메모리 피크는 **64.0M**이었다.
- 실험 후에도 VM은 정상적으로 응답했고, 사용 가능한 메모리는 약 **1.7GiB**였다.

여기서 구별할 점은 **VM 전체 메모리 부족**과 **특정 cgroup의 한도 초과**가 서로 다른 상황이라는 것이다.

## 종료 원인을 추측하지 않고 확인하기

systemd 로그는 프로세스가 OOM Killer에 의해 종료됐음을 보여줬다.

```text
A process of this unit has been killed by the OOM killer.
Main process exited, code=killed, status=9/KILL
Failed with result 'oom-kill'
```

커널 기록에는 원인이 좀 더 구체적으로 남아 있었다.

```text
oom-kill:constraint=CONSTRAINT_MEMCG,...,oom_memcg=/system.slice/oom-lab.service,...,task=python3,pid=27212
Memory cgroup out of memory: Killed process 27212 (python3)
```

`CONSTRAINT_MEMCG`는 시스템 전체 메모리 고갈이 아니라 **메모리 cgroup 제약에서 발생한 OOM**임을 가리킨다. 같은 시점의 `/proc/vmstat`에서 `oom_kill` 카운터도 **0 → 1**로 변했다.

숫자 하나만으로 결론을 내리기보다는, 종료 기록·커널의 제약 정보·VM 상태를 함께 확인했다.

## 한도를 높이면 같은 작업은 통과할까?

실험 프로그램과 목표 할당량(**128MiB**)은 그대로 두고, `MemoryMax`만 **64MiB → 256MiB**로 변경했다.

| 확인한 것 | 64MiB 제한 | 256MiB 제한 |
|---|---|---|
| 목표 할당량 | 128MiB | 128MiB |
| 프로그램 출력 | 48MiB까지 출력 후 종료 | 128MiB 할당 완료 |
| 종료 / 이벤트 | `oom-kill` | 검증 시 `oom_kill=0` |
| 관찰된 피크 | systemd 요약 `64.0M` | cgroup `memory.peak` **133.5MiB** |

256MiB 조건에서 프로그램은 할당을 완료하고 메모리를 유지했다. 처음 실행은 4초 제한을 둔 테스트여서 `status=124`로 끝났는데, **이 값은 OOM이 아니라 `timeout`에 의한 종료**다.

한 가지 걸리는 수치도 있었다. 그 첫 실행의 systemd 요약에는 `Memory peak: 2.9M`이 표시됐다. Python이 128MiB를 확보했다는 출력과 맞지 않는 값이다. 이 수치를 곧바로 사용량으로 채택하지 않고, 동일한 256MiB 제한으로 서비스를 다시 띄워 cgroup 파일을 직접 읽었다.

```text
memory.current  139808768 bytes   (약 133.3MiB)
memory.peak     140034048 bytes   (약 133.5MiB)
memory.max      268435456 bytes   (256MiB)
memory.events   oom 0 / oom_kill 0
```

이 재측정으로 **실행 중 실제 점유량이 약 133MiB였다**는 점을 확인했다. 다만 이전 `2.9M` 요약이 왜 나왔는지는 아직 밝혀내지 못했다. 원인이 확인되지 않은 값은 최종 판단의 근거로 사용하지 않았다.

## 이번 결과를 어떻게 해석했나

이번에 재현한 것은 실제 운영 장애가 아니라 **의도적으로 만든 메모리 제한 초과 상황**이다.

- VM에 여유 메모리가 있어도 개별 서비스의 메모리 제한으로 OOM이 발생할 수 있다.
- `oom-kill`만 확인하는 데서 멈추지 않고, 커널 로그의 `CONSTRAINT_MEMCG`로 종료 원인을 구분할 수 있었다.
- 256MiB에서는 이번 **단일 작업**이 완료됐지만, 그것이 운영 환경의 최적 제한값이라는 의미는 아니다.
- 메모리 제한을 정할 때는 실제 사용량, 순간 피크, 다른 부하에서의 변화까지 봐야 한다.

OOM을 마주쳤다면 우선 시스템 메모리 사용률뿐 아니라 **해당 프로세스의 cgroup 제한과 `memory.events`, 커널 종료 기록**을 확인할 것이다.

## 재현 코드와 증거

- [`memory_hog.py`](memory_hog.py) — 메모리를 단계적으로 할당한 테스트 프로그램
- [`evidence/baseline.txt`](evidence/baseline.txt) — 실험 전 VM 메모리, Swap, OOM 카운터
- [`evidence/oom-journal.txt`](evidence/oom-journal.txt) — systemd 종료 기록
- [`evidence/oom-kernel.txt`](evidence/oom-kernel.txt) — `CONSTRAINT_MEMCG`, 종료된 PID
- [`evidence/after-oom.txt`](evidence/after-oom.txt) — OOM 후 VM 정상 응답과 카운터
- [`evidence/improved-memory.txt`](evidence/improved-memory.txt) — 256MiB 조건의 `memory.current`, `memory.peak`, `memory.events`

### 재현 시 사용한 핵심 설정

```bash
# cgroup 한도 64MiB에서 OOM 재현
sudo systemd-run --unit=oom-lab --collect --wait --pipe -p MemoryMax=64M \
  /usr/bin/python3 -u memory_hog.py --mb 128 --step 16 --interval 0.2

# 제한 256MiB로 변경 후 동일 할당 시도
sudo systemd-run --unit=oom-lab-verify --collect -p MemoryMax=256M \
  /usr/bin/python3 -u memory_hog.py --mb 128 --step 16 --interval 0.2
```

> `oom-lab-verify`는 측정 후 `sudo systemctl stop oom-lab-verify.service`로 종료했다. 실행 경로는 프로젝트 파일이 있는 디렉터리 기준이며, 실제 실행에서는 스크립트의 절대 경로를 사용했다.

**범위와 한계:** 단일 할당 패턴에서 확인한 결과이며, 반복 측정이나 여러 프로세스의 간섭, 서비스 지연 영향은 평가하지 않았다. 실제 운영 시스템의 안전한 `MemoryMax`를 이 결과만으로 결정할 수는 없다.
