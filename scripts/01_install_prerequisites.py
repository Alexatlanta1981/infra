#!/usr/bin/env python3
# =============================================================================
# Stage 2 - Install Kubernetes Pre-requisites
#
# Installs on the EKS cluster (must already exist from Stage 1 Terraform):
#   1. AWS Load Balancer Controller - exposes services via AWS ALB
#   2. ArgoCD                       - GitOps CD controller
#   3. External Secrets Operator    - syncs AWS Secrets Manager -> K8s Secrets
#
# Run from anywhere — paths are resolved relative to this script's location.
# =============================================================================

import json
import os
import re
import subprocess
import sys
from datetime import datetime

# Default project root is two levels above this script (infra/scripts/ → project root)
DEFAULT_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------
RED    = "\033[0;31m"
GREEN  = "\033[0;32m"
YELLOW = "\033[1;33m"
CYAN   = "\033[0;36m"
NC     = "\033[0m"

def _ts():
    return datetime.now().strftime("%H:%M:%S")

def log(msg):   print(f"{GREEN}[{_ts()}] OK  {msg}{NC}")
def warn(msg):  print(f"{YELLOW}[{_ts()}] !!  {msg}{NC}")
def info(msg):  print(f"{CYAN}[{_ts()}]    {msg}{NC}")
def die(msg):
    print(f"{RED}[{_ts()}] ERR {msg}{NC}", file=sys.stderr)
    sys.exit(1)

# ---------------------------------------------------------------------------
# run_cmd: run a shell command, streaming output; die on failure unless ok_fail=True
# ---------------------------------------------------------------------------
def run_cmd(args, ok_fail=False, capture=False, stdin_data=None):
    if capture:
        result = subprocess.run(args, capture_output=True, text=True)
        if result.returncode != 0 and not ok_fail:
            if result.stderr:
                print(result.stderr.strip(), file=sys.stderr)
            die(f"Command failed: {' '.join(str(a) for a in args)}")
        return result.stdout.strip(), result.returncode
    result = subprocess.run(args, input=stdin_data, text=stdin_data is not None)
    if result.returncode != 0 and not ok_fail:
        die(f"Command failed: {' '.join(str(a) for a in args)}")
    return None, result.returncode

# ---------------------------------------------------------------------------
# prompt: ask the user for a value, skip if already in environment
# ---------------------------------------------------------------------------
def prompt(var_name, label, example, default=""):
    current = os.environ.get(var_name, "")
    if current:
        info(f"Using {var_name}={current}  (pre-set in environment, skipping prompt)")
        return current

    print()
    print(f"{CYAN}  {label}{NC}")
    print(f"    Example : {example}")

    if default:
        print(f"    Default : {default}")
        raw = input("    Your value [press Enter to use default]: ").strip()
    else:
        raw = input("    Your value: ").strip()

    value = raw if raw else default
    if not value:
        die(f"'{label}' is required and cannot be empty.")

    log(f"  {var_name} = {value}")
    return value


