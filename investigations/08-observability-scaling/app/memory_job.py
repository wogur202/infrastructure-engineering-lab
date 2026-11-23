"""Finite allocation; only execute the large mode in the isolated OOM Job."""
import argparse
import json
import time


def allocate(total_mib, step_mib, hold_seconds, max_seconds, safe=False):
    cap = 8 if safe else 256
    if not 1 <= total_mib <= cap or not 1 <= step_mib <= cap:
        raise ValueError("allocation outside permitted bounds")
    if not 0 <= hold_seconds <= 10 or not 0.01 <= max_seconds <= 55:
        raise ValueError("invalid duration")
    start = time.monotonic()
    chunks, allocated = [], 0
    while allocated < total_mib:
        if time.monotonic() - start >= max_seconds:
            raise TimeoutError("allocation deadline exceeded")
        size = min(step_mib, total_mib - allocated) * 1024 * 1024
        chunk = bytearray(size)
        for offset in range(0, size, 4096):
            chunk[offset] = 1
        chunks.append(chunk)
        allocated += size // (1024 * 1024)
        print(json.dumps({"allocated_mib": allocated}), flush=True)
        time.sleep(0.02 if safe else 0.25)
    until = time.monotonic() + hold_seconds
    while time.monotonic() < until:
        if time.monotonic() - start >= max_seconds:
            raise TimeoutError("hold deadline exceeded")
        time.sleep(min(0.05, max(0, until - time.monotonic())))
    if time.monotonic() - start >= max_seconds:
        raise TimeoutError("job deadline exceeded")
    return allocated


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mib", type=int, required=True)
    parser.add_argument("--step-mib", type=int, default=16)
    parser.add_argument("--hold-seconds", type=float, default=10)
    parser.add_argument("--max-seconds", type=float, default=50)
    parser.add_argument("--safe", action="store_true")
    args = parser.parse_args()
    result = allocate(args.mib, args.step_mib, args.hold_seconds,
                      args.max_seconds, args.safe)
    print(json.dumps({"completed_mib": result}), flush=True)
