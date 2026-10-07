import json
import os
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse


SERVICES = (
    "mackllc-ui", "auth-service", "drug-catalog-service", "inventory-service",
    "supplier-service", "manufacturing-service", "notification-service",
    "qc-service", "api-gateway",
)
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
TAG = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}")


def command(args, **kwargs):
    result = subprocess.run(args, capture_output=True, text=True, **kwargs)
    if result.returncode:
        raise RuntimeError(f"{' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def command_json(args):
    return json.loads(command(args))


def aws_json(*args):
    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
    region_args = ["--region", region] if region else []
    return command_json(["aws", *args, *region_args, "--output", "json"])


def identity():
    account = aws_json("sts", "get-caller-identity")["Account"]
    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
    if not region:
        region = command(["aws", "configure", "get", "region"]).strip()
    if not re.fullmatch(r"[0-9]{12}", account) or not region:
        raise ValueError("A valid AWS account and region are required.")
    return account, region


def select_services(value):
    choices = {"A": SERVICES, "F": SERVICES[:1], "B": SERVICES[1:]}
    if value.upper() in choices:
        return choices[value.upper()]
    selected = tuple(value.split(","))
    if not selected or len(set(selected)) != len(selected) or any(s not in SERVICES for s in selected):
        raise ValueError("Select A, F, B, or comma-separated service names.")
    return selected


def image_inventory(repo):
    data = aws_json("ecr", "describe-images", "--repository-name", repo)
    images = []
    mapping = {}
    for item in data["imageDetails"]:
        digest = item["imageDigest"]
        tags = sorted(item.get("imageTags", []))
        images.append({"digest": digest, "tags": tags,
                       "pushed_at": item.get("imagePushedAt")})
        for tag in tags:
            if tag in mapping:
                raise ValueError(f"Duplicate tag in ECR inventory: {repo}:{tag}")
            mapping[tag] = digest
    return {"name": repo, "tags": sorted(mapping),
            "digests": sorted({item["digest"] for item in images}),
            "tag_to_digest": mapping, "images": sorted(images, key=lambda item: item["digest"])}


def build_backup(services, account, region):
    backup = {"schema_version": 1, "account_id": account, "region": region,
              "created_at": datetime.now(timezone.utc).isoformat(),
              "repositories": [image_inventory(service) for service in services]}
    validate_backup(backup, account, region)
    return backup


def validate_backup(data, account, region):
    if (not isinstance(data, dict) or data.get("schema_version") != 1
            or data.get("account_id") != account or data.get("region") != region):
        raise ValueError("Backup schema or AWS account/region does not match this deployment.")
    timestamp = data.get("created_at")
    if not isinstance(timestamp, str) or datetime.fromisoformat(timestamp).tzinfo is None:
        raise ValueError("Backup requires a timezone-aware creation timestamp.")
    repos = data.get("repositories")
    if not isinstance(repos, list) or not repos:
        raise ValueError("Backup contains no repositories.")
    names = set()
    for repo in repos:
        if not isinstance(repo, dict):
            raise ValueError("Invalid repository record.")
        name = repo.get("name")
        if name not in SERVICES or name in names:
            raise ValueError("Backup contains an unknown or duplicate repository.")
        names.add(name)
        mapping, tags, digests = repo.get("tag_to_digest"), repo.get("tags"), repo.get("digests")
        if (not isinstance(mapping, dict) or not isinstance(tags, list)
                or not isinstance(digests, list)
                or any(not isinstance(tag, str) or not TAG.fullmatch(tag) for tag in tags)
                or any(not isinstance(d, str) or not DIGEST.fullmatch(d) for d in digests)
                or len(tags) != len(set(tags)) or len(digests) != len(set(digests))
                or set(tags) != set(mapping)
                or any(not isinstance(d, str) or d not in digests for d in mapping.values())):
            raise ValueError(f"Invalid tag/digest mapping for {name}.")
    return data


def s3_location(uri):
    parsed = urlparse(uri)
    if (parsed.scheme != "s3" or not parsed.netloc or not parsed.path.lstrip("/")
            or parsed.query or parsed.fragment):
        raise ValueError("Use an explicit s3://bucket/key backup URI.")
    return parsed.netloc, parsed.path.lstrip("/")


def download_backup(uri, account, region):
    s3_location(uri)
    with tempfile.TemporaryDirectory() as directory:
        destination = Path(directory) / "tags.json"
        command(["aws", "s3", "cp", uri, str(destination), "--only-show-errors"])
        data = json.loads(destination.read_text())
    return validate_backup(data, account, region)


def upload_backup(uri, data, account, region):
    bucket, key = s3_location(uri)
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / "tags.json"
        source.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
        # Never overwrite a prior recovery point, even if two operators race.
        command(["aws", "s3api", "put-object", "--bucket", bucket, "--key", key,
                 "--body", str(source), "--content-type", "application/json",
                 "--if-none-match", "*"])
    downloaded = download_backup(uri, account, region)
    if downloaded != data:
        raise ValueError("S3 read-back does not match the tag backup; teardown is blocked.")
