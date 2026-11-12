import argparse
import os
import time

parser = argparse.ArgumentParser()
parser.add_argument("--mb", type=int, default=256)
parser.add_argument("--step", type=int, default=32)
parser.add_argument("--interval", type=float, default=0.2)
args = parser.parse_args()

chunks = []
allocated = 0

print(f"PID={os.getpid()}", flush=True)

while allocated < args.mb:
    size = min(args.step, args.mb - allocated)
    chunks.append(bytearray(size * 1024 * 1024))
    allocated += size
    print(f"Allocated: {allocated} MiB", flush=True)
    time.sleep(args.interval)

print("Allocation complete. Holding memory...", flush=True)

while True:
    time.sleep(1)
