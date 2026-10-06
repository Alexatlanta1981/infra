# SAAS - HENRY FORD (infra)

Terraform and bootstrap automation that build the AWS side of the `mackllc` platform: network, EKS, RDS, ECR, IAM, secrets, and the CI login. It also holds the scripts that take a bare cluster to running services, and the runbooks.

Companion repos: [gitops](https://github.com/Alexatlanta1981/gitops) (desired state, Argo CD apps), [backend](https://github.com/Alexatlanta1981/backend) (8 services), [frontend](https://github.com/Alexatlanta1981/frontend) (`mackllc-ui`).

## Architecture

```
 GitHub Actions (OIDC, no AWS keys)                      AWS account 058170692253, us-east-1
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
| `scripts/` | Numbered bootstrap scripts 01-06. See [scripts/README.md](scripts/README.md). |
| `.github/workflows/` | `terraform.yml`, `bootstrap.yml`, `scripts-test.yml`. |
| `docs/` | [Deploy runbook](docs/DEPLOY-RUNBOOK.md), [study guide](docs/STUDY-GUIDE.md), [v1.0 issues](docs/V1.0-ISSUES-AND-FIXES.md), [v1.1 rewire](docs/V1.1-ENTERPRISE-REWIRE.md), [v1.1 issues](docs/V1.1-ISSUES-AND-FIXES.md), [script library](docs/SCRIPT-LIBRARY.md). |

## Running it

Everything goes through CI. Do not run `terraform apply` locally.

| Action | How |
|---|---|
| Plan | Open a PR to `main`. `Terraform Plan` runs and is a required check. |
| Apply | Merge to `main`. Plan runs, then the `dev` environment waits for approval, then apply. |
| Destroy | Actions, `Terraform Infrastructure`, run workflow, action `destroy`, type `destroy`, approve. Then run again with `apply` to rebuild. |
| CI login changes | Edit `envs/bootstrap/` or `modules/ci-oidc/`. `bootstrap.yml` plans and applies it. It has no destroy action by design. |

After apply, connect and install the cluster components:

```bash
aws sso login --profile mack-admin
aws eks update-kubeconfig --name mackllc-dev-cluster --region us-east-1 --profile mack-admin
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
