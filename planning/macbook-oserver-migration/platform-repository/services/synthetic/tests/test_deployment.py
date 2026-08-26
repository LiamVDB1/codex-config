from __future__ import annotations

import json
import hashlib
import subprocess
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


def valid_provenance(head: str = SHA_V2) -> dict:
    return {
        "schema_version": "homeserver-synthetic-provenance/v1",
        "clone_path": "/srv/homeserver/repo",
        "remote_url": "https://github.com/LiamVDB1/codex-config.git",
        "head": head,
        "clean": True,
        "source_subdir": "planning/macbook-oserver-migration/platform-repository",
        "subdir_tree": SHA_V1,
        "contained_branches": ["main"],
        "captured_at": "2026-08-26T00:00:00Z",
    }


def write_approval(directory: Path, approval: dict | None = None) -> Path:
    candidate = json.loads(json.dumps(approval or valid_approval()))
    index = {
        "schema_version": "homeserver-synthetic-artifacts/v1",
        "service_id": candidate["service_id"],
        "source_commit_sha": candidate["source_commit_sha"],
        "previous_approved_sha": candidate["previous_approved_sha"],
        "platform_digests": candidate["platform_digests"],
        "rollback_platform_digests": candidate["rollback_platform_digests"],
    }
    index_bytes = (json.dumps(index, indent=2, sort_keys=True) + "\n").encode()
    (directory / "artifact-index.json").write_bytes(index_bytes)
    candidate["artifact_index_digest"] = "sha256:" + hashlib.sha256(index_bytes).hexdigest()
    path = directory / "approval.json"
    path.write_text(json.dumps(candidate))
    return path


