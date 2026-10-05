# SAAS - HENRY FORD (infra)

> ## 🚨 v1.0 — Issues & Fixes
> **16 real problems were hit and fixed while deploying this platform.** See the highlighted
> [❌ Issues → ✅ Fixes scoreboard](docs/V1.0-ISSUES-AND-FIXES.md) and the plain-English
> [Study Guide](docs/STUDY-GUIDE.md). Next: **v1.2** — SSO, OIDC and IRSA, production-grade pipelines.

# Infrastructure and cloud automation scripts

This repository contains Terraform infrastructure code for mackllc. This guide is a companion library of production-minded Bash, Python, and PowerShell examples for cloud and DevOps workflows.

> **Scope:** The scripts below are templates to copy into separate files; this README does not install or run them. Review each script and your organization's change controls before using it against a real account or cluster. They are designed to fail explicitly, avoid embedding credentials, and require explicit flags for infrastructure or application changes.

## Scripts branch and its design

The bootstrap scripts (`scripts/01`–`06`) take a bare EKS cluster to running services. They are developed on a dedicated, protected branch: **`ci/bootstrap-script-tests`**. Work happens there, is tested automatically, then merges to `main`.

**Branch protection** (ruleset "Protect scripts branch"): no deletion, no force-push, changes only via pull request, and these checks must pass with the branch up to date:

| Required check | What it does |
|---|---|
| `static` | `py_compile` plus `ruff` (syntax, undefined names, unused code) on `scripts/*.py` |
| `bootstrap smoke (01-03, kind)` | Spins up a throwaway `kind` cluster, runs scripts 01–03 with dummy AWS values, and asserts Argo CD, External Secrets, the `dev` namespace, the repo secret, the `mackllc` AppProject, the ClusterSecretStore and ExternalSecrets exist |
| `app layer (04-06, kind)` | Fresh `kind` cluster plus the real `gitops` repo; runs 01–06 with a fake `gh` CLI so no real builds start |

Defined in `.github/workflows/scripts-test.yml`. It runs on any PR or push to `main` that touches `scripts/**`, or manually (`gh workflow run scripts-test.yml`).

**Script design:**
- Numbered, run in order: 01 prerequisites (ALB controller, Argo CD, ESO) → 02 Argo CD bootstrap → 03 External Secrets → 04 trigger CI builds → 05 deploy Argo apps → 06 verify.
- Every prompt can be preset as an environment variable, so scripts run unattended in CI (`echo Y | python3 scripts/01_...`).
- Idempotent: safe to re-run.
- No static credentials: AWS via SSO/IRSA, GitHub via App keys at runtime. Nothing secret is committed.
- Cluster-free testing: `SKIP_ALB_CONTROLLER=1` lets 01–03 run on `kind`.

**Workflow to change a script:**
```bash
git fetch origin && git checkout -b fix/my-script-change origin/ci/bootstrap-script-tests
# edit scripts/...
git add -A && git commit -m "fix(script): ..."
git push -u origin fix/my-script-change
gh pr create --base ci/bootstrap-script-tests --fill   # wait for 3 green checks, merge in the UI
```

---

## Inputs to replace

Before running a script, replace every highlighted `CHANGE_ME_...` value with a value for your account and environment. These are configuration inputs, not credentials. Obtain credentials through AWS IAM Identity Center/SSO, Azure sign-in, Google Cloud authentication, workload identity, or your CI secret store. Never put access keys, passwords, tokens, private keys, or Terraform state contents in a script or commit them to Git.

Some scripts accept command-line inputs instead of constants. Their `--help` output and examples below show the required syntax.

## Requirements

- **Bash scripts:** Bash 4+, Linux/WSL, and the tools named in the relevant section.
- **Python scripts:** Python 3.10+; install the listed libraries in a virtual environment. Cloud SDKs use their normal credential chain.
- **PowerShell scripts:** PowerShell 7+ on Windows unless a script says otherwise.
- Run cloud scripts with least-privilege identities, and confirm account, region, cluster context, namespace, and target environment before mutation.
- For production changes, prefer a reviewed CI/CD identity and an approval gate over a developer's personal credentials.

## Contents

