from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from deployment import DeploymentError, build_runtime_plan, load_approval  # noqa: E402


SHA_V1 = "1" * 40
SHA_V2 = "2" * 40
AMD64_DIGEST = "sha256:" + "a" * 64
ARM64_DIGEST = "sha256:" + "b" * 64
INDEX_DIGEST = "sha256:" + "c" * 64


def valid_approval() -> dict:
    return {
        "schema_version": "homeserver-synthetic-approval/v1",
        "service_id": "SVC-SYNTHETIC",
        "source_commit_sha": SHA_V2,
        "previous_approved_sha": SHA_V1,
        "artifact_index_digest": INDEX_DIGEST,
        "platform_digests": {
            "linux/amd64": AMD64_DIGEST,
            "linux/arm64": ARM64_DIGEST,
        },
        "rollback_platform_digests": {
            "linux/amd64": "sha256:" + "d" * 64,
            "linux/arm64": "sha256:" + "e" * 64,
        },
    }


class ApprovalTests(unittest.TestCase):
    def test_valid_approval_loads(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "approval.json"
            path.write_text(json.dumps(valid_approval()))
            self.assertEqual(load_approval(path)["source_commit_sha"], SHA_V2)

    def test_missing_metadata_fails_closed(self) -> None:
        for field in (
            "source_commit_sha",
            "previous_approved_sha",
            "artifact_index_digest",
            "platform_digests",
            "rollback_platform_digests",
        ):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temp_dir:
                approval = valid_approval()
                del approval[field]
                path = Path(temp_dir) / "approval.json"
                path.write_text(json.dumps(approval))
                with self.assertRaisesRegex(DeploymentError, field):
                    load_approval(path)


class RuntimePlanTests(unittest.TestCase):
    def test_approved_plan_is_loopback_only_and_hardened(self) -> None:
        plan = build_runtime_plan(
            valid_approval(),
            host="homeserver",
            architecture="linux/amd64",
            actual_source_commit=SHA_V2,
            source_clean=True,
            image_digest=AMD64_DIGEST,
            action="deploy",
        )
        command = plan["command"]
        self.assertIn("127.0.0.1:18180:8080", command)
        self.assertIn("--read-only", command)
        self.assertIn("no-new-privileges", command)
        self.assertIn("--cap-drop", command)
        self.assertEqual(command[-1], AMD64_DIGEST)

    def test_wrong_architecture_fails(self) -> None:
        with self.assertRaisesRegex(DeploymentError, "architecture"):
            build_runtime_plan(
                valid_approval(),
                host="homeserver",
                architecture="linux/arm64",
                actual_source_commit=SHA_V2,
                source_clean=True,
                image_digest=ARM64_DIGEST,
                action="deploy",
            )

    def test_dirty_source_fails(self) -> None:
        with self.assertRaisesRegex(DeploymentError, "clean"):
            build_runtime_plan(
                valid_approval(),
                host="homeserver",
                architecture="linux/amd64",
                actual_source_commit=SHA_V2,
                source_clean=False,
                image_digest=AMD64_DIGEST,
                action="deploy",
            )

    def test_unknown_digest_fails(self) -> None:
        with self.assertRaisesRegex(DeploymentError, "digest"):
            build_runtime_plan(
                valid_approval(),
                host="homeserver",
                architecture="linux/amd64",
                actual_source_commit=SHA_V2,
                source_clean=True,
                image_digest="sha256:" + "f" * 64,
                action="deploy",
            )

    def test_wrong_commit_fails(self) -> None:
        with self.assertRaisesRegex(DeploymentError, "commit"):
            build_runtime_plan(
                valid_approval(),
                host="homeserver",
                architecture="linux/amd64",
                actual_source_commit=SHA_V1,
                source_clean=True,
                image_digest=AMD64_DIGEST,
                action="deploy",
            )

    def test_rollback_uses_previous_digest(self) -> None:
        approval = valid_approval()
        plan = build_runtime_plan(
            approval,
            host="oserver",
            architecture="linux/arm64",
            actual_source_commit=SHA_V1,
            source_clean=True,
            image_digest=approval["rollback_platform_digests"]["linux/arm64"],
            action="rollback",
        )
        self.assertEqual(plan["source_commit_sha"], SHA_V1)
        self.assertEqual(plan["command"][-1], approval["rollback_platform_digests"]["linux/arm64"])


if __name__ == "__main__":
    unittest.main()
