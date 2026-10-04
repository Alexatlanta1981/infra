# 📘 Personal Study Guide — MackLLC Platform (plain English)

Use this to explain the project and your troubleshooting in an interview.

---

## 1. The 30-second pitch

> "I built and deployed a pharmaceutical microservices platform on AWS. Terraform builds the cloud
> (network, Kubernetes cluster, database, permissions). GitHub Actions builds each service into a
> container image. Argo CD watches a Git repo and automatically deploys whatever is there to the cluster.
> A load balancer exposes it to the internet. I hit about 16 real problems — mostly authentication — and
> documented each one and its fix. The next version (v1.2) replaces stored passwords/tokens with
> SSO and short-lived identity (OIDC / IRSA)."

---

## 2. The big picture (restaurant analogy)

| Real thing | Analogy |
|-----------|---------|
| **Terraform** | The architect + builder: constructs the restaurant building (network, kitchen, storage) |
| **AWS (VPC, EKS, RDS, ECR)** | The building, kitchen, pantry, and recipe-box shelves |
| **Docker image** | A sealed meal kit — everything the app needs |
| **ECR** | The shelf where meal kits are stored |
| **GitHub Actions (CI)** | The prep line: builds the meal kit when code changes |
| **Gitops repo** | The order board: says which meal kit/version should be on the menu |
| **Argo CD** | The manager who watches the board and makes the kitchen match it |
| **Kubernetes (EKS)** | The kitchen that runs the meals (pods = cooks) |
| **Ingress + ALB controller** | The front door: a worker who builds the entrance (load balancer) when told |
| **Load Balancer (ALB)** | The host who sends guests to the right table |
| **RDS (Postgres)** | The filing cabinet with all the data |
| **Secrets Manager + External Secrets** | A locked safe holding the cabinet key, copied into the kitchen automatically |
| **OIDC / IAM roles** | Visitor badges that prove "I'm allowed to do this" |

---

## 3. How it's wired, start to finish

```
Developer pushes code
        │
        ▼
GitHub Actions (CI)  ── badge (OIDC role) ──► AWS
   1. build + test
   2. build Docker image
   3. push image to ECR
   4. edit image tag in the GITOPS repo   (needs GITOPS_TOKEN)
        │
        ▼
Gitops repo (Git = source of truth)
        │  Argo CD watches it
        ▼
Argo CD ──► Kubernetes (EKS) runs pods
        │        │
        │        ├─ reads DB password from Secrets Manager (via External Secrets)
        │        └─ talks to RDS Postgres
        ▼
Ingress object ──► AWS Load Balancer Controller ──► creates the ALB
        ▼
Internet users ──► ALB ──► frontend / api-gateway ──► microservices
```

**Order of operations (setup scripts):**
1. `terraform apply` → network, EKS, RDS, ECR, IAM roles, secrets
2. Install prerequisites → Argo CD + AWS Load Balancer Controller
3. Set up External Secrets → pods can read secrets
4. Run CI pipelines → images land in ECR, tags land in gitops
5. Deploy services → Argo CD applications created, pods start
6. Verify → pods Running, ALB has an address

---

## 4. Troubleshooting stories (say these in interviews)

For each: **Symptom → How I found it → Cause → Fix → Lesson.**

### A. "Terraform succeeded but I see no load balancers"
- **Cause:** Terraform only creates the *permission role*. The ALB is created later by a controller
  *inside* the cluster when it sees an Ingress.
- **Lesson:** Know which tool owns which resource.

### B. "CI can't log in to AWS" (OIDC)
- **Symptom:** `AssumeRoleWithWebIdentity` denied.
- **Cause:** No OIDC provider/role existed; then the trust rule named the wrong org and didn't match
  GitHub's newer *immutable* ID-style subject claim.
- **Fix:** Created the provider + role in Terraform; trust policy allows the correct repo patterns.
- **Lesson:** Read the exact identity claim GitHub sends and match it.

### C. "CI built the image but couldn't update the gitops repo" (403)
- **Cause:** `GITOPS_TOKEN` was missing, empty, or not scoped to the gitops repo.
- **Fix:** Re-created with correct scope.
- **Lesson:** Stored tokens are fragile → v1.2 uses a GitHub App / short-lived credentials.

### D. "SonarCloud failed my build"
- **Cause:** Sonar wasn't configured, yet was a blocking step.
- **Fix:** Non-blocking for v1.0; v1.2 configures it properly as a real quality gate.

### E. "Pods crash-looping — password authentication failed"
- **How I found it:** `kubectl logs` showed a Postgres error.
- **Cause:** The password in Secrets Manager (what pods use) didn't match the real database password.
- **Fix:** Reset the RDS password to match the secret, restarted pods.
- **Lesson:** One source of truth for credentials; Terraform should drive both from the same value.

### F. "Ingress had no address" (the sneaky one)
- **How I found it:** `kubectl describe ingress` showed no events → checked the controller logs →
  `InvalidIdentityToken`.
- **Cause:** My bootstrap script had a hardcoded wrong AWS account ID in the controller's role ARN, so it
  could never log in to AWS.
- **Fix:** Corrected the annotation, restarted the controller, ALB appeared. Scripts now look up the
  account ID automatically.
- **Lesson:** Follow the chain: symptom → events → logs → root cause. Never hardcode account IDs.

### G. "Pods stuck Pending"
- **Cause:** Small cluster, not enough room during rolling restarts.
- **Fix:** Wait/scale. v1.2: autoscaling nodes.

---

## 5. Key words in plain English

- **IAM role** – a set of permissions something can "put on" temporarily.
- **OIDC** – lets GitHub prove who it is to AWS *without* a stored password.
- **IRSA / Pod Identity** – the same idea for a pod inside Kubernetes.
- **SSO** – log in once with your company identity instead of keeping access keys.
- **GitOps** – Git is the source of truth; the cluster automatically matches it.
- **Ingress** – a Kubernetes request: "please expose this app to the internet."
- **Pod** – one running copy of an app.
- **Secret** – sensitive config (passwords) kept out of code.
- **CI** – automatic build/test whenever code changes.

---

## 6. What v1.0 → v1.2 improves (say this at the end)

| v1.0 (works) | v1.2 (production-grade) |
|-------------|--------------------------|
| Long-lived `GITOPS_TOKEN` | GitHub App / short-lived credentials |
| Human access keys | AWS IAM Identity Center (SSO) |
| Broad OIDC trust | Tightly scoped OIDC trust (repo + branch/environment) |
| Hand-typed account IDs/prompts | Values read from Terraform outputs |
| Manual DB password reset | Single source of truth for DB creds |
| Sonar non-blocking | Real quality gates |
| Manual script-driven setup | Fully pipeline-driven; destroy → redeploy proves it |
| Controller cert drift | cert-manager |

**Closing line:** "The most valuable thing I learned: when something 'succeeds' but doesn't work,
trace it step by step — events, then logs — until you find the real cause."

---

## 7. Practice questions

1. Why didn't Terraform create the load balancer?
2. What's the difference between OIDC and a stored token? Why is OIDC safer?
3. How does a change in code end up running in the cluster?
4. Pods crash with a database auth error — what do you check, in order?
5. An Ingress has no address — what do you check?
6. What does GitOps mean and what does Argo CD do?
