# SAAS - HENRY FORD (infra)

Terraform and bootstrap automation that build the AWS side of the `mackllc` platform: network, EKS, RDS, ECR, IAM, secrets, and the CI login. It also holds the scripts that take a bare cluster to running services, and the runbooks.

Companion repos: [gitops](https://github.com/Alexatlanta1981/gitops) (desired state, Argo CD apps), [backend](https://github.com/Alexatlanta1981/backend) (8 services), [frontend](https://github.com/Alexatlanta1981/frontend) (`mackllc-ui`).

## Architecture

```
 GitHub Actions (OIDC, no AWS keys)                      AWS account <ACCOUNT_ID>, us-east-1
┌────────────────────────────────┐   plan / apply     ┌───────────────────────────────────────────┐
│ terraform.yml  (envs/dev)      │──────────────────► │ VPC (public / private / database subnets) │
│ bootstrap.yml  (envs/bootstrap)│  roles from        │ EKS 1.33 + managed nodes, IRSA roles      │
└────────────────────────────────┘  bootstrap state   │ RDS (managed, rotated password)           │
                                                      │ ECR repos, Secrets Manager, ALB controller│
 scripts/01-06 (run by a human)                       └───────────────────────┬───────────────────┘
┌────────────────────────────────┐                                            │
│ 01 ALB ctrl, Argo CD, ESO      │──► installs cluster components ────────────┘
│ 02 Argo CD repo access         │         │
│ 03 External Secrets            │         ▼
│ 04 trigger builds  05 deploy   │    Argo CD ──► reads gitops repo ──► workloads in dev / qa / prod
│ 06 verify                      │
└────────────────────────────────┘
```

Two Terraform roots with **separate state** (bucket `chris-m-terraform-state-buk01`):

- `envs/bootstrap`: the GitHub OIDC provider and the CI plan and apply roles. Never destroyed with the environment.
- `envs/dev`: everything else. `qa` and `prod` are placeholders.

## Layout

| Path | What it holds |
|---|---|
| `envs/bootstrap/` | OIDC provider and CI roles (own state). |
| `envs/dev/` | The dev environment: composes the modules below. |
| `envs/qa/`, `envs/prod/` | Empty placeholders. |
| `modules/` | `vpc`, `eks`, `rds`, `ecr`, `iam`, `irsa-role`, `secrets-manager`, `ci-oidc`. |
| `scripts/` | AWS/GitHub setup scripts and deployment scripts 01-06. See [scripts/README.md](scripts/README.md). |
| `.github/workflows/` | `terraform.yml`, `bootstrap.yml`, `scripts-test.yml`. |
| `docs/` | [Deploy runbook](docs/DEPLOY-RUNBOOK.md), [study guide](docs/STUDY-GUIDE.md), [v1.0 issues](docs/V1.0-ISSUES-AND-FIXES.md), [v1.1 rewire](docs/V1.1-ENTERPRISE-REWIRE.md), [v1.2 portable release](docs/V1.2-PORTABLE.md), [v1.1 issues](docs/V1.1-ISSUES-AND-FIXES.md), [script library](docs/SCRIPT-LIBRARY.md). |

## Running it

**Setting up for the first time?** Follow the [deployment runbook](docs/DEPLOY-RUNBOOK.md) in order. After Terraform bootstrap finishes, use the [plain-language step-3 instructions](scripts/README.md#step-3-set-up-github-settings-start-here-after-terraform-bootstrap) to get the GitHub settings script locally, enter your values, run it, and verify success.

### Step 3: get and run the GitHub settings script

**Already deployed or recovering missing outputs?** Keep the existing state bucket, `chris-m-terraform-state-buk01`, and follow the [existing-state checks and recovery instructions](docs/DEPLOY-RUNBOOK.md#2-one-time-aws-prerequisites) first. Do not create a replacement bucket or apply an import/create plan merely because local outputs are missing.

Follow these commands in order, in the same Ubuntu/WSL terminal. Terraform bootstrap (runbook step 2) must have completed, and the script's PR must be merged into `main`. A merged PR does **not** automatically update files on your laptop.

**3.A Check your local checkout before updating**

```bash
cd ~/devops/chris/infra
git status --short
```

Expected output: nothing. If any changed or untracked files are listed, **stop and preserve those changes** before continuing. Do not delete them, reset the repository, or force a branch switch.

**3.B Switch to main, download the merged changes, and check the file**

```bash
cd ~/devops/chris/infra
git switch main &&
git pull --ff-only origin main &&
ls scripts/00_setup_github_settings.sh
```

Expected final output:

```text
scripts/00_setup_github_settings.sh
```

If switching or pulling fails, or the file is missing, stop. Check the error, repository, and PR merge status before proceeding.

**3.C Find your AWS profile and enter your inputs**

```bash
aws configure list-profiles
```

Choose the same profile used for Terraform bootstrap. Replace `your-sso-profile`, `your-github-owner`, and `your-existing-state-bucket` in the commands below. The GitHub owner is a name such as `Alexatlanta1981`, not a URL. The bucket is the one already created in step 2.

```bash
export AWS_PROFILE=your-sso-profile
export AWS_REGION=us-east-1
export GITHUB_ORG=your-github-owner
export STATE_BUCKET=your-existing-state-bucket
```

**3.D Sign in and verify both accounts**

```bash
aws sso login --profile "$AWS_PROFILE" &&
aws sts get-caller-identity --profile "$AWS_PROFILE" &&
gh auth status
```

Check that `Account` is your intended AWS account. The GitHub account shown becomes the required deployment reviewer. If GitHub is not signed in, run `gh auth login`, then repeat `gh auth status`. Stop if either account is wrong or authentication fails.

**3.E Verify Terraform bootstrap outputs**

```bash
cd ~/devops/chris/infra/envs/bootstrap
terraform output
```

Expect both `terraform_plan_role_arn` and `terraform_apply_role_arn` with your actual role ARNs. If either is missing or Terraform reports an error, stop and finish runbook step 2. The script reads these values automatically; do not paste JSON or role ARNs into its command.

**3.F Run the script**

```bash
cd ~/devops/chris/infra/scripts
./00_setup_github_settings.sh
```

Inside this directory, use `./00_setup_github_settings.sh`, **not** `scripts/00_setup_github_settings.sh`.

- At the SSO admin role prompt, enter your full IAM role ARN to configure EKS admin access. Press Enter to preserve an existing value or skip it if none exists. Skipping does not grant cluster access.
- To find the role ARN, use another terminal with your actual profile:
  ```bash
  aws iam list-roles --profile your-sso-profile --query "Roles[?contains(RoleName,'AWSReservedSSO_')].Arn" --output json
  ```
  Choose the admin role associated with your profile. Use its `arn:aws:iam::...:role/...` value, not an STS assumed-role ARN.
- At `Apply these GitHub settings? [y/N]`, check the repository, reviewer, bucket, and roles. Type `y` only when they are correct. Enter or `n` cancels without changes.

**3.G Check the completion message**

The script lists saved variables, secret names (never secret values), and environment protection settings. Success ends with:

```text
Setup complete. No workflows were dispatched, commits pushed, or PRs merged.
```

Only then continue to runbook step 4. If an error appears, stop and inspect it; some settings may already have changed. The script preserves an existing JWT secret and does not deploy AWS resources. Required-reviewer support depends on GitHub permissions, plan, and repository visibility; do not bypass an environment-protection failure.

Application infrastructure changes go through CI. Do not apply `envs/dev` locally. The one-time `envs/bootstrap` setup is run locally with your SSO admin profile, as explained in runbook step 2, because CI cannot sign in until its roles exist.

| Action | How |
|---|---|
| Plan | Open a PR to `main`. `Terraform Plan` runs and is a required check. |
| Apply | Merge to `main`. Plan runs, then the `dev` environment waits for approval, then apply. |
| Destroy | Actions, `Terraform Infrastructure`, run workflow, action `destroy`, type `destroy`, approve. Then run again with `apply` to rebuild. |
| CI login changes | Edit `envs/bootstrap/` or `modules/ci-oidc/`. `bootstrap.yml` plans and applies it. It has no destroy action by design. |

After apply, connect and install the cluster components:

```bash
aws sso login --profile your-sso-profile
aws eks update-kubeconfig --name mackllc-dev-cluster --region us-east-1 --profile your-sso-profile
cd scripts && python3 01_install_prerequisites.py   # then 02, 03, 04, 05, 06
```

Full step-by-step: [docs/DEPLOY-RUNBOOK.md](docs/DEPLOY-RUNBOOK.md). Teardown is the reverse order, with Terraform last.

## Why it is designed this way

- **Terraform builds AWS, Argo CD builds the apps.** Terraform creates only the ALB controller role. Ingress objects in `gitops` make the controller create the ALB, so Git stays the source of truth for what runs.
- **CI login lives in its own state.** A dev destroy once deleted the OIDC provider and locked CI out. Splitting it into `envs/bootstrap` means destroy and rebuild always has a working login. Proven by a destroy test.
- **GitHub OIDC, no AWS keys.** The plan role is read-only. The apply role works only from `main`, behind a manual approval.
- **SSO and EKS access entries for humans.** No IAM users.
- **IRSA, one role per service.** Least privilege. The trust subject must be `system:serviceaccount:<namespace>:<name>`.
- **RDS-managed, auto-rotated password** synced by External Secrets. No password in code, tfvars or Git.
- **One shared ALB** (Ingress group): `/` to the UI, `/api` to the gateway. One load balancer instead of nine.
- **Rebuildable on demand.** ECR repos use `force_delete`, so a destroy never fails on leftover images. Repos come back empty, so rebuild images after an apply.
- **Concurrency per ref, no cancel.** Runs queue instead of killing an in-flight apply or destroy. A newer queued run still replaces an older pending one, so do not merge to `main` while a destroy awaits approval.
- **Scripts are numbered, idempotent and tested** on a throwaway `kind` cluster before they touch AWS.
- **GitHub App tokens, not PATs**, for CI writes to `gitops`.

Version history and decisions: [study guide](docs/STUDY-GUIDE.md) and the issue logs linked above.

## Troubleshooting

### Argo CD install fails with ALB webhook x509 error

**Symptom:** `helm upgrade --install argocd` fails with `failed calling webhook "mservice.elbv2.k8s.aws" ... x509: certificate signed by unknown authority ... aws-load-balancer-controller-ca`.

**Why:** the ALB controller registers a mutating webhook on every Service. Each `helm upgrade` of the controller regenerates its webhook CA and updates the webhook `caBundle`. The API server then rejects the cert the running pods present until they pick up the new one. The old script upgraded twice, which triggered it.

**Steps:**
1. Compare the CA in secret `kube-system/aws-load-balancer-tls` (`ca.crt`) with the webhook `caBundle` on `mutatingwebhookconfiguration aws-load-balancer-webhook` (`openssl x509 -noout -fingerprint`).
2. Compare the cert each controller pod serves (`kubectl port-forward` to 9443, then `openssl s_client`) with the secret's `tls.crt`.
3. Create a test Service in a scratch namespace. An x509 error means the webhook is broken.

**Testing done:** a restart cleared the error. A full uninstall and reinstall produced a new CA, and the secret, `caBundle` and both pods all matched, with no restart and a successful Service create. A fresh install is fine. The failure comes from repeated upgrades. The pods have a cert watcher, so the stale window is likely a timing gap (not directly reproduced).

**Fix:** `scripts/01_install_prerequisites.py` installs the controller once, then runs `kubectl rollout restart` and `rollout status`. Manual recovery: `kubectl -n kube-system rollout restart deploy/aws-load-balancer-controller`.

More cases: [docs/DEPLOY-RUNBOOK.md](docs/DEPLOY-RUNBOOK.md).

## Known gaps

- Delete the old `GITOPS_TOKEN` secrets after the first build with the App token passes.
- Trivy is non-blocking; turn it back to `exit-code 1` after fixing findings.
- Argo CD SSO is not set up and the local admin user is still enabled.
- `jwt_secret` handling (local tfvars vs CI secret).
- Argo CD ingress has no ALB address yet.
- `qa` and `prod` Terraform environments do not exist yet.
