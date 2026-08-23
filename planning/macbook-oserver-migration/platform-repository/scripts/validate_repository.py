#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from platform_contracts import ContractError, validate_service


ROOT = Path(__file__).resolve().parents[1]


def validate_repository(root: Path) -> list[str]:
    errors: list[str] = []
    policy_path = root / "repository.json"
    try:
        policy = json.loads(policy_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return [f"repository policy: {exc}"]
    required_policy = {"schema_version", "canonical_remote", "canonical_branch", "source_subdir", "hosts"}
    if set(policy) != required_policy or policy["schema_version"] != "homeserver-platform-repository/v1":
        errors.append("repository policy fields or schema are invalid")
    if set(policy["hosts"]) != {"homeserver", "oserver"}:
        errors.append("repository policy must declare both hosts")

    services = sorted((root / "platform/catalogue/services").glob("*.json"))
    if not services:
        errors.append("catalogue must contain at least one service record")
    for service_path in services:
        try:
            validate_service(json.loads(service_path.read_text()))
        except (OSError, json.JSONDecodeError, ContractError) as exc:
            errors.append(f"{service_path.relative_to(root)}: {exc}")
    return errors


def main() -> int:
    errors = validate_repository(ROOT)
    for error in errors:
        print(f"FAIL: {error}")
    if errors:
        return 1
    services = sorted((ROOT / "platform/catalogue/services").glob("*.json"))
    print(f"PASS: repository policy and {len(services)} service record(s) validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
