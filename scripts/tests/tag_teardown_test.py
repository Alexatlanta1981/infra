import copy
import importlib.util
import io
import contextlib
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import ecr_tag_backup as backup

spec = importlib.util.spec_from_file_location("tag_teardown", SCRIPTS / "07_preserve_tags_teardown.py")
teardown = importlib.util.module_from_spec(spec)
spec.loader.exec_module(teardown)
ACCOUNT = "123456789012"
REGION = "us-east-1"
CONTEXT = f"arn:aws:eks:{REGION}:{ACCOUNT}:cluster/test"
DIGEST = "sha256:" + "a" * 64


def snapshot():
    return {"schema_version": 1, "account_id": ACCOUNT, "region": REGION,
            "created_at": "2026-10-07T00:00:00+00:00",
            "repositories": [{"name": "auth-service", "tags": ["sha-1234567"],
                              "digests": [DIGEST], "tag_to_digest": {"sha-1234567": DIGEST},
                              "images": []}]}


class TagTeardownTests(unittest.TestCase):
    def test_inventory_keeps_tags_and_untagged_images(self):
        with patch.object(backup, "aws_json", return_value={"imageDetails": [
            {"imageDigest": DIGEST, "imageTags": ["latest", "sha-1234567"]},
            {"imageDigest": "sha256:" + "b" * 64},
        ]}):
            result = backup.image_inventory("auth-service")
        self.assertEqual(result["tags"], ["latest", "sha-1234567"])
        self.assertEqual(len(result["digests"]), 2)

    def test_schema_rejects_wrong_account_region_and_mapping(self):
        for change in ({"account_id": "000000000000"}, {"region": "us-west-2"},
                       {"schema_version": 2}):
            data = snapshot()
            data.update(change)
            with self.assertRaises(ValueError):
                backup.validate_backup(data, ACCOUNT, REGION)
        data = snapshot()
        data["repositories"][0]["digests"] = []
        with self.assertRaises(ValueError):
            backup.validate_backup(data, ACCOUNT, REGION)

    def test_upload_is_non_overwriting_and_requires_matching_readback(self):
        data = snapshot()
        changed = copy.deepcopy(data)
        changed["created_at"] = "2026-10-08T00:00:00+00:00"
        with patch.object(backup, "command") as command, \
                patch.object(backup, "download_backup", return_value=changed):
            with self.assertRaises(ValueError):
                backup.upload_backup("s3://bucket/tags.json", data, ACCOUNT, REGION)
        self.assertIn("--if-none-match", command.call_args.args[0])

    def test_failed_backup_blocks_teardown_and_default_is_backup_only(self):
        for destructive, failure in ((True, RuntimeError("S3 failed")), (False, None), (True, None)):
            args = ["07", "--backup-uri", "s3://bucket/key"]
            if destructive:
                args += ["--teardown", "--context", CONTEXT]
            with patch.object(sys, "argv", args), \
                    patch.object(teardown, "identity", return_value=(ACCOUNT, REGION)), \
                    patch.object(teardown, "command", return_value=CONTEXT), \
                    patch.object(teardown, "build_backup", return_value=snapshot()), \
                    patch.object(teardown, "upload_backup", side_effect=failure), \
                    patch.object(teardown, "teardown") as delete, \
                    patch("builtins.input", return_value=CONTEXT), \
                    contextlib.redirect_stdout(io.StringIO()):
                if failure:
                    with self.assertRaises(RuntimeError):
                        teardown.main()
                else:
                    teardown.main()
                self.assertEqual(delete.call_count, int(destructive and not failure))

    def test_partial_selection_and_wrong_context_block_teardown(self):
        with patch.object(sys, "argv", [
            "07", "--backup-uri", "s3://bucket/key", "--services", "F",
            "--teardown", "--context", CONTEXT,
        ]), patch.object(teardown, "identity") as identity:
            with self.assertRaises(ValueError):
                teardown.main()
            identity.assert_not_called()
        with patch.object(teardown, "command", return_value="wrong-context"):
            with self.assertRaises(ValueError):
                teardown.teardown("dev", CONTEXT, False)

    def test_teardown_orders_namespace_before_addons_and_never_deletes_eks(self):
        events = []
        releases = {"argocd": "argocd", "external-secrets": "external-secrets",
                    "kube-system": "aws-load-balancer-controller"}

        def command(args):
            events.append(args)
            if args[0] == "helm" and "uninstall" in args:
                releases.pop(args[args.index("-n") + 1])
            return CONTEXT

        def read(args):
            events.append(args)
            if args[0] == "helm":
                release = releases.get(args[args.index("-n") + 1])
                return [{"name": release}] if release else []
            return {"items": []}

        with patch.object(teardown, "command", side_effect=command), \
                patch.object(teardown, "command_json", side_effect=read), \
                patch.object(teardown, "aws_json", return_value={"LoadBalancers": []}), \
                contextlib.redirect_stdout(io.StringIO()):
            teardown.teardown("dev", CONTEXT, True)
        deleted = [event[event.index("namespace") + 1] for event in events
                   if "delete" in event and "namespace" in event]
        self.assertEqual(deleted, ["dev", "argocd", "external-secrets"])
        first_uninstall = next(i for i, event in enumerate(events) if "uninstall" in event)
        namespace_delete = next(i for i, event in enumerate(events)
                                if "delete" in event and "dev" in event)
        self.assertGreater(first_uninstall, namespace_delete)
        self.assertFalse(any("delete-cluster" in event or "terraform" in event for event in events))


if __name__ == "__main__":
    unittest.main()
