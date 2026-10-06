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

Each script prompts for what it needs, skips any prompt already set in the environment, and can be re-run safely.

## Layout

| Script | Purpose |
|---|---|
| `01_install_prerequisites.py` | Installs the ALB controller, Argo CD and External Secrets with Helm. Restarts the ALB controller so its webhook cert is fresh. |
| `02_bootstrap_argocd.py` | Gives Argo CD access to `gitops`, creates the `mackllc` project and the root app for the chosen `ENV`. |
| `03_setup_external_secrets.py` | Creates the ClusterSecretStore and ExternalSecrets from the RDS and Secrets Manager entries. |
| `04_run_pipeline.py` | Triggers the service build workflows and waits for them. |
| `05_deploy_services.py` | Points `gitops` at the new images and syncs. |
| `06_verify_deployment.py` | Checks pods, services and ingress. |

## Running it

```bash
aws sso login --profile mack-admin
export AWS_PROFILE=mack-admin
aws eks update-kubeconfig --name mackllc-dev-cluster --region us-east-1
export GITOPS_PATH=~/devops/chris/gitops     # local clone of gitops
cd scripts
python3 01_install_prerequisites.py          # then 02 ... 06 in order
```

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
