# Detailed deployment reference

For the short, current setup procedure, use [DEPLOY-RUNBOOK](DEPLOY-RUNBOOK.md). Stop there before infrastructure apply. This reference preserves the extended explanations and later cluster, application, and teardown procedures; it is not authorization to deploy or destroy.

Order matters. Run every command from a terminal (Ubuntu/WSL). Replace `<ORG>` with your GitHub org/user and `<ACCOUNT_ID>` with your AWS account ID.

Repos: `infra`, `backend`, `frontend`, `gitops`, all under `<ORG>`.

**How to use this:** follow the steps in order. Each step tells you where to go, what to create, and where to enter the result. Complete the **Verify** check before continuing.

Each numbered step has lettered substeps. Follow them in order: `1.A`, then `1.B`, then `1.C`, before moving to `2.A`. Troubleshooting sections are used only if that step fails.

**Reading commands and output:** copy only the `bash` command blocks, not the example output blocks or your terminal prompt (`chris@...$`). Replace placeholders before running commands; never type the angle brackets. All outputs below are illustrative, not results from your account. IDs, ARNs, versions, timestamps, pod names, and resource counts will differ. A command returning successfully is not enough: check the expected values. Stop on an error rather than proceeding to the next step.

Use the same terminal throughout bootstrap so `AWS_PROFILE`, `AWS_REGION`, `STATE_BUCKET`, `GITHUB_ORG`, and `SUBJECTS_JSON` remain set. In a new terminal, set them again. Every script command below has its working directory above it. If your clones are elsewhere, replace `~/devops` with your actual clone location.

**Change policy:** Human changes to the repos go through pull requests; push only a working branch to open the PR, never a human commit directly to `main`. Merge only after review and required CI checks pass. Terraform changes are applied by GitHub Actions after merge, with approval in the `dev` environment. CI's automated image-tag update to `gitops` is described in step 8.

| Step | What you do | Time |
|---|---|---|
| 0-1 | Install tools, clone repos | 10 min |
| 2-3 | AWS state bucket + CI login roles, GitHub settings | 15 min |
| 4-5 | Terraform builds AWS (VPC, EKS, RDS), connect kubectl | 25 min |
| 6 | Create the two GitHub Apps (writer + reader) | 15 min |
| 7 | Install cluster add-ons (scripts 01-03) | 10 min |
| 8 | Build images (script 04) | 15 min |
| 9 | Deploy and check (script 05) | 5 min |
| 10-11 | Day-2 changes, tear down | - |

## Prerequisites

This runbook assumes you already have:

- An **AWS account** with **IAM Identity Center (SSO)** set up and a user with administrator access to that account (permission set + account assignment).
- A **GitHub org or user** where you can create repos, Actions variables/secrets, environments and GitHub Apps.
- Working knowledge of Terraform, Kubernetes and GitHub Actions.

Account setup, SSO and billing are out of scope here.

## What runs where

| Step | Where it runs | Credentials |
|---|---|---|
| State bucket, `envs/bootstrap` (OIDC provider + CI roles) | Your workstation, once | Your SSO admin login (CI cannot do this: it needs these roles to log in) |
| Terraform for VPC, EKS, RDS | GitHub Actions: PR runs plan, merge runs apply (pauses for approval in the `dev` environment) | OIDC roles from bootstrap |
| Scripts 01-03 (cluster add-ons), 05 (deploy) | Your workstation | SSO login + kubectl access to the cluster |
| Script 04 (image builds) | Triggers GitHub Actions workflows in `backend` and `frontend` | GitHub App + OIDC |
| Every change after setup | Pull request, then CI | none locally |

## 0. Workstation tools (once)

### 0.A Install the required tools

In an Ubuntu/WSL terminal, install `git`, `gh`, AWS CLI v2, Terraform >= 1.11, `kubectl`, `helm`, `yq`, `openssl`, and Python >= 3.10.

### 0.B Sign in to GitHub and AWS

Choose a local AWS profile name, for example `mackllc-admin`. Replace `mackllc-admin` below and anywhere else it appears with your chosen name. When `aws configure sso` prompts you, enter your IAM Identity Center start URL, SSO region, AWS account, and permission set. The profile is saved on your workstation in `~/.aws/config`; do not enter it in GitHub.

```bash
gh auth login
aws configure sso --profile mackllc-admin
aws sso login --profile mackllc-admin
export AWS_PROFILE=mackllc-admin AWS_REGION=us-east-1
aws sts get-caller-identity        # must show <ACCOUNT_ID>
```

Example identity output (use your actual account, not this sample):

```text
{
    "UserId": "AROAXXXXXXXXXXXXXXXX:your-user",
    "Account": "123456789012",
    "Arn": "arn:aws:sts::123456789012:assumed-role/AWSReservedSSO_AdministratorAccess_example/your-user"
}
```

Confirm `Account` is the intended AWS account. If login or identity verification fails, do not continue.

Keep using this terminal so `AWS_PROFILE` remains set. In a new terminal, run `export AWS_PROFILE=mackllc-admin AWS_REGION=us-east-1` again. AWS CLI and Terraform use this local profile.

### 0.C Verify tools and authentication

**Verify:** `git --version && gh --version && aws --version && terraform version && kubectl version --client && helm version --short && yq --version && python3 --version` all print versions. `gh auth status` says logged in.

Example output excerpts (versions and formatting vary):

```text
git version 2.x.x
gh version 2.x.x
aws-cli/2.x.x ...
Terraform v1.11.x
Client Version: v1.x.x
v3.x.x+...
yq ... version ...
Python 3.12.x
github.com
  ✓ Logged in to github.com account your-user
```

If a command says `command not found`, install that tool before continuing. Terraform must be at least 1.11 and AWS CLI must be v2.

## 1. Clone the four repos

### 1.A Clone into your working directory

For an independent demo, first fork or copy all four repositories into your own GitHub owner, keeping their names. Clone your copies below, not the original author's repositories. You need repository administration permission to configure Actions and deployment approval. Use your own AWS account and SSO assignment; neither credentials nor account access are included with the source code.

In an Ubuntu/WSL terminal, replace `<ORG>` with the GitHub username or organization that owns the four repositories. This creates four local folders under `~/devops`.

```bash
mkdir -p ~/devops && cd ~/devops
for r in infra backend frontend gitops; do git clone https://github.com/<ORG>/$r.git; done
```

### 1.B Check the local repositories

**Verify:** `ls ~/devops` lists `infra backend frontend gitops`.

Example output (other folders may also be present):

```text
backend  frontend  gitops  infra
```

If you already cloned the repos, do not clone over them. Ensure your local checkout contains the approved script changes before step 2; a script in another branch or isolated worktree is not automatically available in this clone.

## 2. One-time AWS prerequisites

### 2.A Select your AWS profile and working directory

