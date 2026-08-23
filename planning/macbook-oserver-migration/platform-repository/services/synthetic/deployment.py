#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
HOST_ARCHITECTURES = {
    "homeserver": "linux/amd64",
    "oserver": "linux/arm64",
}
APPROVAL_FIELDS = {
    "schema_version",
    "service_id",
    "source_commit_sha",
    "previous_approved_sha",
    "artifact_index_digest",
    "platform_digests",
    "rollback_platform_digests",
}
ARTIFACT_INDEX_FIELDS = APPROVAL_FIELDS - {"artifact_index_digest"}


class DeploymentError(ValueError):
    pass


def _require_digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or not DIGEST_RE.fullmatch(value):
        raise DeploymentError(f"{field} must be an immutable sha256 digest")
    return value


def _require_sha(value: Any, field: str) -> str:
    if not isinstance(value, str) or not SHA_RE.fullmatch(value):
        raise DeploymentError(f"{field} must be a 40-character lowercase commit SHA")
    return value


def load_approval(path: Path) -> dict[str, Any]:
    try:
        approval = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise DeploymentError(f"approval cannot be loaded: {exc}") from exc
    if not isinstance(approval, dict):
        raise DeploymentError("approval must be an object")
    missing = APPROVAL_FIELDS - approval.keys()
    unknown = approval.keys() - APPROVAL_FIELDS
    if missing:
        raise DeploymentError(f"missing approval field: {sorted(missing)[0]}")
    if unknown:
        raise DeploymentError(f"unknown approval field: {sorted(unknown)[0]}")
    if approval["schema_version"] != "homeserver-synthetic-approval/v1":
        raise DeploymentError("schema_version is unsupported")
    if approval["service_id"] != "SVC-SYNTHETIC":
        raise DeploymentError("service_id is unsupported")
    _require_sha(approval["source_commit_sha"], "source_commit_sha")
    _require_sha(approval["previous_approved_sha"], "previous_approved_sha")
    _require_digest(approval["artifact_index_digest"], "artifact_index_digest")
    for field in ("platform_digests", "rollback_platform_digests"):
        digests = approval[field]
        if not isinstance(digests, dict) or set(digests) != set(HOST_ARCHITECTURES.values()):
            raise DeploymentError(f"{field} must contain linux/amd64 and linux/arm64")
        for architecture, digest in digests.items():
            _require_digest(digest, f"{field}.{architecture}")
    index_path = path.with_name("artifact-index.json")
    try:
        index_bytes = index_path.read_bytes()
        index = json.loads(index_bytes)
    except (OSError, json.JSONDecodeError) as exc:
        raise DeploymentError(f"artifact index cannot be loaded: {exc}") from exc
    actual_index_digest = "sha256:" + hashlib.sha256(index_bytes).hexdigest()
    if approval["artifact_index_digest"] != actual_index_digest:
        raise DeploymentError("artifact index digest does not match approval")
    if not isinstance(index, dict) or set(index) != ARTIFACT_INDEX_FIELDS:
        raise DeploymentError("artifact index fields are invalid")
    expected_index = {key: approval[key] for key in ARTIFACT_INDEX_FIELDS}
    expected_index["schema_version"] = "homeserver-synthetic-artifacts/v1"
    if index != expected_index:
        raise DeploymentError("artifact index metadata does not match approval")
    return approval


def build_runtime_plan(
    approval: dict[str, Any],
    *,
    host: str,
    architecture: str,
    actual_source_commit: str,
    source_clean: bool,
    image_digest: str,
    action: str,
) -> dict[str, Any]:
    if host not in HOST_ARCHITECTURES:
        raise DeploymentError(f"unknown host: {host}")
    if architecture != HOST_ARCHITECTURES[host]:
        raise DeploymentError(f"architecture {architecture} is not approved for {host}")
    if action not in {"deploy", "rollback"}:
        raise DeploymentError(f"unsupported action: {action}")
    if source_clean is not True:
        raise DeploymentError("source must be clean")

    commit_field = "source_commit_sha" if action == "deploy" else "previous_approved_sha"
    digest_field = "platform_digests" if action == "deploy" else "rollback_platform_digests"
    expected_commit = approval[commit_field]
    expected_digest = approval[digest_field][architecture]
    if actual_source_commit != expected_commit:
        raise DeploymentError(
            f"actual source commit {actual_source_commit} does not match approved commit {expected_commit}"
        )
    _require_digest(image_digest, "image_digest")
    if image_digest != expected_digest:
        raise DeploymentError(f"image digest {image_digest} is not approved for {architecture}")

    container_name = "homeserver-synthetic"
    command = [
        "docker",
        "run",
        "--detach",
        "--name",
        container_name,
        "--label",
        f"homeserver.source_commit={expected_commit}",
        "--label",
        f"homeserver.action={action}",
        "--publish",
        "127.0.0.1:18180:8080",
        "--read-only",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=16m",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--memory",
        "128m",
        "--cpus",
        "0.25",
        "--pids-limit",
        "64",
        image_digest,
    ]
    return {
        "schema_version": "homeserver-synthetic-runtime-plan/v1",
        "service_id": approval["service_id"],
        "action": action,
        "host": host,
        "architecture": architecture,
        "source_commit_sha": expected_commit,
        "image_digest": expected_digest,
        "artifact_index_digest": approval["artifact_index_digest"],
        "command": command,
        "health_urls": [
            "http://127.0.0.1:18180/healthz",
            "http://127.0.0.1:18180/readyz",
            "http://127.0.0.1:18180/synthetic",
        ],
        "remove_command": ["docker", "rm", "--force", container_name],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("approval", type=Path)
    parser.add_argument("--host", choices=sorted(HOST_ARCHITECTURES), required=True)
    parser.add_argument("--architecture", choices=sorted(HOST_ARCHITECTURES.values()), required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--source-clean", action="store_true")
    parser.add_argument("--image-digest", required=True)
    parser.add_argument("--action", choices=("deploy", "rollback"), required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        approval = load_approval(args.approval)
        plan = build_runtime_plan(
            approval,
            host=args.host,
            architecture=args.architecture,
            actual_source_commit=args.source_commit,
            source_clean=args.source_clean,
            image_digest=args.image_digest,
            action=args.action,
        )
    except DeploymentError as exc:
        print(f"FAIL: {exc}")
        return 1
    serialized = json.dumps(plan, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(serialized)
    else:
        print(serialized, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
