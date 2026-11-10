#!/usr/bin/env bash
set -euo pipefail

echo "=== Time ==="
date -Is

echo "=== HTTP Server ==="
ss -lntp | grep ':8080' || echo "NOT LISTENING"

echo "=== TCP Listen Counters ==="
awk '
/^TcpExt:/ {
  if (++n == 1) {
    for (i=2; i<=NF; i++) names[i]=$i
  } else {
    for (i=2; i<=NF; i++)
      if (names[i] == "ListenOverflows" ||
          names[i] == "ListenDrops")
        print names[i], $i
  }
}' /proc/net/netstat
