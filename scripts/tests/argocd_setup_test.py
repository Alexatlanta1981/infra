import ast
import contextlib
import io
import os
from pathlib import Path
import runpy
import subprocess
import unittest
from unittest.mock import patch


SCRIPTS = Path(__file__).resolve().parents[1]


class ArgoCDSetupTests(unittest.TestCase):
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
                patch("builtins.input", return_value="Y"), \
                contextlib.redirect_stdout(output):
            runpy.run_path(str(SCRIPTS / "01_install_prerequisites.py"))

        self.assertFalse(any("secret" in command for command in commands))
        self.assertNotIn("Password :", output.getvalue())
        self.assertNotIn("ArgoCD pass", output.getvalue())
        self.assertIn("All pre-requisites installed successfully.", output.getvalue())

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
