"""Bounded, fixed-work CPU endpoint for an isolated experiment, not production."""
import json
import os
import signal
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

MAX_ITERATIONS = 2_000_000


def cpu_work(iterations, deadline):
    checksum = 0
    for i in range(iterations):
        checksum = (checksum * 1664525 + i + 1013904223) & 0xFFFFFFFF
        if i % 1024 == 0 and time.monotonic() >= deadline:
            raise TimeoutError("CPU work deadline exceeded")
    if time.monotonic() >= deadline:
        raise TimeoutError("CPU work deadline exceeded")
    return checksum


class BoundedServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 32

    def __init__(self, address, handler, concurrency):
        self.slots = threading.BoundedSemaphore(concurrency)
        super().__init__(address, handler)

    def get_request(self):
        conn, addr = super().get_request()
        conn.settimeout(5)
        return conn, addr

    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False):
            try:
                request.sendall(b"HTTP/1.0 503 Service Unavailable\r\n"
                                b"Content-Length: 0\r\nConnection: close\r\n\r\n")
            except OSError:
                pass
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.slots.release()


def create_server(host="127.0.0.1", port=8080, version="local", concurrency=16,
                  work_timeout=3.0, default_iterations=50_000):
    if not 1 <= concurrency <= 64 or not 0.01 <= work_timeout <= 30:
        raise ValueError("invalid concurrency or work_timeout")
    if not 1 <= default_iterations <= MAX_ITERATIONS:
        raise ValueError("invalid default_iterations")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass  # Per-request logging would contaminate the CPU experiment.

        def do_GET(self):
            path = urlsplit(self.path)
            status, body = 200, {"status": "ok"}
            if path.path in ("/healthz", "/readyz") and not path.query:
                pass
            elif path.path == "/api/info" and not path.query:
                body = {"service": "aegis-step08-api", "version": version,
                        "hostname": socket.gethostname(), "slot": "step08"}
            elif path.path == "/api/cpu-load":
                try:
                    if len(path.query) > 128:
                        raise ValueError("query too long")
                    query = parse_qs(path.query, keep_blank_values=True,
                                     strict_parsing=True, max_num_fields=2)
                    if set(query) - {"iterations"}:
                        raise ValueError("unknown query parameter")
                    values = query.get("iterations", [str(default_iterations)])
                    if len(values) != 1 or not values[0].isascii() or not values[0].isdigit():
                        raise ValueError("iterations must be one positive integer")
                    iterations = int(values[0])
                    if not 1 <= iterations <= MAX_ITERATIONS:
                        raise ValueError("iterations out of range")
                    checksum = cpu_work(iterations, time.monotonic() + work_timeout)
                    body = {"iterations": iterations, "checksum": checksum,
                            "version": version, "hostname": socket.gethostname()}
                except ValueError as exc:
                    status, body = 400, {"error": str(exc)}
                except TimeoutError as exc:
                    status, body = 503, {"error": str(exc)}
            else:
                status, body = 404, {"error": "not found"}
            payload = json.dumps(body).encode()
            try:
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(payload)
            except OSError:
                pass

    return BoundedServer((host, port), Handler, concurrency)


if __name__ == "__main__":
    server = create_server(os.getenv("BIND_ADDRESS", "0.0.0.0"),
                           int(os.getenv("PORT", "8080")),
                           os.getenv("APP_VERSION", "local"),
                           int(os.getenv("MAX_CONCURRENCY", "16")),
                           float(os.getenv("WORK_TIMEOUT_SECONDS", "3")),
                           int(os.getenv("WORK_ITERATIONS", "50000")))
    def stop(_signum, _frame):
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        server.serve_forever(poll_interval=0.1)
    finally:
        server.server_close()
