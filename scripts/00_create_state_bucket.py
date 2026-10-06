#!/usr/bin/env python3
"""Create the S3 bucket used by the Terraform remote state backend."""

import argparse
import os
import re
import shutil
import subprocess
import sys

REGION = "us-east-1"


def run_aws(args, profile=None, check=True):
    command = ["aws", "--region", REGION, *args]
    if profile:
        command.extend(["--profile", profile])
    result = subprocess.run(command, capture_output=True, text=True)
    if check and result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip()
        print(f"AWS CLI command failed: {' '.join(command)}", file=sys.stderr)
        if message:
            print(message, file=sys.stderr)
        raise SystemExit(result.returncode)
    return result


def valid_bucket_name(name):
    return (
        len(name) >= 3
        and len(name) <= 63
        and re.fullmatch(r"[a-z0-9][a-z0-9.-]*[a-z0-9]", name) is not None
        and ".." not in name
        and ".-" not in name
        and "-." not in name
        and not re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", name)
        and not name.startswith(("xn--", "sthree-", "amzn-s3-demo-"))
        and not name.endswith(("-s3alias", "--ol-s3", ".mrap", "--x-s3", "--table-s3"))
    )


def main():
    parser = argparse.ArgumentParser(
        description="Create a versioned, encrypted Terraform state bucket in us-east-1."
    )
    parser.add_argument(
        "--profile",
        default=os.environ.get("AWS_PROFILE"),
        help="AWS CLI profile (defaults to AWS_PROFILE or the AWS CLI default profile)",
    )
    parser.add_argument(
        "bucket",
        nargs="?",
        default=os.environ.get("STATE_BUCKET"),
        help="globally unique S3 bucket name (or set STATE_BUCKET)",
    )
    args = parser.parse_args()

    if shutil.which("aws") is None:
        print("AWS CLI v2 is required; install it and rerun this helper.", file=sys.stderr)
        return 1

    try:
        bucket = args.bucket or input("Globally unique S3 bucket name: ").strip()
    except EOFError:
        print("Provide a bucket name as an argument or run the helper interactively.", file=sys.stderr)
        return 1
    if not valid_bucket_name(bucket):
        parser.error(
            "bucket name must be 3-63 lowercase letters, numbers, dots, or hyphens; "
            "start and end with a letter or number, and contain no adjacent dots"
        )

    identity = run_aws(
        ["sts", "get-caller-identity", "--query", "Account", "--output", "text"],
        profile=args.profile,
    ).stdout.strip()
    if not re.fullmatch(r"\d{12}", identity):
        print(f"Could not determine a 12-digit AWS account ID: {identity}", file=sys.stderr)
        return 1

    print(f"Using AWS account {identity} in {REGION}.")
    print(f"Checking S3 bucket {bucket}...")
    head_args = [
        "s3api",
        "head-bucket",
        "--bucket",
        bucket,
        "--expected-bucket-owner",
        identity,
    ]
    existing = run_aws(head_args, profile=args.profile, check=False)
    if existing.returncode != 0:
        print(f"Creating S3 bucket {bucket}...")
        create_args = ["s3api", "create-bucket", "--bucket", bucket]
        created = run_aws(create_args, profile=args.profile, check=False)
        if created.returncode != 0:
            message = created.stderr.strip() or created.stdout.strip()
            print(
                f"Could not create bucket '{bucket}'. Choose a globally unique name "
                "or check that your AWS profile has S3 permissions.",
                file=sys.stderr,
            )
            if message:
                print(message, file=sys.stderr)
            return created.returncode

        existing = run_aws(head_args, profile=args.profile, check=False)
        if existing.returncode != 0:
            message = existing.stderr.strip() or existing.stdout.strip()
            print(
                f"Bucket '{bucket}' was created, but AWS could not confirm that "
                f"account {identity} owns it.",
                file=sys.stderr,
            )
            if message:
                print(message, file=sys.stderr)
            return existing.returncode
    else:
        print("Bucket already exists in this AWS account; applying the required settings.")

    owner = ["--expected-bucket-owner", identity]
    run_aws(
        [
            "s3api",
            "put-bucket-versioning",
            "--bucket",
            bucket,
            "--versioning-configuration",
            "Status=Enabled",
            *owner,
        ],
        profile=args.profile,
    )
    run_aws(
        [
            "s3api",
            "put-public-access-block",
            "--bucket",
            bucket,
            "--public-access-block-configuration",
            "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true",
            *owner,
        ],
        profile=args.profile,
    )
    run_aws(
        [
            "s3api",
            "put-bucket-encryption",
            "--bucket",
            bucket,
            "--server-side-encryption-configuration",
            "Rules=[{ApplyServerSideEncryptionByDefault={SSEAlgorithm=AES256}}]",
            *owner,
        ],
        profile=args.profile,
    )
    run_aws(
        [
            "s3api",
            "put-bucket-ownership-controls",
            "--bucket",
            bucket,
            "--ownership-controls",
            "Rules=[{ObjectOwnership=BucketOwnerEnforced}]",
            *owner,
        ],
        profile=args.profile,
    )

    versioning = run_aws(
        [
            "s3api",
            "get-bucket-versioning",
            "--bucket",
            bucket,
            "--expected-bucket-owner",
            identity,
            "--query",
            "Status",
            "--output",
            "text",
        ],
        profile=args.profile,
    ).stdout.strip()
    if versioning != "Enabled":
        print(
            f"Bucket versioning check failed: expected Enabled, got {versioning!r}.",
            file=sys.stderr,
        )
        return 1

    print(f"Terraform state bucket is ready: {bucket}")
    print(f"Region: {REGION}")
    print("GitHub destination: <ORG>/infra → Settings → Secrets and variables → Actions")
    print(f"Create repository variable TF_STATE_BUCKET with value: {bucket}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
