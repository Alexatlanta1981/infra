#!/usr/bin/env bash
# Prints the JSON for the GH_REPO_SUBJECTS repo variable / TF_VAR_github_repo_subject_prefixes.
# Usage: GITHUB_ORG=<org> ./00_oidc_subjects.sh [infra backend frontend gitops]
set -euo pipefail
: "${GITHUB_ORG:?set GITHUB_ORG}"
repos=("${@:-infra backend frontend gitops}")
[ $# -eq 0 ] && repos=(infra backend frontend gitops)
oid=$(gh api "orgs/$GITHUB_ORG" --jq .id 2>/dev/null || gh api "users/$GITHUB_ORG" --jq .id)
out="{"
for r in "${repos[@]}"; do
  rid=$(gh api "repos/$GITHUB_ORG/$r" --jq .id)
  out+="\"$r\":\"repo:${GITHUB_ORG}@${oid}/${r}@${rid}\","
done
echo "${out%,}}"
