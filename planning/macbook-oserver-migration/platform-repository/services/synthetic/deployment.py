#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
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


PROVENANCE_SCHEMA = "homeserver-synthetic-provenance/v1"


def _rederive_from_clone(verify_clone):
    """Re-derive provenance from the live clone using one metadata authority."""
    import git_provenance

    metadata = git_provenance._repository_metadata_fallback(Path(__file__).resolve().parents[2])
    return git_provenance.collect_git_provenance(
        verify_clone,
        expected_remote=metadata["canonical_remote"],
        allowed_branches=metadata["allowed_branches"],
        source_subdir=metadata["source_subdir"],
    )


def require_provenance(
    provenance: dict[str, Any],
    approval: dict[str, Any],
    *,
    action: str,
    verify_clone: Any,
) -> dict[str, Any]:
    """Cross-check a measured provenance receipt against the approval.

    verify_clone is mandatory: the receipt is never trusted on its own; the
    same fields are re-derived from the live clone and must match exactly.
    """
    if verify_clone is None:
        raise DeploymentError("live clone verification is mandatory")
    derived = _rederive_from_clone(verify_clone)
    for field in ("head", "clean", "subdir_tree", "remote_url", "contained_branches"):
        if provenance.get(field) != derived.get(field):
            raise DeploymentError(
                f"provenance receipt field {field!r} does not match the live clone"
            )
    if not isinstance(provenance, dict) or provenance.get("schema_version") != PROVENANCE_SCHEMA:
        raise DeploymentError("provenance receipt schema is unsupported")
    if provenance.get("clean") is not True:
        raise DeploymentError("measured clone state is not clean")
    del action
    # The provenance receipt always describes the deployed tooling clone, which
    # sits at the approved source commit for both deploy and rollback actions.
    if provenance.get("head") != approval["source_commit_sha"]:
        raise DeploymentError(
            f"clone HEAD {provenance.get('head')} does not match approved commit "
            f"{approval['source_commit_sha']}"
        )
    tree = provenance.get("subdir_tree")
    if not isinstance(tree, str) or not SHA_RE.fullmatch(tree):
        raise DeploymentError("provenance receipt lacks the bound source subtree hash")
    return {"subdir_tree": tree}


def build_runtime_plan(
    approval: dict[str, Any],
    *,
    host: str,
    architecture: str,
    provenance: dict[str, Any],
    image_digest: str,
    action: str,
    verify_clone: Any,
) -> dict[str, Any]:
    if host not in HOST_ARCHITECTURES:
        raise DeploymentError(f"unknown host: {host}")
    if architecture != HOST_ARCHITECTURES[host]:
        raise DeploymentError(f"architecture {architecture} is not approved for {host}")
    if action not in {"deploy", "rollback"}:
        raise DeploymentError(f"unsupported action: {action}")

    commit_field = "source_commit_sha" if action == "deploy" else "previous_approved_sha"
    digest_field = "platform_digests" if action == "deploy" else "rollback_platform_digests"
    expected_commit = approval[commit_field]
    source_tree = require_provenance(provenance, approval, action=action, verify_clone=verify_clone)["subdir_tree"]
    expected_digest = approval[digest_field][architecture]
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
        "captured_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "schema_version": "homeserver-synthetic-runtime-plan/v1",
        "service_id": approval["service_id"],
        "action": action,
        "host": host,
        "architecture": architecture,
        "source_commit_sha": expected_commit,
        "provenance_subdir_tree": source_tree,
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
    parser.add_argument("--provenance", type=Path, required=True)
    parser.add_argument("--verify-clone", type=Path, required=True)
    parser.add_argument("--image-digest", required=True)
    parser.add_argument("--action", choices=("deploy", "rollback"), required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        approval = load_approval(args.approval)
        try:
            provenance = json.loads(args.provenance.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            print(f"FAIL: provenance cannot be loaded: {exc}")
            return 1
        plan = build_runtime_plan(
            approval,
            host=args.host,
            architecture=args.architecture,
            provenance=provenance,
            image_digest=args.image_digest,
            action=args.action,
            verify_clone=args.verify_clone,
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
