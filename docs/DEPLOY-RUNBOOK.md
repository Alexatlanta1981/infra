# Setup runbook: stop before infrastructure apply

Follow `0.A`, `0.B`, then the remaining substeps in order. Stop on errors.
Use your own AWS account, SSO profile, GitHub owner, and state bucket.
Keep SSO, STS, GitHub OIDC, and IRSA; do not use static AWS keys.

This runbook is reusable for this project's `infra`, `backend`, `frontend`, and
`gitops` repositories. Supply values from your own AWS and GitHub environment.
It is not a generic procedure for differently named repositories or workloads;
the account must already have this project's GitHub OIDC provider and Terraform
plan/apply roles.

**Scope:** your AWS account already has the GitHub OIDC provider and Terraform
plan/apply roles. Fresh-account onboarding is not part of this procedure.
The bucket script creates storage only; it does not establish AWS trust.

## 0. Workstation tools (once)

### 0.A Install tools

Before bootstrap: Git, GitHub CLI (`gh`), AWS CLI v2, Terraform >= 1.11,
and OpenSSL. Later cluster steps also need Python >= 3.10, kubectl, Helm, and yq.

### 0.B Set your inputs

Run this in an Ubuntu/WSL Bash terminal and answer the prompts. Keep this
terminal open so the values remain available to later commands.

```bash
read -r -p "AWS SSO profile name: " AWS_PROFILE
read -r -p "AWS region [us-east-1]: " AWS_REGION_INPUT
read -r -p "GitHub owner for the four repositories: " GITHUB_ORG
read -r -p "Workspace directory [$HOME/devops]: " WORKSPACE_INPUT
AWS_REGION=${AWS_REGION_INPUT:-us-east-1}
WORKSPACE=${WORKSPACE_INPUT:-$HOME/devops}
while [[ -z "$AWS_PROFILE" ]]; do
  read -r -p "AWS SSO profile name (required): " AWS_PROFILE
done
while [[ -z "$GITHUB_ORG" ]]; do
  read -r -p "GitHub owner (required): " GITHUB_ORG
done
export AWS_PROFILE AWS_REGION GITHUB_ORG WORKSPACE
printf 'AWS_PROFILE=%s\nAWS_REGION=%s\nGITHUB_ORG=%s\nWORKSPACE=%s\n' \
  "$AWS_PROFILE" "$AWS_REGION" "$GITHUB_ORG" "$WORKSPACE"
```

### 0.C Authenticate and verify

If your SSO profile does not exist, configure it first:

```bash
aws configure sso --profile "$AWS_PROFILE"
```

Then:

```bash
gh auth login
aws sso login --profile "$AWS_PROFILE" &&
aws sts get-caller-identity --profile "$AWS_PROFILE" &&
gh auth status
```

**Check:** intended AWS account and GitHub login. Your SSO assignment needs
administrator permissions for first-time bootstrap. SSO does not grant access
to someone else's AWS account.

## 1. Clone the four repos

### 1.A Use repositories you administer

For your own deployment, fork/copy `infra`, `backend`, `frontend`, and `gitops`
under your GitHub owner, keeping those names. Forks do not inherit Actions settings.

This creates missing clones and reuses existing Git clones only when their
`origin` points to the matching repository under your GitHub owner.

```bash
mkdir -p "$WORKSPACE" &&
cd "$WORKSPACE" || exit 1
for repo in infra backend frontend gitops; do
  if git -C "$repo" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    origin=$(git -C "$repo" remote get-url origin) || exit 1
    case "$origin" in
      "https://github.com/$GITHUB_ORG/$repo"|"https://github.com/$GITHUB_ORG/$repo.git"|"git@github.com:$GITHUB_ORG/$repo"|"git@github.com:$GITHUB_ORG/$repo.git")
        ;;
      *)
        printf 'Error: %s origin is %s, not your expected GitHub repository; inspect it before continuing.\n' "$repo" "$origin" >&2
        exit 1
        ;;
    esac
    printf 'Using existing clone: %s/%s\n' "$WORKSPACE" "$repo"
  elif [[ -e "$repo" ]]; then
    printf 'Error: %s exists but is not a Git clone; inspect it before continuing.\n' "$repo" >&2
    exit 1
  else
    git clone "https://github.com/$GITHUB_ORG/$repo.git" "$repo" || exit 1
  fi
done
```

