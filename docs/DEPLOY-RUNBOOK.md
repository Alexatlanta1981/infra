# Deploy Runbook — zero to running platform

Order matters. Run every command from a terminal (Ubuntu/WSL). Replace `<ORG>` with your GitHub org/user and `<ACCOUNT_ID>` with your AWS account ID.

Repos: `infra`, `backend`, `frontend`, `gitops`, all under `<ORG>`.

**How to use this:** follow the steps in order. Each step tells you where to go, what to create, and where to enter the result. Complete the **Verify** check before continuing.

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

In an Ubuntu/WSL terminal, install `git`, `gh`, AWS CLI v2, Terraform >= 1.11, `kubectl`, `helm`, `yq`, and Python >= 3.10.

Choose a local AWS profile name, for example `mackllc-admin`. Replace `mackllc-admin` below and anywhere else it appears with your chosen name. When `aws configure sso` prompts you, enter your IAM Identity Center start URL, SSO region, AWS account, and permission set. The profile is saved on your workstation in `~/.aws/config`; do not enter it in GitHub.

```bash
gh auth login
aws configure sso --profile mackllc-admin
aws sso login --profile mackllc-admin
export AWS_PROFILE=mackllc-admin AWS_REGION=us-east-1
aws sts get-caller-identity        # must show <ACCOUNT_ID>
```

Keep using this terminal so `AWS_PROFILE` remains set. In a new terminal, run `export AWS_PROFILE=mackllc-admin AWS_REGION=us-east-1` again. AWS CLI and Terraform use this local profile.

**Verify:** `git --version && gh --version && aws --version && terraform version && kubectl version --client && helm version --short && yq --version && python3 --version` all print versions. `gh auth status` says logged in.

## 1. Clone the four repos

In an Ubuntu/WSL terminal, replace `<ORG>` with the GitHub username or organization that owns the four repositories. This creates four local folders under `~/devops/chris`.

```bash
mkdir -p ~/devops/chris && cd ~/devops/chris
for r in infra backend frontend gitops; do git clone https://github.com/<ORG>/$r.git; done
```

**Verify:** `ls ~/devops/chris` lists `infra backend frontend gitops`.

## 2. One-time AWS prerequisites

Run these commands in your workstation's Ubuntu/WSL terminal from `~/devops/chris/infra`. They use the AWS profile from step 0 to create the state bucket, GitHub OIDC provider, and CI roles in your AWS account. The profile name stays local; it is not a Terraform variable or GitHub setting.

If you opened a new terminal, set the profile again before running these commands:

```bash
export AWS_PROFILE=mackllc-admin AWS_REGION=us-east-1
cd ~/devops/chris/infra
```

1. **Create the state bucket in AWS.** Choose a globally unique name, for example `mackllc-terraform-state-123456789012`. Run the helper from the `infra` folder and enter that name when prompted:
   ```bash
   python3 scripts/00_create_state_bucket.py
   ```
   The helper creates the bucket in your AWS account, enables versioning and encryption, blocks public access, enforces bucket-owner ownership, and prints the value to use for `TF_STATE_BUCKET`. **Keep that exact bucket name** for Terraform below and GitHub in step 3.
2. **Create the GitHub CI login in AWS.** From your `infra` folder, generate the GitHub OIDC subjects:
   ```bash
   GITHUB_ORG=<ORG> scripts/00_oidc_subjects.sh
   ```
   Copy the JSON output. Then create the OIDC provider and two Terraform roles (plan = read-only, apply = write) from the separate `envs/bootstrap` Terraform root. Replace `<STATE_BUCKET>` and `<SUBJECTS_JSON>` with the bucket name and copied JSON; omit angle brackets. Run this once from your workstation with your SSO admin profile, not from CI:
   ```bash
   cd envs/bootstrap
   terraform init -backend-config="bucket=<STATE_BUCKET>"
   terraform apply -var='github_repo_subject_prefixes=<SUBJECTS_JSON>'
   ```
   Save the plan-role and apply-role ARNs printed by Terraform. In step 3, enter them as the `AWS_TF_PLAN_ROLE_ARN` and `AWS_TF_APPLY_ROLE_ARN` repository variables. This bootstrap root has separate state, so destroying `envs/dev` will not remove the CI login.

**Verify:** `aws s3api get-bucket-versioning --bucket <STATE_BUCKET> --profile "$AWS_PROFILE"` shows `Enabled`; `aws iam list-open-id-connect-providers --profile "$AWS_PROFILE"` lists `token.actions.githubusercontent.com`; `aws iam list-roles --query 'Roles[].RoleName' --profile "$AWS_PROFILE"` shows both CI roles.

## 3. GitHub settings for `infra`

Go to GitHub.com → `<ORG>/infra` → **Settings → Secrets and variables → Actions**. For each Variable row, select **New repository variable**. For the Secret row, select **New repository secret**. Do not enter the AWS SSO profile here.