Run these commands in your workstation's Ubuntu/WSL terminal from `~/devops/infra`. They use the AWS profile from step 0 to create the state bucket, GitHub OIDC provider, and CI roles in your AWS account. The profile name stays local; it is not a Terraform variable or GitHub setting.

If you opened a new terminal, set the profile again before running these commands:

```bash
export AWS_PROFILE=mackllc-admin AWS_REGION=us-east-1
cd ~/devops/infra
```

### 2.B Select the existing state bucket, or create one for a fresh setup

**Existing deployment: do not create another bucket.** First read the bucket already configured for CI:

```bash
cd ~/devops/infra
export GITHUB_ORG=your-github-owner
STATE_BUCKET=$(gh variable get TF_STATE_BUCKET --repo "$GITHUB_ORG/infra") &&
export STATE_BUCKET &&
printf 'Existing state bucket: %s\n' "$STATE_BUCKET"
```

If the variable is missing, empty, or points to an unexpected bucket, stop and inspect the existing deployment and backend before creating anything. Missing local Terraform outputs do not prove that AWS resources or remote state are missing.

Use your own deployment's bucket in `us-east-1`. Keep both `envs/bootstrap/terraform.tfstate` and `envs/dev/terraform.tfstate` there. A new empty bucket hides the existing state from Terraform; it does not move state or make existing IAM resources new.

Verify the selected bucket and state objects without displaying state contents:

```bash
aws s3api get-bucket-versioning --bucket "${STATE_BUCKET:?Set STATE_BUCKET}" &&
aws s3api head-object --bucket "$STATE_BUCKET" --key envs/bootstrap/terraform.tfstate &&
aws s3api head-object --bucket "$STATE_BUCKET" --key envs/dev/terraform.tfstate
```

Expect versioning `Enabled` and metadata for both state objects. Stop on an error. Skip bucket creation and follow step 2.C, then the existing-deployment instructions in step 2.D.

**Fresh setup only:** use the creation script below after confirming there is no existing state or deployment to preserve.

Run this once, before Terraform bootstrap and before scripts 01-06. Choose a globally unique S3 bucket name using lowercase letters, numbers, and hyphens, for example `mackllc-terraform-state-123456789012`. Set `STATE_BUCKET` to your chosen name, without angle brackets:
   ```bash
   export STATE_BUCKET=your-unique-lowercase-state-bucket
   cd ~/devops/infra/scripts
   ./00_create_state_bucket.sh "$STATE_BUCKET"
   ```
   The bucket name is the script's only command argument. It uses the local `AWS_PROFILE` and `AWS_REGION` set above; this runbook's Terraform backends use `us-east-1`.

   The script checks that the AWS CLI is available, gets your active AWS account ID, and displays the account, region, and bucket name. At `Create this bucket and enable versioning? [y/N]`, check the displayed information and type `y` to create the bucket, or `n` (or Enter) to cancel without changes.

   After confirmation, it creates the S3 bucket, enables versioning, verifies that versioning is `Enabled`, and prints a creation report with the AWS account, region, bucket name, versioning status, and AWS `create-bucket` response. It does not run Terraform or change GitHub settings. If an AWS command fails, the script stops; a bucket already created is not automatically deleted.

   **Verify:** the creation report shows versioning `Enabled`. Do not continue after cancellation or an error. Keep the exact bucket name; use it for Terraform initialization below and for `TF_STATE_BUCKET` in step 3. Do not re-run this creation script for an existing bucket.

   Example prompt and successful report:

   ```text
   AWS account: 123456789012
   Region:      us-east-1
   Bucket:      your-unique-lowercase-state-bucket
   Create this bucket and enable versioning? [y/N] y

   Bucket creation report
   AWS account: 123456789012
   Region:      us-east-1
   Bucket:      your-unique-lowercase-state-bucket
   Versioning:  Enabled
   AWS create-bucket response:
   {
       "Location": "/your-unique-lowercase-state-bucket"
   }
   ```

   AWS may include additional fields in the creation response. Cancellation prints `Cancelled; no AWS resources were changed.` If you are already in `infra/scripts`, the command is `./00_create_state_bucket.sh`, not `scripts/00_create_state_bucket.sh`. If the file is missing, check your checkout; changing directories does not download a missing script.

### 2.C Generate the GitHub CI login JSON

Replace `your-github-owner` below with the owner of all four repositories (for example, `Alexatlanta1981`). The script asks GitHub for the owner and repository IDs. Capture its entire JSON output automatically so no braces or quotes are lost:
   ```bash
   export GITHUB_ORG=your-github-owner
   cd ~/devops/infra/scripts
   SUBJECTS_JSON=$(./00_oidc_subjects.sh) &&
   printf '%s\n' "$SUBJECTS_JSON"
   ```

   Example output (all IDs below are dummy values):

   ```json
   {"infra":"repo:your-github-owner@111111/infra@222221","backend":"repo:your-github-owner@111111/backend@222222","frontend":"repo:your-github-owner@111111/frontend@222223","gitops":"repo:your-github-owner@111111/gitops@222224"}
   ```

   **Verify:** all four entries, including `infra`, are present. This JSON is not bucket information and does not go into script 00. It is the value of Terraform's `github_repo_subject_prefixes` variable and, later, GitHub's `GH_REPO_SUBJECTS` repository variable. Use the real output, not the sample above. If the script fails, stop and check `gh auth status`, the owner, and access to all four repos.

### 2.D Initialize and apply Terraform bootstrap

**Existing deployment: verify, do not repeat the first-time apply.** Use the bucket identified in step 2.B and the subjects generated in step 2.C:

```bash
cd ~/devops/infra/envs/bootstrap
terraform init -backend-config="bucket=${STATE_BUCKET:?Set STATE_BUCKET}" &&
terraform output &&
terraform plan -var="github_repo_subject_prefixes=${SUBJECTS_JSON:?Generate SUBJECTS_JSON in step 2}"
```

Expect both role ARNs and, for an unchanged bootstrap, `No changes. Your infrastructure matches the configuration.` If initialization reports a backend change, follow the recovery guidance below first. If the plan unexpectedly proposes creating or importing existing IAM roles or the OIDC provider, stop and check the selected state bucket. Do not approve that plan. Once the existing outputs are verified, continue to step 3; subsequent changes go through a PR and CI.

**Fresh setup only:** the following local apply is needed only before CI roles exist.

