#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any


SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
SERVICE_RE = re.compile(r"^SVC-[A-Z0-9_-]+$")
SECRET_REF_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,127}$")
ARCHITECTURES = {"linux/amd64", "linux/arm64"}
HOSTS = {"homeserver", "oserver"}


class ContractError(ValueError):
    pass


def _object(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError(f"{path} must be an object")
    return value


def _exact_fields(value: dict[str, Any], required: set[str], allowed: set[str], path: str) -> None:
    for key in sorted(required - value.keys()):
        raise ContractError(f"{path}.{key} is required")
    for key in sorted(value.keys() - allowed):
        raise ContractError(f"{path}.{key} is an unknown field")


def _string(value: Any, path: str, *, nonempty: bool = True) -> str:
    if not isinstance(value, str) or (nonempty and not value.strip()):
        raise ContractError(f"{path} must be a non-empty string")
    return value


def _integer(value: Any, path: str, *, minimum: int = 0, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ContractError(f"{path} must be an integer >= {minimum}")
    if maximum is not None and value > maximum:
        raise ContractError(f"{path} must be <= {maximum}")
    return value


def _sha(value: Any, path: str) -> str:
    text = _string(value, path)
    if not SHA_RE.fullmatch(text):
        raise ContractError(f"{path} must be a 40-character lowercase Git SHA")
    return text


def _digest(value: Any, path: str) -> str:
    text = _string(value, path)
    if not DIGEST_RE.fullmatch(text):
        raise ContractError(f"{path} must be a pinned sha256 digest")
    return text


def _relative_path(value: Any, path: str) -> str:
    text = _string(value, path)
    pure = PurePosixPath(text)
    if pure.is_absolute() or ".." in pure.parts:
        raise ContractError(f"{path} must be a normalized repository-relative path")
    return text


def _string_list(value: Any, path: str, *, nonempty: bool = False) -> list[str]:
    if not isinstance(value, list) or (nonempty and not value):
        raise ContractError(f"{path} must be a{' non-empty' if nonempty else ''} string list")
    for index, item in enumerate(value):
        _string(item, f"{path}[{index}]")
    return value


def validate_service(raw: Any) -> dict[str, Any]:
    service = _object(raw, "$")
    required = {
        "schema_version", "service_id", "classification", "owners", "source",
        "artifacts", "deployment", "network", "storage", "health", "resources",
        "backup", "rollback", "secret_refs",
    }
    _exact_fields(service, required, required, "$")
    if service["schema_version"] != "homeserver-service/v1":
        raise ContractError("$.schema_version is unsupported")
    if not SERVICE_RE.fullmatch(_string(service["service_id"], "$.service_id")):
        raise ContractError("$.service_id is invalid")
    if service["classification"] not in {"production", "private", "media", "rollback", "preview"}:
        raise ContractError("$.classification is invalid")

    owners = _object(service["owners"], "$.owners")
    _exact_fields(owners, {"platform", "operational"}, {"platform", "operational"}, "$.owners")
    _string(owners["platform"], "$.owners.platform")
    _string(owners["operational"], "$.owners.operational")

    source = _object(service["source"], "$.source")
    source_fields = {"repository", "commit_sha", "path", "dirty"}
    _exact_fields(source, source_fields, source_fields, "$.source")
    repository = _string(source["repository"], "$.source.repository")
    if not repository.startswith("https://") or not repository.endswith(".git"):
        raise ContractError("$.source.repository must be an HTTPS Git remote")
    _sha(source["commit_sha"], "$.source.commit_sha")
    _relative_path(source["path"], "$.source.path")
    if source["dirty"] is not False:
        raise ContractError("$.source.dirty must be false")

    artifacts = _object(service["artifacts"], "$.artifacts")
    artifact_fields = {"manifest_digest", "platform_digests"}
    _exact_fields(artifacts, artifact_fields, artifact_fields, "$.artifacts")
    _digest(artifacts["manifest_digest"], "$.artifacts.manifest_digest")
    platform_digests = _object(artifacts["platform_digests"], "$.artifacts.platform_digests")
    if set(platform_digests) != ARCHITECTURES:
        raise ContractError("$.artifacts.platform_digests must contain linux/amd64 and linux/arm64")
    for arch, value in platform_digests.items():
        _digest(value, f"$.artifacts.platform_digests.{arch}")

    deployment = _object(service["deployment"], "$.deployment")
    deployment_fields = {"hosts", "compose_path", "project_name", "rollback_artifact_digests"}
    _exact_fields(deployment, deployment_fields, deployment_fields, "$.deployment")
    hosts = set(_string_list(deployment["hosts"], "$.deployment.hosts", nonempty=True))
    if not hosts <= HOSTS:
        raise ContractError("$.deployment.hosts contains an unknown host")
    _relative_path(deployment["compose_path"], "$.deployment.compose_path")
    _string(deployment["project_name"], "$.deployment.project_name")
    rollback_digests = _string_list(
        deployment["rollback_artifact_digests"], "$.deployment.rollback_artifact_digests", nonempty=True
    )
    for index, value in enumerate(rollback_digests):
        _digest(value, f"$.deployment.rollback_artifact_digests[{index}]")

    network = _object(service["network"], "$.network")
    _exact_fields(network, {"bindings", "public_route"}, {"bindings", "public_route"}, "$.network")
    if network["public_route"] is not False:
        raise ContractError("$.network.public_route must be false before BUILD-002")
    if not isinstance(network["bindings"], list):
        raise ContractError("$.network.bindings must be a list")
    for index, raw_binding in enumerate(network["bindings"]):
        binding = _object(raw_binding, f"$.network.bindings[{index}]")
        fields = {"host", "address", "port", "protocol"}
        _exact_fields(binding, fields, fields, f"$.network.bindings[{index}]")
        if binding["host"] not in HOSTS:
            raise ContractError(f"$.network.bindings[{index}].host is invalid")
        if binding["address"] not in {"127.0.0.1", "::1"}:
            raise ContractError(f"$.network.bindings[{index}].address must be loopback")
        _integer(binding["port"], f"$.network.bindings[{index}].port", minimum=1, maximum=65535)
        if binding["protocol"] not in {"tcp", "udp"}:
            raise ContractError(f"$.network.bindings[{index}].protocol is invalid")

    storage = _object(service["storage"], "$.storage")
    _exact_fields(storage, {"stateful", "paths"}, {"stateful", "paths"}, "$.storage")
    if not isinstance(storage["stateful"], bool):
        raise ContractError("$.storage.stateful must be boolean")
    paths = _string_list(storage["paths"], "$.storage.paths")
    for index, value in enumerate(paths):
        if not value.startswith("/srv/homeserver/data/"):
            raise ContractError(f"$.storage.paths[{index}] must be under /srv/homeserver/data")

    health = _object(service["health"], "$.health")
    health_fields = {"liveness", "readiness", "user_flow", "timeout_seconds"}
    _exact_fields(health, health_fields, health_fields, "$.health")
    for key in ("liveness", "readiness", "user_flow"):
        if not _string(health[key], f"$.health.{key}").startswith("/"):
            raise ContractError(f"$.health.{key} must be an absolute HTTP path")
    _integer(health["timeout_seconds"], "$.health.timeout_seconds", minimum=1, maximum=60)

    resources = _object(service["resources"], "$.resources")
    resource_fields = {"cpu", "memory_mb", "pids"}
    _exact_fields(resources, resource_fields, resource_fields, "$.resources")
    cpu = _string(resources["cpu"], "$.resources.cpu")
    try:
        if float(cpu) <= 0:
            raise ValueError
    except ValueError as exc:
        raise ContractError("$.resources.cpu must be a positive decimal string") from exc
    _integer(resources["memory_mb"], "$.resources.memory_mb", minimum=16)
    _integer(resources["pids"], "$.resources.pids", minimum=8)

    backup = _object(service["backup"], "$.backup")
    backup_fields = {
        "required", "owner", "rpo_minutes", "rto_minutes", "destinations", "restore_test_required"
    }
    _exact_fields(backup, backup_fields, backup_fields, "$.backup")
    if not isinstance(backup["required"], bool) or not isinstance(backup["restore_test_required"], bool):
        raise ContractError("$.backup booleans are invalid")
    _string(backup["owner"], "$.backup.owner")
    _integer(backup["rpo_minutes"], "$.backup.rpo_minutes")
    _integer(backup["rto_minutes"], "$.backup.rto_minutes", minimum=1)
    destinations = _string_list(backup["destinations"], "$.backup.destinations")
    if backup["required"] and not destinations:
        raise ContractError("$.backup.destinations is required for stateful backup")
    if storage["stateful"] and not backup["required"]:
        raise ContractError("$.backup.required must be true for stateful services")

    rollback = _object(service["rollback"], "$.rollback")
    rollback_fields = {"strategy", "previous_approved_sha", "max_downtime_minutes", "steps"}
    _exact_fields(rollback, rollback_fields, rollback_fields, "$.rollback")
    _string(rollback["strategy"], "$.rollback.strategy")
    _sha(rollback["previous_approved_sha"], "$.rollback.previous_approved_sha")
    _integer(rollback["max_downtime_minutes"], "$.rollback.max_downtime_minutes", minimum=1)
    _string_list(rollback["steps"], "$.rollback.steps", nonempty=True)

    refs = _string_list(service["secret_refs"], "$.secret_refs")
    for index, ref in enumerate(refs):
        if not SECRET_REF_RE.fullmatch(ref):
            raise ContractError(f"$.secret_refs[{index}] must be an environment variable name")
    return service


DEPLOYMENT_FIELDS = {
    "schema_version", "service_id", "action", "approved_commit_sha", "source_clean",
    "host", "architecture", "manifest_digest", "image_digest", "catalogue_sha256",
    "started_at", "completed_at", "health", "actor",
}


def _validate_receipt_base(receipt: dict[str, Any], allowed: set[str]) -> None:
    _exact_fields(receipt, DEPLOYMENT_FIELDS, allowed, "$")
    if not SERVICE_RE.fullmatch(_string(receipt["service_id"], "$.service_id")):
        raise ContractError("$.service_id is invalid")
    _sha(receipt["approved_commit_sha"], "$.approved_commit_sha")
    if receipt["source_clean"] is not True:
        raise ContractError("$.source_clean must be true")
    if receipt["host"] not in HOSTS:
        raise ContractError("$.host is invalid")
    if receipt["architecture"] not in ARCHITECTURES:
        raise ContractError("$.architecture is invalid")
    _digest(receipt["manifest_digest"], "$.manifest_digest")
    _digest(receipt["image_digest"], "$.image_digest")
    if not re.fullmatch(r"[0-9a-f]{64}", _string(receipt["catalogue_sha256"], "$.catalogue_sha256")):
        raise ContractError("$.catalogue_sha256 is invalid")
    for key in ("started_at", "completed_at", "actor"):
        _string(receipt[key], f"$.{key}")
    health = _object(receipt["health"], "$.health")
    health_fields = {"liveness", "readiness", "user_flow"}
    _exact_fields(health, health_fields, health_fields, "$.health")
    for key in sorted(health_fields):
        if health[key] is not True:
            raise ContractError(f"$.health.{key} must be true")


def validate_deployment_receipt(raw: Any) -> dict[str, Any]:
    receipt = _object(raw, "$")
    _validate_receipt_base(receipt, DEPLOYMENT_FIELDS)
    if receipt["schema_version"] != "homeserver-deployment-receipt/v1" or receipt["action"] != "deploy":
        raise ContractError("deployment receipt schema/action is invalid")
    return receipt


def validate_rollback_receipt(raw: Any) -> dict[str, Any]:
    receipt = _object(raw, "$")
    extra = {"from_commit_sha", "to_commit_sha", "from_image_digest", "to_image_digest"}
    _validate_receipt_base(receipt, DEPLOYMENT_FIELDS | extra)
    _exact_fields(receipt, DEPLOYMENT_FIELDS | extra, DEPLOYMENT_FIELDS | extra, "$")
    if receipt["schema_version"] != "homeserver-rollback-receipt/v1" or receipt["action"] != "rollback":
        raise ContractError("rollback receipt schema/action is invalid")
    for key in ("from_commit_sha", "to_commit_sha"):
        _sha(receipt[key], f"$.{key}")
    for key in ("from_image_digest", "to_image_digest"):
        _digest(receipt[key], f"$.{key}")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("kind", choices=("service", "deployment-receipt", "rollback-receipt"))
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    raw = json.loads(args.path.read_text())
    validators = {
        "service": validate_service,
        "deployment-receipt": validate_deployment_receipt,
        "rollback-receipt": validate_rollback_receipt,
    }
    try:
        validators[args.kind](raw)
    except (ContractError, json.JSONDecodeError) as exc:
        print(f"FAIL: {exc}")
        return 1
    print(f"PASS: {args.kind} {args.path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
