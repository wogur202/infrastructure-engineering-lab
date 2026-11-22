"""GET health, readiness and business responses; failures return a nonzero code."""
import argparse
import json
import sys
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("base_url")
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--expected-slot", required=True)
    parser.add_argument("--timeout", type=float, default=3)
    args = parser.parse_args()
    # Do not route local smoke requests through an environment HTTP proxy.
    opener = build_opener(ProxyHandler({}))
    try:
        for path in ("/healthz", "/readyz", "/api/info"):
            with opener.open(args.base_url.rstrip("/") + path, timeout=args.timeout) as response:
                if response.status != 200:
                    raise ValueError(f"{path}: HTTP {response.status}")
                if response.headers.get_content_type() != "application/json":
                    raise ValueError(f"{path}: expected JSON content type")
                body = json.load(response)
            if path == "/api/info":
                if not isinstance(body, dict) or (
                    body.get("service") != "aegis-api"
                    or body.get("version") != args.expected_version
                    or body.get("slot") != args.expected_slot
                    or not isinstance(body.get("hostname"), str)
                    or not body["hostname"]
                ):
                    raise ValueError("/api/info: unexpected service/version/slot/hostname")
            elif body != {"status": "ok"}:
                raise ValueError(f"{path}: unexpected health response")
            print(f"PASS GET {path}")
    except (URLError, OSError, ValueError, TypeError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
