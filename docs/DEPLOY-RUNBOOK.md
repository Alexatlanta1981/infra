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

**Verify:** `git --version && gh --version && aws --version && terraform version && kubectl version --client && helm version --short && yq --version && python3 --version` all print versions. `gh auth status` says logged in.

## 1. Clone the four repos

```bash
mkdir -p ~/devops/chris && cd ~/devops/chris
for r in infra backend frontend gitops; do git clone https://github.com/<ORG>/$r.git; done
```

**Verify:** `ls ~/devops/chris` lists `infra backend frontend gitops`.

## 2. One-time AWS prerequisites

1. Create the Terraform state bucket (name must match `envs/dev/backend.tf`):
   ```bash
   aws s3api create-bucket --bucket <STATE_BUCKET> --region us-east-1
   aws s3api put-bucket-versioning --bucket <STATE_BUCKET> --versioning-configuration Status=Enabled
   ```
2. Create the GitHub OIDC provider and the two Terraform CI roles (plan = read-only, apply = write) from the separate `envs/bootstrap` root, with admin credentials (never via CI): `cd envs/bootstrap && terraform init && terraform apply`. It has its own state, so `destroy` of `envs/dev` cannot remove CI login. Set the printed role ARNs as the `AWS_TF_PLAN_ROLE_ARN` / `AWS_TF_APPLY_ROLE_ARN` repo variables.
3. Edit `envs/dev/backend.tf` (bucket) and `envs/dev/variables.tf` defaults (`github_org`, `sso_admin_role_arn`).

**Verify:** `aws s3api get-bucket-versioning --bucket <STATE_BUCKET>` shows `Enabled`; `aws iam list-open-id-connect-providers` lists `token.actions.githubusercontent.com`; `aws iam list-roles --query 'Roles[].RoleName'` shows both CI roles.

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

**Verify:** `gh variable list -R <ORG>/infra` shows the four variables; `gh secret list -R <ORG>/infra` shows `DEV_JWT_SECRET`.

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

**Verify:** `gh run list -R <ORG>/infra --workflow terraform.yml --limit 1` shows `completed success`; `aws eks list-clusters` shows `mackllc-dev-cluster`.

## 5. Connect kubectl

```bash
aws eks update-kubeconfig --name mackllc-dev-cluster --region us-east-1
kubectl get nodes
```

**Verify:** nodes show `Ready`.

## 6. GitHub App for CI → gitops (no personal tokens)

Needed so CI can write image tags to the `gitops` repo and Argo CD can read it.

- Create a GitHub App with Contents: write, Pull requests: write, Metadata: read. Install it on the `gitops` repo only.
- In the `backend` and `frontend` repos, `dev` environment: variable `GITOPS_APP_ID`, secret `GITOPS_APP_PRIVATE_KEY` (the `.pem` contents).
- Also set in both repos: variable `GITOPS_REPO` (`<ORG>/gitops`), secret `AWS_ACCOUNT_ID`, plus the Sonar/NVD secrets.
- For Argo CD read access, create a read-only App (Contents: read) and keep its App ID, installation ID, and `.pem` for step 7.

> Status: workflows mint a short-lived GitHub App token (`GITOPS_APP_ID` variable + `GITOPS_APP_PRIVATE_KEY` secret). The old `GITOPS_TOKEN` is being retired.

**Verify:** `gh variable list -R <ORG>/backend --env dev` shows `GITOPS_APP_ID`; `gh secret list -R <ORG>/backend --env dev` shows `GITOPS_APP_PRIVATE_KEY`. Repeat for `frontend`.

## 7. Install cluster components (scripts, in order)

```bash
cd ~/devops/chris/infra/scripts
export GITOPS_PATH=~/devops/chris/gitops
python3 01_install_prerequisites.py     # ALB controller, Argo CD, External Secrets Operator
python3 02_bootstrap_argocd.py          # registers gitops repo (asks App ID, installation ID, key path)
python3 03_setup_external_secrets.py    # DB + JWT secrets from AWS Secrets Manager
```

