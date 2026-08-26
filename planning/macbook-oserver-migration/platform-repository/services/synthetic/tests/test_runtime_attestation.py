from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from runtime_attestation import validate_runtime_attestation  # noqa: E402


SHA = "a" * 40
DIGEST = "sha256:" + "b" * 64


def valid_plan() -> dict:
    return {
        "schema_version": "homeserver-synthetic-runtime-plan/v1",
        "service_id": "SVC-SYNTHETIC",
        "action": "deploy",
        "host": "homeserver",
        "architecture": "linux/amd64",
        "source_commit_sha": SHA,
        "image_digest": DIGEST,
        "artifact_index_digest": "sha256:" + "c" * 64,
        "command": [],
        "health_urls": [],
        "remove_command": [],
    }


def valid_inspect() -> list[dict]:
    ports = {"8080/tcp": [{"HostIp": "127.0.0.1", "HostPort": "18180"}]}
    return [{
        "Id": "f" * 64,
        "Image": DIGEST,
        "Name": "/homeserver-synthetic",
        "Config": {
            "User": "65532:65532",
            "Env": None,
            "Labels": {
                "homeserver.action": "deploy",
                "homeserver.source_commit": SHA,
                "org.opencontainers.image.revision": SHA,
            },
        },
        "HostConfig": {
            "Privileged": False,
            "ReadonlyRootfs": True,
            "Memory": 134217728,
            "NanoCpus": 250000000,
            "PidsLimit": 64,
            "CapDrop": ["ALL"],
            "SecurityOpt": ["no-new-privileges"],
            "PortBindings": ports,
        },
        "Mounts": [],
        "NetworkSettings": {"Ports": ports},
        "State": {"Running": True, "Health": {"Status": "healthy"}},
    }]


def valid_endpoints() -> dict[str, dict]:
    return {
        "liveness": {"status": "ok"},
        "readiness": {"status": "ready"},
        "user_flow": {"service": "SVC-SYNTHETIC", "version": "v2"},
    }


class RuntimeAttestationTests(unittest.TestCase):
    def test_hardened_runtime_passes(self) -> None:
        self.assertEqual(
            validate_runtime_attestation(valid_inspect(), valid_plan(), valid_endpoints(), "v2"),
            [],
        )

    def test_public_binding_fails(self) -> None:
        inspect = valid_inspect()
        inspect[0]["HostConfig"]["PortBindings"]["8080/tcp"][0]["HostIp"] = "0.0.0.0"
        self.assertIn("host binding must be exactly 127.0.0.1:18180", validate_runtime_attestation(
            inspect, valid_plan(), valid_endpoints(), "v2"
        ))

    def test_wrong_digest_fails(self) -> None:
        inspect = valid_inspect()
        inspect[0]["Image"] = "sha256:" + "d" * 64
        self.assertIn("container image does not match approved digest", validate_runtime_attestation(
            inspect, valid_plan(), valid_endpoints(), "v2"
        ))

    def test_writable_or_mounted_runtime_fails(self) -> None:
        inspect = valid_inspect()
        inspect[0]["HostConfig"]["ReadonlyRootfs"] = False
        inspect[0]["Mounts"] = [{"Destination": "/data"}]
        errors = validate_runtime_attestation(inspect, valid_plan(), valid_endpoints(), "v2")
        self.assertIn("root filesystem is not read-only", errors)
        self.assertIn("synthetic runtime must not have mounts", errors)

    def test_wrong_user_flow_version_fails(self) -> None:
        endpoints = copy.deepcopy(valid_endpoints())
        endpoints["user_flow"]["version"] = "v1"
        self.assertIn("user-flow version does not match", validate_runtime_attestation(
            valid_inspect(), valid_plan(), endpoints, "v2"
        ))

    def test_root_user_fails(self) -> None:
        inspect = valid_inspect()
        inspect[0]["Config"]["User"] = "root"
        self.assertIn(
            "container must run as the unprivileged 65532:65532 user",
            validate_runtime_attestation(inspect, valid_plan(), valid_endpoints(), "v2"),
        )

    def test_privileged_runtime_fails(self) -> None:
        inspect = valid_inspect()
        inspect[0]["HostConfig"]["Privileged"] = True
        self.assertIn(
            "container must not be privileged",
            validate_runtime_attestation(inspect, valid_plan(), valid_endpoints(), "v2"),
        )

    def test_environment_leakage_fails(self) -> None:
        inspect = valid_inspect()
        inspect[0]["Config"]["Env"] = ["PATH=/usr/bin"]
        self.assertIn(
            "container environment must be empty",
            validate_runtime_attestation(inspect, valid_plan(), valid_endpoints(), "v2"),
        )

    def test_extra_endpoint_evidence_fails_closed(self) -> None:
        endpoints = copy.deepcopy(valid_endpoints())
        endpoints["debug"] = {"status": "ok"}
        self.assertIn("health payload keys are not exact", validate_runtime_attestation(
            valid_inspect(), valid_plan(), endpoints, "v2"
        ))


if __name__ == "__main__":
    unittest.main()
