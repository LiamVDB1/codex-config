from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from removal import RemovalError, capture_removal_identity, verify_absence  # noqa: E402


DIGEST = "sha256:" + "a" * 64
COMMIT = "2" * 40


def plan(action: str = "rollback") -> dict:
    return {
        "image_digest": DIGEST,
        "source_commit_sha": COMMIT,
        "action": action,
        "remove_command": ["docker", "rm", "--force", "homeserver-synthetic"],
    }


def inspect_payload(labels_action: str = "rollback", image: str = DIGEST) -> list[dict]:
    return [
        {
            "Name": "/homeserver-synthetic",
            "Image": image,
            "Config": {
                "Labels": {
                    "homeserver.source_commit": COMMIT,
                    "homeserver.action": labels_action,
                }
            },
        }
    ]


class RemovalIdentityTests(unittest.TestCase):
    def test_identity_binds_plan_facts(self) -> None:
        receipt = capture_removal_identity(
            inspect_payload(), plan(), now="2026-08-26T00:00:00Z"
        )
        self.assertEqual(receipt["schema_version"], "homeserver-synthetic-removal-identity/v1")
        self.assertEqual(receipt["container_name"], "homeserver-synthetic")
        self.assertEqual(receipt["captured_at"], "2026-08-26T00:00:00Z")

    def test_wrong_image_rejected(self) -> None:
        with self.assertRaisesRegex(RemovalError, "digest"):
            capture_removal_identity(inspect_payload(image="sha256:" + "f" * 64), plan())

    def test_wrong_commit_label_rejected(self) -> None:
        payload = inspect_payload()
        payload[0]["Config"]["Labels"]["homeserver.source_commit"] = "9" * 40
        with self.assertRaisesRegex(RemovalError, "commit"):
            capture_removal_identity(payload, plan())

    def test_wrong_target_name_rejected(self) -> None:
        payload = inspect_payload()
        payload[0]["Name"] = "/other-container"
        with self.assertRaisesRegex(RemovalError, "target"):
            capture_removal_identity(payload, plan())

    def test_absence_proof_passes_only_when_empty(self) -> None:
        receipt = verify_absence([], inspect_failed=True, now="2026-08-26T00:01:00Z")
        self.assertEqual(receipt["ps_matches"], 0)
        self.assertTrue(receipt["inspect_absent"])
        with self.assertRaisesRegex(RemovalError, "still present"):
            verify_absence(["abc123 homeserver-synthetic"], inspect_failed=True)
        with self.assertRaisesRegex(RemovalError, "must fail"):
            verify_absence([], inspect_failed=False)


if __name__ == "__main__":
    unittest.main()