Run from `envs/bootstrap`, not the repository root and not `scripts`. The root `infra` folder has no Terraform configuration. Before applying, display the working directory and saved inputs:
   ```bash
   cd ~/devops/infra/envs/bootstrap
   pwd
   ls *.tf
   printf 'Bucket: %s\nSubjects: %s\n' "$STATE_BUCKET" "$SUBJECTS_JSON"
   ```

   Example directory and file output:

   ```text
   /home/your-user/devops/infra/envs/bootstrap
   backend.tf  main.tf  outputs.tf  providers.tf  variables.tf
   Bucket: your-unique-lowercase-state-bucket
   Subjects: {"infra":...,"backend":...,"frontend":...,"gitops":...}
   ```

   The `Subjects` line above is abbreviated for readability; your actual value must be complete JSON. If the bucket or JSON is blank, repeat the corresponding input step in this terminal.

   Run this once locally with your SSO admin profile, not from CI. Shell double quotes expand the variables; you do not need to paste JSON into the command:
   ```bash
   cd ~/devops/infra/envs/bootstrap
   terraform init -backend-config="bucket=${STATE_BUCKET:?Set STATE_BUCKET to your bucket name}" &&
   terraform apply -var="github_repo_subject_prefixes=${SUBJECTS_JSON:?Generate SUBJECTS_JSON in step 2}"
   ```

   Example successful initialization:

   ```text
   Successfully configured the backend "s3"!
   Terraform has been successfully initialized!
   ```

   Terraform then displays a plan and asks `Enter a value:`. Review the account, planned resources, and any changes before typing `yes`; do not approve unexpected deletions. A fresh account creates the OIDC provider and CI roles; there are no automatic imports from another deployment. If these resources already exist, find their owning state first. Do not create duplicate ownership. After verifying ownership and backing up state, use explicit `terraform import` commands only for resources that are not managed elsewhere, through a reviewed adoption procedure. An existing GitHub OIDC provider must also be adopted rather than recreated.

   A successful apply prints `Apply complete!` followed by outputs such as:

   ```text
   Outputs:

   terraform_apply_role_arn = "arn:aws:iam::123456789012:role/mackllc-dev-terraform-apply-gha"
   terraform_plan_role_arn = "arn:aws:iam::123456789012:role/mackllc-dev-terraform-plan-gha"
   ```

   Save the plan-role and apply-role ARNs printed by Terraform. In step 3, enter them as the `AWS_TF_PLAN_ROLE_ARN` and `AWS_TF_APPLY_ROLE_ARN` repository variables. This bootstrap root has separate state, so destroying `envs/dev` will not remove the CI login.

### If bootstrap stops with an error

**`Terraform initialized in an empty directory!` or `No configuration files`:** you ran Terraform in the wrong folder. No resources were changed by that failed apply. Change to `~/devops/infra/envs/bootstrap`, check `ls *.tf`, then rerun initialization and apply above. Do not use `terraform destroy` to fix this error.

**`Backend configuration changed`:** first determine whether this configuration already has state managing AWS resources in a different bucket or local state. Do not discard or overwrite existing state.

- If this is your first bootstrap apply and there is no existing managed state to preserve, use the following command, then retry apply:
  ```bash
  cd ~/devops/infra/envs/bootstrap
  terraform init -reconfigure -backend-config="bucket=${STATE_BUCKET:?Set STATE_BUCKET}"
  ```
- If resources were already managed using the old backend, stop and review both state locations. Back up existing state and use `terraform init -migrate-state` only when intentionally moving that state. `-reconfigure` does not migrate it.
- If the local backend accidentally points at a new empty bucket, but the original remote state is verified and backed up, reconnect to the original bucket without migrating:
  ```bash
  cd ~/devops/infra/envs/bootstrap
  terraform init -reconfigure -backend-config="bucket=${STATE_BUCKET:?Set STATE_BUCKET to the verified original bucket}" &&
  terraform output
  ```
  Check the dev backend separately from `~/devops/infra/envs/dev` using the same verified bucket. Keep the two roots' distinct state keys. Ensure GitHub's `TF_STATE_BUCKET` also uses that bucket. Re-set `STATE_BUCKET` in any terminal that still has the wrong value.
- If you are unsure, stop and establish where the existing state is before choosing either option.

Before any intentional migration or bucket deletion, make a private backup outside the repository of current state, historical object versions, and delete-marker metadata. Check the downloaded files' checksums and keep a manifest mapping keys and version IDs to backup files. State can contain secrets: never commit it or attach it to a PR. Versioned buckets can retain old versions and delete markers even when an object listing looks empty; do not force-delete them to fix missing Terraform outputs.

**`No valid credential sources found`, `InvalidGrantException`, or cached SSO token refresh failed:** sign in again and verify the account before retrying initialization. Replace the profile example with your configured profile:

```bash
export AWS_PROFILE=mackllc-admin AWS_REGION=us-east-1
aws sso login --profile "$AWS_PROFILE" &&
aws sts get-caller-identity --profile "$AWS_PROFILE"
```

The identity output should show your intended AWS account as in step 0. Login does not create resources. Keep the same terminal so the bucket and JSON variables remain available.

### 2.E Verify bootstrap and save the role ARNs

**Verify bootstrap:**

```bash
aws s3api get-bucket-versioning --bucket "${STATE_BUCKET:?Set STATE_BUCKET}" --profile "$AWS_PROFILE" --output json
aws iam list-open-id-connect-providers --profile "$AWS_PROFILE" --output json
cd ~/devops/infra/envs/bootstrap
terraform output
```

Example AWS verification output:

```json
{"Status":"Enabled"}
```

```json
{"OpenIDConnectProviderList":[{"Arn":"arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com"}]}
```

`terraform output` should show both role ARNs as illustrated above. Other OIDC providers may also be listed. Save the actual values, not these examples.

## 3. GitHub settings for `infra`

### 3.A Check prerequisites and run the settings script

Run the GitHub settings script after Terraform bootstrap has succeeded. It requires `gh`, Terraform, OpenSSL, access to the bootstrap state, and repository administration permission. It uses the GitHub account shown by `gh auth status`; that account becomes the required reviewer. Do not enter your AWS SSO profile in GitHub.

Use the owner and bucket already set in step 2:

```bash
cd ~/devops/infra/scripts
./00_setup_github_settings.sh
```

If `GITHUB_ORG` or `STATE_BUCKET` is unset, the script prompts for it. Enter the GitHub owner only (for example, `Alexatlanta1981`, not a URL or `owner/infra`) and the exact existing bucket name from step 2. It does not create a bucket or reinitialize Terraform.

The script reads `terraform_plan_role_arn` and `terraform_apply_role_arn` from `envs/bootstrap` using Terraform's `-chdir` option and regenerates the complete OIDC subjects JSON. Keep your AWS SSO session active so Terraform can read the state. If a prerequisite read fails, no settings are written.

### 3.B Enter the optional SSO admin role

At the SSO role prompt, enter the full IAM role ARN if you want the EKS admin access grant. Enter preserves an existing `SSO_ADMIN_ROLE_ARN` variable, or skips it if absent. To look up available SSO role ARNs:

```bash
aws iam list-roles --query "Roles[?contains(RoleName,'AWSReservedSSO_')].Arn" --profile "$AWS_PROFILE" --output json
```

### 3.C Review and approve the GitHub settings

