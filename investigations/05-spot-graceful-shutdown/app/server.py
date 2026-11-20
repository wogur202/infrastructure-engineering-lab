import signal
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

stopping = threading.Event()
active = 0
condition = threading.Condition()


def log(message):
    now = datetime.now(timezone.utc).isoformat()
    print(f"{now} {message}", flush=True)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        global active

        with condition:
            if stopping.is_set():
                self.send_error(503, "Server shutting down")
                return
            active += 1

        try:
            log("request started")
            time.sleep(3)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK\n")
            log("request completed")
        finally:
            with condition:
                active -= 1
                condition.notify_all()


server = ThreadingHTTPServer(("0.0.0.0", 8080), Handler)


def on_sigterm(signum, frame):
    log("SIGTERM received")
    stopping.set()
    threading.Thread(target=server.shutdown, daemon=True).start()


signal.signal(signal.SIGTERM, on_sigterm)

log("HTTP server started on port 8080")
server.serve_forever()

with condition:
    condition.wait_for(lambda: active == 0, timeout=10)

log("graceful shutdown completed")
server.server_close()
