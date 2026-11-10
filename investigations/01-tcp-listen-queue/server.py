import argparse
import socket
import time

parser = argparse.ArgumentParser()
parser.add_argument("--host", default="0.0.0.0")
parser.add_argument("--port", type=int, default=8080)
parser.add_argument("--backlog", type=int, default=128)
parser.add_argument("--accept-delay", type=float, default=0.0)

args = parser.parse_args()

server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

server.bind((args.host, args.port))
server.listen(args.backlog)

print(
    f"Listening on {args.host}:{args.port} "
    f"(backlog={args.backlog}, accept_delay={args.accept_delay})"
)

while True:
    if args.accept_delay > 0:
        time.sleep(args.accept_delay)

    conn, addr = server.accept()

    try:
        conn.recv(1024)

        response = (
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Length: 2\r\n"
            b"Connection: close\r\n"
            b"\r\n"
            b"OK"
        )

        conn.sendall(response)

    finally:
        conn.close()
