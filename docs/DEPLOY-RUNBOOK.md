# Deploy Runbook — zero to running platform

Order matters. Run every command from a terminal (Ubuntu/WSL). Replace `<ORG>` with your GitHub org/user and `<ACCOUNT_ID>` with your AWS account ID.

Repos: `infra`, `backend`, `frontend`, `gitops`, all under `<ORG>`.

## 0. Workstation tools (once)

Install: `git`, `gh`, `aws` (v2), `terraform` (>= 1.11), `kubectl`, `helm`, `yq`, `python3` (>= 3.10).

```bash
gh auth login                      # GitHub CLI login (browser)
aws configure sso --profile mack-admin
aws sso login --profile mack-admin
export AWS_PROFILE=mack-admin AWS_REGION=us-east-1
aws sts get-caller-identity        # must show <ACCOUNT_ID>
```

## 1. Clone the four repos

```bash
mkdir -p ~/devops/chris && cd ~/devops/chris
for r in infra backend frontend gitops; do git clone https://github.com/<ORG>/$r.git; done
```

## 2. One-time AWS prerequisites

1. Create the Terraform state bucket (name must match `envs/dev/backend.tf`):
   ```bash
   aws s3api create-bucket --bucket <STATE_BUCKET> --region us-east-1
   aws s3api put-bucket-versioning --bucket <STATE_BUCKET> --versioning-configuration Status=Enabled
   ```
2. Create the GitHub OIDC provider and the two Terraform CI roles (plan = read-only, apply = write) in AWS IAM. Trust them to `repo:<ORG>/infra`.
3. Edit `envs/dev/backend.tf` (bucket) and `envs/dev/variables.tf` defaults (`github_org`, `sso_admin_role_arn`).

## 3. GitHub settings for `infra`

Settings → Secrets and variables → Actions:

| Type | Name | Value |
|---|---|---|
| Variable | `GH_ORG` | `<ORG>` |
| Variable | `TF_STATE_BUCKET` | `<STATE_BUCKET>` |
| Variable | `AWS_TF_PLAN_ROLE_ARN` | plan role ARN |
| Variable | `AWS_TF_APPLY_ROLE_ARN` | apply role ARN |
| Secret | `DEV_JWT_SECRET` | any long random string |

Create the `dev` **environment** (Settings → Environments) with yourself as required reviewer. Apply pauses there for approval.

Generate a JWT secret: `openssl rand -base64 48`

## 4. Create the AWS infrastructure (Terraform, via Git)

Always through a pull request, never from your laptop:

```bash
cd ~/devops/chris/infra
git checkout -b my-change
# edit files
git add -A && git commit -m "describe change"
git push -u origin my-change
gh pr create --fill
```

- The PR runs `terraform plan`. Read it.
- Merge the PR (you, in the GitHub UI).
- Run apply: `gh workflow run terraform.yml -R <ORG>/infra -f action=apply`, then approve it in the `dev` environment (Actions tab → the run → Review deployments).
- This creates VPC, EKS, RDS, ECR, IAM/IRSA roles, secrets. Takes ~20 min.

## 5. Connect kubectl

```bash
aws eks update-kubeconfig --name mackllc-dev-cluster --region us-east-1
kubectl get nodes
```

## 6. GitHub App for CI → gitops (no personal tokens)

Needed so CI can write image tags to the `gitops` repo and Argo CD can read it.

- Create a GitHub App with Contents: write, Pull requests: write, Metadata: read. Install it on the `gitops` repo only.
- In the `backend` and `frontend` repos, `dev` environment: variable `GITOPS_APP_ID`, secret `GITOPS_APP_PRIVATE_KEY` (the `.pem` contents).
- Also set in both repos: variable `GITOPS_REPO` (`<ORG>/gitops`), secret `AWS_ACCOUNT_ID`, plus the Sonar/NVD secrets.
- For Argo CD read access, create a read-only App (Contents: read) and keep its App ID, installation ID, and `.pem` for step 7.