**Enter the bucket name:** create a repository variable named `TF_STATE_BUCKET`. Set its value to the exact S3 bucket name you created in AWS in step 2. It must match the bucket name passed to `terraform init`.

| Type | Name | Value |
|---|---|---|
| Variable | `GH_ORG` | `<ORG>` |
| Variable | `TF_STATE_BUCKET` | The exact bucket name created in step 2 |
| Variable | `AWS_TF_PLAN_ROLE_ARN` | Plan role ARN printed by Terraform in step 2 |
| Variable | `AWS_TF_APPLY_ROLE_ARN` | Apply role ARN printed by Terraform in step 2 |
| Variable | `GH_REPO_SUBJECTS` | The JSON printed by `scripts/00_oidc_subjects.sh` in step 2 |
| Variable | `SSO_ADMIN_ROLE_ARN` | Your IAM Identity Center admin role ARN (leave empty to skip). To look it up, run `aws iam list-roles --query "Roles[?contains(RoleName,'AWSReservedSSO_')].Arn" --profile "$AWS_PROFILE"` in your terminal. |
| Secret | `DEV_JWT_SECRET` | A long random string; generate one in your terminal with `openssl rand -base64 48` |

Also create the `dev` **environment** at `<ORG>/infra` → **Settings → Environments**, and add yourself as a required reviewer. Terraform apply pauses for approval there.

**Verify:** `gh variable list -R <ORG>/infra` shows the six variables; `gh secret list -R <ORG>/infra` shows `DEV_JWT_SECRET`.

## 4. Create the AWS infrastructure (Terraform, via Git)

Make infrastructure code changes in your local `infra` clone on a working branch. Push that branch and open a PR; never push directly to `main`. GitHub Actions runs the Terraform plan and CI checks. Review the plan and wait for review and required checks to pass, then merge the PR. After merge, start the apply workflow and approve it in the `dev` environment. The apply creates the VPC, EKS, RDS, ECR, IAM/IRSA roles, and secrets in AWS. Do not run Terraform apply from your workstation.

```bash
cd ~/devops/chris/infra
git checkout -b my-change
# edit files
git add -A && git commit -m "describe change"
git push -u origin my-change
gh pr create --fill
```

After opening the PR, review the Terraform plan and wait for required CI checks and review to pass. Merge it in GitHub. Then run `gh workflow run terraform.yml -R <ORG>/infra -f action=apply` and approve the run at **GitHub → `<ORG>/infra` → Actions → the run → Review deployments**. The apply creates VPC, EKS, RDS, ECR, IAM/IRSA roles, and secrets; it takes about 20 minutes.

**Verify:** `gh run list -R <ORG>/infra --workflow terraform.yml --limit 1` shows `completed success`; `aws eks list-clusters` shows `mackllc-dev-cluster`.

## 5. Connect kubectl

After the apply workflow succeeds, run these commands in your workstation's Ubuntu/WSL terminal. The first command adds EKS credentials to your local `~/.kube/config`; the second verifies access.

```bash
aws eks update-kubeconfig --name mackllc-dev-cluster --region us-east-1 --profile "$AWS_PROFILE"
kubectl get nodes
```

**Verify:** nodes show `Ready`.

## 6. GitHub App for CI → gitops (no personal tokens)

Go to GitHub → the organization/account that owns the repos → **Settings → Developer settings → GitHub Apps**. Create two Apps and install both on the `gitops` repository only.

1. **Writer App for CI:** Select Contents: write, Pull requests: write, and Metadata: read. Generate its private key. In step 6a, enter this App ID and key in both the `backend` and `frontend` repositories.
2. **Reader App for Argo CD:** Create a separate App with Contents: read only. Generate a different private key. Keep its App ID, installation ID, and `.pem` file for step 7. Do not use the writer App credentials for Argo CD.
3. Find each App ID on its settings page under **About**. Find the installation ID by opening **Install App** and selecting the gear icon. Use the number at the end of the URL (`.../settings/installations/<ID>`); it is not the App ID.

### 6a. Where to put GitHub App and CI values

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


**Verify:** `gh variable list -R <ORG>/backend --env dev` shows `GITOPS_APP_ID`; `gh secret list -R <ORG>/backend --env dev` shows `GITOPS_APP_PRIVATE_KEY`. Check repository-level values with `gh variable list -R <ORG>/backend` and `gh secret list -R <ORG>/backend`. Repeat for `frontend`.

## 7. Install cluster components (scripts, in order)

After step 5 reports EKS nodes as `Ready`, open an Ubuntu/WSL terminal and run these scripts from `~/devops/chris/infra/scripts` in order. They install the AWS Load Balancer Controller, Argo CD, External Secrets Operator, connect Argo CD to `gitops`, and configure the cluster secret store.

