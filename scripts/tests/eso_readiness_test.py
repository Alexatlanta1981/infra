import ast
import contextlib
import io
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import Mock


SCRIPT = Path(__file__).resolve().parents[1] / "03_setup_external_secrets.py"
ROLE = "arn:aws:iam::123456789012:role/demo-eso"


def pod(ready=False, phase="Running"):
    return {"metadata": {}, "status": {"phase": phase, "conditions": [
        {"type": "Ready", "status": "True" if ready else "False"}]}}


class ESOReadinessTests(unittest.TestCase):
    def run_helper(self, observations, failed_command=None):
        commands = []
        sleeps = Mock()
        observed = iter(observations)

        def run(args, **kwargs):
            commands.append(args)
            if failed_command and failed_command(args):
                return subprocess.CompletedProcess(args, 1, stdout="", stderr="mock error")
            if args[:3] == ["kubectl", "get", "pods"]:
                return subprocess.CompletedProcess(args, 0,
                                                   stdout=json.dumps({"items": next(observed)}))
            return subprocess.CompletedProcess(args, 0)

        def die(message):
            raise SystemExit(message)

        tree = ast.parse(SCRIPT.read_text())
        functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                     and node.name in ("run_cmd", "ensure_eso_ready")]
        namespace = {"subprocess": Mock(run=run), "json": json,
                     "sys": Mock(stderr=io.StringIO()), "time": Mock(sleep=sleeps),
                     "die": die, "info": Mock(), "warn": Mock(), "log": Mock()}
        exec(compile(ast.Module(body=functions, type_ignores=[]), str(SCRIPT), "exec"),
             namespace)
        return namespace["ensure_eso_ready"], commands, sleeps

    def test_ready_first_attempt_preserves_irsa_and_checks_crds(self):
        helper, commands, sleeps = self.run_helper([[pod(True)]])
        helper(ROLE)
        upgrades = [cmd for cmd in commands if cmd[:2] == ["helm", "upgrade"]]
        self.assertEqual(len(upgrades), 1)
        self.assertIn("--reuse-values", upgrades[0])
        self.assertIn("installCRDs=true", upgrades[0])
        self.assertIn("serviceAccount.annotations.eks\\.amazonaws\\.com/role-arn=" + ROLE,
                      upgrades[0])
        self.assertEqual(commands[-1][:2], ["kubectl", "wait"])
        sleeps.assert_not_called()

    def test_absent_pending_and_running_unready_pods_retry_before_success(self):
        helper, commands, sleeps = self.run_helper([
            [], [pod(True, phase="Pending")], [pod(False)], [pod(True)]])
        helper(ROLE)
        self.assertEqual(sum(cmd[:2] == ["helm", "upgrade"] for cmd in commands), 4)
        self.assertEqual(sleeps.call_count, 3)
        self.assertTrue(all(call.args == (30,) for call in sleeps.call_args_list))

    def test_exhaustion_stops_after_ten_attempts_and_nine_sleeps(self):
        helper, commands, sleeps = self.run_helper([[pod(False)]] * 10)
        with self.assertRaisesRegex(SystemExit, "not Ready after 10 attempts"):
            helper(ROLE)
        self.assertEqual(sum(cmd[:2] == ["helm", "upgrade"] for cmd in commands), 10)
        self.assertEqual(sleeps.call_count, 9)
        self.assertFalse(any(cmd[:2] == ["kubectl", "wait"] for cmd in commands))

    def test_all_active_certificate_controller_pods_must_be_ready(self):
        terminating = pod(True)
        terminating["metadata"]["deletionTimestamp"] = "2026-10-06T23:00:00Z"
        helper, commands, sleeps = self.run_helper([
            [terminating], [pod(True), pod(False)], [pod(True)]])
        helper(ROLE)
        self.assertEqual(sum(cmd[:2] == ["helm", "upgrade"] for cmd in commands), 3)
        self.assertEqual(sleeps.call_count, 2)

    def test_command_failures_abort_without_readiness_retry(self):
        for prefix in (["helm", "upgrade"], ["kubectl", "get"], ["kubectl", "wait"]):
            with self.subTest(prefix=prefix):
                helper, _, sleeps = self.run_helper([[pod(True)]],
                                                    lambda cmd: cmd[:2] == prefix)
                with contextlib.redirect_stderr(io.StringIO()), \
                        self.assertRaises(SystemExit):
                    helper(ROLE)
                sleeps.assert_not_called()

    def test_gate_precedes_namespace_and_secret_store_mutations(self):
        tree = ast.parse(SCRIPT.read_text())
        gate = next(node.lineno for node in tree.body if isinstance(node, ast.Expr)
                    and isinstance(node.value, ast.Call)
                    and isinstance(node.value.func, ast.Name)
                    and node.value.func.id == "ensure_eso_ready")
        namespace = next(node.lineno for node in tree.body if isinstance(node, ast.Assign)
                         and any(isinstance(target, ast.Tuple) and any(
                             isinstance(item, ast.Name) and item.id == "dry_run"
                             for item in target.elts) for target in node.targets))
        self.assertLess(gate, namespace)


if __name__ == "__main__":
    unittest.main()