### 1.B Update an existing infra clone

```bash
cd "$WORKSPACE/infra"
git status --short
```

If output is not empty, preserve your changes before continuing. Otherwise:

```bash
cd "$WORKSPACE/infra"
git switch main &&
git pull --ff-only origin main &&
bash scripts/00_create_state_bucket.sh --help &&
bash scripts/00_setup_github_settings.sh --help
```

The `--help` calls run each script without changing AWS or GitHub. The bucket
script is run for real only in step 2.A for a genuinely new deployment. The
GitHub settings script is run for real in step 3.B. Another worktree does not
update this clone.

## 2. One-time AWS prerequisites

### 2.A Select the state bucket

**Existing deployment:** read the existing CI bucket; do not create a replacement.

```bash
cd "$WORKSPACE/infra"
STATE_BUCKET=$(gh variable get TF_STATE_BUCKET --repo "$GITHUB_ORG/infra") &&
export STATE_BUCKET &&
printf 'State bucket: %s\n' "$STATE_BUCKET"
```

Verify the bucket and both state keys:

```bash
aws s3api get-bucket-versioning --bucket "${STATE_BUCKET:?Set STATE_BUCKET}" &&
aws s3api head-object --bucket "$STATE_BUCKET" --key envs/bootstrap/terraform.tfstate &&
aws s3api head-object --bucket "$STATE_BUCKET" --key envs/dev/terraform.tfstate
```

**Check:** versioning `Enabled`; both objects exist. Missing outputs do not mean
missing infrastructure. If the bucket is unknown or unexpected, stop and recover
the original state before planning.

**New bucket only:** confirm there is no existing deployment/state to preserve,
and that GitHub OIDC and CI roles already exist, then:

```bash
read -r -p "New globally unique Terraform state bucket name: " STATE_BUCKET
while [[ -z "$STATE_BUCKET" ]]; do
  read -r -p "Bucket name is required; enter it to continue: " STATE_BUCKET
done
export STATE_BUCKET
cd "$WORKSPACE/infra/scripts" &&
bash ./00_create_state_bucket.sh "$STATE_BUCKET"
```

Check the displayed account, region, and bucket before answering `y`.
Expect versioning `Enabled`. Keep `terraform` in the name: the current CI
plan-role state policy matches bucket names containing it.

### 2.B Generate OIDC subjects

```bash
cd "$WORKSPACE/infra/scripts" &&
SUBJECTS_JSON=$(bash ./00_oidc_subjects.sh) &&
export SUBJECTS_JSON &&
printf '%s\n' "$SUBJECTS_JSON"
```

**Check:** JSON contains your owner/repository IDs for all four repos.

### 2.C Initialize bootstrap

```bash
cd "$WORKSPACE/infra/envs/bootstrap"
terraform init -backend-config="bucket=${STATE_BUCKET:?Set STATE_BUCKET}"
```

**Wrong local backend:** first verify and privately back up the original state,
including historical versions and delete-marker metadata. Then reconnect:

```bash
cd "$WORKSPACE/infra/envs/bootstrap"
terraform init -reconfigure -backend-config="bucket=${STATE_BUCKET:?Use the verified original bucket}"
```

Reconfiguration does not migrate state. Check the dev backend separately using
the same bucket and its distinct state key. Never commit state or backup files.

### 2.D Review bootstrap plan

```bash
cd "$WORKSPACE/infra/envs/bootstrap"
terraform plan -var="github_repo_subject_prefixes=${SUBJECTS_JSON:?Generate subjects first}"
```

