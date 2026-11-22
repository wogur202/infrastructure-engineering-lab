"""Render local JSON/YAML templates without calling Terraform, AWS or Kubernetes."""
import argparse
import ipaddress
import json
from pathlib import Path
import re
import sys

TEMPLATES = Path(__file__).resolve().parents[1] / "k8s"
IMAGE = re.compile(r"[0-9]{12}\.dkr\.ecr\.ap-northeast-2\.amazonaws\.com/aegis-api@sha256:[0-9a-f]{64}")


def render(value, variables):
    if isinstance(value, dict):
        return {key: render(item, variables) for key, item in value.items()}
    if isinstance(value, list):
        return [render(item, variables) for item in value]
    if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
        return variables[value[2:-1]]
    return value


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--outputs-json", type=Path, required=True)
    parser.add_argument("--blue-image", required=True)
    parser.add_argument("--green-image", required=True)
    parser.add_argument("--blue-version", required=True)
    parser.add_argument("--green-version", required=True)
    parser.add_argument("--green-failure", choices=("0", "1"), default="0")
    parser.add_argument("--allowed-cidr", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        for image in (args.blue_image, args.green_image):
            if not IMAGE.fullmatch(image):
                raise ValueError("expected Seoul aegis-api ECR image pinned by sha256 digest")
        for version in (args.blue_version, args.green_version):
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,127}", version):
                raise ValueError("invalid version identifier")
        cidr = ipaddress.ip_network(args.allowed_cidr, strict=True)
        if cidr.version != 4 or cidr.prefixlen != 32:
            raise ValueError("allowed-cidr must be an explicit IPv4 /32")
        outputs = json.loads(args.outputs_json.read_text())
        subnets = outputs["public_subnet_ids"]["value"]
        if not isinstance(subnets, list) or len(subnets) != 2 or any(
            not isinstance(item, str) or not re.fullmatch(r"subnet-(?:[0-9a-f]{8}|[0-9a-f]{17})", item)
            for item in subnets
        ) or len(set(subnets)) != 2:
            raise ValueError("expected two distinct public subnet IDs in Terraform output JSON")
        variables = {
            "BLUE_IMAGE": args.blue_image, "GREEN_IMAGE": args.green_image,
            "BLUE_VERSION": args.blue_version, "GREEN_VERSION": args.green_version,
            "BLUE_FAILURE": "0", "GREEN_FAILURE": args.green_failure,
            "PUBLIC_SUBNET_IDS": ",".join(subnets), "ALLOWED_CIDR": str(cidr),
        }
        rendered = {}
        for name in ("blue.yaml", "green.yaml", "ingress.yaml"):
            document = render(json.loads((TEMPLATES / name).read_text()), variables)
            content = json.dumps(document, indent=2) + "\n"
            if "${" in content:
                raise ValueError("unresolved template variable")
            rendered[name] = content
        # Refuse existing directories so previous renders/evidence cannot be overwritten.
        args.output_dir.mkdir(parents=True, exist_ok=False)
        for name, content in rendered.items():
            (args.output_dir / name).write_text(content)
        print("Rendered three local manifests; no external commands executed.")
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