def argocd_ingress(region, account_id):
    enabled = os.environ.get("ARGOCD_INGRESS_ENABLED", "0")
    if enabled not in ("0", "1"):
        die("ARGOCD_INGRESS_ENABLED must be 0 or 1.")
    if enabled == "0":
        return None
    host = prompt("ARGOCD_HOSTNAME", "Argo CD DNS hostname", "argocd.example.com")
    if len(host) > 253 or not all(
            re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
            for label in host.split(".")):
        die("ARGOCD_HOSTNAME must be a DNS hostname, not a URL.")
    certificate = prompt("ARGOCD_CERTIFICATE_ARN", "ACM certificate ARN for this hostname",
                         "arn:aws:acm:<region>:<account>:certificate/<id>")
    if not re.fullmatch(
            rf"arn:aws[a-z-]*:acm:{re.escape(region)}:{account_id}:certificate/[A-Za-z0-9-]+",
            certificate):
        die("ACM certificate must belong to the selected account and region.")
    scheme = os.environ.get("ARGOCD_INGRESS_SCHEME", "internal")
    if scheme not in ("internal", "internet-facing"):
        die("ARGOCD_INGRESS_SCHEME must be internal or internet-facing.")
    annotations = {
        "alb.ingress.kubernetes.io/scheme": scheme,
        "alb.ingress.kubernetes.io/target-type": "ip",
        "alb.ingress.kubernetes.io/backend-protocol": "HTTPS",
        "alb.ingress.kubernetes.io/listen-ports": '[{"HTTPS":443}]',
        "alb.ingress.kubernetes.io/certificate-arn": certificate,
        "alb.ingress.kubernetes.io/ssl-policy": "ELBSecurityPolicy-TLS13-1-2-2021-06",
    }
    group = os.environ.get("ARGOCD_ALB_GROUP", "")
    if group:
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]{0,61}[a-z0-9])?", group):
            die("ARGOCD_ALB_GROUP must be 1-63 lowercase letters, numbers, dots or hyphens.")
        annotations["alb.ingress.kubernetes.io/group.name"] = group
    return {
        "apiVersion": "networking.k8s.io/v1", "kind": "Ingress",
        "metadata": {"name": "argocd-server-ingress", "namespace": "argocd",
                     "labels": {"managed-by": "infra-bootstrap"},
                     "annotations": annotations},
        "spec": {"ingressClassName": "alb", "rules": [{
            "host": host, "http": {"paths": [{
                "path": "/", "pathType": "Prefix",
                "backend": {"service": {"name": "argocd-server",
                                       "port": {"number": 443}}}}]}}]},
    }

# ---------------------------------------------------------------------------
# Verify required tools are installed
# ---------------------------------------------------------------------------
print()
print("Checking required tools...")
for tool in ["kubectl", "helm", "aws"]:
    rc = subprocess.run(["which", tool], capture_output=True).returncode
    if rc != 0:
        die(f"{tool} not found. Install it before running this script.")
log("kubectl, helm, and aws CLI found.")

# ---------------------------------------------------------------------------
# Collect inputs
# ---------------------------------------------------------------------------
print()
print("============================================")
print("  MackLLC -- Pre-requisites Installer")
print("============================================")
print()
print("  This script installs AWS Load Balancer Controller, ArgoCD, and")
print("  External Secrets Operator on your EKS cluster using Helm.")
print()
print("  You will be asked for 4 values:")
print("    1. EKS cluster name         - from Terraform outputs or AWS console")
print("    2. AWS region               - where your cluster is running")
print("    3. VPC ID                   - VPC where the cluster lives (auto-fetched if blank)")
print("    4. ALB controller role ARN  - IAM role ARN for the ALB controller")
print("       (arn:aws:iam::<account-id>:role/<project>-<env>-alb-controller-irsa)")
print()

CLUSTER_NAME        = prompt("CLUSTER_NAME",        "EKS cluster name",
                             "your-project-your-env-cluster")
configured_region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION", "")
if not configured_region:
    configured_region, _ = run_cmd(["aws", "configure", "get", "region"], capture=True,
                                   ok_fail=True)
AWS_REGION          = prompt("AWS_REGION",          "AWS region where the cluster is deployed",
                             "your-cluster-region", configured_region)
account_id, _ = run_cmd(["aws", "sts", "get-caller-identity", "--query", "Account",
                        "--output", "text"], capture=True)
if not re.fullmatch(r"[0-9]{12}", account_id):
    die("AWS identity did not return a valid account ID.")
ALB_CONTROLLER_ROLE = prompt("ALB_CONTROLLER_ROLE", "IAM role ARN for the AWS Load Balancer Controller",
                             "arn:aws:iam::<account>:role/<project>-<env>-alb-controller-irsa")
if not re.fullmatch(rf"arn:aws[a-z-]*:iam::{account_id}:role/.+", ALB_CONTROLLER_ROLE):
    die("ALB controller role must belong to the authenticated AWS account.")

default_gitops = os.path.join(DEFAULT_PROJECT_ROOT, "gitops")
GITOPS_PATH         = prompt("GITOPS_PATH",         "Local path to your gitops repo",
                             default_gitops, default_gitops)

