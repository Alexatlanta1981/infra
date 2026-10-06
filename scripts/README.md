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

Bucket creation, input values, confirmation, and the creation report are documented in [deployment runbook step 2](../docs/DEPLOY-RUNBOOK.md#2-one-time-aws-prerequisites). Run script 00 there before Terraform bootstrap; run scripts 01-06 after Terraform creates the cluster.

## Layout

| Script | Purpose |
|---|---|
| `00_create_state_bucket.sh` | Creates the Terraform state S3 bucket and enables versioning. Run once during AWS bootstrap; uses the active AWS CLI credentials and `AWS_REGION` (default `us-east-1`). |
| `00_setup_github_settings.sh` | Configures infra repository variables, creates a JWT secret only if absent, and requires your review in the `dev` environment. See [runbook step 3](../docs/DEPLOY-RUNBOOK.md#3-github-settings-for-infra) for inputs and verification. |
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
export GITOPS_PATH=~/devops/chris/gitops     # local clone of gitops
cd ~/devops/chris/infra/scripts
python3 01_install_prerequisites.py          # then 02 ... 06 in order
```

Build and deploy with presets (replace the `<...>` values; see the runbook, step 8):

```bash
cd ~/devops/chris/infra/scripts
GITHUB_ORG=<GITHUB_ORG> FRONTEND_REPO=<FRONTEND_REPO> BACKEND_REPO=<BACKEND_REPO> BRANCH=<BRANCH> \
  AWS_PROFILE=<AWS_SSO_PROFILE> python3 04_run_pipeline.py
cd ~/devops/chris/infra/scripts
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
| `RDS_MASTER_SECRET_ARN` | 03 | Otherwise looked up from RDS. |
| `POLL_INTERVAL`, `MAX_WAIT` | 04 | Build polling (default 30 s, 30 min). |
| `TRIGGER_DELAY` | 04 | Seconds between workflow triggers. |

Full procedure and teardown: [DEPLOY-RUNBOOK](../docs/DEPLOY-RUNBOOK.md). Reference examples: [SCRIPT-LIBRARY](../docs/SCRIPT-LIBRARY.md).

## GitHub Apps: how many, where they go

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
git -C ~/devops/chris/gitops pull && git -C ~/devops/chris/gitops log --oneline -10   # ci(dev) tag commits

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
cd ~/devops/chris/infra/scripts
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
