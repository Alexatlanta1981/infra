#!/usr/bin/env bash
set -euo pipefail

fail() { echo "Error: $*" >&2; exit 1; }
trap 'echo "Setup failed. Some settings may already have changed; inspect the repository before retrying." >&2' ERR

if [[ $# -ne 0 ]]; then
  echo "Usage: GITHUB_ORG=<owner> STATE_BUCKET=<bucket> $0" >&2
  [[ $# -eq 1 && ( "$1" == "--help" || "$1" == "-h" ) ]] && exit 0
  exit 2
fi

for tool in gh terraform openssl; do
  command -v "$tool" >/dev/null 2>&1 || fail "$tool is required."
done
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)

owner=${GITHUB_ORG:-}
bucket=${STATE_BUCKET:-}
[[ -n "$owner" ]] || read -r -p "GitHub owner of infra, backend, frontend, and gitops: " owner || fail "No GitHub owner input received."
[[ "$owner" =~ ^[A-Za-z0-9][A-Za-z0-9-]*$ ]] || fail "Enter a GitHub owner, not a URL or owner/repo."
[[ -n "$bucket" ]] || read -r -p "Existing Terraform state bucket name: " bucket || fail "No bucket input received."
[[ "$bucket" =~ ^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$ ]] || fail "Enter a valid lowercase bucket name."

gh auth status
repo="$owner/infra"
admin=$(gh api "repos/$repo" --jq '.permissions.admin')
[[ "$admin" == true ]] || fail "Repository administration permission is required for $repo."
user_id=$(gh api user --jq '.id')
login=$(gh api user --jq '.login')
[[ "$user_id" =~ ^[0-9]+$ ]] || fail "GitHub returned an invalid user ID."

plan_arn=$(terraform -chdir="$script_dir/../envs/bootstrap" output -raw terraform_plan_role_arn)
apply_arn=$(terraform -chdir="$script_dir/../envs/bootstrap" output -raw terraform_apply_role_arn)
for arn in "$plan_arn" "$apply_arn"; do
  [[ "$arn" =~ ^arn:aws[a-z-]*:iam::[0-9]{12}:role/.+ ]] || fail "Bootstrap output is not an IAM role ARN."
done
subjects=$(GITHUB_ORG="$owner" bash "$script_dir/00_oidc_subjects.sh")
[[ -n "$subjects" ]] || fail "OIDC subjects script returned no JSON."
existing_sso=$(gh api "repos/$repo/actions/variables?per_page=100" --paginate \
  --jq '.variables[] | select(.name == "SSO_ADMIN_ROLE_ARN") | .value')
sso_arn=${SSO_ADMIN_ROLE_ARN:-}
if [[ -z "$sso_arn" ]]; then
  read -r -p "Full SSO admin IAM role ARN (Enter preserves existing value or skips): " sso_arn || fail "No SSO role input received."
fi
sso_arn=${sso_arn:-$existing_sso}
if [[ -n "$sso_arn" ]]; then
  [[ "$sso_arn" =~ ^arn:aws[a-z-]*:iam::[0-9]{12}:role/.+ ]] || fail "Use the IAM role ARN, not an STS assumed-role ARN."
fi
secret_names=$(gh secret list -R "$repo" --json name --jq '.[].name')
secret_exists=false
while IFS= read -r name; do
  [[ "$name" != DEV_JWT_SECRET ]] || secret_exists=true
done <<< "$secret_names"

environment=$(gh api "repos/$repo/environments?per_page=100" --paginate \
  --jq '.environments[] | select(.name == "dev") | .name')
payload="{\"reviewers\":[{\"type\":\"User\",\"id\":$user_id}],\"wait_timer\":0,\"prevent_self_review\":false,\"can_admins_bypass\":false,\"deployment_branch_policy\":null}"
if [[ -n "$environment" ]]; then
  other_reviewers=$(gh api "repos/$repo/environments/dev" --jq \
    ".protection_rules[] | select(.type == \"required_reviewers\") | .reviewers[] | select(.type != \"User\" or .reviewer.id != $user_id) | .reviewer.id")
  [[ -z "$other_reviewers" ]] || fail "dev has other reviewers. Review its protection rules manually; this script will not remove them or allow them to substitute for your approval."
  payload=$(gh api "repos/$repo/environments/dev" --jq \
    "{reviewers:[{type:\"User\",id:$user_id}],wait_timer:([.protection_rules[] | select(.type == \"wait_timer\") | .wait_timer][0] // 0),prevent_self_review:([.protection_rules[] | select(.type == \"required_reviewers\") | .prevent_self_review][0] // false),can_admins_bypass:false,deployment_branch_policy:.deployment_branch_policy}")
fi

printf '\nRepository: %s\nRequired dev reviewer: %s\nState bucket: %s\n' "$repo" "$login" "$bucket"
printf 'Plan role: %s\nApply role: %s\nOIDC subjects: %s\n' "$plan_arn" "$apply_arn" "$subjects"
if [[ -n "$sso_arn" ]]; then
  printf 'SSO admin role: %s\n' "$sso_arn"
else
  echo "SSO admin role: skipped (no existing value)"
fi
if [[ "$secret_exists" == true ]]; then
  echo "DEV_JWT_SECRET: preserve existing secret"
else
  echo "DEV_JWT_SECRET: generate a new secret (value will not be displayed)"
fi
echo "dev environment: require your approval, disable admin bypass, preserve existing wait timer and branch policy."
read -r -p "Apply these GitHub settings? [y/N] " answer || fail "No confirmation input received; no settings were changed."
if [[ ! "$answer" =~ ^[Yy]$ ]]; then
  echo "Cancelled; no GitHub settings were changed."
  exit 0
fi

if ! printf '%s\n' "$payload" | gh api --method PUT "repos/$repo/environments/dev" --input - >/dev/null; then
  fail "Cannot configure dev protection. Check permissions and GitHub plan/visibility support; required reviewers must not be silently skipped."
fi
reviewer_verified=$(gh api "repos/$repo/environments/dev" --jq \
  "any(.protection_rules[]; .type == \"required_reviewers\" and any(.reviewers[]; .type == \"User\" and .reviewer.id == $user_id))")
[[ "$reviewer_verified" == true ]] || fail "GitHub did not retain the required reviewer; variables and secrets were not changed."

gh variable set GH_ORG -R "$repo" --body "$owner"
gh variable set TF_STATE_BUCKET -R "$repo" --body "$bucket"
gh variable set AWS_TF_PLAN_ROLE_ARN -R "$repo" --body "$plan_arn"
gh variable set AWS_TF_APPLY_ROLE_ARN -R "$repo" --body "$apply_arn"
gh variable set GH_REPO_SUBJECTS -R "$repo" --body "$subjects"
if [[ -n "$sso_arn" ]]; then
  gh variable set SSO_ADMIN_ROLE_ARN -R "$repo" --body "$sso_arn"
fi
if [[ "$secret_exists" != true ]]; then
  openssl rand -base64 48 | gh secret set DEV_JWT_SECRET -R "$repo"
fi

verify_variable() {
  local actual
  actual=$(gh api "repos/$repo/actions/variables/$1" --jq '.value')
  [[ "$actual" == "$2" ]] || fail "Verification failed for repository variable $1."
}
verify_variable GH_ORG "$owner"
verify_variable TF_STATE_BUCKET "$bucket"
verify_variable AWS_TF_PLAN_ROLE_ARN "$plan_arn"
verify_variable AWS_TF_APPLY_ROLE_ARN "$apply_arn"
verify_variable GH_REPO_SUBJECTS "$subjects"
if [[ -n "$sso_arn" ]]; then
  verify_variable SSO_ADMIN_ROLE_ARN "$sso_arn"
fi
verified_secret=$(gh secret list -R "$repo" --json name --jq \
  'any(.[]; .name == "DEV_JWT_SECRET")')
[[ "$verified_secret" == true ]] || fail "DEV_JWT_SECRET was not found after setup."
bypass=$(gh api "repos/$repo/environments/dev" --jq '.can_admins_bypass')
[[ "$bypass" == false ]] || fail "dev environment still permits admin bypass."

printf '\nGitHub settings verification for %s\n' "$repo"
gh variable list -R "$repo"
gh secret list -R "$repo"
gh api "repos/$repo/environments/dev" --jq \
  '{name, can_admins_bypass, protection_rules, deployment_branch_policy}'
echo "Setup complete. No workflows were dispatched, commits pushed, or PRs merged."
