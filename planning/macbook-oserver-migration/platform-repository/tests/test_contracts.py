from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from bootstrap_plan import build_plan  # noqa: E402
from platform_contracts import (  # noqa: E402
    ContractError,
    validate_deployment_receipt,
    validate_rollback_receipt,
    validate_service,
)
from validate_repository import validate_repository  # noqa: E402


SHA_A = "a" * 40
SHA_B = "b" * 40
DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64
DIGEST_C = "sha256:" + "c" * 64


def valid_service() -> dict:
    return {
        "schema_version": "homeserver-service/v1",
        "service_id": "SVC-SYNTHETIC",
        "classification": "private",
        "owners": {"platform": "liamvdb", "operational": "liamvdb"},
        "source": {
            "repository": "https://github.com/LiamVDB1/codex-config.git",
            "commit_sha": SHA_A,
            "path": "planning/macbook-oserver-migration/platform-repository/services/synthetic",
            "dirty": False,
        },
        "artifacts": {
            "manifest_digest": DIGEST_A,
            "platform_digests": {"linux/amd64": DIGEST_B, "linux/arm64": DIGEST_C},
        },
        "deployment": {
            "hosts": ["homeserver", "oserver"],
            "compose_path": "services/synthetic/compose.json",
            "project_name": "homeserver-synthetic",
            "rollback_artifact_digests": [DIGEST_B],
        },
        "network": {
            "bindings": [
                {"host": "homeserver", "address": "127.0.0.1", "port": 18180, "protocol": "tcp"}
            ],
            "public_route": False,
        },
        "storage": {"stateful": False, "paths": []},
        "health": {
            "liveness": "/healthz",
            "readiness": "/readyz",
            "user_flow": "/synthetic",
            "timeout_seconds": 5,
        },
        "resources": {"cpu": "0.25", "memory_mb": 128, "pids": 64},
        "backup": {
            "required": False,
            "owner": "liamvdb",
            "rpo_minutes": 0,
            "rto_minutes": 15,
            "destinations": [],
            "restore_test_required": False,
        },
        "rollback": {
            "strategy": "redeploy-previous-digest",
            "previous_approved_sha": SHA_B,
            "max_downtime_minutes": 10,
            "steps": ["stop", "deploy previous digest", "verify health"],
        },
        "secret_refs": ["SYNTHETIC_UNUSED_SECRET_REF"],
    }


def valid_deployment_receipt() -> dict:
    return {
        "schema_version": "homeserver-deployment-receipt/v1",
        "service_id": "SVC-SYNTHETIC",
        "action": "deploy",
        "approved_commit_sha": SHA_A,
        "source_clean": True,
        "host": "homeserver",
        "architecture": "linux/amd64",
        "manifest_digest": DIGEST_A,
        "image_digest": DIGEST_B,
        "catalogue_sha256": "d" * 64,
        "started_at": "2026-08-23T20:00:00Z",
        "completed_at": "2026-08-23T20:01:00Z",
        "health": {"liveness": True, "readiness": True, "user_flow": True},
        "actor": "root.active_session_implementer",
    }


class ServiceContractTests(unittest.TestCase):
    def test_valid_service_passes(self) -> None:
        validate_service(valid_service())

    def test_every_top_level_authority_is_required(self) -> None:
        required = {
            "source", "artifacts", "health", "resources", "backup", "rollback", "deployment"
        }
        for key in required:
            with self.subTest(key=key):
                candidate = valid_service()
                del candidate[key]
                with self.assertRaisesRegex(ContractError, f"{key} is required"):
                    validate_service(candidate)

    def test_floating_or_unpinned_artifact_is_rejected(self) -> None:
        candidate = valid_service()
        candidate["artifacts"]["manifest_digest"] = "synthetic:latest"
        with self.assertRaisesRegex(ContractError, "manifest_digest"):
            validate_service(candidate)

    def test_non_loopback_binding_is_rejected_before_build_002(self) -> None:
        candidate = valid_service()
        candidate["network"]["bindings"][0]["address"] = "0.0.0.0"
        with self.assertRaisesRegex(ContractError, "loopback"):
            validate_service(candidate)

    def test_secret_value_field_is_rejected(self) -> None:
        candidate = valid_service()
        candidate["api_key"] = "literal-value"
        with self.assertRaisesRegex(ContractError, "unknown field"):
            validate_service(candidate)

    def test_source_must_be_clean(self) -> None:
        candidate = valid_service()
        candidate["source"]["dirty"] = True
        with self.assertRaisesRegex(ContractError, "dirty must be false"):
            validate_service(candidate)


class ReceiptContractTests(unittest.TestCase):
    def test_valid_deployment_receipt_passes(self) -> None:
        validate_deployment_receipt(valid_deployment_receipt())

    def test_failed_health_rejects_deployment_receipt(self) -> None:
        receipt = valid_deployment_receipt()
        receipt["health"]["user_flow"] = False
        with self.assertRaisesRegex(ContractError, "health.user_flow"):
            validate_deployment_receipt(receipt)

    def test_valid_rollback_receipt_passes(self) -> None:
        receipt = valid_deployment_receipt()
        receipt.update({
            "schema_version": "homeserver-rollback-receipt/v1",
            "action": "rollback",
            "from_commit_sha": SHA_A,
            "to_commit_sha": SHA_B,
            "from_image_digest": DIGEST_C,
            "to_image_digest": DIGEST_B,
        })
        validate_rollback_receipt(receipt)


class BootstrapPlanTests(unittest.TestCase):
    def test_exact_durable_target_is_planned(self) -> None:
        plan = build_plan("homeserver", SHA_A, target="/srv/homeserver/repo")
        self.assertEqual(plan["architecture"], "linux/amd64")
        self.assertEqual(plan["target"], "/srv/homeserver/repo")
        self.assertTrue(plan["dry_run"])

    def test_unapproved_target_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "approved durable path"):
            build_plan("oserver", SHA_A, target="/tmp/platform")

    def test_invalid_commit_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "40-character"):
            build_plan("homeserver", "main", target="/srv/homeserver/repo")


class RepositoryValidationTests(unittest.TestCase):
    def test_empty_catalogue_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "platform/catalogue/services").mkdir(parents=True)
            (root / "repository.json").write_text(json.dumps({
                "schema_version": "homeserver-platform-repository/v1",
                "canonical_remote": "https://github.com/LiamVDB1/codex-config.git",
                "canonical_branch": "main",
                "source_subdir": "planning/macbook-oserver-migration/platform-repository",
                "hosts": {
                    "homeserver": {"architecture": "linux/amd64", "durable_clone": "/srv/homeserver/repo"},
                    "oserver": {"architecture": "linux/arm64", "durable_clone": "/home/opc/server-platform"},
                },
            }))
            errors = validate_repository(root)
        self.assertIn("catalogue must contain at least one service record", errors)

    def test_canonical_repository_has_a_valid_service(self) -> None:
        self.assertEqual(validate_repository(ROOT), [])


if __name__ == "__main__":
    unittest.main()
