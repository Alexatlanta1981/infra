# Deploy Runbook — zero to running platform

Order matters. Run every command from a terminal (Ubuntu/WSL). Replace `<ORG>` with your GitHub org/user and `<ACCOUNT_ID>` with your AWS account ID.

Repos: `infra`, `backend`, `frontend`, `gitops`, all under `<ORG>`.

**How to use this:** go top to bottom. Each step ends with a **Verify** line; do not continue until it passes.

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

## 0. Workstation tools (once)

Install: `git`, `gh`, `aws` (v2), `terraform` (>= 1.11), `kubectl`, `helm`, `yq`, `python3` (>= 3.10).

```bash
gh auth login                      # GitHub CLI login (browser)
aws configure sso --profile your-sso-profile
aws sso login --profile your-sso-profile
export AWS_PROFILE=your-sso-profile AWS_REGION=us-east-1
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
3. Edit `envs/dev/backend.tf` (bucket) and the `envs/dev/variables.tf` default for `github_org`. The SSO admin role ARN is not stored in Git: set it as the repo variable `SSO_ADMIN_ROLE_ARN` (step 3; leave empty to skip).

**Verify:** `aws s3api get-bucket-versioning --bucket <STATE_BUCKET>` shows `Enabled`; `aws iam list-open-id-connect-providers` lists `token.actions.githubusercontent.com`; `aws iam list-roles --query 'Roles[].RoleName'` shows both CI roles.

## 3. GitHub settings for `infra`

Settings → Secrets and variables → Actions:

| Type | Name | Value |
|---|---|---|
| Variable | `GH_ORG` | `<ORG>` |
| Variable | `TF_STATE_BUCKET` | `<STATE_BUCKET>` |
| Variable | `AWS_TF_PLAN_ROLE_ARN` | plan role ARN |
| Variable | `AWS_TF_APPLY_ROLE_ARN` | apply role ARN |
| Variable | `SSO_ADMIN_ROLE_ARN` | your IAM Identity Center admin role ARN (`aws iam list-roles --query "Roles[?contains(RoleName,'AWSReservedSSO_')].Arn"`) |
| Secret | `DEV_JWT_SECRET` | any long random string |

Create the `dev` **environment** (Settings → Environments) with yourself as required reviewer. Apply pauses there for approval.

Generate a JWT secret: `openssl rand -base64 48`

**Verify:** `gh variable list -R <ORG>/infra` shows the five variables; `gh secret list -R <ORG>/infra` shows `DEV_JWT_SECRET`.

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

Two Apps are needed (2 private keys total):

| App | Permission | Credentials go in |
|---|---|---|
| Writer (CI) | Contents: **write**, Pull requests: write, Metadata: read | `backend` and `frontend` repos, `dev` environment: variable `GITOPS_APP_ID`, secret `GITOPS_APP_PRIVATE_KEY`; plus the gitops ruleset bypass list |
| Reader (Argo CD) | Contents: **read** only | Cluster secret `gitops-repo` (namespace `argocd`) via script 02: App ID, installation ID, `.pem` path |

Details:

- Create the writer GitHub App with Contents: write, Pull requests: write, Metadata: read. Install it on the `gitops` repo only.
- In the `backend` and `frontend` repos, `dev` environment: variable `GITOPS_APP_ID`, secret `GITOPS_APP_PRIVATE_KEY` (the `.pem` contents).
- Also set in both repos: variable `GITOPS_REPO` (`<ORG>/gitops`), secret `AWS_ACCOUNT_ID`, plus the Sonar/NVD secrets.
- For Argo CD read access, create a **separate** read-only App (Contents: read), owned by the org, installed on `gitops` only. Keep its App ID, installation ID, and a generated `.pem` for step 7.
- Never mix the writer and reader IDs or keys.
- Find the **App ID** on the App's settings page ("About" section). Find the **installation ID** under Install App > gear icon: it is the number at the end of the URL (`.../settings/installations/<ID>`). The installation ID is never equal to the App ID.
- Check an App/key/installation match before step 7 (prints the installation ID the key belongs to):

```bash
python3 - <<'PY'
import time,json,base64,subprocess
b=lambda x:base64.urlsafe_b64encode(x).rstrip(b'=')
h=b(json.dumps({"alg":"RS256","typ":"JWT"}).encode());n=int(time.time())
p=b(json.dumps({"iat":n-60,"exp":n+500,"iss":"<APP_ID>"}).encode())
s=subprocess.run(["openssl","dgst","-sha256","-sign","<PATH_TO_PEM>"],input=h+b"."+p,capture_output=True).stdout
open("/tmp/jwt","wb").write(h+b"."+p+b"."+b(s))
PY
curl -s -H "Authorization: Bearer $(cat /tmp/jwt)" https://api.github.com/app/installations | grep '"id"' | head -1; rm /tmp/jwt
```

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

When `02` prompts: `GITHUB_APP_ID` = the **reader** App ID, `GITHUB_APP_INSTALLATION_ID` = its installation ID, `GITHUB_APP_KEY_PATH` = path to the reader `.pem`. A wrong value shows up later as `401 Unauthorized` / `could not refresh installation id` on every Argo CD app (sync `Unknown`, no pods).

**Fix a wrong value without re-running 02:**

```bash
kubectl -n argocd patch secret gitops-repo --type merge -p \
  "{\"data\":{\"githubAppID\":\"$(printf '<APP_ID>' | base64)\",\"githubAppInstallationID\":\"$(printf '<INSTALLATION_ID>' | base64)\",\"githubAppPrivateKey\":\"$(base64 -w0 <PATH_TO_PEM>)\"}}"