Before making changes, the script shows the repository, authenticated reviewer, bucket, role ARNs, OIDC subjects, and whether it will create or preserve the JWT secret. Type `y` at `Apply these GitHub settings? [y/N]` only after checking the values. Enter or `n` cancels without changes.

It configures the `dev` environment first, then verifies that GitHub retained the reviewer before setting variables and the secret. It disables admin bypass and preserves existing wait timers, self-review restrictions, and deployment branch policies. If `dev` already lists other reviewers, it stops before writing: only one listed reviewer needs to approve on GitHub, so adding you alongside others would not guarantee your approval. Review that policy manually rather than silently removing existing reviewers.

Required reviewers depend on GitHub plan and repository visibility. An unsupported setting or insufficient permissions stops setup; do not bypass this error by deploying without protection. If existing rules prevent self-review, your own dispatched job cannot be approved by you; review the intended approval flow before dispatching.

The script writes or updates these repository settings (the SSO variable is optional):

| Type | Name | Value |
|---|---|---|
| Variable | `GH_ORG` | `<ORG>` |
| Variable | `TF_STATE_BUCKET` | The exact bucket name created in step 2 |
| Variable | `AWS_TF_PLAN_ROLE_ARN` | Plan role ARN printed by Terraform in step 2 |
| Variable | `AWS_TF_APPLY_ROLE_ARN` | Apply role ARN printed by Terraform in step 2 |
| Variable | `GH_REPO_SUBJECTS` | The JSON printed by `scripts/00_oidc_subjects.sh` in step 2 |
| Variable | `SSO_ADMIN_ROLE_ARN` | Your IAM Identity Center admin role ARN (leave empty to skip). To look it up, run `aws iam list-roles --query "Roles[?contains(RoleName,'AWSReservedSSO_')].Arn" --profile "$AWS_PROFILE"` in your terminal. |
| Secret | `DEV_JWT_SECRET` | Generated with OpenSSL only when absent; an existing secret is never intentionally replaced |

The generated secret is piped directly to GitHub and never printed or saved to a file. Do not run this script with shell tracing (`bash -x`). Re-running updates the variables but preserves an existing JWT secret. If a write fails partway through, the script reports failure; some settings may already have changed. Inspect them before retrying.

Example confirmation summary excerpt (role ARNs and JSON also appear):

```text
Repository: your-github-owner/infra
Required dev reviewer: your-user
State bucket: your-unique-lowercase-state-bucket
DEV_JWT_SECRET: preserve existing secret
Apply these GitHub settings? [y/N] y
```

For a new secret the message says `generate a new secret (value will not be displayed)` instead.

### 3.D Verify the saved settings

**Verify:** the script reads back each variable and checks its value, verifies the JWT secret name exists, checks admin bypass is disabled, and prints variables, secret names, and environment protection rules. A successful run ends with:

```text
Setup complete. No workflows were dispatched, commits pushed, or PRs merged.
```

You can also verify manually:

```bash
gh variable list -R "$GITHUB_ORG/infra"
gh secret list -R "$GITHUB_ORG/infra"
gh api "repos/$GITHUB_ORG/infra/environments/dev" --jq '{name, can_admins_bypass, protection_rules}'
```

Expect five required variables, plus `SSO_ADMIN_ROLE_ARN` if provided or already present, and the `DEV_JWT_SECRET` secret name. Terraform apply pauses for approval in the configured `dev` environment.

**Verify OIDC subjects on your own repositories before CI.** The Terraform trust policies use the immutable owner/repository ID prefixes generated in step 2.C, not another owner's repository names or IDs. Read each repository's configuration:

```bash
for repo in infra backend frontend gitops; do
  gh api "repos/$GITHUB_ORG/$repo/actions/oidc/customization/sub" || break
done
```

For the default immutable subject format, expect `use_default: true`, `use_immutable_subject: true`, and a `sub_claim_prefix` matching that repository's entry in `SUBJECTS_JSON`. If the repository uses a different format, or the API call fails, stop and resolve the repository OIDC configuration with its administrator before running CI. Do not change STS, replace OIDC with static credentials, or broaden IAM trust to unrelated repositories to work around a mismatch. The settings script generates the prefixes but does not alter GitHub's OIDC subject configuration.

Example output excerpts (timestamps omitted here; secret values are never printed):

```text
NAME                   VALUE
GH_ORG                 your-github-owner
TF_STATE_BUCKET        your-unique-lowercase-state-bucket
AWS_TF_PLAN_ROLE_ARN    arn:aws:iam::123456789012:role/mackllc-dev-terraform-plan-gha
AWS_TF_APPLY_ROLE_ARN   arn:aws:iam::123456789012:role/mackllc-dev-terraform-apply-gha
GH_REPO_SUBJECTS       {"infra":...,"backend":...,"frontend":...,"gitops":...}
SSO_ADMIN_ROLE_ARN     arn:aws:iam::123456789012:role/aws-reserved/sso.amazonaws.com/AWSReservedSSO_AdministratorAccess_example
```

```text
NAME
DEV_JWT_SECRET
```

The JSON above is abbreviated; the actual GitHub value must be the complete `SUBJECTS_JSON` generated in step 2. For `SSO_ADMIN_ROLE_ARN`, use the full IAM role ARN returned by `list-roles` (including its path), not the STS assumed-role ARN from `get-caller-identity`. If multiple SSO roles are listed, select the role used by your admin profile. This variable is optional; omitting it means this access grant is skipped.

## 4. Create the AWS infrastructure (Terraform, via Git)

### 4.A Submit infrastructure changes through a PR

Make infrastructure code changes in your local `infra` clone on a working branch. Push that branch and open a PR; never push directly to `main`. GitHub Actions runs the Terraform plan and CI checks. Review the plan and wait for review and required checks to pass, then merge the PR. After merge, start the apply workflow and approve it in the `dev` environment. The apply creates the VPC, EKS, RDS, ECR, IAM/IRSA roles, and secrets in AWS. Do not run Terraform apply from your workstation.

```bash
cd ~/devops/infra
git checkout -b my-change
# edit files
git add -A && git commit -m "describe change"
git push -u origin my-change
gh pr create --fill
```

### 4.B Approve the PR and launch Terraform apply

After opening the PR, review the Terraform plan and wait for required CI checks and review to pass. Merge it in GitHub. Then run `gh workflow run terraform.yml -R <ORG>/infra -f action=apply` and approve the run at **GitHub → `<ORG>/infra` → Actions → the run → Review deployments**. The apply creates VPC, EKS, RDS, ECR, IAM/IRSA roles, and secrets; it takes about 20 minutes.

### 4.C Verify the apply run and cluster

**Verify:** `gh run list -R <ORG>/infra --workflow terraform.yml --limit 1` shows `completed success`; `aws eks list-clusters` shows `mackllc-dev-cluster`.

For easy-to-read status output, run:

```bash
gh run list -R <ORG>/infra --workflow terraform.yml --limit 1 --json status,conclusion,displayTitle
aws eks list-clusters --output json
```