class ApprovalTests(unittest.TestCase):
    def test_valid_approval_loads(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = write_approval(Path(temp_dir))
            self.assertEqual(load_approval(path)["source_commit_sha"], SHA_V2)

    def test_tampered_artifact_index_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            path = write_approval(directory)
            index = json.loads((directory / "artifact-index.json").read_text())
            index["platform_digests"]["linux/amd64"] = "sha256:" + "f" * 64
            (directory / "artifact-index.json").write_text(json.dumps(index))
            with self.assertRaisesRegex(DeploymentError, "artifact index digest"):
                load_approval(path)

    def test_rebound_artifact_index_metadata_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            path = write_approval(directory)
            index = json.loads((directory / "artifact-index.json").read_text())
            index["service_id"] = "SVC-OTHER"
            index_bytes = (json.dumps(index, indent=2, sort_keys=True) + "\n").encode()
            (directory / "artifact-index.json").write_bytes(index_bytes)
            approval = json.loads(path.read_text())
            approval["artifact_index_digest"] = "sha256:" + hashlib.sha256(index_bytes).hexdigest()
            path.write_text(json.dumps(approval))
            with self.assertRaisesRegex(DeploymentError, "metadata"):
                load_approval(path)

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


_KEEPALIVE = []


def _make_clone() -> Path:
    """Minimal canonical-shaped git clone for live rederivation."""
    tmp = tempfile.TemporaryDirectory()
    _KEEPALIVE.append(tmp)
    base = Path(tmp.name)
    sub = "planning/macbook-oserver-migration/platform-repository"
    seed = base / "seed"
    seed.mkdir(parents=True)

    def g(*args):
        subprocess.run(["git", *args], check=True, capture_output=True)

    g("init", "-q", "-b", "main", str(seed))
    (seed / sub).mkdir(parents=True)
    (seed / sub / "repository.json").write_text("{}")
    g("-C", str(seed), "add", ".")
    g("-C", str(seed), "-c", "user.name=t", "-c", "user.email=t@e", "commit", "-qm", "x")
    bare = base / "origin.git"
    g("init", "-q", "--bare", str(bare))
    g("-C", str(seed), "push", "-q", str(bare), "main")
    clone = base / "clone"
    g("clone", "-q", str(bare), str(clone))
    g("-C", str(clone), "remote", "set-url", "origin",
      "https://github.com/LiamVDB1/codex-config.git")
    return clone


def _clone_fixture() -> Path:
    return _make_clone()


class ProvenanceGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clone = _clone_fixture()

    def _receipt(self):
        from git_provenance import collect_git_provenance

        return collect_git_provenance(
            self.clone,
            expected_remote="https://github.com/LiamVDB1/codex-config.git",
            allowed_branches=["main"],
            source_subdir="planning/macbook-oserver-migration/platform-repository",
        )

    def _plan(self, **overrides):
        args = dict(
            approval={"source_commit_sha": self._receipt()["head"]},
            host="homeserver",
            architecture="linux/amd64",
            provenance=self._receipt(),
            image_digest=AMD64_DIGEST,
            action="deploy",
            verify_clone=self.clone,
        )
        args.update(overrides)
        return build_runtime_plan(**args)

    def test_dirty_measured_provenance_fails(self) -> None:
        receipt = self._receipt()
        receipt["clean"] = False
        # The live-clone rederivation rejects the mismatch before the clean flag
        # is even consulted; either message is a fail-closed outcome.
        with self.assertRaisesRegex(DeploymentError, "live clone"):
            self._plan(approval={"source_commit_sha": receipt["head"]}, provenance=receipt)

    def test_wrong_head_fails(self) -> None:
        receipt = self._receipt()
        approval = {"source_commit_sha": SHA_V1}
        with self.assertRaisesRegex(DeploymentError, "does not match approved commit"):
            build_runtime_plan(
                approval,
                host="homeserver",
                architecture="linux/amd64",
                provenance=receipt,
                image_digest=AMD64_DIGEST,
                action="deploy",
                verify_clone=self.clone,
            )

    def test_forged_subtree_rejected_by_live_clone(self) -> None:
        from git_provenance import collect_git_provenance

        real = collect_git_provenance(
            self.clone,
            expected_remote="https://github.com/LiamVDB1/codex-config.git",
            allowed_branches=["main"],
            source_subdir="planning/macbook-oserver-migration/platform-repository",
        )
        approval = {"source_commit_sha": real["head"]}
        forged = dict(real)
        forged["subdir_tree"] = "0" * 40
        with self.assertRaisesRegex(DeploymentError, "does not match the live clone"):
            build_runtime_plan(
                approval,
                host="homeserver",
                architecture="linux/amd64",
                provenance=forged,
                image_digest=AMD64_DIGEST,
                action="deploy",
                verify_clone=self.clone,
            )

    def test_unsupported_provenance_schema_fails(self) -> None:
        receipt = self._receipt()
        receipt["schema_version"] = "asserted/v1"
        with self.assertRaisesRegex(DeploymentError, "schema"):
            self._plan(approval={"source_commit_sha": receipt["head"]}, provenance=receipt)


class RuntimePlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clone = _clone_fixture()
        from git_provenance import collect_git_provenance

        self.receipt = collect_git_provenance(
            self.clone,
            expected_remote="https://github.com/LiamVDB1/codex-config.git",
            allowed_branches=["main"],
            source_subdir="planning/macbook-oserver-migration/platform-repository",
        )
        self.approval = {
            "schema_version": "homeserver-synthetic-approval/v1",
            "service_id": "SVC-SYNTHETIC",
            "source_commit_sha": self.receipt["head"],
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

    def test_approved_plan_is_loopback_only_and_hardened(self) -> None:
        plan = build_runtime_plan(
            self.approval,
            host="homeserver",
            architecture="linux/amd64",
            provenance=self.receipt,
            image_digest=AMD64_DIGEST,
            action="deploy",
            verify_clone=self.clone,
        )
        command = plan["command"]
        self.assertIn("127.0.0.1:18180:8080", command)
        self.assertIn("--read-only", command)
        self.assertIn("no-new-privileges", command)
        self.assertIn("--cap-drop", command)
        self.assertEqual(command[-1], AMD64_DIGEST)
        self.assertTrue(plan["captured_at"].endswith("Z"))

    def test_wrong_architecture_fails(self) -> None:
        with self.assertRaisesRegex(DeploymentError, "architecture"):
            build_runtime_plan(
                valid_approval(),
                host="homeserver",
                architecture="linux/arm64",
                provenance=valid_provenance(),
                image_digest=ARM64_DIGEST,
                action="deploy",
                verify_clone=self.clone,
            )

    def test_unknown_digest_fails(self) -> None:
        with self.assertRaisesRegex(DeploymentError, "digest"):
            build_runtime_plan(
                self.approval,
                host="homeserver",
                architecture="linux/amd64",
                provenance=self.receipt,
                image_digest="sha256:" + "f" * 64,
                action="deploy",
                verify_clone=self.clone,
            )

    def test_rollback_binds_previous_approval_and_digest(self) -> None:
        approval = valid_approval()
        plan = build_runtime_plan(
            self.approval,
            host="oserver",
            architecture="linux/arm64",
            provenance=self.receipt,
            image_digest=self.approval["rollback_platform_digests"]["linux/arm64"],
            action="rollback",
            verify_clone=self.clone,
        )
        self.assertEqual(plan["source_commit_sha"], SHA_V1)
        self.assertEqual(plan["command"][-1], self.approval["rollback_platform_digests"]["linux/arm64"])


if __name__ == "__main__":
    unittest.main()
