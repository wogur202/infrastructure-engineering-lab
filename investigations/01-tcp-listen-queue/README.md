# Investigation 01 — TCP Listen Queue Saturation

> Why does increasing the TCP listen backlog not always resolve HTTP timeouts?

## 1. Question

When concurrent connections exceed the rate at which an application accepts them, requests may experience increased latency or timeouts.

Can increasing the TCP listen backlog resolve this problem, or must the application bottleneck also be addressed?

## 2. Environment

- Ubuntu Linux VM (Multipass, ARM64)
- Python TCP socket server
- HTTP endpoint: TCP port 8080
- Client: curl on macOS
- Workload: 30 concurrent HTTP requests
- Per-request timeout: 2 seconds

The server is intentionally single-threaded. The --accept-delay parameter introduces artificial delay before accept() to simulate slow connection acceptance.

This is a controlled fault-injection experiment, not a production incident.

## 3. Reproduction

The server creates a listening socket using:

- socket()
- bind()
- listen(backlog)
- accept()

A configurable delay is inserted before each accept() call.

With a small backlog and slow acceptance, concurrent requests can overwhelm the effective listening capacity.

Kernel observations were collected using:

- ss -lntp
- /proc/net/netstat (ListenOverflows, ListenDrops)

HTTP outcomes were measured using curl.

## 4. Experimental Results

| Trial | Backlog | Accept delay | HTTP 200 | HTTP failures | ListenOverflows delta |
|---|---:|---:|---:|---:|---:|
| 2 | 5 | 0.2 s | 8/30 | 22/30 | +92 |
| 3 | 128 | 0.2 s | 8/30 | 22/30 | 0 |
| 4 | 128 | 0 s | 30/30 | 0/30 | Not conclusively validated |

All three trials used 30 concurrent requests and a 2-second client timeout.

Trial 2 and Trial 3 HTTP counts are preserved in experiment notes and conversation records, but their original client-side output files are unavailable.

Trial 4 HTTP output is preserved in evidence/trial4/http-results.txt. All 30 requests returned HTTP 200, with a maximum observed response time of approximately 21.9 ms.

Trial 4 kernel counters were recorded as zero before and during a later check. However, the server was no longer listening at the later check, and the measurement continuity was not established. Therefore, its overflow delta is not claimed as conclusive.

## 5. Investigation

### Trial 2 — Small backlog, slow acceptance

With backlog=5 and accept-delay=0.2, the workload produced both HTTP timeouts and increased ListenOverflows/ListenDrops counters.

The small pending-connection queue could not absorb the arrival burst while acceptance was deliberately slowed.

### Trial 3 — Larger backlog, same processing delay

Increasing backlog from 5 to 128 eliminated the observed overflow increase in this trial.

However, HTTP success remained at 8/30 under the same timeout constraint.

This showed that reducing queue overflow did not, by itself, resolve application-visible latency.

### Trial 4 — Remove artificial acceptance delay

With backlog=128 and accept-delay=0, all 30 requests returned HTTP 200 within the timeout.

The experimental improvement targeted the intentionally introduced application-side delay rather than increasing queue capacity again.

## 6. Engineering Interpretation

The listen backlog controls the capacity of the pending connection queue, subject to kernel behavior and limits. It does not determine how quickly an application calls accept() or handles requests.

Increasing backlog may absorb short connection bursts, but sustained application-side slowness can still cause unacceptable request latency.

Also, ListenOverflows and ListenDrops count kernel events; they should not be interpreted as a one-to-one count of failed HTTP requests.

The observations support an application-acceptance bottleneck in this controlled workload. They do not establish that the same configuration would be optimal for every production service.

## 7. Evidence

- evidence/baseline-ss.txt
- evidence/baseline-resources.txt
- evidence/baseline-listen-counters.txt
- evidence/trial2/before.txt
- evidence/trial2/after.txt
- evidence/trial3/before.txt
- evidence/trial3/after.txt
- evidence/trial4/before.txt
- evidence/trial4/after.txt
- evidence/trial4/http-results.txt

Reproduction implementation:
- server.py
- scripts/check-state.sh

## 8. Takeaway

A larger queue can reduce overflow without fixing request latency.

The correct response to connection pressure depends on identifying whether the limiting factor is queue capacity, connection acceptance, application processing, or another part of the request path.

In this experiment, removing artificial acceptance delay produced a much larger improvement in HTTP outcomes than increasing the backlog alone.

## 9. Limitations and Follow-up

- Only one workload size was evaluated in the final comparison.
- Each configuration requires additional repeated runs for statistical confidence.
- Trial 2 and Trial 3 client-side raw logs are unavailable.
- Trial 4 post-load server state was not captured continuously.
- No production-level throughput, CPU utilization under load, or latency distribution was established.

Future validation could use repeated trials, different concurrency levels, and improved capture of client and kernel metrics.

## 10. Results Visualization

![HTTP Outcomes](evidence/http-outcomes.png)

The chart compares HTTP success and failure counts across Trials 2–4. Trial 2 and 3 counts are reconstructed from experiment notes; Trial 4 is supported by the saved client log.