Example outputs:

```json
[{"status":"completed","conclusion":"success","displayTitle":"Terraform Infrastructure"}]
```

```json
{"clusters":["mackllc-dev-cluster"]}
```

Make sure the run is your intended apply run, not an unrelated plan or an older successful run. `queued`, `in_progress`, or a blank conclusion is not a completed deployment. Review failures in GitHub Actions; do not proceed to kubectl until apply succeeds.

## 5. Connect kubectl

### 5.A Configure local cluster access

After the apply workflow succeeds, run these commands in your workstation's Ubuntu/WSL terminal. The first command adds EKS credentials to your local `~/.kube/config`; the second verifies access.

```bash
aws eks update-kubeconfig --name mackllc-dev-cluster --region us-east-1 --profile "$AWS_PROFILE"
kubectl get nodes
```

### 5.B Verify node readiness

**Verify:** nodes show `Ready`.

Example output:

```text
Added new context arn:aws:eks:us-east-1:123456789012:cluster/mackllc-dev-cluster to /home/chris/.kube/config
NAME                          STATUS   ROLES    AGE   VERSION
ip-10-0-1-10.ec2.internal      Ready    <none>   5m    v1.x.x
```

The CLI may say `Updated context` instead. An `Unauthorized` response from kubectl is not fixed by recreating the bucket: verify SSO login, account, cluster context, and the EKS access grant for your SSO role.

## 6. GitHub App for CI → gitops (no personal tokens)

Go to GitHub → the organization/account that owns the repos → **Settings → Developer settings → GitHub Apps**. Create two Apps and install both on the `gitops` repository only.

### 6.A Create the writer App for CI

