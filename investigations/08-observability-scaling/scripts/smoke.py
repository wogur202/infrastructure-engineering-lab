import argparse
import json
import urllib.request


def smoke(base):
    for path in ("/healthz", "/readyz", "/api/info", "/api/cpu-load?iterations=100"):
        with urllib.request.urlopen(base.rstrip("/") + path, timeout=5) as response:
            assert response.status == 200, path
            body = json.load(response)
            if "cpu-load" in path:
                assert body["iterations"] == 100 and isinstance(body["checksum"], int)
    print("HTTP smoke: 4 endpoints PASS (not a performance benchmark)")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("base")
    smoke(p.parse_args().base)