1. [Ubuntu/WSL DevOps workstation bootstrap](#1-ubuntuwsl-devops-workstation-bootstrap)
2. [AWS SSO, EKS access, and controlled deployment](#2-aws-sso-eks-access-and-controlled-deployment)
3. [Terraform plan and approved apply](#3-terraform-plan-and-approved-apply)
4. [Build and push an image to ECR](#4-build-and-push-an-image-to-ecr)
5. [Kubernetes CrashLoopBackOff report](#5-kubernetes-crashloopbackoff-report)
6. [Kubernetes pod log collection](#6-kubernetes-pod-log-collection)
7. [Kubernetes rollout validation](#7-kubernetes-rollout-validation)
8. [GitOps image tag update](#8-gitops-image-tag-update)
9. [Argo CD application sync](#9-argo-cd-application-sync)
10. [Argo CD drift check](#10-argo-cd-drift-check)
11. [Terraform plus Kubernetes deployment pipeline](#11-terraform-plus-kubernetes-deployment-pipeline)
12. [Terraform backend and Kubernetes health check](#12-terraform-backend-and-kubernetes-health-check)
13. [AWS EC2 inventory to CSV (Python)](#13-aws-ec2-inventory-to-csv-python)
14. [Upload a backup to S3 (Python)](#14-upload-a-backup-to-s3-python)
15. [Kubernetes Deployment readiness validator (Python)](#15-kubernetes-deployment-readiness-validator-python)
16. [CI/CD Kubernetes manifest runner (Python)](#16-cicd-kubernetes-manifest-runner-python)
17. [Azure login and AKS credentials (PowerShell)](#17-azure-login-and-aks-credentials-powershell)
18. [Install WSL Ubuntu (PowerShell)](#18-install-wsl-ubuntu-powershell)
19. [Encrypted, versioned Terraform state backup (PowerShell)](#19-encrypted-versioned-terraform-state-backup-powershell)
20. [Workstation security baseline check (Bash)](#20-workstation-security-baseline-check-bash)
21. [Repository secret scan (Bash)](#21-repository-secret-scan-bash)
22. [Bash syntax and invocation quick reference](#22-bash-syntax-and-invocation-quick-reference)
23. [Expansions, syntax walkthrough, and use cases](#expansions-syntax-walkthrough-and-use-cases)

---

## 1. Ubuntu/WSL DevOps workstation bootstrap

Installs commonly used cloud tools from signed package repositories on Ubuntu. It is intended for a personal development workstation, not a production server or ephemeral CI runner. Review package sources and versions for your organization's endpoint policy before running it.

**Inputs to edit:** `KUBECTL_MINOR` and the optional VS Code extension list.

**Requirements:** Ubuntu 22.04/24.04, `sudo`, Bash, `curl`, `gpg`. Docker group membership grants root-equivalent privileges; use Docker Desktop/WSL integration instead if that is your managed standard.

Save as `bootstrap-devops.sh`:

```bash
#!/usr/bin/env bash
set -Eeuo pipefail

KUBECTL_MINOR="CHANGE_ME_V1_XX" # Example format: v1.34; use your approved Kubernetes minor.
INSTALL_VSCODE_EXTENSIONS="false" # Change to true only when the VS Code CLI is installed.

log() { printf '[%s] %s\n' "$(date -Is)" "$*"; }
fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
need_command() { command -v "$1" >/dev/null 2>&1 || fail "Required command not found: $1"; }

[[ $EUID -ne 0 ]] || fail "Run as a normal user; this script uses sudo only for package changes."
[[ -r /etc/os-release ]] || fail "Cannot identify the operating system."
# shellcheck disable=SC1091
source /etc/os-release
[[ ${ID:-} == ubuntu ]] || fail "This script supports Ubuntu only (detected: ${ID:-unknown})."
[[ $KUBECTL_MINOR =~ ^v[0-9]+\.[0-9]+$ ]] || fail "Set KUBECTL_MINOR to an approved value such as v1.34."
need_command sudo
need_command curl
need_command gpg

ARCH="$(dpkg --print-architecture)"
CODENAME="${VERSION_CODENAME:?VERSION_CODENAME is missing from /etc/os-release}"
KEYRING_DIR="/etc/apt/keyrings"
sudo install -d -m 0755 "$KEYRING_DIR"

log "Installing base packages"
sudo apt-get update
sudo apt-get install -y ca-certificates curl git gnupg jq python3 python3-venv \
  python3-pip unzip wget build-essential

log "Registering signed package repositories"
curl -fsSL https://apt.releases.hashicorp.com/gpg \
  | gpg --dearmor \
  | sudo tee "$KEYRING_DIR/hashicorp-archive-keyring.gpg" >/dev/null
echo "deb [arch=${ARCH} signed-by=${KEYRING_DIR}/hashicorp-archive-keyring.gpg] https://apt.releases.hashicorp.com ${CODENAME} main" \
  | sudo tee /etc/apt/sources.list.d/hashicorp.list >/dev/null

curl -fsSL https://packages.microsoft.com/keys/microsoft.asc \
  | gpg --dearmor \
  | sudo tee "$KEYRING_DIR/microsoft.gpg" >/dev/null
echo "deb [arch=${ARCH} signed-by=${KEYRING_DIR}/microsoft.gpg] https://packages.microsoft.com/repos/azure-cli/ ${CODENAME} main" \
  | sudo tee /etc/apt/sources.list.d/azure-cli.list >/dev/null

curl -fsSL https://packages.cloud.google.com/apt/doc/apt-key.gpg \
  | gpg --dearmor \
  | sudo tee "$KEYRING_DIR/google-cloud.gpg" >/dev/null
echo "deb [signed-by=${KEYRING_DIR}/google-cloud.gpg] https://packages.cloud.google.com/apt cloud-sdk main" \
  | sudo tee /etc/apt/sources.list.d/google-cloud-sdk.list >/dev/null

curl -fsSL "https://pkgs.k8s.io/core:/stable:/${KUBECTL_MINOR}/deb/Release.key" \
  | gpg --dearmor \
  | sudo tee "$KEYRING_DIR/kubernetes-apt-keyring.gpg" >/dev/null
echo "deb [signed-by=${KEYRING_DIR}/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/${KUBECTL_MINOR}/deb/ /" \
  | sudo tee /etc/apt/sources.list.d/kubernetes.list >/dev/null

curl -fsSL https://baltocdn.com/helm/signing.asc \
  | gpg --dearmor \
  | sudo tee "$KEYRING_DIR/helm.gpg" >/dev/null
echo "deb [arch=${ARCH} signed-by=${KEYRING_DIR}/helm.gpg] https://baltocdn.com/helm/stable/debian/ all main" \
  | sudo tee /etc/apt/sources.list.d/helm-stable-debian.list >/dev/null

curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  | gpg --dearmor \
  | sudo tee "$KEYRING_DIR/docker.gpg" >/dev/null
echo "deb [arch=${ARCH} signed-by=${KEYRING_DIR}/docker.gpg] https://download.docker.com/linux/ubuntu ${CODENAME} stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null

curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
  | sudo tee "$KEYRING_DIR/githubcli-archive-keyring.gpg" >/dev/null
sudo chmod 0644 "$KEYRING_DIR/githubcli-archive-keyring.gpg"
echo "deb [arch=${ARCH} signed-by=${KEYRING_DIR}/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
  | sudo tee /etc/apt/sources.list.d/github-cli.list >/dev/null

log "Installing cloud and DevOps CLIs"
sudo apt-get update
sudo apt-get install -y awscli azure-cli google-cloud-cli terraform kubectl helm \
  docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin gh \
  nodejs npm golang-go

if [[ $INSTALL_VSCODE_EXTENSIONS == true ]]; then
  need_command code
  code --install-extension ms-vscode-remote.remote-wsl
  code --install-extension hashicorp.terraform
  code --install-extension amazonwebservices.aws-toolkit-vscode
  code --install-extension ms-kubernetes-tools.vscode-kubernetes-tools
  code --install-extension redhat.vscode-yaml
  code --install-extension eamodio.gitlens
fi

log "Bootstrap complete. Authenticate separately; no cloud credentials were created."
log "For Docker without Docker Desktop, review your host's Docker service and group policy before enabling it."
```

Run:

```bash
chmod 0755 bootstrap-devops.sh
./bootstrap-devops.sh
```

The AWS CLI package supplied by Ubuntu may not be AWS CLI v2. Check `aws --version` and install the organization's approved AWS CLI version if required. The script does not run cloud logins, enable a Docker daemon, add the user to the `docker` group, or silently change shell startup files.

### Optional interactive multi-cloud login helpers

Use these only in an interactive shell after installing the CLIs. `CHANGE_ME_AWS_PROFILE` and `CHANGE_ME_AZURE_SUBSCRIPTION` are examples; avoid adding secrets.

```bash
aws sso login --profile CHANGE_ME_AWS_PROFILE
aws sts get-caller-identity --profile CHANGE_ME_AWS_PROFILE

az login
az account set --subscription CHANGE_ME_AZURE_SUBSCRIPTION
az account show --output table

gcloud auth login
gcloud config list
```

Optional interactive shell aliases (add them to `~/.bashrc` once, then open a new shell):

```bash
alias aws-login='aws sso login --profile CHANGE_ME_AWS_PROFILE && aws sts get-caller-identity --profile CHANGE_ME_AWS_PROFILE'
alias az-login='az login && az account set --subscription CHANGE_ME_AZURE_SUBSCRIPTION && az account show --output table'
alias gcp-login='gcloud auth login && gcloud config list'
alias k='kubectl'
alias kgp='kubectl get pods --all-namespaces'
alias tf='terraform'
```

---

## 2. AWS SSO, EKS access, and controlled deployment

Authenticates using an existing AWS IAM Identity Center profile, updates kubeconfig, checks the AWS identity and cluster access, applies one manifest, then waits for a named Deployment rollout. It does **not** delete or restart pods.

**Inputs to edit:** `AWS_PROFILE`, `AWS_REGION`, `EKS_CLUSTER`, `NAMESPACE`, `MANIFEST`, and `DEPLOYMENT`.

**Requirements:** AWS CLI, `kubectl`, `jq`; an existing SSO profile and permission to access the specified EKS cluster.

Save as `eks-deploy.sh`:

```bash
#!/usr/bin/env bash
set -Eeuo pipefail

AWS_PROFILE="CHANGE_ME_SSO_PROFILE"
AWS_REGION="CHANGE_ME_AWS_REGION"
EKS_CLUSTER="CHANGE_ME_EKS_CLUSTER"
NAMESPACE="CHANGE_ME_NAMESPACE"
MANIFEST="CHANGE_ME_PATH_TO_MANIFEST.yaml"
DEPLOYMENT="CHANGE_ME_DEPLOYMENT"
ROLLOUT_TIMEOUT="5m"

log() { printf '[%s] %s\n' "$(date -Is)" "$*"; }
fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
for cmd in aws kubectl jq; do command -v "$cmd" >/dev/null || fail "Install $cmd first."; done
for value in "$AWS_PROFILE" "$AWS_REGION" "$EKS_CLUSTER" "$NAMESPACE" "$MANIFEST" "$DEPLOYMENT"; do
  [[ $value != CHANGE_ME_* ]] || fail "Replace all CHANGE_ME_* inputs before running."
done
[[ -f $MANIFEST ]] || fail "Manifest not found: $MANIFEST"

log "Logging in to AWS IAM Identity Center"
aws sso login --profile "$AWS_PROFILE"
aws sts get-caller-identity --profile "$AWS_PROFILE" --output json

log "Updating kubeconfig for the requested EKS cluster"
aws eks update-kubeconfig --name "$EKS_CLUSTER" --region "$AWS_REGION" \
  --profile "$AWS_PROFILE" --alias "${AWS_PROFILE}@${EKS_CLUSTER}"
kubectl config current-context
kubectl get nodes -o json | jq -e '.items | length > 0' >/dev/null \
  || fail "The cluster returned no nodes or node listing failed."

log "Applying $MANIFEST to namespace $NAMESPACE"
kubectl apply --namespace "$NAMESPACE" --filename "$MANIFEST"
log "Waiting for Deployment/$DEPLOYMENT rollout"
kubectl rollout status "deployment/$DEPLOYMENT" --namespace "$NAMESPACE" --timeout="$ROLLOUT_TIMEOUT"
log "Deployment completed."
```

Run `./eks-deploy.sh` after replacing the inputs. Confirm the current AWS account and Kubernetes context shown by the script before approving its `kubectl apply` action.

---

## 3. Terraform plan and approved apply

Runs formatting, initialization, and validation before producing a saved plan. The default action is **plan only**. Applying requires the separate `--apply` flag and applies that exact saved plan.

**Inputs to edit:** `TF_ROOT`, `VAR_FILE`, `PLAN_FILE`.

**Requirements:** Terraform CLI, a configured backend, and any provider credentials required by the configuration.

Save as `terraform-run.sh`:

```bash
#!/usr/bin/env bash
set -Eeuo pipefail

TF_ROOT="CHANGE_ME_TERRAFORM_DIRECTORY"
VAR_FILE="CHANGE_ME_ENVIRONMENT.tfvars"
PLAN_FILE="CHANGE_ME_PLAN_FILE"
APPLY=false

usage() {
  printf 'Usage: %s [--apply]\n' "$0"
  printf 'Default: fmt, init, validate, and create a saved plan. --apply applies that plan.\n'
}
[[ $# -le 1 ]] || { usage >&2; exit 2; }
if [[ ${1:-} == --apply ]]; then APPLY=true
elif [[ $# -eq 1 ]]; then usage >&2; exit 2
fi

for value in "$TF_ROOT" "$VAR_FILE" "$PLAN_FILE"; do
  [[ $value != CHANGE_ME_* ]] || { printf 'Replace all CHANGE_ME_* inputs first.\n' >&2; exit 2; }
done
command -v terraform >/dev/null || { printf 'terraform is required.\n' >&2; exit 127; }
[[ -d $TF_ROOT ]] || { printf 'Terraform directory not found: %s\n' "$TF_ROOT" >&2; exit 2; }
[[ -f $TF_ROOT/$VAR_FILE ]] || { printf 'Variable file not found: %s\n' "$TF_ROOT/$VAR_FILE" >&2; exit 2; }

terraform -chdir="$TF_ROOT" fmt -check -recursive
terraform -chdir="$TF_ROOT" init -input=false
terraform -chdir="$TF_ROOT" validate
terraform -chdir="$TF_ROOT" plan -input=false -var-file="$VAR_FILE" -out="$PLAN_FILE"
printf 'Plan saved to %s/%s\n' "$TF_ROOT" "$PLAN_FILE"

if [[ $APPLY == true ]]; then
  printf 'Applying the saved Terraform plan.\n'
  terraform -chdir="$TF_ROOT" apply -input=false -auto-approve "$PLAN_FILE"
else
  printf 'Plan only. Review it, then run: %s --apply\n' "$0"
fi
```

The plan file can contain sensitive values. Keep it out of source control and store it only in an access-controlled pipeline artifact. Use backend locking and an approval process for production.

---

## 4. Build and push an image to ECR

Builds an image tagged with the checked-out Git commit and pushes it to an existing ECR repository.

**Inputs to edit:** `AWS_PROFILE`, `AWS_REGION`, `AWS_ACCOUNT_ID`, `ECR_REPOSITORY`, `BUILD_CONTEXT`, `DOCKERFILE`.

**Requirements:** AWS CLI, Docker with Buildx, Git, existing ECR repository, and push permissions.

Save as `ecr-build-push.sh`:

```bash
#!/usr/bin/env bash
set -Eeuo pipefail

AWS_PROFILE="CHANGE_ME_AWS_PROFILE"
AWS_REGION="CHANGE_ME_AWS_REGION"
AWS_ACCOUNT_ID="CHANGE_ME_12_DIGIT_ACCOUNT_ID"
ECR_REPOSITORY="CHANGE_ME_REPOSITORY"
BUILD_CONTEXT="."
DOCKERFILE="Dockerfile"

for cmd in aws docker git; do command -v "$cmd" >/dev/null || { echo "Required command missing: $cmd" >&2; exit 127; }; done
for value in "$AWS_PROFILE" "$AWS_REGION" "$AWS_ACCOUNT_ID" "$ECR_REPOSITORY"; do
  [[ $value != CHANGE_ME_* ]] || { echo "Replace all CHANGE_ME_* inputs first." >&2; exit 2; }
done
[[ $AWS_ACCOUNT_ID =~ ^[0-9]{12}$ ]] || { echo "AWS_ACCOUNT_ID must contain 12 digits." >&2; exit 2; }
[[ -f $DOCKERFILE && -d $BUILD_CONTEXT ]] || { echo "Dockerfile or build context not found." >&2; exit 2; }

IMAGE_TAG="$(git rev-parse --short=12 HEAD)"
REGISTRY="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
IMAGE="${REGISTRY}/${ECR_REPOSITORY}:${IMAGE_TAG}"

aws ecr describe-repositories --repository-names "$ECR_REPOSITORY" \
  --region "$AWS_REGION" --profile "$AWS_PROFILE" >/dev/null
aws ecr get-login-password --region "$AWS_REGION" --profile "$AWS_PROFILE" \
  | docker login --username AWS --password-stdin "$REGISTRY"
docker buildx build --file "$DOCKERFILE" --tag "$IMAGE" --push "$BUILD_CONTEXT"
printf 'Pushed %s\n' "$IMAGE"
```

This uses an immutable commit-derived tag rather than `latest`. Configure ECR lifecycle, image scanning, and deployment approvals separately.

---

## 5. Kubernetes CrashLoopBackOff report

Finds containers currently reporting `CrashLoopBackOff`, prints each pod's namespace/name, and describes each affected pod. It intentionally does not delete or restart pods; investigate the cause before remediation.

**Inputs to edit:** `CONTEXT` (optional; leave empty to use the current context).

**Requirements:** `kubectl`, `jq`, a read-only Kubernetes identity with permission to list and describe pods.

Save as `k8s-crashloop-report.sh`:

```bash
#!/usr/bin/env bash
set -Eeuo pipefail

CONTEXT="CHANGE_ME_KUBE_CONTEXT" # Set to "" to use the current context.
if ! command -v kubectl >/dev/null || ! command -v jq >/dev/null; then
  echo "kubectl and jq are required." >&2
  exit 127
fi
if [[ $CONTEXT == CHANGE_ME_KUBE_CONTEXT ]]; then
  echo "Replace CONTEXT or set it to an empty string." >&2
  exit 2
fi
KUBE_ARGS=()
[[ -n $CONTEXT ]] && KUBE_ARGS+=(--context "$CONTEXT")

PODS_JSON="$(kubectl "${KUBE_ARGS[@]}" get pods --all-namespaces -o json)"
mapfile -t AFFECTED_PODS < <(
  jq -r '
    .items[]
    | select(any((.status.containerStatuses // [])[]; .state.waiting.reason == "CrashLoopBackOff")
        or any((.status.initContainerStatuses // [])[]; .state.waiting.reason == "CrashLoopBackOff"))
    | [.metadata.namespace, .metadata.name] | @tsv
  ' <<<"$PODS_JSON"
)

if ((${#AFFECTED_PODS[@]} == 0)); then
  echo "No CrashLoopBackOff containers found."
  exit 0
fi

printf 'Found %d affected pod(s):\n' "${#AFFECTED_PODS[@]}"
printf '%s\n' "${AFFECTED_PODS[@]}"
for item in "${AFFECTED_PODS[@]}"; do
  IFS=$'\t' read -r namespace pod <<<"$item"
  printf '\n===== describe %s/%s =====\n' "$namespace" "$pod"
  kubectl "${KUBE_ARGS[@]}" describe pod "$pod" --namespace "$namespace"
done
```

---

## 6. Kubernetes pod log collection

Collects current logs for every pod in one namespace into a timestamped directory. Files are named with namespace and pod to avoid collisions. Logs may contain personal data or secrets; protect and expire the output.

**Inputs to edit:** `NAMESPACE`, optional `CONTEXT`.

**Requirements:** `kubectl`, `jq` (used to check access), and read permission for pod logs.

Save as `k8s-collect-logs.sh`:

```bash
#!/usr/bin/env bash
set -Eeuo pipefail

NAMESPACE="CHANGE_ME_NAMESPACE"
CONTEXT="" # Optional context; empty means current context.
OUTPUT_ROOT="./k8s-logs"

[[ $NAMESPACE != CHANGE_ME_* ]] || { echo "Set NAMESPACE before running." >&2; exit 2; }
if ! command -v kubectl >/dev/null || ! command -v jq >/dev/null; then
  echo "kubectl and jq are required." >&2
  exit 127
fi
KUBE_ARGS=()
[[ -n $CONTEXT ]] && KUBE_ARGS+=(--context "$CONTEXT")
kubectl "${KUBE_ARGS[@]}" get pods --namespace "$NAMESPACE" -o json | jq -e '.items | type == "array"' >/dev/null

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUTPUT_DIR="${OUTPUT_ROOT}/${NAMESPACE}-${STAMP}"
mkdir -p "$OUTPUT_ROOT"
install -d -m 0700 "$OUTPUT_DIR"
mapfile -t PODS < <(kubectl "${KUBE_ARGS[@]}" get pods --namespace "$NAMESPACE" -o name)
FAILED=0

for resource in "${PODS[@]}"; do
  pod="${resource#pod/}"
  safe_pod="${pod//[^[:alnum:]._-]/_}"
  log_file="${OUTPUT_DIR}/${safe_pod}.log"
  printf 'Collecting %s/%s -> %s\n' "$NAMESPACE" "$pod" "$log_file"
  if ! kubectl "${KUBE_ARGS[@]}" logs "$resource" --namespace "$NAMESPACE" \
      --all-containers=true --prefix=true >"$log_file" 2>&1; then
    printf 'Log collection failed for %s/%s; see %s\n' "$NAMESPACE" "$pod" "$log_file" >&2
    FAILED=1
  fi
done

printf 'Logs saved under %s\n' "$OUTPUT_DIR"
exit "$FAILED"
```

Use `kubectl logs --previous` manually for a crashed container's previous instance; previous logs are not the same as current logs and are not silently substituted here.

---

## 7. Kubernetes rollout validation

Waits for one Deployment rollout and returns a nonzero exit code if it does not finish within the timeout.

**Inputs:** supply Deployment name and namespace as arguments. Optional `--context` selects the kube context.

Save as `k8s-check-rollout.sh`:

```bash
#!/usr/bin/env bash
set -Eeuo pipefail

usage() { echo "Usage: $0 DEPLOYMENT NAMESPACE [--context CONTEXT]"; }
[[ $# -ge 2 && $# -le 4 ]] || { usage >&2; exit 2; }
DEPLOYMENT="$1"
NAMESPACE="$2"
shift 2
KUBE_ARGS=()
if [[ $# -eq 2 && $1 == --context ]]; then
  KUBE_ARGS+=(--context "$2")
elif [[ $# -ne 0 ]]; then
  usage >&2
  exit 2
fi

command -v kubectl >/dev/null || { echo "kubectl is required." >&2; exit 127; }
kubectl "${KUBE_ARGS[@]}" rollout status "deployment/${DEPLOYMENT}" \
  --namespace "$NAMESPACE" --timeout=5m
```

Example: `./k8s-check-rollout.sh api production --context prod-eks`.

---

## 8. GitOps image tag update

Updates `.image.tag` in a checked-out GitOps repository's values file, creates a commit, and pushes to the named branch. The script refuses to run in a dirty working tree and uses Mike Farah `yq` rather than fragile text replacement.

**Inputs to edit:** `GITOPS_REPO`, `BRANCH`, `VALUES_FILE`; supply the new tag as argument 1.

**Requirements:** Git, Mike Farah `yq` v4, repository write access configured through SSH/credential manager.

Save as `gitops-update-image.sh`:

```bash
#!/usr/bin/env bash
set -Eeuo pipefail

GITOPS_REPO="CHANGE_ME_PATH_TO_GITOPS_CHECKOUT"
BRANCH="CHANGE_ME_APPROVED_BRANCH"
VALUES_FILE="CHANGE_ME_ENV_PATH/values.yaml"
BOT_NAME="CHANGE_ME_AUTOMATION_NAME"
BOT_EMAIL="CHANGE_ME_AUTOMATION_EMAIL"

[[ $# -eq 1 ]] || { echo "Usage: $0 IMAGE_TAG" >&2; exit 2; }
IMAGE_TAG="$1"
[[ $GITOPS_REPO != CHANGE_ME_* && $BRANCH != CHANGE_ME_* && $VALUES_FILE != CHANGE_ME_* ]] \
  || { echo "Replace all CHANGE_ME_* inputs first." >&2; exit 2; }
[[ $IMAGE_TAG =~ ^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$ ]] || { echo "Invalid image tag." >&2; exit 2; }
if ! command -v git >/dev/null || ! command -v yq >/dev/null; then
  echo "git and yq v4 are required." >&2
  exit 127
fi
git -C "$GITOPS_REPO" rev-parse --is-inside-work-tree >/dev/null
[[ -f "$GITOPS_REPO/$VALUES_FILE" ]] || { echo "Values file not found." >&2; exit 2; }
[[ -z "$(git -C "$GITOPS_REPO" status --porcelain)" ]] \
  || { echo "Refusing to update a dirty checkout; commit or stash its changes first." >&2; exit 2; }

git -C "$GITOPS_REPO" switch "$BRANCH"
git -C "$GITOPS_REPO" pull --ff-only origin "$BRANCH"
IMAGE_TAG="$IMAGE_TAG" yq -i '.image.tag = strenv(IMAGE_TAG)' "$GITOPS_REPO/$VALUES_FILE"
git -C "$GITOPS_REPO" config user.name "$BOT_NAME"
git -C "$GITOPS_REPO" config user.email "$BOT_EMAIL"
git -C "$GITOPS_REPO" add -- "$VALUES_FILE"
if git -C "$GITOPS_REPO" diff --cached --quiet; then
  echo "Image tag is already current; no commit created."
  exit 0
fi
git -C "$GITOPS_REPO" commit -m "Update image tag to ${IMAGE_TAG}"
git -C "$GITOPS_REPO" push origin "$BRANCH"
```

Protect production branches with repository review rules. This updates only the GitOps repository; it does not bypass the deployment controller or commit application code.

---

## 9. Argo CD application sync

Requests a sync for one Argo CD application, then waits for both synced and healthy state.

**Input:** supply the application name as argument 1. Authenticate with the approved Argo CD method first.

**Requirements:** `argocd` CLI and permission to sync the specified app.

Save as `argocd-sync.sh`:

```bash
#!/usr/bin/env bash
set -Eeuo pipefail

[[ $# -eq 1 ]] || { echo "Usage: $0 ARGOCD_APP_NAME" >&2; exit 2; }
command -v argocd >/dev/null || { echo "argocd CLI is required." >&2; exit 127; }
APP="$1"
argocd app get "$APP" >/dev/null
argocd app sync "$APP"
argocd app wait "$APP" --sync --health --timeout 300
```

The sync can change live resources. Confirm the application, destination cluster, and namespace before use.

---

## 10. Argo CD drift check

Lists applications in `OutOfSync` state and returns exit code 1 if any are found. Suitable as a monitoring or pipeline check; it does not sync or mutate applications.

**Requirements:** authenticated `argocd` CLI, `jq`, permission to list applications.

Save as `argocd-drift-check.sh`:

```bash
#!/usr/bin/env bash
set -Eeuo pipefail

if ! command -v argocd >/dev/null || ! command -v jq >/dev/null; then
  echo "argocd and jq are required." >&2
  exit 127
fi
APPS_JSON="$(argocd app list -o json)"
mapfile -t DRIFTED < <(
  jq -r '.[] | select(.status.sync.status == "OutOfSync") | [.metadata.name, .status.sync.status, .status.health.status] | @tsv' \
    <<<"$APPS_JSON"
)
if ((${#DRIFTED[@]})); then
  printf 'Out-of-sync applications:\n%s\n' "$(printf '%s\n' "${DRIFTED[@]}")" >&2
  exit 1
fi
echo "No OutOfSync applications found."
```

---

## 11. Terraform plus Kubernetes deployment pipeline

Coordinates an infrastructure plan with a Kubernetes manifest deployment. The default is **plan and validate only**. The explicit `--apply-infra` flag applies the saved Terraform plan; `--deploy-app` applies manifests. Both changes require their own flag.

**Inputs to edit:** `TF_ROOT`, `ENVIRONMENT`, `NAMESPACE`, `MANIFEST_DIR`, `DEPLOYMENT`.

**Requirements:** Terraform, kubectl, configured Terraform backend, and access to the target cluster.

Save as `infra-and-app-deploy.sh`:

```bash
#!/usr/bin/env bash
set -Eeuo pipefail

TF_ROOT="CHANGE_ME_TERRAFORM_DIRECTORY"
ENVIRONMENT="CHANGE_ME_ENVIRONMENT"
NAMESPACE="CHANGE_ME_NAMESPACE"
MANIFEST_DIR="CHANGE_ME_KUBERNETES_MANIFEST_DIRECTORY"
DEPLOYMENT="CHANGE_ME_DEPLOYMENT"
APPLY_INFRA=false
DEPLOY_APP=false

usage() { echo "Usage: $0 [--apply-infra] [--deploy-app]"; }
while (($#)); do
  case "$1" in
    --apply-infra) APPLY_INFRA=true ;;
    --deploy-app) DEPLOY_APP=true ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
  shift
done
for value in "$TF_ROOT" "$ENVIRONMENT" "$NAMESPACE" "$MANIFEST_DIR" "$DEPLOYMENT"; do
  [[ $value != CHANGE_ME_* ]] || { echo "Replace all CHANGE_ME_* inputs first." >&2; exit 2; }
done
[[ -d $TF_ROOT && -d $MANIFEST_DIR ]] || { echo "Terraform or manifest directory not found." >&2; exit 2; }
[[ -f "$TF_ROOT/${ENVIRONMENT}.tfvars" ]] || { echo "Environment tfvars file not found." >&2; exit 2; }
if ! command -v terraform >/dev/null || ! command -v kubectl >/dev/null; then
  echo "terraform and kubectl are required." >&2
  exit 127
fi

PLAN_FILE="${ENVIRONMENT}.tfplan"
terraform -chdir="$TF_ROOT" init -input=false
terraform -chdir="$TF_ROOT" validate
terraform -chdir="$TF_ROOT" plan -input=false -var-file="${ENVIRONMENT}.tfvars" -out="$PLAN_FILE"
if [[ $APPLY_INFRA == true ]]; then
  terraform -chdir="$TF_ROOT" apply -input=false -auto-approve "$PLAN_FILE"
else
  echo "Infrastructure plan only. Re-run with --apply-infra to apply it."
fi

if [[ $DEPLOY_APP == true ]]; then
  kubectl apply --namespace "$NAMESPACE" --filename "$MANIFEST_DIR"
  kubectl rollout status "deployment/$DEPLOYMENT" --namespace "$NAMESPACE" --timeout=5m
else
  echo "No Kubernetes changes made. Re-run with --deploy-app to apply manifests."
fi
```

Example after reviewing the plan: `./infra-and-app-deploy.sh --apply-infra --deploy-app`. Keep infrastructure and application approvals separate where your change policy requires it.

---

## 12. Terraform backend and Kubernetes health check

Checks access to an S3 Terraform state bucket, an optional DynamoDB lock table, and the active Kubernetes cluster. It is read-only.

**Inputs to edit:** `AWS_PROFILE`, `AWS_REGION`, `STATE_BUCKET`, `LOCK_TABLE` (set to empty if not used), `KUBE_CONTEXT` (set to empty for current context).

**Requirements:** AWS CLI, kubectl, AWS read permissions, Kubernetes read permissions.

Save as `cloud-health-check.sh`:

```bash
#!/usr/bin/env bash
set -Eeuo pipefail

AWS_PROFILE="CHANGE_ME_AWS_PROFILE"
AWS_REGION="CHANGE_ME_AWS_REGION"
STATE_BUCKET="CHANGE_ME_TERRAFORM_STATE_BUCKET"
LOCK_TABLE="" # Optional. Set to a table name if this backend uses DynamoDB locking.
KUBE_CONTEXT="" # Optional. Empty means current context.

for cmd in aws kubectl; do command -v "$cmd" >/dev/null || { echo "Required command missing: $cmd" >&2; exit 127; }; done
for value in "$AWS_PROFILE" "$AWS_REGION" "$STATE_BUCKET"; do
  [[ $value != CHANGE_ME_* ]] || { echo "Replace all required CHANGE_ME_* inputs first." >&2; exit 2; }
done
AWS_ARGS=(--profile "$AWS_PROFILE" --region "$AWS_REGION")
KUBE_ARGS=()
[[ -n $KUBE_CONTEXT ]] && KUBE_ARGS+=(--context "$KUBE_CONTEXT")

aws sts get-caller-identity "${AWS_ARGS[@]}" --output table
aws s3api head-bucket --bucket "$STATE_BUCKET" "${AWS_ARGS[@]}"
if [[ -n $LOCK_TABLE ]]; then
  aws dynamodb describe-table --table-name "$LOCK_TABLE" "${AWS_ARGS[@]}" \
    --query 'Table.TableStatus' --output text
fi
kubectl "${KUBE_ARGS[@]}" cluster-info
kubectl "${KUBE_ARGS[@]}" get nodes -o wide
```

---

## 13. AWS EC2 inventory to CSV (Python)

Exports EC2 instance identity, state, type, AZ, private/public IP, and Name tag to a CSV file. Uses boto3 pagination and the standard AWS credential chain.

**Inputs:** supply a region and output path; optionally supply an AWS profile.

**Requirements:** `python3 -m pip install boto3` (prefer a virtual environment), AWS read-only EC2 permissions.

Save as `ec2_inventory.py`:

```python
#!/usr/bin/env python3
"""Export a regional EC2 inventory as CSV."""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import boto3
from botocore.exceptions import BotoCoreError, ClientError


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", required=True, help="AWS region, e.g. us-east-1")
    parser.add_argument("--output", type=Path, default=Path("ec2-inventory.csv"))
    parser.add_argument("--profile", help="Optional named AWS profile")
    args = parser.parse_args()

    try:
        session = boto3.Session(profile_name=args.profile, region_name=args.region)
        client = session.client("ec2")
        pages = client.get_paginator("describe_instances").paginate()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(
                file,
                fieldnames=[
                    "instance_id", "name", "state", "instance_type",
                    "availability_zone", "private_ip", "public_ip",
                ],
            )
            writer.writeheader()
            for page in pages:
                for reservation in page.get("Reservations", []):
                    for instance in reservation.get("Instances", []):
                        tags = {tag["Key"]: tag["Value"] for tag in instance.get("Tags", [])}
                        writer.writerow(
                            {
                                "instance_id": instance.get("InstanceId", ""),
                                "name": tags.get("Name", ""),
                                "state": instance.get("State", {}).get("Name", ""),
                                "instance_type": instance.get("InstanceType", ""),
                                "availability_zone": instance.get("Placement", {}).get(
                                    "AvailabilityZone", ""
                                ),
                                "private_ip": instance.get("PrivateIpAddress", ""),
                                "public_ip": instance.get("PublicIpAddress", ""),
                            }
                        )
    except (BotoCoreError, ClientError, OSError) as error:
        print(f"Inventory failed: {error}", file=sys.stderr)
        return 1

    print(f"Inventory written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Example: `python3 ec2_inventory.py --region CHANGE_ME_REGION --profile CHANGE_ME_PROFILE --output reports/ec2.csv`.

---

## 14. Upload a backup to S3 (Python)

Uploads one local file to S3 using server-side encryption (SSE-S3) and verifies that the uploaded object has the expected size. For databases, Terraform state, or business-critical data, use a purpose-built backup procedure with retention, versioning, restore tests, and your required KMS key policy.

**Inputs:** local file path, bucket, and destination key are command-line arguments.

**Requirements:** `python3 -m pip install boto3`; S3 put/head permissions.

Save as `s3_backup.py`:

```python
#!/usr/bin/env python3
"""Upload one file to an encrypted S3 object and verify its size."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import boto3
from botocore.exceptions import BotoCoreError, ClientError


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--key", required=True, help="Destination object key")
    parser.add_argument("--region", required=True)
    parser.add_argument("--profile", help="Optional named AWS profile")
    args = parser.parse_args()

    if not args.source.is_file():
        parser.error(f"source file does not exist: {args.source}")

    try:
        session = boto3.Session(profile_name=args.profile, region_name=args.region)
        s3 = session.client("s3")
        s3.upload_file(
            str(args.source),
            args.bucket,
            args.key,
            ExtraArgs={"ServerSideEncryption": "AES256"},
        )
        result = s3.head_object(Bucket=args.bucket, Key=args.key)
        if result["ContentLength"] != args.source.stat().st_size:
            raise RuntimeError("S3 object size does not match the local source.")
    except (BotoCoreError, ClientError, OSError, RuntimeError) as error:
        print(f"Backup upload or verification failed: {error}", file=sys.stderr)
        return 1

    print(f"Verified s3://{args.bucket}/{args.key}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Example: `python3 s3_backup.py --source ./backup.tar.gz --bucket CHANGE_ME_BUCKET --key backups/backup.tar.gz --region CHANGE_ME_REGION`.

---

## 15. Kubernetes Deployment readiness validator (Python)

Checks that every selected Deployment has all requested replicas available. It is read-only and exits nonzero if any Deployment is not ready.

**Requirements:** `python3 -m pip install kubernetes`; kubeconfig or in-cluster identity with read access to Deployments.

Save as `k8s_validate_deployments.py`:

```python
#!/usr/bin/env python3
"""Check Deployment replica readiness in one namespace or across the cluster."""

from __future__ import annotations

import argparse
import sys

from kubernetes import client, config
from kubernetes.client.exceptions import ApiException


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--namespace", help="Namespace to inspect; omit to inspect all namespaces")
    parser.add_argument("--context", help="Optional kubeconfig context")
    args = parser.parse_args()

    try:
        try:
            config.load_incluster_config()
        except config.ConfigException:
            config.load_kube_config(context=args.context)
        apps = client.AppsV1Api()
        if args.namespace:
            deployments = apps.list_namespaced_deployment(args.namespace).items
        else:
            deployments = apps.list_deployment_for_all_namespaces().items
    except (ApiException, config.ConfigException, OSError) as error:
        print(f"Could not query Kubernetes Deployments: {error}", file=sys.stderr)
        return 1

    failures = []
    for deployment in deployments:
        metadata = deployment.metadata
        status = deployment.status
        desired = deployment.spec.replicas or 0
        ready = status.ready_replicas or 0
        available = status.available_replicas or 0
        name = f"{metadata.namespace}/{metadata.name}"
        if ready < desired or available < desired:
            failures.append(f"{name}: ready={ready}/{desired}, available={available}/{desired}")
        else:
            print(f"READY {name}: {ready}/{desired}")

    if failures:
        print("Deployment readiness failures:", file=sys.stderr)
        print("\n".join(failures), file=sys.stderr)
        return 1
    print(f"All {len(deployments)} selected Deployment(s) are ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

---

## 16. CI/CD Kubernetes manifest runner (Python)

Validates a manifest directory with server-side dry-run by default. Applying requires explicit `--apply`. An optional Deployment name adds a rollout wait after apply.

**Requirements:** Python 3.10+, `kubectl`, a Kubernetes identity allowed to dry-run/apply the manifests.

Save as `k8s_pipeline.py`:

```python
#!/usr/bin/env python3
"""Validate Kubernetes manifests; apply only when explicitly requested."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def run(command: list[str], *, allow_diff: bool = False) -> int:
    result = subprocess.run(command, check=False)
    if allow_diff and result.returncode == 1:
        return 0
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--context", help="Optional kubeconfig context")
    parser.add_argument("--deployment", help="Deployment name to wait for after apply")
    parser.add_argument("--apply", action="store_true", help="Apply after server-side validation")
    args = parser.parse_args()

    if not args.manifest.exists():
        parser.error(f"manifest path does not exist: {args.manifest}")
    base = ["kubectl"]
    if args.context:
        base += ["--context", args.context]
    base += ["--namespace", args.namespace]

    diff_code = run(base + ["diff", "--filename", str(args.manifest)], allow_diff=True)
    if diff_code:
        print("kubectl diff failed.", file=sys.stderr)
        return diff_code
    validation_code = run(
        base + ["apply", "--dry-run=server", "--filename", str(args.manifest)]
    )
    if validation_code:
        print("Server-side validation failed; no resources were changed.", file=sys.stderr)
        return validation_code
    if not args.apply:
        print("Validation succeeded; no resources were changed. Use --apply to deploy.")
        return 0

    apply_code = run(base + ["apply", "--filename", str(args.manifest)])
    if apply_code:
        return apply_code
    if args.deployment:
        return run(
            base
            + [
                "rollout",
                "status",
                f"deployment/{args.deployment}",
                "--timeout=5m",
            ]
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Examples:

```bash
python3 k8s_pipeline.py --manifest CHANGE_ME_MANIFEST_DIR --namespace CHANGE_ME_NAMESPACE
python3 k8s_pipeline.py --manifest CHANGE_ME_MANIFEST_DIR --namespace CHANGE_ME_NAMESPACE --deployment CHANGE_ME_DEPLOYMENT --apply
```

---

## 17. Azure login and AKS credentials (PowerShell)

Signs in with Azure CLI if necessary, selects an explicit subscription, obtains AKS credentials, and verifies the current kubectl context.

**Inputs to edit:** `$TenantId`, `$SubscriptionId`, `$ResourceGroup`, `$ClusterName`, `$KubeContext`.

**Requirements:** Azure CLI, kubectl, PowerShell 7+.

Save as `Connect-Aks.ps1`:

```powershell
$ErrorActionPreference = 'Stop'

$TenantId = 'CHANGE_ME_TENANT_ID'
$SubscriptionId = 'CHANGE_ME_SUBSCRIPTION_ID'
$ResourceGroup = 'CHANGE_ME_RESOURCE_GROUP'
$ClusterName = 'CHANGE_ME_AKS_CLUSTER'
$KubeContext = 'CHANGE_ME_KUBE_CONTEXT'

foreach ($value in @($TenantId, $SubscriptionId, $ResourceGroup, $ClusterName, $KubeContext)) {
    if ($value -like 'CHANGE_ME_*') { throw 'Replace all CHANGE_ME_* values before running.' }
}
foreach ($command in @('az', 'kubectl')) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) { throw "$command is required." }
}

az account show --output none 2>$null
if ($LASTEXITCODE -ne 0) {
    az login --tenant $TenantId
    if ($LASTEXITCODE -ne 0) { throw 'Azure login failed.' }
}

az account set --subscription $SubscriptionId
if ($LASTEXITCODE -ne 0) { throw 'Could not select the requested subscription.' }
az aks get-credentials --resource-group $ResourceGroup --name $ClusterName --context $KubeContext
if ($LASTEXITCODE -ne 0) { throw 'Could not retrieve AKS credentials.' }

kubectl config use-context $KubeContext
if ($LASTEXITCODE -ne 0) { throw 'Could not select the requested Kubernetes context.' }
kubectl config current-context
kubectl get nodes
if ($LASTEXITCODE -ne 0) { throw 'AKS connectivity check failed.' }
```

Run from PowerShell: `.\Connect-Aks.ps1`. This changes the current kubectl context; select the intended context before running deployment commands.

---

## 18. Install WSL Ubuntu (PowerShell)

Installs WSL and Ubuntu on a Windows machine. This is a host-level setup operation and may require a reboot; run it only on a machine you administer.

**Input:** change `$Distribution` if a different supported distro is approved.

**Requirements:** Windows 10/11 with WSL support; run PowerShell as Administrator if prompted by Windows.

Save as `Install-WslUbuntu.ps1`:

```powershell
$ErrorActionPreference = 'Stop'
$Distribution = 'Ubuntu'

if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
    throw 'wsl.exe was not found. Install or update Windows Subsystem for Linux on this host first.'
}

wsl.exe --list --quiet | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Could not query WSL distributions.' }

wsl.exe --install --distribution $Distribution
if ($LASTEXITCODE -ne 0) {
    throw "WSL installation returned exit code $LASTEXITCODE. Check Windows features, permissions, and reboot requirements."
}

Write-Host "WSL installation request completed for $Distribution."
Write-Host 'Complete the first-run Linux user setup, then run the Ubuntu bootstrap script from inside that distribution.'
```

On supported Windows builds the first run may request a reboot or username/password setup. Run the Ubuntu workstation bootstrap in the Linux shell afterward; Linux `sudo` commands do not run directly in PowerShell.

---

## 19. Encrypted, versioned Terraform state backup (PowerShell)

Copies an existing S3 state object server-side to a timestamped backup key. It requires destination bucket versioning and requests SSE-KMS encryption. Run only when Terraform operations are quiesced; this script does not acquire Terraform's state lock.

**Inputs to edit:** `$SourceBucket`, `$SourceKey`, `$BackupBucket`, `$Region`, `$KmsKeyId`.

**Requirements:** AWS CLI, PowerShell 7+, read access to source, write access to destination, KMS permissions.

Save as `Backup-TerraformState.ps1`:

```powershell
$ErrorActionPreference = 'Stop'

$SourceBucket = 'CHANGE_ME_SOURCE_STATE_BUCKET'
$SourceKey = 'CHANGE_ME_STATE_OBJECT_KEY'
$BackupBucket = 'CHANGE_ME_VERSIONED_BACKUP_BUCKET'
$Region = 'CHANGE_ME_AWS_REGION'
$KmsKeyId = 'CHANGE_ME_KMS_KEY_ID'
$Profile = 'CHANGE_ME_AWS_PROFILE'

foreach ($value in @($SourceBucket, $SourceKey, $BackupBucket, $Region, $KmsKeyId, $Profile)) {
    if ($value -like 'CHANGE_ME_*') { throw 'Replace all CHANGE_ME_* values before running.' }
}
if (-not (Get-Command aws -ErrorAction SilentlyContinue)) { throw 'AWS CLI is required.' }

$versioning = aws s3api get-bucket-versioning --bucket $BackupBucket --region $Region --profile $Profile --output json
if ($LASTEXITCODE -ne 0) { throw 'Could not inspect backup bucket versioning.' }
$versioningObject = $versioning | ConvertFrom-Json
if ($versioningObject.Status -ne 'Enabled') { throw 'Backup bucket versioning must be Enabled.' }

$timestamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ')
$destinationKey = "terraform-state-backups/$timestamp/$([IO.Path]::GetFileName($SourceKey))"
$sourceUri = "s3://$SourceBucket/$SourceKey"
$destinationUri = "s3://$BackupBucket/$destinationKey"

aws s3 cp $sourceUri $destinationUri --region $Region --profile $Profile `
    --sse aws:kms --sse-kms-key-id $KmsKeyId
if ($LASTEXITCODE -ne 0) { throw 'State backup copy failed.' }

aws s3api head-object --bucket $BackupBucket --key $destinationKey --region $Region --profile $Profile `
    --query '{Key:Key,VersionId:VersionId,Encryption:ServerSideEncryption,KmsKey:SSEKMSKeyId}' --output table
if ($LASTEXITCODE -ne 0) { throw 'Could not verify the copied backup object.' }
Write-Host "Backup created at $destinationUri"
```

Terraform state can contain secrets. Restrict source and destination access, use a dedicated KMS key, define retention/lifecycle policy, and test restore procedures. The timestamp in the destination key avoids overwriting the prior backup.

---

## 20. Workstation security baseline check (Bash)

Audits SSH private-key file permissions, UFW status, and recent high-priority system log entries. It reports findings without changing firewall, SSH daemon, or file permissions; those changes depend on whether the host is WSL, remote, or a physical workstation.

**Inputs:** no required inputs. Optional `--fix-key-permissions` changes only local SSH private-key permissions to `0600`.

Save as `workstation-security-check.sh`:

```bash
#!/usr/bin/env bash
set -Eeuo pipefail

FIX_KEYS=false
[[ $# -le 1 ]] || { echo "Usage: $0 [--fix-key-permissions]" >&2; exit 2; }
if [[ ${1:-} == --fix-key-permissions ]]; then FIX_KEYS=true
elif [[ $# -eq 1 ]]; then echo "Usage: $0 [--fix-key-permissions]" >&2; exit 2
fi

SSH_DIR="${HOME}/.ssh"
if [[ -d $SSH_DIR ]]; then
  while IFS= read -r -d '' key; do
    mode="$(stat -c '%a' "$key")"
    if [[ $mode != 600 ]]; then
      printf 'SSH private key has mode %s: %s\n' "$mode" "$key"
      if [[ $FIX_KEYS == true ]]; then chmod 600 -- "$key"; fi
    fi
  done < <(find "$SSH_DIR" -maxdepth 1 -type f -name 'id_*' ! -name '*.pub' -print0)
  if [[ $FIX_KEYS == true ]]; then chmod 700 "$SSH_DIR"; fi
else
  echo "No ~/.ssh directory found."
fi

if command -v ufw >/dev/null 2>&1; then
  echo "UFW status (review host/network requirements before enabling):"
  sudo ufw status verbose
else
  echo "UFW is not installed; no firewall changes were made."
fi

if command -v journalctl >/dev/null 2>&1; then
  echo "Recent priority 3 (error) system logs:"
  sudo journalctl --priority=3 --since='24 hours ago' --no-pager --lines=50
fi
```

Use the default mode first. Only use `--fix-key-permissions` after checking the listed files. Do not automatically enable UFW or disable SSH password authentication without a host-specific access and recovery plan.

---

## 21. Repository secret scan (Bash)

Scans the current Git repository with Gitleaks and requests redacted output. This avoids printing discovered secret values as the original generic `grep` examples could do.

**Requirements:** Gitleaks installed and available on `PATH`.

Save as `scan-secrets.sh`:

```bash
#!/usr/bin/env bash
set -Eeuo pipefail

REPOSITORY="${1:-.}"
command -v gitleaks >/dev/null || { echo "Install an organization-approved Gitleaks version first." >&2; exit 127; }
git -C "$REPOSITORY" rev-parse --show-toplevel >/dev/null \
  || { echo "Not a Git repository: $REPOSITORY" >&2; exit 2; }

gitleaks detect --source "$REPOSITORY" --redact --no-banner
```

Use the exit status in CI to fail a build when findings are detected. A clean scan does not prove that no secret exists. Rotate any credential that was committed or exposed; removing it from the latest commit is not sufficient.

---

## 22. Bash syntax and invocation quick reference

These are reusable syntax patterns; they are not separate cloud operations.

```bash
#!/usr/bin/env bash
set -Eeuo pipefail

NAME="example"
printf 'Name: %s\n' "$NAME"

if [[ -z ${TOKEN:-} ]]; then
  printf 'TOKEN is required\n' >&2
  exit 2
fi

for item in one two three; do
  printf '%s\n' "$item"
done

while IFS= read -r line; do
  printf '%s\n' "$line"
done < input.txt

deploy() {
  printf 'Deploying %s\n' "$1"
}
deploy "$NAME"

if command -v kubectl >/dev/null 2>&1; then
  kubectl version --client
else
  printf 'kubectl is not installed\n' >&2
  exit 127
fi
```

Save a Bash script as a text file, inspect it, then make it executable with `chmod 0755 script.sh` and run it as `./script.sh`. `"$1"` is the first argument; `"$?"` is the previous command's exit code. Prefer `if command; then ...` to checking `$?` later. `set -Eeuo pipefail` helps catch command failures, unset variables, and pipeline failures; still check expected nonzero statuses explicitly.

---

## Expansions, syntax walkthrough, and use cases

### What the script syntax means

- **Shebang:** `#!/usr/bin/env bash` asks the operating system to find Bash on `PATH` and use it to interpret the file.
- **Strict mode:** `set -Eeuo pipefail` stops many scripts at the first unexpected failure, treats unset variables as errors, and propagates errors through pipelines. It does not replace input validation or safe change controls.
- **Inputs:** `CHANGE_ME_...` marks a value you must edit. Quoted variables such as `"$NAMESPACE"` preserve spaces and avoid shell word splitting. Avoid putting credentials in these variables.
- **Arguments:** `--apply`, `--deploy-app`, and positional arguments make potentially changing behavior explicit. Defaults are read-only or plan-only wherever practical.
- **Functions:** `log`, `fail`, and `need_command` package repeated behavior such as timestamped messages and prerequisite checks.
- **Exit codes:** `0` means success; nonzero signals failure to a person or calling pipeline. Python scripts use `raise SystemExit(main())` to expose the same convention.
- **Pipelines:** `aws ... | docker login ...` streams a short-lived ECR authorization token to Docker's standard input rather than putting it in a command argument or file.
- **JSON handling:** `jq` and boto3/Kubernetes client objects inspect structured data instead of relying on fragile column positions in human-readable command output.
- **PowerShell native commands:** PowerShell scripts check `$LASTEXITCODE` after `az`/`aws` commands because a native CLI's failure does not always become a terminating PowerShell error.
- **Python subprocesses:** The CI runner passes an argument list to `subprocess.run` without a shell, preventing shell expansion of manifest paths or other inputs.

### What each script does and when to use it

| Script | Expansion / purpose | Typical use |
|---|---|---|
| Ubuntu/WSL bootstrap | Registers signed package sources and installs common cloud CLIs and DevOps tools. | New, managed Ubuntu development workstation. |
| AWS SSO + EKS deploy | Authenticates, selects the named EKS context, verifies access, applies a manifest, and waits for rollout. | Approved deployment run from a workstation or controlled runner. |
| Terraform wrapper | Formats, initializes, validates, plans, then applies only with `--apply`. | Repeatable Terraform runs with reviewed plan artifacts. |
| ECR build/push | Builds an image using a Git commit tag and pushes to the selected ECR registry/repository. | Container CI pipeline. |
| CrashLoop report | Detects failing containers and gathers pod descriptions without deleting pods. | Kubernetes incident triage. |
| Pod log collector | Collects current logs into a timestamped, private local directory. | Time-bounded troubleshooting evidence collection. |
| Rollout validator | Waits for one Deployment to become ready. | Post-deploy health gate in CI/CD. |
| GitOps image update | Changes a Helm values tag, commits the change, and pushes the approved branch. | Image promotion through a GitOps controller. |
| Argo CD sync | Requests and waits for sync/health of one named application. | Explicit, authorized manual synchronization. |
| Argo CD drift check | Reports OutOfSync apps and exits nonzero; makes no changes. | Monitoring or a deployment pre-check. |
| Terraform + Kubernetes pipeline | Separates infrastructure apply and application deploy behind independent flags. | Environments where infra and app changes share an orchestrated run. |
| Backend/cluster health check | Confirms state bucket/table access and lists cluster information/nodes. | Preflight before a planned maintenance or deployment. |
| EC2 inventory | Uses boto3 pagination to export a region's instance inventory. | Asset inventory, audit, or reporting. |
| S3 backup | Uploads one local file with server-side encryption and verifies object size. | Basic file backup; use a dedicated process for critical data. |
| Deployment readiness validator | Checks desired, ready, and available replica counts. | Read-only deployment health gate. |
| CI/CD manifest runner | Server-side dry-run first; only applies with `--apply`. | Kubernetes deployment job with explicit authorization. |
| Azure/AKS connector | Signs in, selects a subscription, and updates the local kube context. | Azure operator workstation or authorized runner. |
| WSL installer | Requests installation of WSL Ubuntu on Windows. | User-administered Windows development machine. |
| Terraform state backup | Server-side copies state into a versioned, KMS-encrypted destination bucket. | Quiesced maintenance window and tested recovery process. |
| Security baseline check | Checks local private-key permissions, firewall status, and recent system errors. | Workstation audit; optional key permission correction. |
| Secret scan | Runs Gitleaks with redaction and surfaces its exit code. | Local pre-commit check or CI security gate. |

### Production-use checklist

1. Replace all `CHANGE_ME_...` inputs and verify the account, region, project, cluster, namespace, branch, and file paths.
2. Review the script and the plan/diff before using any mutating flag.
3. Use least-privilege roles and short-lived identity; never place credentials in source files or shell history.
4. Keep Terraform plans and collected logs out of public artifacts; both may contain sensitive information.
5. Use locking, approvals, immutable image tags, protected branches, and cluster context safeguards.
6. Test restore procedures and backup retention rather than treating a successful upload as proof of recoverability.
7. Pin package, CLI, and Python dependency versions according to your organization's lifecycle and supply-chain policy.
8. Run shell linting (for example ShellCheck), Python lint/type checks, and script tests in CI before adopting these examples.

Duplicate examples in the source notes (such as the AWS/EKS login, Terraform wrapper, and workstation setup) are consolidated here. Unsafe shortcuts—such as deleting CrashLoop pods automatically, scraping secrets with `grep`, changing SSH/firewall policy without host context, or applying Terraform without reviewing a saved plan—are intentionally replaced with safer report, validation, or explicit-approval behavior.
