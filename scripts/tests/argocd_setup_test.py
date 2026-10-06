import ast
import contextlib
import io
import json
import os
import re
from pathlib import Path
import runpy
import subprocess
import unittest
from unittest.mock import patch


SCRIPTS = Path(__file__).resolve().parents[1]


class ArgoCDSetupTests(unittest.TestCase):
    def ingress_helper(self):
        tree = ast.parse((SCRIPTS / "01_install_prerequisites.py").read_text())
        functions = [node for node in tree.body
                     if isinstance(node, ast.FunctionDef) and node.name == "argocd_ingress"]
        def die(message):
            raise SystemExit(message)
        namespace = {"os": os, "re": re, "die": die,
                     "prompt": lambda variable, *args: os.environ[variable]}
        exec(compile(ast.Module(body=functions, type_ignores=[]), "<ingress>", "exec"),
             namespace)
        return namespace["argocd_ingress"]

    def test_ingress_disabled_by_default(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(self.ingress_helper()("eu-west-1", "123456789012"))

    def test_ingress_adapts_to_deployment_without_shared_group(self):
        environment = {
            "ARGOCD_INGRESS_ENABLED": "1", "ARGOCD_HOSTNAME": "argo.example.org",
            "ARGOCD_CERTIFICATE_ARN": "arn:aws:acm:eu-west-1:123456789012:certificate/demo",
        }
        with patch.dict(os.environ, environment, clear=True):
            data = self.ingress_helper()("eu-west-1", "123456789012")
            annotations = data["metadata"]["annotations"]
            self.assertEqual(data["spec"]["rules"][0]["host"], "argo.example.org")
            self.assertEqual(annotations["alb.ingress.kubernetes.io/scheme"], "internal")
            self.assertNotIn("alb.ingress.kubernetes.io/group.name", annotations)
            os.environ["ARGOCD_INGRESS_SCHEME"] = "internet-facing"
            os.environ["ARGOCD_ALB_GROUP"] = "demo-qa-argocd"
            data = self.ingress_helper()("eu-west-1", "123456789012")
            self.assertEqual(data["metadata"]["annotations"]["alb.ingress.kubernetes.io/group.name"],
                             "demo-qa-argocd")
            self.assertNotIn("mackllc", json.dumps(data))

    def test_ingress_rejects_invalid_inputs(self):
        base = {
            "ARGOCD_INGRESS_ENABLED": "1", "ARGOCD_HOSTNAME": "argo.example.org",
            "ARGOCD_CERTIFICATE_ARN": "arn:aws:acm:eu-west-1:123456789012:certificate/demo",
        }
        for variable, value in [
                ("ARGOCD_INGRESS_ENABLED", "yes"), ("ARGOCD_HOSTNAME", "https://example.org"),
                ("ARGOCD_CERTIFICATE_ARN", "arn:aws:acm:us-east-1:123456789012:certificate/demo"),
                ("ARGOCD_CERTIFICATE_ARN", "arn:aws:acm:eu-west-1:999999999999:certificate/demo"),
                ("ARGOCD_INGRESS_SCHEME", "public"), ("ARGOCD_ALB_GROUP", "bad/group")]:
            with self.subTest(variable=variable, value=value), \
                    patch.dict(os.environ, {**base, variable: value}, clear=True):
                with self.assertRaises(SystemExit):
                    self.ingress_helper()("eu-west-1", "123456789012")

    def test_installer_never_reads_admin_secret(self):
        commands = []

        def run(args, **kwargs):
            commands.append(args)
            return subprocess.CompletedProcess(args, 0, stdout="123456789012")

        environment = {
            "CLUSTER_NAME": "demo",
            "AWS_REGION": "us-east-1",
            "ALB_CONTROLLER_ROLE": "arn:aws:iam::123456789012:role/demo",
            "GITOPS_PATH": "/nonexistent-demo-gitops",
            "VPC_ID": "vpc-demo",
            "SKIP_ALB_CONTROLLER": "1",
        }
        output = io.StringIO()
        with patch.dict(os.environ, environment, clear=True), \
                patch("subprocess.run", side_effect=run), \
                patch("os.path.isfile", side_effect=lambda path: path.endswith("argocd-ingress.yaml")), \
                patch("builtins.input", return_value="Y"), \
                contextlib.redirect_stdout(output):
            runpy.run_path(str(SCRIPTS / "01_install_prerequisites.py"))

        self.assertFalse(any("secret" in command for command in commands))
        self.assertFalse(any(command[:2] == ["kubectl", "apply"] for command in commands))
        self.assertNotIn("Password :", output.getvalue())
        self.assertNotIn("ArgoCD pass", output.getvalue())
        self.assertIn("All pre-requisites installed successfully.", output.getvalue())

    def test_enabled_ingress_and_controller_use_selected_deployment(self):
        commands = []
        manifests = []

        def run(args, **kwargs):
            commands.append(args)
            if kwargs.get("input"):
                manifests.append(json.loads(kwargs["input"]))
            stdout = "vpc-selected" if "describe-cluster" in args else "123456789012"
            return subprocess.CompletedProcess(args, 0, stdout=stdout)

        environment = {
            "CLUSTER_NAME": "recruiter-qa", "AWS_REGION": "eu-west-1",
            "ALB_CONTROLLER_ROLE": "arn:aws:iam::123456789012:role/recruiter-qa-alb",
            "GITOPS_PATH": "/nonexistent-demo-gitops", "ARGOCD_INGRESS_ENABLED": "1",
            "ARGOCD_HOSTNAME": "argo.example.org",
            "ARGOCD_CERTIFICATE_ARN": "arn:aws:acm:eu-west-1:123456789012:certificate/demo",
            "ARGOCD_INGRESS_SCHEME": "internet-facing", "ARGOCD_ALB_GROUP": "recruiter-qa",
        }
        with patch.dict(os.environ, environment, clear=True), \
                patch("subprocess.run", side_effect=run), \
                patch("builtins.input", return_value="Y"), \
                contextlib.redirect_stdout(io.StringIO()):
            runpy.run_path(str(SCRIPTS / "01_install_prerequisites.py"))
        self.assertIn(["aws", "eks", "update-kubeconfig", "--region", "eu-west-1",
                       "--name", "recruiter-qa"], commands)
        controller = next(cmd for cmd in commands if "eks/aws-load-balancer-controller" in cmd)
        for setting in ["clusterName=recruiter-qa", "region=eu-west-1", "vpcId=vpc-selected",
                        "serviceAccount.annotations.eks\\.amazonaws\\.com/role-arn="
                        + environment["ALB_CONTROLLER_ROLE"]]:
            self.assertIn(setting, controller)
        self.assertEqual(len(manifests), 1)
        self.assertEqual(manifests[0]["spec"]["rules"][0]["host"], "argo.example.org")
        self.assertEqual(manifests[0]["metadata"]["annotations"][
            "alb.ingress.kubernetes.io/certificate-arn"], environment["ARGOCD_CERTIFICATE_ARN"])
        self.assertEqual(manifests[0]["metadata"]["annotations"][
            "alb.ingress.kubernetes.io/scheme"], "internet-facing")

    def test_failed_kubeconfig_does_not_install_in_old_context(self):
        commands = []
        def run(args, **kwargs):
            commands.append(args)
            rc = 1 if args[:3] == ["aws", "eks", "update-kubeconfig"] else 0
            return subprocess.CompletedProcess(args, rc, stdout="123456789012")
        environment = {
            "CLUSTER_NAME": "demo", "AWS_REGION": "eu-west-1",
            "ALB_CONTROLLER_ROLE": "arn:aws:iam::123456789012:role/demo",
            "GITOPS_PATH": "/nonexistent-demo-gitops", "VPC_ID": "vpc-demo",
        }
        with patch.dict(os.environ, environment, clear=True), \
                patch("subprocess.run", side_effect=run), \
                patch("builtins.input", return_value="Y"), \
                contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                runpy.run_path(str(SCRIPTS / "01_install_prerequisites.py"))
        self.assertFalse(any(command[0] == "helm" for command in commands))

    def repository_prompt(self):
        tree = ast.parse((SCRIPTS / "02_bootstrap_argocd.py").read_text())
        prompt = next(node for node in tree.body
                      if isinstance(node, ast.FunctionDef) and node.name == "prompt")
        assignment = next(node for node in tree.body
                          if isinstance(node, ast.Assign)
                          and any(isinstance(target, ast.Name)
                                  and target.id == "GITOPS_REPO_URL"
                                  for target in node.targets))
        namespace = {
            "os": os,
            "info": lambda message: None,
            "log": lambda message: None,
            "die": lambda message: self.fail(message),
            "CYAN": "",
            "NC": "",
        }
        exec(compile(ast.Module(body=[prompt], type_ignores=[]), "<prompt>", "exec"),
             namespace)
        return assignment, namespace

    def test_reader_key_is_loaded_from_file_not_command_arguments(self):
        commands = []
        inputs = []
        generated_secret = "mock-generated-secret-yaml"

        def run(args, **kwargs):
            commands.append(args)
            if "input" in kwargs:
                inputs.append(kwargs["input"])
            return subprocess.CompletedProcess(args, 0, stdout=generated_secret)

        environment = {
            "ENV": "dev",
            "GITOPS_REPO_URL": "https://github.com/demo-owner/gitops.git",
            "GITHUB_APP_ID": "123",
            "GITHUB_APP_INSTALLATION_ID": "456",
            "GITHUB_APP_KEY_PATH": "~/reader key.pem",
            "GITOPS_PATH": "/nonexistent-demo-gitops",
        }
        with patch.dict(os.environ, environment, clear=True), \
                patch("subprocess.run", side_effect=run), \
                patch("builtins.input", return_value="Y"), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            runpy.run_path(str(SCRIPTS / "02_bootstrap_argocd.py"))
        create = next(cmd for cmd in commands if cmd[:3] == ["kubectl", "create", "secret"])
        self.assertIn("--from-file=githubAppPrivateKey=" +
                      os.path.expanduser("~/reader key.pem"), create)
        self.assertFalse(any(arg.startswith("--from-literal=githubAppPrivateKey=")
                             for cmd in commands for arg in cmd))
        self.assertIn(generated_secret, inputs)
        self.assertNotIn(generated_secret, output.getvalue())
        self.assertIn("argocd.argoproj.io/secret-type=repository",
                      next(cmd for cmd in commands if cmd[:2] == ["kubectl", "label"]))

    def test_repository_url_is_required(self):
        assignment, namespace = self.repository_prompt()

        def die(message):
            raise SystemExit(message)

        namespace["die"] = die
        with patch.dict(os.environ, {}, clear=True), \
                patch("builtins.input", return_value=""), \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(SystemExit, "required and cannot be empty"):
                exec(compile(ast.Module(body=[assignment], type_ignores=[]),
                             "<repository>", "exec"), namespace)

    def test_repository_url_uses_operator_input(self):
        assignment, namespace = self.repository_prompt()
        for supplied_by_environment in (True, False):
            with self.subTest(environment=supplied_by_environment):
                url = "https://github.com/demo-owner/gitops.git"
                environment = {"GITOPS_REPO_URL": url} if supplied_by_environment else {}
                with patch.dict(os.environ, environment, clear=True), \
                        patch("builtins.input", return_value=url), \
                        contextlib.redirect_stdout(io.StringIO()):
                    exec(compile(ast.Module(body=[assignment], type_ignores=[]),
                                 "<repository>", "exec"), namespace)
                self.assertEqual(namespace["GITOPS_REPO_URL"], url)


if __name__ == "__main__":
    unittest.main()
