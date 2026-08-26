#!/usr/bin/env python3
"""Derive synthetic-service build provenance from real Git state.

Every field is measured on the host clone; nothing is caller-asserted. The
resulting receipt is the only provenance input the deployment planner accepts.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "homeserver-synthetic-provenance/v1"
SHA_RE_LENGTH = 40


class ProvenanceError(ValueError):
    pass


def _repository_metadata_fallback(platform_repo_root):
    """Load canonical remote/branch/subdir from the platform repository root."""
    metadata = json.loads((Path(platform_repo_root) / "repository.json").read_text())
    return {
        "canonical_remote": metadata["canonical_remote"],
        "canonical_branch": metadata["canonical_branch"],
        "source_subdir": metadata["source_subdir"],
        "allowed_branches": [metadata["canonical_branch"], "codex/homeserver-platform"],
    }


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _git(clone: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", "-C", str(clone), *args],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()
        message = detail[-1] if detail else f"exit code {result.returncode}"
        raise ProvenanceError(f"git {' '.join(args[:2])} failed: {message}")
    return result


def normalize_remote(url: str) -> str:
    """Reduce remote URL spellings to one comparable form."""
    text = url.strip().lower()
    for prefix in ("ssh://", "https://", "http://", "git://"):
        if text.startswith(prefix):
            text = text[len(prefix):]
    if text.startswith("git@"):
        text = text[4:].replace(":", "/", 1)
    if text.endswith(".git"):
        text = text[:-4]
    return text.rstrip("/")


def _require_sha(value: str, field: str) -> str:
    text = value.strip().lower()
    if len(text) != SHA_RE_LENGTH or any(ch not in "0123456789abcdef" for ch in text):
        raise ProvenanceError(f"{field} is not a 40-character lowercase commit SHA")
    return text


def collect_git_provenance(
    clone: Path,
    *,
    expected_remote: str,
    allowed_branches: list[str],
    source_subdir: str,
    now: Any = None,
) -> dict[str, Any]:
    """Measure one clone and return a provenance receipt, or raise."""
    if not clone.is_dir():
        raise ProvenanceError(f"clone path does not exist: {clone}")
    if not allowed_branches:
        raise ProvenanceError("at least one allowed branch is required")

    remote_url = _git(clone, "remote", "get-url", "origin").stdout.strip()
    if normalize_remote(remote_url) != normalize_remote(expected_remote):
        raise ProvenanceError(
            f"origin {remote_url!r} is not the canonical remote {expected_remote!r}"
        )

    head = _require_sha(_git(clone, "rev-parse", "HEAD").stdout, "HEAD")

    status = _git(clone, "status", "--porcelain").stdout
    clean = status.strip() == ""

    contained: list[str] = []
    for branch in sorted(allowed_branches):
        probe = _git(clone, "merge-base", "--is-ancestor", "HEAD", f"origin/{branch}", check=False)
        if probe.returncode == 0:
            contained.append(branch)
    if not contained:
        raise ProvenanceError(
            "HEAD is not contained in any allowed remote branch: " + ", ".join(sorted(allowed_branches))
        )

    subtree = _require_sha(
        _git(clone, "rev-parse", f"HEAD:{source_subdir}").stdout, "source subtree"
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "clone_path": str(clone),
        "remote_url": remote_url,
        "remote_url_normalized": normalize_remote(remote_url),
        "head": head,
        "clean": clean,
        "source_subdir": source_subdir,
        "subdir_tree": subtree,
        "contained_branches": contained,
        "captured_at": (_utc_now() if now is None else now),
    }


def require_deployable(provenance: dict[str, Any], approved_sha: str) -> None:
    """Cross-check one provenance receipt against the approved commit."""
    if not isinstance(provenance, dict) or provenance.get("schema_version") != SCHEMA_VERSION:
        raise ProvenanceError("provenance receipt schema is unsupported")
    if provenance.get("clean") is not True:
        raise ProvenanceError("clone working tree is not clean")
    if provenance.get("head") != approved_sha:
        raise ProvenanceError(
            f"clone HEAD {provenance.get('head')} does not match approved commit {approved_sha}"
        )
    contained = provenance.get("contained_branches")
    if not isinstance(contained, list) or not contained:
        raise ProvenanceError("provenance receipt lists no containing remote branch")


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect synthetic build provenance")
    parser.add_argument("--clone", type=Path, required=True)
    parser.add_argument("--expected-remote", required=True)
    parser.add_argument("--allowed-branch", action="append", required=True)
    parser.add_argument("--source-subdir", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        receipt = collect_git_provenance(
            args.clone,
            expected_remote=args.expected_remote,
            allowed_branches=list(args.allowed_branch),
            source_subdir=args.source_subdir,
        )
    except ProvenanceError as exc:
        print(f"FAIL: {exc}")
        return 1
    serialized = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(serialized)
    else:
        print(serialized, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
