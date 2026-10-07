#!/usr/bin/env python3
"""Back up ECR tag metadata before optional Kubernetes-only teardown."""

import argparse
import sys
import time

from ecr_tag_backup import (
    SERVICES, aws_json, build_backup, command, command_json, identity,
    select_services, upload_backup,
)


def teardown(namespace, context, remove_addons):
    def kube(*args):
        return command(["kubectl", "--context", context, *args])

    def kube_json(*args):
        return command_json(["kubectl", "--context", context, *args])

    current = command(["kubectl", "config", "current-context"]).strip()
    if current != context:
        raise ValueError(f"Active Kubernetes context {current!r} does not match {context!r}.")
    applications = kube_json("get", "applications", "-n", "argocd", "-o", "json")["items"]
    selected = [app for app in applications
                if app["spec"]["destination"].get("namespace") == namespace]
    if any(app["spec"]["destination"].get("server") != "https://kubernetes.default.svc"
           for app in selected):
        raise ValueError("Selected Applications must target the current in-cluster Kubernetes API.")
    if remove_addons and len(selected) != len(applications):
        raise ValueError("Other Argo CD Applications remain; shared add-ons cannot be removed.")
    ingresses = kube_json("get", "ingress", "-A", "-o", "json")["items"]
    if remove_addons and any(ingress["metadata"]["namespace"] != namespace for ingress in ingresses):
        raise ValueError("Other namespaces have Ingresses; shared controllers cannot be removed.")
    if remove_addons:
        for addon_namespace, expected_release in (("argocd", "argocd"),
                                                  ("external-secrets", "external-secrets")):
            releases = command_json(["helm", "--kube-context", context, "list",
                                     "-n", addon_namespace, "-a", "-o", "json"])
            if any(item["name"] != expected_release for item in releases):
                raise ValueError(f"Unrelated Helm releases in {addon_namespace}; teardown is blocked.")
    hosts = {
        entry["hostname"] for ingress in ingresses
        if ingress["metadata"]["namespace"] == namespace
        for entry in ingress.get("status", {}).get("loadBalancer", {}).get("ingress", [])
        if entry.get("hostname")
    }
    for ingress in ingresses:
        if ingress["metadata"]["namespace"] != namespace:
            for entry in ingress.get("status", {}).get("loadBalancer", {}).get("ingress", []):
                if entry.get("hostname") in hosts:
                    raise ValueError("An ALB is shared with another namespace; teardown is blocked.")
    load_balancers = aws_json("elbv2", "describe-load-balancers")["LoadBalancers"]
    tracked = {lb["LoadBalancerArn"] for lb in load_balancers if lb["DNSName"] in hosts}
    if hosts - {lb["DNSName"] for lb in load_balancers}:
        raise ValueError("Cannot identify every Ingress ALB in this AWS account/region.")

    print(f"Deleting workloads in {namespace}; preserving EKS, RDS, VPC, IAM, ECR and S3.")
    for app in selected:
        kube("delete", "application", app["metadata"]["name"],
             "-n", "argocd", "--wait=true", "--timeout=300s")
    kube("delete", "ingress", "--all", "-n", namespace,
         "--wait=true", "--timeout=300s")
    deadline = time.monotonic() + 300
    while tracked:
        existing = {lb["LoadBalancerArn"] for lb in
                    aws_json("elbv2", "describe-load-balancers")["LoadBalancers"]}
        if not tracked & existing:
            break
        if time.monotonic() >= deadline:
            raise RuntimeError("ALB cleanup timed out; retaining controllers and namespaces.")
        print("Waiting for the ALB controller to remove this namespace's ALB...")
        time.sleep(10)
    # ESO stays running until namespace finalizers are resolved.
    kube("delete", "namespace", namespace, "--ignore-not-found=true",
         "--wait=true", "--timeout=300s")
    if remove_addons:
        for release, release_namespace in (
            ("argocd", "argocd"), ("external-secrets", "external-secrets"),
            ("aws-load-balancer-controller", "kube-system"),
        ):
            releases = command_json(["helm", "--kube-context", context, "list",
                                     "-n", release_namespace, "-a", "-o", "json"])
            if any(item["name"] == release for item in releases):
                command(["helm", "--kube-context", context, "uninstall", release, "-n", release_namespace,
                         "--wait", "--timeout", "300s"])
            remaining = command_json(["helm", "--kube-context", context, "list",
                                      "-n", release_namespace, "-a", "-o", "json"])
            if any(item["name"] == release for item in remaining):
                raise RuntimeError(f"Helm release {release} remains after uninstall.")
        for addon_namespace in ("argocd", "external-secrets"):
            kube("delete", "namespace", addon_namespace,
                 "--ignore-not-found=true", "--wait=true", "--timeout=300s")
    remaining_apps = kube_json("get", "applications", "-n", "argocd", "-o", "json")
    if any(app["spec"]["destination"].get("namespace") == namespace
           for app in remaining_apps["items"]):
        raise RuntimeError("Selected Applications remain after teardown.")
    namespaces = kube_json("get", "namespaces", "-o", "json")
    if any(item["metadata"]["name"] == namespace for item in namespaces["items"]):
        raise RuntimeError("Workload namespace remains after teardown.")
    print("Kubernetes teardown verified. Terraform infrastructure and ECR images were retained.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup-uri", required=True, help="Unique s3://bucket/key recovery point")
    parser.add_argument("--services", default="A", help="A, F, B, or comma-separated service names")
    parser.add_argument("--namespace", choices=("dev", "qa", "prod"), default="dev")
    parser.add_argument("--context", help="Exact expected Kubernetes context for teardown")
    parser.add_argument("--teardown", action="store_true", help="Delete the selected workload namespace")
    parser.add_argument("--remove-addons", action="store_true", help="Also remove base Helm releases/namespaces")
    args = parser.parse_args()
    services = select_services(args.services)
    if args.remove_addons and not args.teardown:
        raise ValueError("--remove-addons requires --teardown.")
    if args.teardown and (set(services) != set(SERVICES) or not args.context):
        raise ValueError("Namespace teardown requires all services and an exact --context.")
    account, region = identity()
    if args.teardown:
        if f":eks:{region}:{account}:cluster/" not in args.context:
            raise ValueError("Expected context must identify an EKS cluster in the active account/region.")
        if command(["kubectl", "config", "current-context"]).strip() != args.context:
            raise ValueError("Active Kubernetes context does not match --context.")
        print(f"Account: {account}; region: {region}; context: {args.context}")
        print(f"Backup: {args.backup_uri}; workload namespace: {args.namespace}")
        if input("Type the exact cluster context to approve Kubernetes teardown: ").strip() != args.context:
            raise ValueError("Teardown was not confirmed.")
    backup = build_backup(services, account, region)
    upload_backup(args.backup_uri, backup, account, region)
    # Fail closed if ECR changed during backup upload/read-back.
    current = build_backup(services, account, region)
    if current["repositories"] != backup["repositories"]:
        raise ValueError("ECR inventory changed while backing up; teardown is blocked. Use a new backup key.")
    print(f"Tag backup uploaded, read back and verified: {args.backup_uri}")
    if args.teardown:
        teardown(args.namespace, args.context, args.remove_addons)
    else:
        print("Backup-only mode: nothing was deleted.")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, KeyError, OSError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)
