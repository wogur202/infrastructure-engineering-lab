import os
import signal
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def log(message):
    now = datetime.now(timezone.utc).isoformat()
    print(f"{now} {message}", flush=True)


def on_sigterm(signum, frame):
    log("SIGTERM received")
    os._exit(0)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        log("request started")
        time.sleep(3)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK\n")
        log("request completed")


signal.signal(signal.SIGTERM, on_sigterm)

server = ThreadingHTTPServer(("0.0.0.0", 8080), Handler)
log("HTTP server started on port 8080")
server.serve_forever()
