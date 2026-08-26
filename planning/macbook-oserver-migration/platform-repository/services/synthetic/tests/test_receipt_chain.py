from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from receipt_chain import ChainError, validate_bundle  # noqa: E402


SHA_V2 = "2" * 40
SHA_V1 = "1" * 40
TREE = "3" * 40
DIGESTS = {
    "linux/amd64": "sha256:" + "a" * 64,
    "linux/arm64": "sha256:" + "b" * 64,
}
ROLLBACK = {
    "linux/amd64": "sha256:" + "d" * 64,
    "linux/arm64": "sha256:" + "e" * 64,
}
ARCH_BY_HOST = {"homeserver": "linux/amd64", "oserver": "linux/arm64"}
VERSION = "v3"


def _ts(base: int) -> str:
    return f"2026-08-26T00:{base // 60:02d}:{base % 60:02d}Z"


def _write(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _approval(directory: Path) -> dict:
    index = {
        "schema_version": "homeserver-synthetic-artifacts/v1",
        "service_id": "SVC-SYNTHETIC",
        "source_commit_sha": SHA_V2,
        "previous_approved_sha": SHA_V1,
        "platform_digests": DIGESTS,
        "rollback_platform_digests": ROLLBACK,
    }
    index_bytes = (json.dumps(index, indent=2, sort_keys=True) + "\n").encode()
    (directory / "artifact-index.json").write_bytes(index_bytes)
    approval = {
        "schema_version": "homeserver-synthetic-approval/v1",
        "service_id": "SVC-SYNTHETIC",
        "source_commit_sha": SHA_V2,
        "previous_approved_sha": SHA_V1,
        "artifact_index_digest": "sha256:" + hashlib.sha256(index_bytes).hexdigest(),
        "platform_digests": DIGESTS,
        "rollback_platform_digests": ROLLBACK,
    }
    _write(directory / "approval.json", approval)
    return approval


def _inspect(commit: str, digest: str, action: str) -> list[dict]:
    return [
        {
            "Name": "/homeserver-synthetic",
            "Image": digest,
            "Config": {
                "User": "65532:65532",
                "Env": None,
                "Labels": {
                    "homeserver.source_commit": commit,
                    "homeserver.action": action,
                },
            },
            "Mounts": [],
            "HostConfig": {
                "ReadonlyRootfs": True,
                "Privileged": False,
                "CapDrop": ["ALL"],
                "SecurityOpt": ["no-new-privileges"],
                "Memory": 134217728,
                "NanoCpus": 250_000_000,
                "PidsLimit": 64,
                "PortBindings": {"8080/tcp": [{"HostIp": "127.0.0.1", "HostPort": "18180"}]},
            },
            "NetworkSettings": {"Ports": {"8080/tcp": [{"HostIp": "127.0.0.1", "HostPort": "18180"}]}},
            "State": {"Running": True, "Health": {"Status": "healthy"}},
        }
    ]


def _health() -> dict:
    return {
        "liveness": {"status": "ok"},
        "readiness": {"status": "ready"},
        "user_flow": {"service": "SVC-SYNTHETIC", "version": VERSION},
    }


def build_bundle(bundle: Path) -> None:
    _approval(bundle)
    for arch, digest in DIGESTS.items():
        _write(
            bundle / f"build-{arch.replace('/', '_')}.json",
            {
                "schema_version": "homeserver-synthetic-build/v1",
                "architecture": arch,
                "image_id": digest,
                "tag": f"homeserver-synthetic:candidate-{SHA_V2[:12]}",
                "source_subdir_tree": TREE,
                "captured_at": _ts(60),
            },
        )
    clock = 70
    for host, arch in ARCH_BY_HOST.items():
        _write(
            bundle / f"provenance-{host}.json",
            {
                "schema_version": "homeserver-synthetic-provenance/v1",
                "clone_path": f"/srv/{host}/repo",
                "remote_url": "https://github.com/LiamVDB1/codex-config.git",
                "head": SHA_V2,
                "clean": True,
                "source_subdir": "planning/macbook-oserver-migration/platform-repository",
                "subdir_tree": TREE,
                "contained_branches": ["codex/homeserver-platform"],
                "captured_at": _ts(clock),
            },
        )
        clock += 1
        for action, commit, digest_map in (
            ("deploy", SHA_V2, DIGESTS),
            ("recover", SHA_V2, DIGESTS),
            ("rollback", SHA_V1, ROLLBACK),
        ):
            arch_digest = digest_map[arch]
            if action == "recover":
                _write(
                    bundle / f"attest-{host}-recover.json",
                    {
                        "inspect": _inspect(SHA_V2, DIGESTS[arch], "deploy"),
                        "health": _health(),
                        "captured_at": _ts(clock),
                    },
                )
                clock += 1
                continue
            _write(
                bundle / f"plan-{host}-{action}.json",
                {
                    "captured_at": _ts(clock),
                    "schema_version": "homeserver-synthetic-runtime-plan/v1",
                    "service_id": "SVC-SYNTHETIC",
                    "action": action,
                    "host": host,
                    "architecture": arch,
                    "source_commit_sha": commit,
                    "provenance_subdir_tree": TREE,
                    "image_digest": arch_digest,
                    "health_urls": ["http://127.0.0.1:18180/healthz"],
                    "remove_command": ["docker", "rm", "--force", "homeserver-synthetic"],
                },
            )
            clock += 1
            _write(
                bundle / f"attest-{host}-{action}.json",
                {
                    "inspect": _inspect(commit, arch_digest, action),
                    "health": _health(),
                    "captured_at": _ts(clock),
                },
            )
            clock += 1
        _write(
            bundle / f"removal-identity-{host}.json",
            {
                "schema_version": "homeserver-synthetic-removal-identity/v1",
                "container_name": "homeserver-synthetic",
                "image_digest": ROLLBACK[arch],
                "source_commit_sha": SHA_V1,
                "action": "rollback",
                "captured_at": _ts(clock),
            },
        )
        clock += 1
        _write(
            bundle / f"absence-proof-{host}.json",
            {
                "schema_version": "homeserver-synthetic-absence-proof/v1",
                "container_name": "homeserver-synthetic",
                "ps_matches": 0,
                "inspect_absent": True,
                "captured_at": _ts(clock),
            },
        )
        clock += 7  # keep the next host strictly after this one


class ReceiptChainTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.bundle = Path(self._tmp.name)
        build_bundle(self.bundle)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_complete_bundle_passes(self) -> None:
        summary = validate_bundle(self.bundle, version=VERSION)
        self.assertEqual(summary["approval_commit"], SHA_V2)
        self.assertGreater(summary["receipts_checked"], 10)

    def test_missing_receipt_fails_closed(self) -> None:
        (self.bundle / "absence-proof-oserver.json").unlink()
        with self.assertRaisesRegex(ChainError, "missing receipt"):
            validate_bundle(self.bundle, version=VERSION)

    def test_attested_image_mismatch_is_caught(self) -> None:
        path = self.bundle / "attest-homeserver-deploy.json"
        payload = json.loads(path.read_text())
        payload["inspect"][0]["Image"] = ROLLBACK["linux/amd64"]
        path.write_text(json.dumps(payload))
        with self.assertRaisesRegex(ChainError, "attested image"):
            validate_bundle(self.bundle, version=VERSION)

    def test_out_of_order_timestamp_is_caught(self) -> None:
        path = self.bundle / "plan-homeserver-rollback.json"
        payload = json.loads(path.read_text())
        payload["captured_at"] = _ts(61)
        path.write_text(json.dumps(payload))
        with self.assertRaisesRegex(ChainError, "backwards"):
            validate_bundle(self.bundle, version=VERSION)

    def test_simultaneous_plan_and_attest_is_rejected(self) -> None:
        plan_path = self.bundle / "plan-homeserver-deploy.json"
        attest_path = self.bundle / "attest-homeserver-deploy.json"
        stamp = json.loads(attest_path.read_text())["captured_at"]
        payload = json.loads(plan_path.read_text())
        payload["captured_at"] = stamp
        plan_path.write_text(json.dumps(payload))
        with self.assertRaisesRegex(ChainError, "does not follow its plan"):
            validate_bundle(self.bundle, version=VERSION)

    def test_secret_like_key_in_receipt_fails_scan(self) -> None:
        _write(self.bundle / "extra-notes.json", {"deployment_token_file_note": "ok", "api_key_hint": "x"})
        with self.assertRaisesRegex(ChainError, "secret-scan"):
            validate_bundle(self.bundle, version=VERSION)

    def test_host_subtree_disagreement_is_caught(self) -> None:
        path = self.bundle / "provenance-oserver.json"
        payload = json.loads(path.read_text())
        payload["subdir_tree"] = "9" * 40
        path.write_text(json.dumps(payload))
        with self.assertRaisesRegex(ChainError, "subtree"):
            validate_bundle(self.bundle, version=VERSION)


if __name__ == "__main__":
    unittest.main()
