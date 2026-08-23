#!/usr/bin/env python3
"""Validate captured Docker inspect and synthetic health responses."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


CONTAINER_NAME = "/homeserver-synthetic"
EXPECTED_BINDING = ("127.0.0.1", "18180")
EXPECTED_PORT = "8080/tcp"


def _equal(errors: list[str], actual: Any, expected: Any, message: str) -> None:
    if actual != expected:
        errors.append(message)


def _port_bindings(errors: list[str], inspect: dict[str, Any]) -> None:
    host_config = inspect.get("HostConfig")
    network = inspect.get("NetworkSettings")
    bindings = host_config.get("PortBindings") if isinstance(host_config, dict) else None
    network_ports = network.get("Ports") if isinstance(network, dict) else None
    expected = {EXPECTED_PORT: [{"HostIp": EXPECTED_BINDING[0], "HostPort": EXPECTED_BINDING[1]}]}
    if bindings != expected or network_ports != expected:
        errors.append("host binding must be exactly 127.0.0.1:18180")


def validate_runtime_attestation(
    inspect_payload: list[dict[str, Any]],
    plan: dict[str, Any],
    endpoints: dict[str, dict[str, Any]],
    version: str,
) -> list[str]:
    """Return deterministic contract violations for one captured runtime."""
    errors: list[str] = []
    if not isinstance(inspect_payload, list) or len(inspect_payload) != 1:
        return ["docker inspect must contain exactly one container"]
    inspect = inspect_payload[0]
    if not isinstance(inspect, dict):
        return ["docker inspect container must be an object"]

    _equal(errors, inspect.get("Name"), CONTAINER_NAME, "container name is not approved")
    _equal(errors, inspect.get("Image"), plan.get("image_digest"), "container image does not match approved digest")
    config = inspect.get("Config")
    labels = config.get("Labels") if isinstance(config, dict) else None
    if not isinstance(labels, dict):
        errors.append("container labels are missing")
    else:
        _equal(errors, labels.get("homeserver.source_commit"), plan.get("source_commit_sha"), "container source commit does not match approved source")
        _equal(errors, labels.get("homeserver.action"), plan.get("action"), "container action does not match approved action")

    host_config = inspect.get("HostConfig")
    if not isinstance(host_config, dict):
        errors.append("container host configuration is missing")
        host_config = {}
    _equal(errors, host_config.get("ReadonlyRootfs"), True, "root filesystem is not read-only")
    _equal(errors, inspect.get("Mounts"), [], "synthetic runtime must not have mounts")
    _equal(errors, host_config.get("CapDrop"), ["ALL"], "container capabilities are not dropped exactly")
    _equal(errors, host_config.get("SecurityOpt"), ["no-new-privileges"], "no-new-privileges is not enabled exactly")
    _equal(errors, host_config.get("Memory"), 128 * 1024 * 1024, "container memory limit is not 128MiB")
    _equal(errors, host_config.get("NanoCpus"), 250_000_000, "container CPU limit is not 0.25")
    _equal(errors, host_config.get("PidsLimit"), 64, "container pids limit is not 64")
    _port_bindings(errors, inspect)

    state = inspect.get("State")
    health = state.get("Health") if isinstance(state, dict) else None
    _equal(errors, state.get("Running") if isinstance(state, dict) else None, True, "container is not running")
    _equal(errors, health.get("Status") if isinstance(health, dict) else None, "healthy", "container is not healthy")

    expected_endpoints = {
        "liveness": {"status": "ok"},
        "readiness": {"status": "ready"},
        "user_flow": {"service": "SVC-SYNTHETIC", "version": version},
    }
    if not isinstance(endpoints, dict):
        errors.append("health payloads are missing")
    else:
        if set(endpoints) != set(expected_endpoints):
            errors.append("health payload keys are not exact")
        for endpoint, expected in expected_endpoints.items():
            if endpoints.get(endpoint) != expected:
                if endpoint == "user_flow":
                    errors.append("user-flow version does not match")
                else:
                    errors.append(f"{endpoint} health payload is not exact")
    return errors


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate captured synthetic runtime attestation")
    parser.add_argument("--inspect", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--health", type=Path, required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    try:
        errors = validate_runtime_attestation(
            _load_json(args.inspect), _load_json(args.plan), _load_json(args.health), args.version
        )
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        print(f"FAIL: input cannot be loaded: {exc}")
        return 1
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1
    print("PASS: synthetic runtime attestation")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
