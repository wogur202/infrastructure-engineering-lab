import json
import os
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

VERSION = "1.0.0"


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/healthz", "/readyz"):
            status = 200
            body = {"status": "ok"}
        elif self.path == "/api/info":
            status = 200
            body = {
                "service": "aegis-api",
                "version": VERSION,
                "hostname": socket.gethostname()
            }
        else:
            status = 404
            body = {"error": "not found"}

        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


server = ThreadingHTTPServer(
    ("0.0.0.0", int(os.getenv("PORT", "8080"))),
    Handler
)
server.serve_forever()