> Status: workflows mint a short-lived GitHub App token (`GITOPS_APP_ID` variable + `GITOPS_APP_PRIVATE_KEY` secret). The old `GITOPS_TOKEN` is being retired.

## 7. Install cluster components (scripts, in order)

```bash
cd ~/devops/chris/infra/scripts
export GITOPS_PATH=~/devops/chris/gitops
python3 01_install_prerequisites.py     # ALB controller, Argo CD, External Secrets Operator
python3 02_bootstrap_argocd.py          # registers gitops repo (asks App ID, installation ID, key path)
python3 03_setup_external_secrets.py    # DB + JWT secrets from AWS Secrets Manager
```

Each script prompts for values; press Enter to accept defaults. You can pre-set any prompt as an env var (e.g. `export ENV=dev`).

## 8. Build the images

```bash
python3 04_run_pipeline.py              # triggers CI for chosen services (GITHUB_ORG, repos, BRANCH prompts)
```

Or one at a time:

```bash
gh workflow run ci-auth-service.yml -R <ORG>/backend --ref main
gh workflow run ci-mackllc-ui.yml  -R <ORG>/frontend --ref main
gh run list -R <ORG>/backend --limit 8
```

Each build: test → scan → push to ECR → sign → write the new image tag into `gitops`.
ECR tags are immutable: re-running the same commit fails to push. Make a new commit to rebuild.

## 9. Deploy and verify

```bash
export GITHUB_USERNAME=<ORG> ENV=dev
python3 05_deploy_services.py           # creates the Argo CD apps
echo 1 | python3 06_verify_deployment.py
```

Manual checks:

```bash
kubectl get applications -n argocd      # all Synced + Healthy
kubectl get pods -n dev  # all Running
kubectl get ingress -n dev  # ADDRESS filled in
```

Open the UI at the ingress ADDRESS (`http://<alb-hostname>/`).

## 10. Day-2: shipping a change

```bash
cd ~/devops/chris/backend
git checkout -b feat/my-change
git add -A && git commit -m "feat: ..."
git push -u origin feat/my-change
gh pr create --fill                     # merge in the UI
gh workflow run ci-<service>.yml -R <ORG>/backend --ref main
```

CI updates the tag in `gitops`; Argo CD syncs it. Roll back by reverting the tag commit in `gitops`.

## 11. Tear down (reverse order, Terraform last)

Do the steps in order. Destroying the cluster first leaves orphaned ALBs and security groups that block the VPC delete.

```bash
# 1. Stop Argo from recreating things, then delete the apps
kubectl -n argocd delete applications --all
# 2. Delete Ingresses so the ALB controller removes the load balancer
kubectl delete ingress --all -A
# 3. Wait until no ALBs remain (empty output = ready)
aws elbv2 describe-load-balancers --query 'LoadBalancers[].LoadBalancerName' --output text
# 4. Remove cluster add-ons
helm uninstall argocd -n argocd
helm uninstall external-secrets -n external-secrets
helm uninstall aws-load-balancer-controller -n kube-system
# 5. Destroy AWS (VPC, EKS, RDS, ECR, IAM) via CI
gh workflow run terraform.yml -R <ORG>/infra -f action=destroy -f confirm_destroy=destroy
```
Approve in the `dev` environment. Then confirm nothing is left: no EKS cluster, RDS instance, ECR repos, load balancers or unattached volumes. RDS may keep a final snapshot; delete it if you don't want it.

## Troubleshooting

| Symptom | Check |
|---|---|
| Ingress has no ADDRESS | `kubectl logs -n kube-system deploy/aws-load-balancer-controller` (look for AccessDenied) |
| Pod CrashLoop | `kubectl logs <pod> -n dev --previous` |
| ExternalSecret not ready | `kubectl describe externalsecret -n dev` |
| Push to ECR fails "tag immutable" | New commit needed |
| CI 403 writing gitops | App not installed on `gitops` or missing Contents: write |