Use [the short runbook's 6.A checklist](DEPLOY-RUNBOOK.md#6a-create-or-reuse-the-writer-app-for-ci) for exact setup locations and verification. Check existing App settings first; reuse a verified writer rather than creating another.

Scripted path (local onboarding, not CI): sign in with `gh auth login`. You need admin access to `backend`/`frontend`, existing `dev` environments in both, and permission to create/install Apps under your GitHub owner.

```bash
export GITHUB_ORG=your-github-owner
cd ~/devops/infra/scripts
python3 00_setup_writer_app.py --credentials-dir "$HOME/.config/infra-writer-app"
```

The script binds a temporary server to loopback only. Open its local URL in a browser on the same machine (WSL may require opening the URL manually). Confirm creation in the terminal and GitHub, then install the App on **selected repositories: gitops only**. Return to the terminal and press Enter; it verifies installation once, without polling. Confirm the separate settings-write prompt to save the App ID and private key in both repositories' `dev` environments. No workflows or deployments are launched.

The recovery directory must be outside the repository with mode `700`; the generated credential file is mode `600`. It contains the private key and other generated App secrets: do not share, commit, or attach it to a PR. The script never prints credentials. Keep this file securely to recover interrupted setup:

```bash
cd ~/devops/infra/scripts
python3 00_setup_writer_app.py --credentials-dir "$HOME/.config/infra-writer-app" --resume
```

Existing matching App IDs/keys are preserved; mismatched IDs or keys without an ID stop setup. A failure can leave the App or partial settings in place; inspect and resume rather than creating another App. The script verifies secret presence, not its encrypted value. It does not rotate keys or change the gitops ruleset bypass list (step 6.D). Writer and reader Apps remain separate.

Manual alternative: open the owner's **Settings → Developer settings → GitHub Apps → New GitHub App**. Enter a unique name and your infra repository URL as the homepage; disable webhooks for this token-only App. Under repository permissions select Contents: write, Pull requests: write, and Metadata: read. Create the App, record its App ID, and use **Private keys → Generate a private key**. Save the downloaded `.pem` outside Git with private permissions. Use **Install App** to install it on selected repositories: `gitops` only. In step 6.D, enter this App ID and key in both the `backend` and `frontend` repositories' `dev` environments. Verify installation scope and the environment setting names before continuing.

### 6.B Create the reader App for Argo CD

Create a separate App with Contents: read only. Generate a different private key. Keep its App ID, installation ID, and `.pem` file for step 7. Do not use the writer App credentials for Argo CD.

### 6.C Find the App and installation IDs

Find each App ID on its settings page under **About**. Find the installation ID by opening **Install App** and selecting the gear icon. Use the number at the end of the URL (`.../settings/installations/<ID>`); it is not the App ID.

### 6.D Enter GitHub App and CI values

For each repository, go to GitHub.com → `<ORG>/backend` or `<ORG>/frontend` → **Settings → Environments → dev**. Add:

| Type | Name | Value to enter |
|---|---|---|
| Variable | `GITOPS_APP_ID` | Writer App ID |
| Secret | `GITOPS_APP_PRIVATE_KEY` | Entire contents of the writer App's `.pem` file |

In each repository, go to **Settings → Secrets and variables → Actions**. Select **New repository variable** or **New repository secret** as indicated:

| Type | Name | Value to enter |
|---|---|---|
| Variable | `GITOPS_REPO` | `<ORG>/gitops` |
| Variable | `SONAR_ORG` | SonarCloud organization key |
| Variable | `SONAR_PROJECT_KEY_BACKEND` | Backend SonarCloud project key (backend only) |
| Variable | `SONAR_PROJECT_KEY_FRONTEND` | Frontend SonarCloud project key (frontend only) |
| Secret | `AWS_ACCOUNT_ID` | AWS account ID |
| Secret | `SONAR_TOKEN` | SonarCloud token; optional, scan is non-blocking if omitted |
| Secret | `NVD_API_KEY` | NIST NVD API key (backend only; optional) |

If the `gitops` main branch is protected, add the **writer App** to its ruleset bypass list: `<ORG>/gitops` → **Settings → Rules → Rulesets** → the main-branch ruleset → **Bypass list**.

Do not enter the reader App values in GitHub settings. In step 7, enter its App ID and installation ID when script 02 prompts. For its private key, enter the path to the `.pem` file on your workstation. Script 02 saves these credentials in the Kubernetes secret `gitops-repo` in namespace `argocd`.


### 6.E Verify both repositories

**Verify:** `gh variable list -R <ORG>/backend --env dev` shows `GITOPS_APP_ID`; `gh secret list -R <ORG>/backend --env dev` shows `GITOPS_APP_PRIVATE_KEY`. Check repository-level values with `gh variable list -R <ORG>/backend` and `gh secret list -R <ORG>/backend`. Repeat for `frontend`.

Example output excerpts:

```text
NAME            VALUE
GITOPS_APP_ID   123456
```

```text
NAME
GITOPS_APP_PRIVATE_KEY
```

The first value must be your writer App ID; the second command lists only the secret name, not its private key. Missing rows mean the setting is absent or you are checking the wrong repository/environment. Never paste private keys or secret values into troubleshooting messages.

## 7. Install cluster components (scripts, in order)

After step 5 reports EKS nodes as `Ready`, open an Ubuntu/WSL terminal and run these scripts from `~/devops/infra/scripts` in order. They install the AWS Load Balancer Controller, Argo CD, External Secrets Operator, connect Argo CD to `gitops`, and configure the cluster secret store.

### 7.A Install cluster prerequisites (script 01)

Set inputs for **your deployment** before running script 01. Get the cluster
name from your CI Terraform outputs and the ALB IRSA role ARN from your deployed
IAM resources; do not assume another project's names.

```bash
export CLUSTER_NAME=your-cluster-name
export AWS_REGION=your-cluster-region
export ALB_CONTROLLER_ROLE=your-alb-controller-iam-role-arn
export GITOPS_PATH="$WORKSPACE/gitops"
cd "$WORKSPACE/infra/scripts"
python3 01_install_prerequisites.py
```

Unset values prompt; region can default to your AWS CLI profile's configured
region. The script uses your SSO identity, checks the role's account, and discovers
the VPC from EKS unless supplied. Failed AWS reads or kubeconfig updates stop
installation rather than using a stale cluster. SSO, STS, and IRSA remain unchanged.

**Argo CD Ingress is disabled by default.** Access the UI using
`kubectl -n argocd port-forward svc/argocd-server 8080:443`.
The script no longer auto-applies the GitOps checkout's fixed Ingress manifest.
It does not remove an existing Ingress.

For an explicitly approved ALB endpoint, set these before running:

```bash
export ARGOCD_INGRESS_ENABLED=1
export ARGOCD_HOSTNAME=argocd.your-domain.example
export ARGOCD_CERTIFICATE_ARN=your-acm-certificate-arn
export ARGOCD_INGRESS_SCHEME=internal
```

Use an issued ACM certificate for the hostname, in the selected account/region,
and configure DNS to the resulting ALB yourself. Certificate validity, domain
coverage and DNS are operator prerequisites; the script checks ARN account/region
but does not create a certificate or DNS record. `internet-facing` must be explicitly
selected for public exposure and incurs ALB charges. No ALB group is set by default,
preventing accidental grouping; set `ARGOCD_ALB_GROUP` only for deliberate sharing.
Review hostname and scheme in the installation summary before confirmation.

Script 01 does not retrieve or print the Argo CD administrator password. If you need the UI, retrieve the initial password explicitly in a private, unrecorded local terminal after installation:

```bash
kubectl -n argocd get secret argocd-initial-admin-secret \
  -o jsonpath='{.data.password}' | base64 --decode
printf '\n'
```

This command displays a credential. Do not run it in CI, paste its output into a PR, or record/share that terminal. Log in as `admin`, change the password, and delete the initial secret after verifying the new login. If the initial secret no longer exists, use your configured credentials or the Argo CD password-reset procedure; do not reinstall to recover it.

```bash
# Run script 01 above once with your deployment inputs.
```

### 7.B Connect Argo CD to gitops (script 02)

Script 02 requires your own `GITOPS_REPO_URL` (or prompts for it); there is no personal repository default. An empty answer stops the script before repository registration.

```bash
cd ~/devops/infra/scripts
python3 02_bootstrap_argocd.py          # registers gitops repo (asks App ID, installation ID, key path)
```

The scripts prompt for any required values. When `02_bootstrap_argocd.py` prompts, enter:

- The **reader App ID** for `GITHUB_APP_ID`.
- That App's **installation ID** for `GITHUB_APP_INSTALLATION_ID`.
- The path to that App's `.pem` file on your workstation for `GITHUB_APP_KEY_PATH`.

Script 02 saves these credentials in Kubernetes secret `gitops-repo` in namespace `argocd`. Do not enter them in GitHub settings. Wrong credentials cause `401 Unauthorized` errors and Argo CD applications may remain `Unknown`.

The private key is loaded by `kubectl --from-file`; only its path, not its contents,
is passed in command arguments. The generated Secret manifest is captured and
sent to `kubectl apply` through standard input, without printing it. Keep the
key file private and readable only by the intended workstation user.

**Fix a wrong value without re-running 02:**

```bash
kubectl -n argocd patch secret gitops-repo --type merge -p \
  "{\"data\":{\"githubAppID\":\"$(printf '<APP_ID>' | base64)\",\"githubAppInstallationID\":\"$(printf '<INSTALLATION_ID>' | base64)\",\"githubAppPrivateKey\":\"$(base64 -w0 <PATH_TO_PEM>)\"}}"
kubectl -n argocd rollout restart deploy argocd-repo-server
kubectl annotate applications -n argocd --all argocd.argoproj.io/refresh=hard --overwrite
```

### 7.C Configure External Secrets (script 03)

```bash
cd ~/devops/infra/scripts
python3 03_setup_external_secrets.py
```

### 7.D Verify cluster components and secrets

**Verify:** run each check separately:

```bash
kubectl get pods -n argocd
kubectl get pods -n external-secrets
kubectl get pods -n kube-system -l app.kubernetes.io/name=aws-load-balancer-controller
kubectl get clustersecretstore
kubectl get externalsecret -A
```

Example excerpts from the three pod listings:

```text
NAME                                   READY   STATUS    RESTARTS   AGE
argocd-repo-server-example              1/1     Running   0          3m
external-secrets-example                1/1     Running   0          3m
aws-load-balancer-controller-example    1/1     Running   0          3m
```

Example secret-store and external-secret output:

```text
NAME                  AGE   STATUS   CAPABILITIES   READY
aws-secrets-manager   3m    Valid    ReadWrite      True
```

```text
NAMESPACE   NAME             STORETYPE            STORE                 REFRESH INTERVAL   STATUS         READY
dev         db-credentials   ClusterSecretStore   aws-secrets-manager   1h                 SecretSynced   True
dev         jwt-secret       ClusterSecretStore   aws-secrets-manager   1h                 SecretSynced   True
```

Column layouts depend on the installed version. All expected pods must be ready, not just `Running`; the store must be valid and both secrets synced. `No resources found`, `Pending`, or `SecretSyncedError` is not success; use the troubleshooting section before continuing.

## 8. Build the images

### 8.A Set build inputs and run script 04

In an Ubuntu/WSL terminal, run script 04 from `~/devops/infra/scripts`. It triggers GitHub Actions in `backend` and `frontend`; the image builds run in those repositories, not on your workstation. Replace each placeholder with your value:

```bash
cd ~/devops/infra/scripts
GITHUB_ORG=<GITHUB_ORG> FRONTEND_REPO=<FRONTEND_REPO> BACKEND_REPO=<BACKEND_REPO> BRANCH=<BRANCH> \
  AWS_PROFILE=<AWS_SSO_PROFILE> python3 04_run_pipeline.py
```

| Value | What to put | Notes |
|---|---|---|
| `<GITHUB_ORG>` | GitHub user or org that owns the repos | The script default (`mackllc`) is only an example; a wrong owner gives HTTP 404 |
| `<FRONTEND_REPO>` / `<BACKEND_REPO>` | Repo names only, not `owner/name` | e.g. `frontend`, `backend` |
| `<BRANCH>` | Branch that exists in **both** repos | Check with `gh api repos/<ORG>/<REPO>/branches`; the default `develop` may not exist |
| `<AWS_SSO_PROFILE>` | Your AWS CLI profile | Run `aws sso login --profile <AWS_SSO_PROFILE>` first |

At the menu choose `A` (all) and confirm `Y`.

**gitops push:** CI writes the image tag straight to gitops `main`. If the gitops ruleset requires PRs, add the **writer** GitHub App to the ruleset bypass list (Settings > Rules > Rulesets > Protect main > Bypass list, mode Always). Otherwise builds fail at the push step.

Or trigger one service at a time:

```bash
gh workflow run ci-auth-service.yml -R <ORG>/backend --ref main
gh workflow run ci-mackllc-ui.yml  -R <ORG>/frontend --ref main
gh run list -R <ORG>/backend --limit 8
```

Each build: test → scan → push to ECR → sign → write the new image tag into `gitops`.
ECR tags are immutable: re-running the same commit fails to push. Make a new commit to rebuild.

### 8.B Verify builds and image tags

**Verify:** `gh run list -R <ORG>/backend --limit 8` all `success`; `aws ecr describe-images --repository-name <repo> --query 'imageDetails[].imageTags'` shows a `sha-xxxxxxx` tag; `git -C ~/devops/gitops pull` shows new tag commits.

Example ECR output with `--output json`:

```json
[["sha-abc1234"]]
```

Example Git pull output excerpt when CI has updated the image tag:

```text
Updating abc1234..def5678
Fast-forward
```

The actual tag must match the commit you built. A pull that says `Already up to date.` does not by itself prove a new image was deployed. Check the specific service's workflow run and the resulting tag change; older failed runs in the list need not describe the current build.

## 9. Deploy and verify

### 9.A Deploy services (script 05)

Script 05 monitors the actual Application names returned by `kubectl apply`
from the GitOps manifests, not the service menu labels. It exits unsuccessfully
if any selected manifest is skipped or an Application is degraded or times out.
Investigate those results before proceeding; exit success requires every selected
Application to reach Synced/Healthy.

After step 8 succeeds, run script 05 from `~/devops/infra/scripts` in your Ubuntu/WSL terminal. Replace `<ORG>` with the GitHub owner and `<AWS_SSO_PROFILE>` with the local profile name from step 0. These are command-line values; do not add them to GitHub settings. Script 05 creates the Argo CD applications in namespace `dev`.

```bash
export GITHUB_USERNAME=<ORG> ENV=dev
cd ~/devops/infra/scripts
AWS_PROFILE=<AWS_SSO_PROFILE> python3 05_deploy_services.py   # creates the Argo CD apps
```

### 9.B Run deployment verification (script 06)

```bash
cd ~/devops/infra/scripts
echo 1 | python3 06_verify_deployment.py
```

### 9.C Check applications, pods, and Ingress

Manual checks:

```bash
kubectl get applications -n argocd      # all Synced + Healthy
kubectl get pods -n dev  # all Running
kubectl get ingress -n dev  # ADDRESS filled in
```

Example output excerpts:

```text
NAME             SYNC STATUS   HEALTH STATUS
auth-service     Synced        Healthy
```

```text
NAME                      READY   STATUS    RESTARTS   AGE
auth-service-example      1/1     Running   0          2m
```

```text
NAME          CLASS   HOSTS   ADDRESS                                                    PORTS   AGE
app-ingress   alb     *       example-alb-123456.us-east-1.elb.amazonaws.com               80      2m
```

Resource names are illustrative; check every deployed application's sync and health, every expected pod's readiness, and your actual Ingress address. `OutOfSync`, `Degraded`, an empty address, or an unready pod requires investigation.

### 9.D Check the application HTTP responses

Get the load balancer hostname from the `ADDRESS` column of `kubectl get ingress -n dev`, then open `http://<alb-hostname>/`.

**Verify:** `curl -s -o /dev/null -w '%{http_code}\n' http://<alb-hostname>/` prints `200`; `curl -s -o /dev/null -w '%{http_code}\n' http://<alb-hostname>/api/` prints 200, 401, 403 or 404 (not 502/503).

Example outputs:

```text
200
```

```text
401
```

These are separate responses for `/` and `/api/`. `401` means authentication is required; `404` alone does not prove the backend is healthy. Use script 06's service-route checks as well. `000` means curl did not receive an HTTP response; `502`/`503` indicates routing or backend availability trouble.

## 10. Day-2: shipping a change

### 10.A Submit the service change through a PR

Create and push a working branch from your local `backend` clone, then open a PR in GitHub. Wait for review and required CI checks to pass before merging; never push directly to `main`. After merge, trigger the service workflow if it did not start automatically. CI builds the image and updates its tag in `gitops`.

```bash
cd ~/devops/backend
git checkout -b feat/my-change
git add -A && git commit -m "feat: ..."
git push -u origin feat/my-change
gh pr create --fill
```

### 10.B Approve the PR and trigger the build

After CI checks pass, merge the PR in GitHub. If the build did not start automatically, trigger it after merge:

```bash
gh workflow run ci-<service>.yml -R <ORG>/backend --ref main
```

CI updates the tag in `gitops`; Argo CD syncs it. Roll back by reverting the tag commit in `gitops`.

### 10.C Verify the new image and rollout

**Verify:** the new `sha-` tag appears in `kubectl get deploy -n dev -o wide` and the pod is `Running`.

To inspect images directly:

```bash
kubectl get deploy -n dev -o custom-columns='NAME:.metadata.name,READY:.status.readyReplicas,IMAGES:.spec.template.spec.containers[*].image'
```

Example output:

```text
NAME           READY   IMAGES
auth-service   1       123456789012.dkr.ecr.us-east-1.amazonaws.com/auth-service:sha-abc1234
```

Compare the actual tag to the new build and verify the expected ready replica count; the image field alone does not confirm a successful rollout.

## 11. Tear down (reverse order, Terraform last)

**Where:** Run the `kubectl`, `helm` and AWS commands from your workstation terminal; start the final Terraform destroy from GitHub Actions. Use the AWS SSO profile from step 0.

Run each step, then its **Verify** command, before moving on. Destroying the cluster first leaves orphaned ALBs and security groups that block the VPC delete.

If you opened a new terminal, run `export AWS_PROFILE=mackllc-admin AWS_REGION=us-east-1` first, replacing `mackllc-admin` with the profile name you chose in step 0.

Before any deletion, verify your account and cluster:

```bash
aws sts get-caller-identity
kubectl config current-context
```

The account must be your intended dev account and the context should identify `mackllc-dev-cluster`, for example `arn:aws:eks:us-east-1:123456789012:cluster/mackllc-dev-cluster`. The commands below delete all applications and Ingresses in that cluster; use them only for the dedicated platform cluster, not a shared cluster.

### 11.A Delete the Argo apps
```bash
kubectl -n argocd delete applications --all
```
Verify: `kubectl -n argocd get applications` prints `No resources found`.

Example deletion and verification output:

```text
application.argoproj.io "auth-service" deleted
No resources found in argocd namespace.
```

### 11.B Delete Ingresses (the ALB controller removes the ALB)
```bash
kubectl delete ingress --all -A
```
Verify: `kubectl get ingress -A` prints `No resources found`.

Example output:

```text
ingress.networking.k8s.io "app-ingress" deleted
No resources found
```

### 11.C Wait for the ALB to disappear (can take 1-3 minutes)
```bash
aws elbv2 describe-load-balancers --query 'LoadBalancers[].LoadBalancerName' --output text
```
Verify: empty output. If a name is still listed, wait and rerun. Do not continue until it is empty.

Successful verification prints no load balancer names and returns to the shell prompt. This query lists all load balancers in the selected account/region. In an account with unrelated workloads, do not delete their load balancers or wait for them to disappear; verify removal of this platform's load balancer specifically.

### 11.D Remove cluster add-ons
```bash
helm uninstall argocd -n argocd
helm uninstall external-secrets -n external-secrets
helm uninstall aws-load-balancer-controller -n kube-system
```
Verify: `helm list -A` shows none of the three.

Example uninstall messages:

```text
release "argocd" uninstalled
release "external-secrets" uninstalled
release "aws-load-balancer-controller" uninstalled
```

An empty Helm listing still prints its column header. Other releases may remain; none of these three should remain.

### 11.E Destroy AWS (VPC, EKS, RDS, ECR, workload IAM) via CI

The OIDC provider and CI roles in `envs/bootstrap` are intentionally left in place.
```bash
gh workflow run terraform.yml -R <ORG>/infra -f action=destroy -f confirm_destroy=destroy
gh run list -R <ORG>/infra --workflow terraform.yml --limit 1
```
Approve the run in the `dev` environment (GitHub > Actions > the run > Review deployments). Verify: the run shows `completed success`.

As in step 4, the desired status is `completed` and conclusion is `success`, specifically for the destroy run. A queued approval is not a completed destroy.

### 11.F Verify AWS resource cleanup
```bash
aws eks list-clusters --query clusters
aws rds describe-db-instances --query 'DBInstances[].DBInstanceIdentifier'
aws ecr describe-repositories --query 'repositories[].repositoryName'
aws elbv2 describe-load-balancers --query 'LoadBalancers[].LoadBalancerName'
aws ec2 describe-volumes --filters Name=status,Values=available --query 'Volumes[].VolumeId'
aws rds describe-db-snapshots --snapshot-type manual --query 'DBSnapshots[].DBSnapshotIdentifier'
```
Verify: every command returns `[]` (or empty). Delete any leftover RDS snapshot if you do not want to keep it.

Example output per command with `--output json`:

```json
[]
```

These queries cover the selected account/region, not just this platform. If other workloads exist, unrelated resources may legitimately remain; identify resources by this deployment before considering cleanup. The state bucket, bootstrap OIDC provider, and CI roles are intentionally retained and are not covered by these empty-list checks.

### 11.G Clean up local and GitHub leftovers (optional)
```bash
rm -rf /tmp/mf
gh secret list -R <ORG>/backend; gh secret list -R <ORG>/frontend
```
Delete the GitHub App (Settings > Developer settings > GitHub Apps) if the platform is retired.

`gh secret list` displays secret names and update times, not their contents. Listing does not delete them.

## Troubleshooting

| Symptom | Check |
|---|---|
| Script says `No such file or directory` | Run the `cd` above that script. Inside `infra/scripts`, use `./00_create_state_bucket.sh`, not `scripts/00_create_state_bucket.sh`. Verify the approved script exists in this checkout. |
| Bucket name rejected | Use a valid globally unique lowercase S3 name; capital letters are not allowed. |
| Terraform says empty directory / no configuration files | Use `cd ~/devops/infra/envs/bootstrap`; see step 2. Do not destroy anything. |
| Backend configuration changed | Determine whether state already exists before choosing reconfiguration or migration; see step 2. |
| No valid credentials / SSO `InvalidGrantException` | Refresh the selected SSO profile and verify the account; see step 2. |
| JSON parse error or missing `infra` entry | Regenerate the complete `SUBJECTS_JSON` as in step 2; do not manually paste a partial object. |
| Ingress has no ADDRESS | `kubectl logs -n kube-system deploy/aws-load-balancer-controller` (look for AccessDenied) |
| Pod CrashLoop | `kubectl logs <pod> -n dev --previous` |
| ExternalSecret not ready | `kubectl describe externalsecret -n dev` |
| Push to ECR fails "tag immutable" | New commit needed |
| Build fails at gitops push (protected branch) | Add the writer App to the gitops ruleset bypass list |
| Argo CD apps `Unknown`, no pods, `401` in `kubectl describe application` | Wrong App ID / installation ID / key in `gitops-repo`; see step 7 fix |
| `04_run_pipeline.py` HTTP 404 | Wrong `GITHUB_ORG`, repo name or `BRANCH` |
| CI 403 writing gitops | App not installed on `gitops` or missing Contents: write |

### Commands that do not produce a resource report

- `cd` and `export` normally print nothing. Use `pwd` to confirm your directory and `printf '%s\n' "$STATE_BUCKET"` to inspect the selected bucket name.
- AWS `put-bucket-versioning` normally prints nothing on success; script 00 follows it with a read-back verification. No output is not a substitute for verification.
- `gh pr create` prints the new PR URL, such as `https://github.com/your-github-owner/infra/pull/42`. It does not merge the PR or prove CI passed.
- `gh workflow run` may print a dispatch confirmation or no output, depending on the CLI version. Inspect the new run in GitHub Actions or with `gh run list`; do not assume dispatch means success.
- `git clone`, `git push`, and `git pull` print progress and repository-specific summaries. Read errors such as authentication failures or rejected pushes rather than continuing.
- Scripts 01-06 print prompts, progress, and errors that vary with selected services and installed resources. Use the concrete verification commands above rather than expecting identical log output. Stop on failures; never share private keys, JWT secrets, or database credentials as example output.


## Using your own account or organization

Replace `<ORG>` with the GitHub username or organization that owns your four repositories wherever it appears in this runbook. In each local clone, replace `@YOUR-GITHUB-USER-OR-TEAM` in `.github/CODEOWNERS` with your username or team; submit the change on a branch through a PR. The preceding steps tell you where to enter the AWS and GitHub values. You do not need to add values to `gitops` by hand; script 05 fills in the account ID and organization during deployment.
