"""Run an isolated local container; remove only the container created here."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    args = parser.parse_args()
    container = None
    try:
        container = subprocess.check_output([
            "docker", "run", "--detach", "--rm", "--platform", "linux/amd64",
            "--publish", "127.0.0.1::8080", "--env", "APP_VERSION=container-smoke",
            "--env", "APP_SLOT=green", "--env", "INJECT_API_FAILURE=0", args.image,
        ], text=True).strip()
        ports = json.loads(subprocess.check_output([
            "docker", "inspect", "--format", "{{json .NetworkSettings.Ports}}", container,
        ], text=True))
        port = ports["8080/tcp"][0]["HostPort"]
        base = f"http://127.0.0.1:{port}"
        opener = build_opener(ProxyHandler({}))
        for _ in range(30):
            try:
                with opener.open(base + "/healthz", timeout=1) as response:
                    if response.status == 200:
                        break
            except (URLError, OSError):
                pass
            time.sleep(0.5)
        else:
            raise RuntimeError("container startup timeout")
        subprocess.run([
            sys.executable, str(Path(__file__).with_name("smoke.py")), base,
            "--expected-version", "container-smoke", "--expected-slot", "green",
        ], check=True, timeout=15)
        print("PASS linux/amd64 container smoke")
        return 0
    except (subprocess.SubprocessError, OSError, ValueError, KeyError, RuntimeError) as error:
        print(f"FAIL container smoke: {error}", file=sys.stderr)
        return 1
    finally:
        if container:
            subprocess.run(["docker", "rm", "--force", container], stdout=subprocess.DEVNULL, check=False)


if __name__ == "__main__":
    sys.exit(main())
