import contextlib
import io
import json
import os
from pathlib import Path
import runpy
import subprocess
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "05_deploy_services.py"


class DeployApplicationTests(unittest.TestCase):
    def execute(self, status="Synced|Healthy", apply_output=None, apply_rc=0):
        commands = []
        with tempfile.TemporaryDirectory() as directory:
            apps = Path(directory) / "argocd/apps/dev"
            apps.mkdir(parents=True)
            (apps / "catalog-service-app.yaml").write_text("mock manifest")
            resource = {"apiVersion": "argoproj.io/v1alpha1", "kind": "Application",
                        "metadata": {"name": "custom-catalog-stage", "namespace": "argocd"}}

            def run(args, **kwargs):
                commands.append(args)
                if args[:2] == ["kubectl", "apply"]:
                    return subprocess.CompletedProcess(
                        args, apply_rc, stdout=apply_output if apply_output is not None
                        else json.dumps(resource), stderr="mock apply failure" if apply_rc else "")
                if args[:3] == ["kubectl", "get", "application"]:
                    return subprocess.CompletedProcess(args, 0, stdout=status)
                return subprocess.CompletedProcess(args, 0, stdout="")

            environment = {"ENV": "dev", "GITHUB_USERNAME": "demo-owner",
                           "AWS_ACCOUNT_ID": "123456789012", "GITOPS_PATH": directory,
                           "POLL_INTERVAL": "1", "MAX_WAIT": "1"}
            output = io.StringIO()
            error = None
            with patch.dict(os.environ, environment, clear=True), \
                    patch("subprocess.run", side_effect=run), \
                    patch("time.sleep"), patch("builtins.input", side_effect=["3", "Y"]), \
                    contextlib.redirect_stdout(output), \
                    contextlib.redirect_stderr(io.StringIO()):
                try:
                    runpy.run_path(str(SCRIPT))
                except SystemExit as exception:
                    error = exception.code
            return commands, output.getvalue(), error

    def test_monitors_applied_name_not_catalog_menu_name(self):
        commands, output, error = self.execute()
        self.assertIsNone(error)
        queries = [cmd for cmd in commands if cmd[:3] == ["kubectl", "get", "application"]]
        self.assertEqual(len(queries), 1)
        self.assertEqual(queries[0][3], "custom-catalog-stage")
        self.assertIn("custom-catalog-stage", output)
        self.assertIn("Synced/Healthy", output)
        self.assertIn("-o", next(cmd for cmd in commands if cmd[:2] == ["kubectl", "apply"]))

    def test_degraded_and_timeout_exit_unsuccessfully(self):
        for status in ("Synced|Degraded", "OutOfSync|Progressing", ""):
            with self.subTest(status=status):
                _, output, error = self.execute(status=status)
                self.assertEqual(error, 1)
                self.assertNotIn("Next step:", output)
                self.assertNotIn("deployment/custom-catalog-stage", output)

    def test_invalid_apply_results_stop_before_monitoring(self):
        for output in ("invalid json", "[]", "{}", '{"metadata":null}',
                       '{"kind":"List","items":[]}'):
            with self.subTest(output=output):
                commands, _, error = self.execute(apply_output=output)
                self.assertEqual(error, 1)
                self.assertFalse(any(cmd[:3] == ["kubectl", "get", "application"]
                                     for cmd in commands))

    def test_apply_failure_stops_before_monitoring(self):
        commands, _, error = self.execute(apply_rc=1)
        self.assertEqual(error, 1)
        self.assertFalse(any(cmd[:3] == ["kubectl", "get", "application"]
                             for cmd in commands))


if __name__ == "__main__":
    unittest.main()
