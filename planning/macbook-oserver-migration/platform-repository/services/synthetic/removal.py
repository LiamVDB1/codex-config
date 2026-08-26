#!/usr/bin/env python3
"""Identity-checked removal and absence proof for the synthetic runtime."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_IDENTITY = "homeserver-synthetic-removal-identity/v1"
SCHEMA_ABSENCE = "homeserver-synthetic-absence-proof/v1"


class RemovalError(ValueError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _single_container(inspect_payload: Any) -> dict[str, Any]:
    if not isinstance(inspect_payload, list) or len(inspect_payload) != 1:
        raise RemovalError("docker inspect must contain exactly one container")
    inspect = inspect_payload[0]
    if not isinstance(inspect, dict):
        raise RemovalError("docker inspect container must be an object")
    return inspect


def capture_removal_identity(
    inspect_payload: Any,
    plan: dict[str, Any],
    *,
    now: Any = None,
) -> dict[str, Any]:
    """Bind the exact running container identity to the plan before removal."""
    inspect = _single_container(inspect_payload)
    name = inspect.get("Name")
    image = inspect.get("Image")
    config = inspect.get("Config") if isinstance(inspect.get("Config"), dict) else {}
    labels = config.get("Labels") if isinstance(config.get("Labels"), dict) else {}

    expected_name = f"/{(plan.get('remove_command') or ['docker', 'rm', '--force', ''])[-1]}"
    if name != expected_name:
        raise RemovalError(f"container {name!r} is not the planned removal target {expected_name!r}")
    if image != plan.get("image_digest"):
        raise RemovalError("running container image does not match the receipt-bound digest")
    if labels.get("homeserver.source_commit") != plan.get("source_commit_sha"):
        raise RemovalError("running container source commit label does not match the plan")
    if labels.get("homeserver.action") != plan.get("action"):
        raise RemovalError("running container action label does not match the plan")

    return {
        "schema_version": SCHEMA_IDENTITY,
        "container_name": name.lstrip("/"),
        "image_digest": image,
        "source_commit_sha": labels.get("homeserver.source_commit"),
        "action": labels.get("homeserver.action"),
        "captured_at": (_utc_now() if now is None else now),
    }


def verify_absence(
    ps_lines: list[str],
    *,
    ps_probe_ok: bool,
    inspect_not_found: bool,
    container_name: str = "homeserver-synthetic",
    now: Any = None,
) -> dict[str, Any]:
    """Prove absence: empty ps result plus an explicit docker "No such object"."""
    if not ps_probe_ok:
        raise RemovalError("docker ps probe failed; absence cannot be established")
    matches = [line for line in ps_lines if line.strip()]
    if matches:
        raise RemovalError(f"containers still present: {len(matches)}")
    if not inspect_not_found:
        raise RemovalError(
            'docker inspect must fail with "No such object"; other failures are not absence'
        )
    return {
        "schema_version": SCHEMA_ABSENCE,
        "container_name": container_name,
        "ps_matches": 0,
        "inspect_not_found": True,
        "captured_at": (_utc_now() if now is None else now),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Synthetic removal identity and absence proof")
    parser.add_argument("--mode", choices=("identity", "absence"), required=True)
    parser.add_argument("--inspect", type=Path)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--ps-file", type=Path, help="newline-separated docker ps -a names output")
    args = parser.parse_args()
    try:
        if args.mode == "identity":
            if not args.inspect or not args.plan:
                raise RemovalError("--inspect and --plan are required for identity mode")
            receipt = capture_removal_identity(json.loads(args.inspect.read_text()), json.loads(args.plan.read_text()))
            print(json.dumps(receipt, indent=2, sort_keys=True))
            return 0
        raise RemovalError("use host_rollout.py remove; standalone absence mode is disabled")
        print(json.dumps(receipt, indent=2, sort_keys=True))
        return 0
    except (RemovalError, OSError, json.JSONDecodeError) as exc:
        print(f"FAIL: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
