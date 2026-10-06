#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: $0 <state-bucket-name>" >&2
  echo "Creates an S3 bucket in AWS_REGION (default: us-east-1) and enables versioning." >&2
}

if [[ $# -ne 1 || "$1" == "-h" || "$1" == "--help" ]]; then
  usage
  [[ $# -eq 1 ]] && exit 0
  exit 2
fi

if ! command -v aws >/dev/null 2>&1; then
  echo "Error: AWS CLI is not installed or not on PATH." >&2
  exit 1
fi

bucket=$1
region=${AWS_REGION:-us-east-1}
account_id=$(aws sts get-caller-identity --query Account --output text --region "$region")

printf 'AWS account: %s\nRegion:      %s\nBucket:      %s\n' "$account_id" "$region" "$bucket"
read -r -p "Create this bucket and enable versioning? [y/N] " answer
if [[ ! "$answer" =~ ^[Yy]$ ]]; then
  echo "Cancelled; no AWS resources were changed."
  exit 0
fi

create_args=(s3api create-bucket --bucket "$bucket" --region "$region")
if [[ "$region" != "us-east-1" ]]; then
  create_args+=(--create-bucket-configuration "LocationConstraint=$region")
fi
creation_response=$(aws "${create_args[@]}" --output json)

aws s3api put-bucket-versioning \
  --bucket "$bucket" \
  --versioning-configuration Status=Enabled \
  --region "$region"

status=$(aws s3api get-bucket-versioning \
  --bucket "$bucket" \
  --query Status \
  --output text \
  --region "$region")
if [[ "$status" != "Enabled" ]]; then
  echo "Error: S3 bucket versioning verification failed (status: $status)." >&2
  exit 1
fi

printf '\nBucket creation report\n'
printf 'AWS account: %s\nRegion:      %s\nBucket:      %s\n' "$account_id" "$region" "$bucket"
printf 'Versioning:  %s\n' "$status"
printf 'AWS create-bucket response:\n%s\n' "$creation_response"
