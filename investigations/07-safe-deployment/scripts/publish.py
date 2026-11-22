"""Manually gated ECR publishing; default plan mode executes no external commands."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

REGION = "ap-northeast-2"


def describe(repository, tag):
    result = subprocess.run([
        "aws", "ecr", "describe-images", "--region", REGION,
        "--repository-name", repository, "--image-ids", f"imageTag={tag}",
        "--output", "json", "--no-cli-pager",
    ], text=True, capture_output=True, timeout=60)
    if result.returncode:
        if "(ImageNotFoundException)" in result.stderr:
            return None
        raise RuntimeError("ECR lookup failed; check credentials, repository and DescribeImages permission")
    details = json.loads(result.stdout)["imageDetails"]
    if len(details) != 1 or not re.fullmatch(r"sha256:[0-9a-f]{64}", details[0]["imageDigest"]):
        raise ValueError("unexpected ECR digest response")
    return details[0]["imageDigest"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--local-image", required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        if not re.fullmatch(r"[0-9]{12}\.dkr\.ecr\.ap-northeast-2\.amazonaws\.com", args.registry):
            raise ValueError("expected Seoul private ECR registry")
        if not re.fullmatch(r"[0-9a-f]{40}", args.commit):
            raise ValueError("expected full commit SHA")
        tag = f"git-{args.commit}"
        if not args.execute:
            print("PLAN only: lookup immutable commit tag; reuse existing digest or push tested image; no AWS calls")
            return 0
        digest = describe("aegis-api", tag)
        # Keep temporary registry credentials outside the user's Docker config.
        with tempfile.TemporaryDirectory(prefix="aegis-ecr-") as directory:
            env = dict(os.environ, DOCKER_CONFIG=directory)
            password = subprocess.check_output([
                "aws", "ecr", "get-login-password", "--region", REGION,
            ], timeout=60)
            subprocess.run(["docker", "login", "--username", "AWS", "--password-stdin", args.registry],
                           input=password, env=env, check=True, timeout=60)
            if digest is None:
                remote = f"{args.registry}/aegis-api:{tag}"
                subprocess.run(["docker", "tag", args.local_image, remote], check=True, env=env)
                result = subprocess.run(["docker", "push", remote], env=env, timeout=600)
                if result.returncode:
                    # A concurrent immutable-tag push is acceptable only when a digest now exists.
                    digest = describe("aegis-api", tag)
                    if digest is None:
                        raise RuntimeError("ECR push failed and commit tag is absent")
                else:
                    digest = describe("aegis-api", tag)
            if digest is None:
                raise RuntimeError("pushed digest unavailable")
            image = f"{args.registry}/aegis-api@{digest}"
            # On reruns, test the existing registry artifact, not a different local rebuild.
            subprocess.run(["docker", "pull", "--platform", "linux/amd64", image],
                           env=env, check=True, timeout=300)
            subprocess.run([sys.executable, str(Path(__file__).with_name("container_smoke.py")),
                            "--image", image], env=env, check=True, timeout=60)
        print(f"Published or reused immutable image: {image}")
        if os.getenv("GITHUB_OUTPUT"):
            with Path(os.environ["GITHUB_OUTPUT"]).open("a") as output:
                output.write(f"image={image}\nversion={args.commit}\n")
        return 0
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"FAIL publish: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