# Auto-fetch VPC ID from EKS cluster if not set in environment
VPC_ID = os.environ.get("VPC_ID", "")
if not VPC_ID:
    info(f"Auto-fetching VPC ID for cluster '{CLUSTER_NAME}'...")
    VPC_ID, rc = run_cmd(
        ["aws", "eks", "describe-cluster", "--name", CLUSTER_NAME,
         "--region", AWS_REGION,
         "--query", "cluster.resourcesVpcConfig.vpcId",
         "--output", "text"],
        capture=True,
    )
    if rc == 0 and VPC_ID and VPC_ID != "None":
        log(f"VPC ID auto-detected: {VPC_ID}")
    else:
        die("EKS did not return a valid VPC ID; check the cluster and region.")

ARGOCD_INGRESS = argocd_ingress(AWS_REGION, account_id)
if ARGOCD_INGRESS and os.environ.get("SKIP_ALB_CONTROLLER") == "1":
    die("Argo CD Ingress requires the ALB controller; do not combine with SKIP_ALB_CONTROLLER.")

print()
print("  ----- Configuration Summary -----")
print(f"  Cluster          : {CLUSTER_NAME}")
print(f"  Region           : {AWS_REGION}")
print(f"  VPC ID           : {VPC_ID}")
print(f"  ALB role ARN     : {ALB_CONTROLLER_ROLE}")
print(f"  AWS account      : {account_id}")
if ARGOCD_INGRESS:
    print(f"  ArgoCD Ingress   : {ARGOCD_INGRESS['spec']['rules'][0]['host']}")
    print(f"  ALB scheme       : {ARGOCD_INGRESS['metadata']['annotations']['alb.ingress.kubernetes.io/scheme']}")
else:
    print("  ArgoCD Ingress   : disabled (private port-forward access)")
print("  ---------------------------------")
print()
confirm = input("  Proceed with installation? [Y/n]: ").strip() or "Y"
if confirm.upper() != "Y":
    print("Aborted.")
    sys.exit(0)
print()

# ---------------------------------------------------------------------------
# Configure kubectl
# ---------------------------------------------------------------------------
info(f"Updating kubeconfig for cluster '{CLUSTER_NAME}' in '{AWS_REGION}'...")
_, rc = run_cmd(
    ["aws", "eks", "update-kubeconfig", "--region", AWS_REGION, "--name", CLUSTER_NAME],
)

ctx, _ = run_cmd(["kubectl", "config", "current-context"], capture=True)
log(f"kubectl context: {ctx}")

# ---------------------------------------------------------------------------
# Add Helm repositories
# ---------------------------------------------------------------------------
print()
info("Adding Helm repositories...")
for name, url in [
    ("eks",              "https://aws.github.io/eks-charts"),
    ("external-secrets", "https://charts.external-secrets.io"),
    ("argo",             "https://argoproj.github.io/argo-helm"),
]:
    run_cmd(["helm", "repo", "add", name, url, "--force-update"])
run_cmd(["helm", "repo", "update"])
log("Helm repos updated.")

# ---------------------------------------------------------------------------
# Step 1 - AWS Load Balancer Controller
#
# Watches Ingress resources with ingressClassName: alb and provisions an
# AWS Application Load Balancer for each IngressGroup. Runs in kube-system
# and uses IRSA (IAM Roles for Service Accounts) to call AWS APIs.
# ---------------------------------------------------------------------------
print()
print("--------------------------------------------")
print("  Step 1 of 3: AWS Load Balancer Controller")
print("--------------------------------------------")

# SKIP_ALB_CONTROLLER=1 is for CI smoke tests on kind (no AWS).
if os.environ.get("SKIP_ALB_CONTROLLER") == "1":
    warn("SKIP_ALB_CONTROLLER=1 - skipping AWS Load Balancer Controller.")
