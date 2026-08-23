#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from platform_contracts import ContractError, validate_service


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    policy_path = ROOT / "repository.json"
    try:
        policy = json.loads(policy_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        print(f"FAIL: repository policy: {exc}")
        return 1
    required_policy = {"schema_version", "canonical_remote", "canonical_branch", "source_subdir", "hosts"}
    if set(policy) != required_policy or policy["schema_version"] != "homeserver-platform-repository/v1":
        print("FAIL: repository policy fields or schema are invalid")
        return 1
    if set(policy["hosts"]) != {"homeserver", "oserver"}:
        print("FAIL: repository policy must declare both hosts")
        return 1

    services = sorted((ROOT / "platform/catalogue/services").glob("*.json"))
    for service_path in services:
        try:
            validate_service(json.loads(service_path.read_text()))
        except (OSError, json.JSONDecodeError, ContractError) as exc:
            print(f"FAIL: {service_path.relative_to(ROOT)}: {exc}")
            return 1
    print(f"PASS: repository policy and {len(services)} service record(s) validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