**Existing deployment:** expect `No changes` when unchanged. Do not apply an
unexpected import/create plan for resources that already exist.

Do not repeat local bootstrap apply. Missing roles or unmanaged existing roles
and OIDC providers require a separate reviewed setup/adoption procedure.
Stop rather than creating duplicate ownership.

### 2.E Verify role outputs

```bash
cd "$WORKSPACE/infra/envs/bootstrap"
terraform output
```

**Check:** `terraform_plan_role_arn` and `terraform_apply_role_arn` use your account.

## 3. GitHub settings for `infra`

### 3.A Find your SSO admin role

```bash
aws iam list-roles --profile "$AWS_PROFILE" \
  --query "Roles[?contains(RoleName,'AWSReservedSSO_')].Arn" --output json
```

Select the IAM role used by your administrator profile, including its path.
Use `arn:aws:iam::...:role/...`, not the STS session ARN.

### 3.B Run settings setup

```bash
cd "$WORKSPACE/infra/scripts" &&
bash ./00_setup_github_settings.sh
```

Enter your SSO admin role ARN. Enter preserves an existing value or skips it;
skipping does not grant EKS access. Check the summary, then answer `y`.
Your signed-in GitHub user becomes the required reviewer.

The script saves bucket, role, owner, and subject variables; preserves an existing
JWT secret; and disables administrator bypass. It stops on unsupported protection
or conflicting reviewers. Do not bypass that failure or run with `bash -x`.

### 3.C Verify settings and approval

```bash
gh variable list -R "$GITHUB_ORG/infra"
gh secret list -R "$GITHUB_ORG/infra"
gh api "repos/$GITHUB_ORG/infra/environments/dev" \
  --jq '{name,can_admins_bypass,protection_rules}'
```

**Check:** `GH_ORG`, `TF_STATE_BUCKET`, both role ARN variables, `GH_REPO_SUBJECTS`,
your `SSO_ADMIN_ROLE_ARN`, and the secret name `DEV_JWT_SECRET`.
`dev` must show the intended reviewer and `can_admins_bypass: false`.
Secret values must not appear in output.

### 3.D Verify OIDC on your repositories

```bash
for repo in infra backend frontend gitops; do
  printf '\nOIDC settings for %s/%s:\n' "$GITHUB_ORG" "$repo"
  gh api "repos/$GITHUB_ORG/$repo/actions/oidc/customization/sub" || {
    printf 'Failed to read OIDC settings for %s/%s; stopping.\n' "$GITHUB_ORG" "$repo" >&2
    exit 1
  }
done
```

**Check:** `use_default: true`, `use_immutable_subject: true`, and each
`sub_claim_prefix` matches its generated JSON entry. Stop on mismatch or error;
resolve with the repository administrator. Do not weaken trust or change STS.

## 4. CI plans: current stopping point

### 4.A Submit changes through a PR

With a clean checkout, create a working branch and make the intended edits:

```bash
cd "$WORKSPACE/infra"
git switch -c setup/my-change
```

Stage only intended files, commit, and push the working branch. Never push to main.
Then:

```bash
cd "$WORKSPACE/infra"
git push -u origin HEAD &&
gh pr create --base main --fill
```

### 4.B Review CI once, without polling

```bash
cd "$WORKSPACE/infra"
gh pr checks
```

In GitHub, review **Terraform Plan**, **Bootstrap Plan**, and **security-scan**.
Check script tests when scripts change. Pending checks are not success.
Read the plan totals and resource changes; a green check alone is not approval.

### 4.C Stop before apply

- Bootstrap plan should have no unintended changes.
- Dev plan must target your account, bucket, repositories, and SSO role.
- Required checks must pass before an approved merge.
- Changes under bootstrap/dev/modules can queue apply after merge.
- Leave deployment approval pending. Do not dispatch apply or approve a queued run.
- Manual `bootstrap.yml` dispatch is **not plan-only**.
- Never run `envs/dev` apply locally. EKS/RDS infrastructure incurs AWS charges.