```bash
cd ~/devops/chris/infra/scripts
export GITOPS_PATH=~/devops/chris/gitops
python3 01_install_prerequisites.py     # ALB controller, Argo CD, External Secrets Operator
python3 02_bootstrap_argocd.py          # registers gitops repo (asks App ID, installation ID, key path)
python3 03_setup_external_secrets.py    # DB + JWT secrets from AWS Secrets Manager
```

The scripts prompt for any required values. When `02_bootstrap_argocd.py` prompts, enter:

- The **reader App ID** for `GITHUB_APP_ID`.
- That App's **installation ID** for `GITHUB_APP_INSTALLATION_ID`.
- The path to that App's `.pem` file on your workstation for `GITHUB_APP_KEY_PATH`.

Script 02 saves these credentials in Kubernetes secret `gitops-repo` in namespace `argocd`. Do not enter them in GitHub settings. Wrong credentials cause `401 Unauthorized` errors and Argo CD applications may remain `Unknown`.

**Fix a wrong value without re-running 02:**

```bash
kubectl -n argocd patch secret gitops-repo --type merge -p \
  "{\"data\":{\"githubAppID\":\"$(printf '<APP_ID>' | base64)\",\"githubAppInstallationID\":\"$(printf '<INSTALLATION_ID>' | base64)\",\"githubAppPrivateKey\":\"$(base64 -w0 <PATH_TO_PEM>)\"}}"
kubectl -n argocd rollout restart deploy argocd-repo-server
kubectl annotate applications -n argocd --all argocd.argoproj.io/refresh=hard --overwrite
```

**Verify:** `kubectl get pods -n argocd` and `-n external-secrets` and `-n kube-system -l app.kubernetes.io/name=aws-load-balancer-controller` are all `Running`; `kubectl get clustersecretstore` shows `Valid`; `kubectl get externalsecret -A` shows `SecretSynced`.

## 8. Build the images

In an Ubuntu/WSL terminal, run script 04 from `~/devops/chris/infra/scripts`. It triggers GitHub Actions in `backend` and `frontend`; the image builds run in those repositories, not on your workstation. Replace each placeholder with your value:

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

After step 8 succeeds, run script 05 from `~/devops/chris/infra/scripts` in your Ubuntu/WSL terminal. Replace `<ORG>` with the GitHub owner and `<AWS_SSO_PROFILE>` with the local profile name from step 0. These are command-line values; do not add them to GitHub settings. Script 05 creates the Argo CD applications in namespace `dev`.

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

Get the load balancer hostname from the `ADDRESS` column of `kubectl get ingress -n dev`, then open `http://<alb-hostname>/`.

**Verify:** `curl -s -o /dev/null -w '%{http_code}\n' http://<alb-hostname>/` prints `200`; `curl -s -o /dev/null -w '%{http_code}\n' http://<alb-hostname>/api/` prints 200, 401, 403 or 404 (not 502/503).

## 10. Day-2: shipping a change

Create and push a working branch from your local `backend` clone, then open a PR in GitHub. Wait for review and required CI checks to pass before merging; never push directly to `main`. After merge, trigger the service workflow if it did not start automatically. CI builds the image and updates its tag in `gitops`.

```bash
cd ~/devops/chris/backend
git checkout -b feat/my-change
git add -A && git commit -m "feat: ..."
git push -u origin feat/my-change
gh pr create --fill
```

After CI checks pass, merge the PR in GitHub. If the build did not start automatically, trigger it after merge:

```bash
gh workflow run ci-<service>.yml -R <ORG>/backend --ref main
```

CI updates the tag in `gitops`; Argo CD syncs it. Roll back by reverting the tag commit in `gitops`.

**Verify:** the new `sha-` tag appears in `kubectl get deploy -n dev -o wide` and the pod is `Running`.

## 11. Tear down (reverse order, Terraform last)

**Where:** Run the `kubectl`, `helm` and AWS commands from your workstation terminal; start the final Terraform destroy from GitHub Actions. Use the AWS SSO profile from step 0.

Run each step, then its **Verify** command, before moving on. Destroying the cluster first leaves orphaned ALBs and security groups that block the VPC delete.

If you opened a new terminal, run `export AWS_PROFILE=mackllc-admin AWS_REGION=us-east-1` first, replacing `mackllc-admin` with the profile name you chose in step 0.

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


## Using your own account or organization

Replace `<ORG>` with the GitHub username or organization that owns your four repositories wherever it appears in this runbook. In each local clone, replace `@YOUR-GITHUB-USER-OR-TEAM` in `.github/CODEOWNERS` with your username or team; submit the change on a branch through a PR. The preceding steps tell you where to enter the AWS and GitHub values. You do not need to add values to `gitops` by hand; script 05 fills in the account ID and organization during deployment.
