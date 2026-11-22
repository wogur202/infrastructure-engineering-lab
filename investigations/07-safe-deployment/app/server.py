import json
import os
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def create_server(host, port, version, slot, fail_api=False):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path in ("/healthz", "/readyz"):
                status, body = 200, {"status": "ok"}
            elif self.path == "/api/info":
                status = 503 if fail_api else 200
                body = {
                    "service": "aegis-api",
                    "version": version,
                    "slot": slot,
                    "hostname": socket.gethostname(),
                }
                if fail_api:
                    body["error"] = "injected API failure"
            else:
                status, body = 404, {"error": "not found"}
            payload = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    return ThreadingHTTPServer((host, port), Handler)


if __name__ == "__main__":
    server = create_server(
        os.getenv("BIND_ADDRESS", "0.0.0.0"),
        int(os.getenv("PORT", "8080")),
        os.getenv("APP_VERSION", "1.0.0"),
        os.getenv("APP_SLOT", "local"),
        os.getenv("INJECT_API_FAILURE", "0") == "1",
    )
    server.serve_forever()