## After explicit apply approval

Proceed only after your intended CI apply succeeds. The full later procedure remains in
[the detailed deployment reference](DEPLOY-REFERENCE.md#4-create-the-aws-infrastructure-terraform-via-git).

## 5. Connect kubectl

After successful CI apply, follow [cluster access](DEPLOY-REFERENCE.md#5-connect-kubectl).

## 6. GitHub App for CI and Argo CD

### 6.A Create or reuse the writer App for CI

**Check existing settings first:**

```bash
for repo in backend frontend; do
  gh variable list -R "$GITHUB_ORG/$repo" --env dev
  gh secret list -R "$GITHUB_ORG/$repo" --env dev
done
```

If both have the same `GITOPS_APP_ID` and `GITOPS_APP_PRIVATE_KEY` secret name,
verify that App below; do not create a duplicate. Secret listings do not verify
the key's value. The script cannot adopt an existing App from its ID alone.

**New App: prepare GitHub.** In both `backend` and `frontend`, open
**Settings → Environments → New environment**, name it `dev` if absent.
Use a GitHub login with repo admin access and permission to create Apps for the owner.

**Run the script locally after its PR is merged:**

```bash
cd "$WORKSPACE/infra"
git status --short
```

If clean, update and run:

```bash
cd "$WORKSPACE/infra"
git switch main &&
git pull --ff-only origin main &&
cd scripts &&
python3 00_setup_writer_app.py --owner "$GITHUB_ORG" \
  --credentials-dir "$HOME/.config/infra-writer-app"
```

1. Confirm creation; enter a unique App name.
2. Open the printed local URL in a browser on the same machine.
3. Click **Create writer App on GitHub** and confirm the owner/name.
4. Open the printed installation link. Choose **Only select repositories → gitops**.
5. Return to the terminal, press Enter for verification, then confirm settings writes.

The manifest sets **Contents: write, Pull requests: write, Metadata: read**.
The script stores `GITOPS_APP_ID` as a variable and `GITOPS_APP_PRIVATE_KEY` as
a secret in **backend/dev and frontend/dev**, not infra. It prints no key values.
Keep its private recovery file outside Git; use `--resume` after interruptions.

**Where to verify in GitHub:**

- Organization owner: **organization Settings → Developer settings → GitHub Apps**.
  Personal owner: **account Settings → Developer settings → GitHub Apps**.
- Open the writer App. Check **App ID** and **Permissions & events** against the
  permissions above.
- Open **Install App → your owner → Configure**. Confirm only `gitops` is selected.
- In each backend/frontend repo, open **Settings → Environments → dev**.
  Verify matching App IDs and the private-key secret name; never reveal the key.
- In `gitops`, open **Settings → Rules → Rulesets → main ruleset → Bypass list**.
  If required for automated tag pushes, add this writer App only after approval.
  The script does not change rulesets.

Repeat the listing commands above. In each repo, also verify `GITOPS_REPO`:

```bash
for repo in backend frontend; do
  gh variable get GITOPS_REPO -R "$GITHUB_ORG/$repo"
done
```

Expect your `owner/gitops`. Set missing values in
**Settings → Secrets and variables → Actions → Variables**.
An existing CI deploy job with successful **Generate short-lived GitOps token**,
**Checkout GitOps repo**, and **Update image tag — DEV** verifies actual use.
Do not trigger an image build just to inspect settings.

Manual creation and recovery details: [reference 6.A](DEPLOY-REFERENCE.md#6a-create-the-writer-app-for-ci).

### 6.B Create or verify the reader App for Argo CD

Use a **different App** with Contents: read and Metadata: read, installed on
`gitops` only. Keep its App ID, installation ID, and private `.pem` path for script 02.
Follow [reader setup](DEPLOY-REFERENCE.md#6b-create-the-reader-app-for-argo-cd).

### 6.C Find the installation ID

Open the reader App's **Install App → owner → Configure** page.
Use the final number in its installation URL, not the App ID.

### 6.D Check remaining CI settings

Follow [the settings table](DEPLOY-REFERENCE.md#6d-enter-github-app-and-ci-values).
Sonar organization/project keys and token creation instructions are deferred
until the end; the current table lists destinations only.

### 6.E Verify before Helm

Writer settings and repository scope verified; reader App IDs and local private
key available; intended cluster nodes ready. Never share keys in logs or a PR.

## 7. Install cluster components

### 7.A Install cluster prerequisites (script 01)

Follow [script 01 and private password retrieval](DEPLOY-REFERENCE.md#7a-install-cluster-prerequisites-script-01).
Never print credentials in CI or share terminal recordings.

Run this in the same Ubuntu/WSL Bash terminal after the cluster is ready. The
script prompts for your cluster name, region, ALB IRSA role ARN, and GitOps path;
it does not guess project/environment names. It uses AWS SSO and discovers the VPC.

```bash
cd "$WORKSPACE/infra/scripts" &&
python3 01_install_prerequisites.py
```

Argo CD Ingress is off by default (port-forward access). Enable it explicitly
with your hostname and ACM certificate; choose the ALB scheme and optional
group for your deployment. The script prompts for these values if you choose
to enable Ingress; do not paste example hostnames or certificate ARNs literally.

### 7.B Connect Argo CD to gitops (script 02)

Follow [script 02](DEPLOY-REFERENCE.md#7b-connect-argo-cd-to-gitops-script-02)
with your own GitOps URL and reader App credentials.

```bash
cd "$WORKSPACE/infra/scripts" &&
python3 02_bootstrap_argocd.py
```

### 7.C Configure External Secrets (script 03)

Follow [script 03 and verification](DEPLOY-REFERENCE.md#7c-configure-external-secrets-script-03).

```bash
cd "$WORKSPACE/infra/scripts" &&
python3 03_setup_external_secrets.py
```

## 8. Build the images

Follow [image builds](DEPLOY-REFERENCE.md#8-build-the-images).

## 9. Deploy and verify

Follow [deployment checks](DEPLOY-REFERENCE.md#9-deploy-and-verify).

## 10. Day-2 changes

Follow [PR and rollout steps](DEPLOY-REFERENCE.md#10-day-2-shipping-a-change).

## 11. Tear down

Requires separate approval. Follow [reverse-order teardown](DEPLOY-REFERENCE.md#11-tear-down-reverse-order-terraform-last);
verify account/cluster and preserve the state bucket and bootstrap CI identity.
To retain Terraform infrastructure and ECR images, use
[Script 07 tag preservation and Kubernetes-only teardown](DEPLOY-REFERENCE.md#tag-backup-and-kubernetes-only-rebuild)
instead of the AWS destroy phase. Script 07 defaults to backup only; teardown
still requires separate approval.
After Script 07 succeeds, a separately approved
[full dev Terraform destroy](DEPLOY-REFERENCE.md#11e-destroy-aws-vpc-eks-rds-ecr-workload-iam-via-ci)
also deletes ECR images. The tag JSON cannot restore image content; fresh image
builds are required afterward. ECR recovery/reuse changes remain deferred.

## Troubleshooting

| Problem | Action |
|---|---|
| Missing script | Update the correct clone; use the `cd` above its command. |
| Expired SSO | Repeat step 0.C with your profile. |
| Missing outputs or duplicate IAM creation | Verify original state; do not create another bucket. |
| Backend changed | Step 2.C; back up before reconfiguration or intentional migration. |
| GitHub protection/OIDC failure | Stop; resolve permissions/configuration without weakening authentication. |

More detail: [troubleshooting reference](DEPLOY-REFERENCE.md#troubleshooting).