else:
    ALB_VALUES_FILE = os.path.join(GITOPS_PATH, "k8s/ingress/alb-controller-values.yaml")

    alb_cmd = [
        "helm", "upgrade", "--install", "aws-load-balancer-controller",
        "eks/aws-load-balancer-controller",
        "--namespace", "kube-system",
        "--set", f"clusterName={CLUSTER_NAME}",
        "--set", f"region={AWS_REGION}",
        "--set", f"vpcId={VPC_ID}",
        "--set", "serviceAccount.create=true",
        "--set", "serviceAccount.name=aws-load-balancer-controller",
        "--set", f"serviceAccount.annotations.eks\\.amazonaws\\.com/role-arn={ALB_CONTROLLER_ROLE}",
        "--wait", "--timeout", "5m",
    ]

    if os.path.isfile(ALB_VALUES_FILE):
        alb_cmd += ["-f", ALB_VALUES_FILE]
        info(f"Using values file: {ALB_VALUES_FILE}")

    run_cmd(alb_cmd)
    log("AWS Load Balancer Controller installed.")

    alb_version, _ = run_cmd(
        ["helm", "list", "-n", "kube-system", "--filter", "aws-load-balancer-controller",
         "--short"],
        capture=True, ok_fail=True,
    )
    log(f"Release: {alb_version or 'aws-load-balancer-controller'}")
    print("  NOTE: ALB hostnames are provisioned per-Ingress after ArgoCD syncs apps.")

    # Every helm upgrade regenerates the webhook CA, but running pods keep the
    # old cert and every Service create then fails with x509 errors. Restart the
    # controller so it serves the cert that matches the webhook CA bundle.
    info("Restarting ALB controller so its webhook cert matches the CA bundle...")
    run_cmd(["kubectl", "-n", "kube-system", "rollout", "restart",
             "deployment/aws-load-balancer-controller"])
    run_cmd(["kubectl", "-n", "kube-system", "rollout", "status",
             "deployment/aws-load-balancer-controller", "--timeout=180s"])
    log("ALB controller restarted.")

# ---------------------------------------------------------------------------
# Step 2 - ArgoCD
# ---------------------------------------------------------------------------
print()
print("--------------------------------------------")
print("  Step 2 of 3: ArgoCD")
print("--------------------------------------------")

run_cmd([
    "helm", "upgrade", "--install", "argocd", "argo/argo-cd",
    "--namespace", "argocd",
    "--create-namespace",
    "--wait", "--timeout", "10m",
])

log("ArgoCD installed.")
print()
print("  ============================================================")
print("  ArgoCD access (credentials are not retrieved or printed)")
print("  ============================================================")
print("  Username : admin")
print("  Retrieve the initial password privately using runbook step 7.A.")
print()
print("  To access the ArgoCD UI:")
print("    kubectl port-forward svc/argocd-server -n argocd 8080:443")
print("    Then open: https://localhost:8080")
print("  ============================================================")
print()

if ARGOCD_INGRESS:
    run_cmd(["kubectl", "apply", "-f", "-"], stdin_data=json.dumps(ARGOCD_INGRESS))
    log("ArgoCD ingress applied.")
else:
    info("ArgoCD Ingress not applied. Existing Ingresses are not removed.")

# ---------------------------------------------------------------------------
# Step 3 - External Secrets Operator
# ---------------------------------------------------------------------------
print()
print("--------------------------------------------")
print("  Step 3 of 3: External Secrets Operator")
print("--------------------------------------------")

run_cmd([
    "helm", "upgrade", "--install", "external-secrets", "external-secrets/external-secrets",
    "--namespace", "external-secrets",
    "--create-namespace",
    "--set", "installCRDs=true",
    "--wait", "--timeout", "5m",
])

log("External Secrets Operator installed.")

# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------
print()
print("--------------------------------------------")
print("  Verification")
print("--------------------------------------------")
print()
print("AWS Load Balancer Controller pods (namespace: kube-system):")
run_cmd(["kubectl", "get", "pods", "-n", "kube-system",
         "-l", "app.kubernetes.io/name=aws-load-balancer-controller"])
print()
print("ArgoCD pods (namespace: argocd):")
run_cmd(["kubectl", "get", "pods", "-n", "argocd"])
print()
print("External Secrets pods (namespace: external-secrets):")
run_cmd(["kubectl", "get", "pods", "-n", "external-secrets"])

print()
log("All pre-requisites installed successfully.")
print()
print("  Summary:")
print(f"    ALB controller   : installed in kube-system")
print("    ArgoCD           : installed in argocd")
print()
print("  ALB hostnames will appear in 'kubectl get ingress -n <env>'")
print("  once ArgoCD has synced your applications.")
print()
print("Next step: ./scripts/02_bootstrap_argocd.py")