kubectl -n argocd rollout restart deploy argocd-repo-server
kubectl annotate applications -n argocd --all argocd.argoproj.io/refresh=hard --overwrite
```

**Verify:** `kubectl get pods -n argocd` and `-n external-secrets` and `-n kube-system -l app.kubernetes.io/name=aws-load-balancer-controller` are all `Running`; `kubectl get clustersecretstore` shows `Valid`; `kubectl get externalsecret -A` shows `SecretSynced`.

## 8. Build the images

Run from `infra/scripts`. Replace the `<...>` values with your own:

```bash
cd ~/devops/chris/infra/scripts
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

**Verify:** `gh run list -R <ORG>/backend --limit 8` all `success`; `aws ecr describe-images --repository-name <repo> --query 'imageDetails[].imageTags'` shows a `sha-xxxxxxx` tag; `git -C ~/devops/chris/gitops pull` shows new tag commits.

## 9. Deploy and verify

```bash
export GITHUB_USERNAME=<ORG> ENV=dev
AWS_PROFILE=<AWS_SSO_PROFILE> python3 05_deploy_services.py   # creates the Argo CD apps
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
| Build fails at gitops push (protected branch) | Add the writer App to the gitops ruleset bypass list |
| Argo CD apps `Unknown`, no pods, `401` in `kubectl describe application` | Wrong App ID / installation ID / key in `gitops-repo`; see step 7 fix |
| `04_run_pipeline.py` HTTP 404 | Wrong `GITHUB_ORG`, repo name or `BRANCH` |
| CI 403 writing gitops | App not installed on `gitops` or missing Contents: write |


## Using your own account/org

1. `GITHUB_ORG=<your-org> scripts/00_oidc_subjects.sh` prints JSON. Save it as repo variable `GH_REPO_SUBJECTS` (Settings > Variables) on `infra`.
2. Set repo variable `SSO_ADMIN_ROLE_ARN` (or leave empty).
3. Edit `bucket` in `envs/*/backend.tf` to your own state bucket.
4. Replace `@YOUR-GITHUB-USER-OR-TEAM` in each repo's `.github/CODEOWNERS`.
5. gitops repo: replace account ID and `repoURL` org in `envs/dev/values-*.yaml` and `argocd/` (separate gitops PR pending).