Each script prompts for values; press Enter to accept defaults. You can pre-set any prompt as an env var (e.g. `export ENV=dev`).

**Verify:** `kubectl get pods -n argocd` and `-n external-secrets` and `-n kube-system -l app.kubernetes.io/name=aws-load-balancer-controller` are all `Running`; `kubectl get clustersecretstore` shows `Valid`; `kubectl get externalsecret -A` shows `SecretSynced`.

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

**Verify:** `gh run list -R <ORG>/backend --limit 8` all `success`; `aws ecr describe-images --repository-name <repo> --query 'imageDetails[].imageTags'` shows a `sha-xxxxxxx` tag; `git -C ~/devops/chris/gitops pull` shows new tag commits.

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

**Verify:** `curl -s -o /dev/null -w '%{http_code}\n' http://<alb-hostname>/` prints `200`; `curl -s -o /dev/null -w '%{http_code}\n' http://<alb-hostname>/api/` prints 200, 401, 403 or 404 (not 502/503).

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

**Verify:** the new `sha-` tag appears in `kubectl get deploy -n dev -o wide` and the pod is `Running`.

## 11. Tear down (reverse order, Terraform last)

Run each step, then its **Verify** command, before moving on. Destroying the cluster first leaves orphaned ALBs and security groups that block the VPC delete.

**1. Delete the Argo apps**
```bash
kubectl -n argocd delete applications --all
```
Verify: `kubectl -n argocd get applications` prints `No resources found`.

**2. Delete Ingresses (the ALB controller removes the ALB)**
```bash
kubectl delete ingress --all -A
```
Verify: `kubectl get ingress -A` prints `No resources found`.

**3. Wait for the ALB to disappear (can take 1-3 minutes)**
```bash
aws elbv2 describe-load-balancers --query 'LoadBalancers[].LoadBalancerName' --output text
```
Verify: empty output. If a name is still listed, wait and rerun. Do not continue until it is empty.

**4. Remove cluster add-ons**
```bash
helm uninstall argocd -n argocd
helm uninstall external-secrets -n external-secrets
helm uninstall aws-load-balancer-controller -n kube-system
```
Verify: `helm list -A` shows none of the three.

**5. Destroy AWS (VPC, EKS, RDS, ECR, workload IAM) via CI** (the OIDC provider and CI roles in `envs/bootstrap` are intentionally left in place)
```bash
gh workflow run terraform.yml -R <ORG>/infra -f action=destroy -f confirm_destroy=destroy
gh run list -R <ORG>/infra --workflow terraform.yml --limit 1
```
Approve the run in the `dev` environment (GitHub > Actions > the run > Review deployments). Verify: the run shows `completed success`.

**6. Confirm nothing is left in AWS**
```bash
aws eks list-clusters --query clusters
aws rds describe-db-instances --query 'DBInstances[].DBInstanceIdentifier'
aws ecr describe-repositories --query 'repositories[].repositoryName'
aws elbv2 describe-load-balancers --query 'LoadBalancers[].LoadBalancerName'
aws ec2 describe-volumes --filters Name=status,Values=available --query 'Volumes[].VolumeId'
aws rds describe-db-snapshots --snapshot-type manual --query 'DBSnapshots[].DBSnapshotIdentifier'
```
Verify: every command returns `[]` (or empty). Delete any leftover RDS snapshot if you do not want to keep it.

**7. Clean up local and GitHub leftovers (optional)**
```bash
rm -rf /tmp/mf
gh secret list -R <ORG>/backend; gh secret list -R <ORG>/frontend
```
Delete the GitHub App (Settings > Developer settings > GitHub Apps) if the platform is retired.

## Troubleshooting

| Symptom | Check |
|---|---|
| Ingress has no ADDRESS | `kubectl logs -n kube-system deploy/aws-load-balancer-controller` (look for AccessDenied) |
| Pod CrashLoop | `kubectl logs <pod> -n dev --previous` |
| ExternalSecret not ready | `kubectl describe externalsecret -n dev` |
| Push to ECR fails "tag immutable" | New commit needed |
| CI 403 writing gitops | App not installed on `gitops` or missing Contents: write |
