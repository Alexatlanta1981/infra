# SAAS - HENRY FORD (infra scripts)

Six numbered Python scripts that take a bare EKS cluster (built by Terraform) to running services: install cluster add-ons, connect Argo CD to `gitops`, sync secrets, build images, deploy, verify.

Companion repos: [gitops](https://github.com/Alexatlanta1981/gitops), [backend](https://github.com/Alexatlanta1981/backend), [frontend](https://github.com/Alexatlanta1981/frontend). Parent: [infra README](../README.md).

## Architecture

```
01 install prerequisites ─► 02 bootstrap Argo CD ─► 03 external secrets
 (ALB controller, Argo CD,    (repo access, AppProject,   (ClusterSecretStore,
  External Secrets)            root app)                   ExternalSecrets from RDS/Secrets Manager)
                                                              │
06 verify  ◄── 05 deploy services  ◄── 04 run pipelines ◄─────┘
 (pods, ingress)  (image tags in gitops,   (trigger backend/frontend CI,
                   Argo CD sync)            wait for images)
```

Scripts 01-06 prompt for what they need, skip prompts already satisfied by the environment, and can be re-run safely. `00_create_state_bucket.sh` is a one-time AWS bootstrap step and is not intended to be re-run after bucket creation. `00_setup_github_settings.sh` runs after Terraform bootstrap and can be re-run to verify or update GitHub settings without rotating an existing JWT secret.

Script 01 does not retrieve or print the Argo CD administrator password. Use the explicit private-terminal retrieval instructions in [runbook step 7.A](../docs/DEPLOY-RUNBOOK.md#7a-install-cluster-prerequisites-script-01) only when you need UI access. Script 02 requires your own GitOps HTTPS URL through `GITOPS_REPO_URL` or its prompt; there is no personal repository default.

Script 02 loads the reader App private key from `GITHUB_APP_KEY_PATH` using
`kubectl --from-file`. Only the file path, not private-key contents, appears in
command arguments. The generated Secret manifest is captured and passed to
`kubectl apply` through standard input without printing it. Keep the key file
outside Git and restrict access to the intended workstation user. This change
does not alter GitHub App permissions, AWS SSO, OIDC, or IRSA.

Script 05 uses the applied Application object's `metadata.name` as the source
of truth for sync/health monitoring and reporting, rather than the menu's service
label. Skipped, degraded, or timed-out Applications cause a nonzero exit;
the next-step message is shown only when all selected Applications are Synced/Healthy.

Bucket creation, input values, confirmation, and the creation report are documented in [deployment runbook step 2](../docs/DEPLOY-RUNBOOK.md#2-one-time-aws-prerequisites). Run script 00 there before Terraform bootstrap; run scripts 01-06 after Terraform creates the cluster.

## Step 3: set up GitHub settings (start here after Terraform bootstrap)

This script fills in the GitHub settings that let CI use your AWS infrastructure. It also sets your signed-in GitHub account as the reviewer for deployments. **It does not deploy the application or create AWS resources.**

### 1. Get the approved script into your local folder

After the script's PR is approved and merged into `main`, run:

```bash
cd ~/devops/infra
git status --short
```

If this prints changed or untracked files, stop and preserve them before switching branches. Do not delete files or discard changes to force the next commands to work. With a clean checkout:

```bash
cd ~/devops/infra
git switch main &&
git pull --ff-only origin main &&
ls scripts/00_setup_github_settings.sh
```

Expected final output:

```text
scripts/00_setup_github_settings.sh
```

If the file is missing, do not continue. Check that the PR was merged and that this is the correct repository checkout. Files in an isolated worktree do not automatically appear in your normal checkout.

### 2. Enter your profile, GitHub owner, and existing bucket name

First, list your configured AWS profiles:

```bash
aws configure list-profiles
```

Use the same profile you used for Terraform bootstrap. Replace the three example values below before running them:

| Value | What to enter |
|---|---|
| `your-sso-profile` | Your local AWS CLI profile name from the list above. |
| `your-github-owner` | The owner of all four repos, such as `Alexatlanta1981`. Do not enter a URL or `owner/infra`. |
| `your-existing-state-bucket` | The exact bucket name you already created in step 2. Do not create another bucket. |

```bash
export AWS_PROFILE=your-sso-profile
export AWS_REGION=us-east-1
export GITHUB_ORG=your-github-owner
export STATE_BUCKET=your-existing-state-bucket

aws sso login --profile "$AWS_PROFILE" &&
aws sts get-caller-identity --profile "$AWS_PROFILE" &&
gh auth status
```

Check the AWS account ID and the GitHub login shown in the output. **The signed-in GitHub account becomes the deployment reviewer.** If it is the wrong account, correct your GitHub login before continuing.

Keep this terminal open. These values are local terminal settings, not edits to the script.

### 3. Check that Terraform bootstrap finished

```bash
cd ~/devops/infra/envs/bootstrap
terraform output
```

Expected output has both names below, with your actual AWS account and role ARNs:

```text
terraform_apply_role_arn = "arn:aws:iam::123456789012:role/mackllc-dev-terraform-apply-gha"
terraform_plan_role_arn = "arn:aws:iam::123456789012:role/mackllc-dev-terraform-plan-gha"
```

These ARNs are examples. If either output is missing or Terraform reports an error, stop and finish [runbook step 2](../docs/DEPLOY-RUNBOOK.md#2-one-time-aws-prerequisites). The settings script reads these outputs automatically; you do not paste them or JSON into its command.

### 4. Run the script and answer its prompts

```bash
cd ~/devops/infra/scripts
./00_setup_github_settings.sh
```

**At the SSO admin role prompt:**

- Enter the full IAM role ARN if you want this role granted EKS admin access. It must start with `arn:aws:iam::`, not `arn:aws:sts::`.
- Press Enter to preserve the existing setting. If none exists, Enter skips this optional setting; it does not grant you cluster access.
- To find the ARN, run this in another terminal using your actual profile name, then return to the prompt:

```bash
aws iam list-roles --profile your-sso-profile --query "Roles[?contains(RoleName,'AWSReservedSSO_')].Arn" --output json
```

If several roles appear, select the administrator role associated with your profile, not an arbitrary entry.

**At `Apply these GitHub settings? [y/N]`:**

Read the summary. Confirm the repository, reviewer, bucket, and role ARNs are correct. Type `y` and press Enter to apply. Type `n` or press Enter to cancel without changes.

The script sets repository variables, generates the JWT secret only if it is absent, and protects the `dev` environment. It preserves an existing JWT secret. It stops if GitHub does not support the required protection or if existing additional reviewers would allow approval without you.

### 5. Know when it is done

The script prints the saved variables, secret names (not secret values), and environment protection settings. A successful run ends with:

```text
Setup complete. No workflows were dispatched, commits pushed, or PRs merged.
```

Only after that success message should you continue to [runbook step 4](../docs/DEPLOY-RUNBOOK.md#4-ci-plans-current-stopping-point). If an error appears, stop. Some settings may already have changed; read the error and inspect them before retrying.

| Problem | What to do |
|---|---|
| `No such file or directory` | Repeat section 1. From inside `infra/scripts`, use `./00_setup_github_settings.sh`, not `scripts/00_setup_github_settings.sh`. |
| Expired SSO / `InvalidGrantException` | Run `aws sso login --profile "$AWS_PROFILE"` again in this terminal, verify the account, then retry. |
| Missing Terraform outputs | Complete Terraform bootstrap in runbook step 2; do not invent role ARNs. |
| Repository administration permission required | Sign in to GitHub with the correct account and confirm it has admin permission on `infra`. |
| Unsupported `dev` protection or other existing reviewers | Review GitHub permissions, plan support, and the existing environment rules. Do not bypass required approval to continue. |

## Layout

| Script | Purpose |
|---|---|
| `00_create_state_bucket.sh` | Creates the Terraform state S3 bucket and enables versioning. Run once during AWS bootstrap; uses the active AWS CLI credentials and `AWS_REGION` (default `us-east-1`). |
| `00_setup_github_settings.sh` | Configures infra repository variables, creates a JWT secret only if absent, and requires your review in the `dev` environment. See [runbook step 3](../docs/DEPLOY-RUNBOOK.md#3-github-settings-for-infra) for inputs and verification. |
| `00_setup_writer_app.py` | Creates a writer GitHub App through browser approval, verifies gitops-only installation, and configures backend/frontend environment settings with private recovery storage. |
| `01_install_prerequisites.py` | Installs the ALB controller, Argo CD and External Secrets with Helm. Restarts the ALB controller so its webhook cert is fresh. |
| `02_bootstrap_argocd.py` | Gives Argo CD access to `gitops`, creates the `mackllc` project and the root app for the chosen `ENV`. |
| `03_setup_external_secrets.py` | Creates the ClusterSecretStore and ExternalSecrets from the RDS and Secrets Manager entries. |
| `04_run_pipeline.py` | Triggers the service build workflows and waits for them. |
| `05_deploy_services.py` | Points `gitops` at the new images and syncs. |
| `06_verify_deployment.py` | Checks pods, services and ingress. |

## Running it

```bash
aws sso login --profile your-sso-profile
export AWS_PROFILE=your-sso-profile
aws eks update-kubeconfig --name mackllc-dev-cluster --region us-east-1
export GITOPS_PATH=~/devops/gitops     # local clone of gitops
cd ~/devops/infra/scripts
python3 01_install_prerequisites.py          # then 02 ... 06 in order
```

Build and deploy with presets (replace the `<...>` values; see the runbook, step 8):

```bash
cd ~/devops/infra/scripts
GITHUB_ORG=<GITHUB_ORG> FRONTEND_REPO=<FRONTEND_REPO> BACKEND_REPO=<BACKEND_REPO> BRANCH=<BRANCH> \
  AWS_PROFILE=<AWS_SSO_PROFILE> python3 04_run_pipeline.py
cd ~/devops/infra/scripts
AWS_PROFILE=<AWS_SSO_PROFILE> python3 05_deploy_services.py
```

Notes:
- Use the **reader** GitHub App for Argo CD (script 02) and the **writer** App for CI. The installation ID is never the App ID.
- CI pushes image tags to gitops `main`; the writer App must be on the ruleset bypass list.
- ECR tags are immutable (`sha-<commit>`); rebuilding the same commit needs a new commit or emptied repos.

Optional presets (skip prompts or tune behavior):

| Variable | Used by | Meaning |
|---|---|---|
| `ENV` | 02, 03 | Target environment: dev, qa or prod. |
| `VPC_ID` | 01 | Otherwise read from the EKS cluster. |
| `SKIP_ALB_CONTROLLER=1` | 01 | Skip the ALB controller install. |
| `CLUSTER_NAME`, `AWS_REGION`, `ALB_CONTROLLER_ROLE` | 01 | Your deployment's cluster, region, and IRSA role. No project-specific role/cluster fallback. Region can use AWS CLI profile configuration. |
| `ARGOCD_INGRESS_ENABLED=1` | 01 | Explicitly create Argo CD ALB Ingress; disabled by default. Existing Ingresses are not deleted. |
| `ARGOCD_HOSTNAME`, `ARGOCD_CERTIFICATE_ARN` | 01 | Required when enabling Ingress; DNS hostname and ACM certificate in the current account/region. |
| `ARGOCD_INGRESS_SCHEME` | 01 | `internal` by default; explicitly choose `internet-facing` for public exposure. |
| `ARGOCD_ALB_GROUP` | 01 | Optional deliberate sharing; no group set by default. |
| `RDS_MASTER_SECRET_ARN` | 03 | Otherwise looked up from RDS. |
| `POLL_INTERVAL`, `MAX_WAIT` | 04 | Build polling (default 30 s, 30 min). |
| `TRIGGER_DELAY` | 04 | Seconds between workflow triggers. |

Full procedure and teardown: [DEPLOY-RUNBOOK](../docs/DEPLOY-RUNBOOK.md). Reference examples: [SCRIPT-LIBRARY](../docs/SCRIPT-LIBRARY.md).

## GitHub Apps: how many, where they go

Create/configure the writer App with `python3 00_setup_writer_app.py --owner your-github-owner --credentials-dir "$HOME/.config/infra-writer-app"` from this scripts directory. See [step 6.A](../docs/DEPLOY-REFERENCE.md#6a-create-the-writer-app-for-ci) for browser approval, installation, private recovery storage, and `--resume`. This is one-time local onboarding, not a CI job. It does not create the reader App or change ruleset bypass settings.

Two GitHub Apps are needed. Both are owned by the org/account that owns the repos and installed on the `gitops` repo only.

| # | App | Permission | Used by | Where the credentials go |
|---|---|---|---|---|
| 1 | **Writer** (CI) | Contents: **write**, Pull requests: write, Metadata: read | `backend` and `frontend` CI, to push image tags to gitops | In **each** of `backend` and `frontend`, `dev` environment: variable `GITOPS_APP_ID` = App ID, secret `GITOPS_APP_PRIVATE_KEY` = `.pem` contents. Also add the App to the gitops ruleset bypass list. |
| 2 | **Reader** (Argo CD) | Contents: **read** (read-only), Metadata: read | Argo CD in the cluster, to read gitops | Kubernetes secret `gitops-repo` in namespace `argocd`, created by script 02: App ID, installation ID, and `.pem` path prompts. |

That is 2 Apps, 2 private keys, and 1 installation ID per App. The installation ID is only needed for the reader (script 02). The installation ID is never the App ID. Do not reuse a key across Apps.

## Validation commands

Replace `<ORG>` with your GitHub owner and `<AWS_SSO_PROFILE>` with your AWS profile.

```bash
# GitHub App settings in CI repos (writer App)
gh variable list -R <ORG>/backend  --env dev    # GITOPS_APP_ID present
gh variable list -R <ORG>/frontend --env dev
gh secret list   -R <ORG>/backend  --env dev    # GITOPS_APP_PRIVATE_KEY present
gh secret list   -R <ORG>/frontend --env dev

# Writer App can bypass the gitops ruleset
gh api repos/<ORG>/gitops/rulesets --jq '.[].id'
gh api repos/<ORG>/gitops/rulesets/<RULESET_ID> --jq '.bypass_actors'

# Builds and images
gh run list -R <ORG>/backend --limit 8          # all success
gh run list -R <ORG>/frontend --limit 1
aws ecr describe-images --repository-name <ECR_REPO> --query 'imageDetails[].imageTags'
git -C ~/devops/gitops pull && git -C ~/devops/gitops log --oneline -10   # ci(dev) tag commits

# Cluster
export AWS_PROFILE=<AWS_SSO_PROFILE>
kubectl get pods -n argocd
kubectl get clustersecretstore                  # Valid
kubectl get externalsecret -A                   # SecretSynced
kubectl get applications -n argocd              # Synced + Healthy
kubectl get pods -n dev                         # all 1/1 Running
kubectl get ingress -n dev                      # ADDRESS filled in
kubectl describe application <APP>-dev -n argocd | grep -i -A3 "error\|401"   # no 401

# Endpoints
curl -s -o /dev/null -w '%{http_code}\n' http://<ALB_HOSTNAME>/        # 200
curl -s -o /dev/null -w '%{http_code}\n' http://<ALB_HOSTNAME>/api/    # 200/401/403/404, not 502/503
cd ~/devops/infra/scripts
echo 1 | python3 06_verify_deployment.py
```

## Why it is designed this way

- **Numbered, one job each.** A failure is easy to place, and you can re-run from any step.
- **Idempotent.** `helm upgrade --install` and apply-style kubectl are safe to repeat.
- **Prompt unless preset.** Humans get guidance, CI gets determinism.
- **Python, not Bash.** Clear errors, testable, shared helpers.
- **Tested on `kind` before AWS.** Throwaway clusters catch breakage cheaply.
- **No secrets in scripts.** Passwords come from Secrets Manager through External Secrets.
- **Fresh ALB webhook cert.** The ALB controller is installed once and then restarted, instead of upgraded twice. See the [infra README troubleshooting](../README.md#troubleshooting).

## Testing and branch protection

Script changes go through a pull request to **`main`**. CI tests them automatically before they merge. (The old `ci/bootstrap-script-tests` branch is stale and no longer used.)

**Checks on every script PR:**

| Required check | What it does |
|---|---|
| `static` | `py_compile` plus `ruff` (syntax, undefined names, unused code) on `scripts/*.py` |
| `static` (shell checks) | Bash syntax checks and mocked GitHub settings setup tests; no real AWS or GitHub changes |
| `bootstrap smoke (01-03, kind)` | Spins up a throwaway `kind` cluster, runs scripts 01–03 with dummy AWS values, and asserts Argo CD, External Secrets, the `dev` namespace, the repo secret, the `mackllc` AppProject, the ClusterSecretStore and ExternalSecrets exist |
| `app layer (04-06, kind)` | Fresh `kind` cluster plus the real `gitops` repo; runs 01–06 with a fake `gh` CLI so no real builds start |

Defined in `.github/workflows/scripts-test.yml`. It runs on any PR or push to `main` that touches `scripts/**`, or manually (`gh workflow run scripts-test.yml`).

**Workflow to change a script:**

```bash
git fetch origin && git checkout -b fix/my-script-change origin/main
# edit scripts/...
git add -A && git commit -m "fix(script): ..."
git push -u origin fix/my-script-change
gh pr create --base main --fill   # wait for 3 green checks, merge in the UI
```

## Known gaps

- The restart fix in 01 is not yet proven end to end on a full rebuild.
- `qa` and `prod` flows are untested.
