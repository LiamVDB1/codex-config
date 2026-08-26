#!/usr/bin/env python3
"""Validate the relational integrity of one synthetic rollout receipt bundle.

The chain binds measured provenance, native build digests, the approval, per
host deploy/rollback plans and attestations, and removal identity plus absence
proof into one ordered, cross-checked lifecycle. Every timestamp is ISO-8601 Z
and strictly ordered; every relation is checked against both endpoints; every
file is secret-scanned.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from deployment import HOST_ARCHITECTURES, load_approval  # noqa: E402
import runtime_attestation  # noqa: E402
import scan_repository_secrets  # noqa: E402


TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")


class ChainError(ValueError):
    pass


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ChainError(f"{path.name} cannot be loaded: {exc}") from exc


def _ts(value: Any, label: str) -> str:
    if not isinstance(value, str) or not TS_RE.fullmatch(value):
        raise ChainError(f"{label}.captured_at is not an ISO-8601 UTC Z timestamp")
    return value


def _check_inspect_matches_plan(inspect_payload: Any, plan: dict[str, Any]) -> None:
    if not isinstance(inspect_payload, list) or len(inspect_payload) != 1:
        raise ChainError("attestation inspect payload must contain exactly one container")
    inspect = inspect_payload[0]
    if not isinstance(inspect, dict):
        raise ChainError("attestation inspect container must be an object")
    if inspect.get("Image") != plan.get("image_digest"):
        raise ChainError("attested image does not match the plan digest")
    labels = (inspect.get("Config") or {}).get("Labels") or {}
    if labels.get("homeserver.source_commit") != plan.get("source_commit_sha"):
        raise ChainError("attested source commit does not match the plan")
    if labels.get("homeserver.action") != plan.get("action"):
        raise ChainError("attested action label does not match the plan")


def validate_bundle(bundle: Path, *, version: str, rollback_version: str) -> dict[str, Any]:
    errors: list[str] = []
    hosts = sorted(HOST_ARCHITECTURES)
    arch_by_host = HOST_ARCHITECTURES

    approval_path = bundle / "approval.json"
    approval = load_approval(approval_path)

    def read(name: str) -> Any:
        path = bundle / name
        if not path.is_file():
            raise ChainError(f"missing receipt: {name}")
        return _load(path)

    stage_stamps: list[tuple[str, str]] = []

    def stamp(label: str, value: Any) -> str:
        parsed = _ts(value, label)
        stage_stamps.append((label, parsed))
        return parsed

    provenance_by_host: dict[str, dict[str, Any]] = {}
    subtree_by_host: dict[str, str] = {}
    for host in hosts:
        provenance = read(f"provenance-{host}.json")
        if provenance.get("clean") is not True:
            errors.append(f"{host} provenance is not clean")
        if provenance.get("head") != approval["source_commit_sha"]:
            errors.append(f"{host} provenance head does not match approved commit")
        tree = provenance.get("subdir_tree")
        if not isinstance(tree, str) or len(tree) != 40:
            errors.append(f"{host} provenance lacks a bound source subtree")
        else:
            subtree_by_host[host] = tree
        stamp(f"provenance/{host}", provenance.get("captured_at"))
        provenance_by_host[host] = provenance
    if len(set(subtree_by_host.values())) > 1:
        errors.append("hosts disagree on the bound source subtree hash")

    builds: dict[str, dict[str, Any]] = {}
    for architecture in sorted(HOST_ARCHITECTURES.values()):
        build = read(f"build-{architecture.replace('/', '_')}.json")
        if build.get("image_id") != approval["platform_digests"][architecture]:
            errors.append(f"build {architecture} image id does not match approved digest")
        if build.get("schema_version") != "homeserver-synthetic-build/v1":
            errors.append(f"build {architecture} schema is unsupported")
        if subtree_by_host and build.get("source_subdir_tree") not in set(
            subtree_by_host.values()
        ):
            errors.append(f"build {architecture} subtree does not match the measured provenance")
        stamp(f"build/{architecture}", build.get("captured_at"))
        builds[architecture] = build

    last_stamp: dict[str, str] = {}
    for host in hosts:
        architecture = arch_by_host[host]
        actions = [
            ("deploy", approval["source_commit_sha"], approval["platform_digests"][architecture]),
            ("recover", approval["source_commit_sha"], approval["platform_digests"][architecture]),
            ("rollback", approval["previous_approved_sha"], approval["rollback_platform_digests"][architecture]),
        ]
        preroll_stamp = None
        for action, stage_commit, stage_digest in actions:
            if action == "recover":
                # Stateless recovery re-runs the approved deploy plan after an
                # identity-checked removal whose own receipts are required and
                # strictly ordered against this stage's attestation.
                plan = read(f"plan-{host}-deploy.json")
                rec_identity = read(f"removal-identity-{host}-recover.json")
                if rec_identity.get("schema_version") != "homeserver-synthetic-removal-identity/v1":
                    errors.append(f"{host}: recovery removal schema is unsupported")
                if rec_identity.get("container_name") != "homeserver-synthetic":
                    errors.append(f"{host}: recovery removal names the wrong container")
                if rec_identity.get("action") != "deploy":
                    errors.append(f"{host}: recovery removal action does not match the deploy plan")
                if rec_identity.get("image_digest") != approval["platform_digests"][architecture]:
                    errors.append(f"{host}: recovery removal is not the deployed runtime")
                if rec_identity.get("source_commit_sha") != approval["source_commit_sha"]:
                    errors.append(f"{host}: recovery removal is not the deployed commit")
                rec_id_time = stamp(f"removal-identity/{host}-recover", rec_identity.get("captured_at"))
                rec_absence = read(f"absence-proof-{host}-recover.json")
                if rec_absence.get("ps_matches") != 0 or rec_absence.get("inspect_not_found") is not True:
                    errors.append(f"{host}: recovery absence proof does not prove emptiness")
                rec_ab_time = stamp(f"absence/{host}-recover", rec_absence.get("captured_at"))
                if rec_ab_time <= rec_id_time:
                    errors.append(f"{host}: recovery absence does not follow recovery removal")
                # The recovery attestation that follows must come after this
                # fence; raise the per-host floor to the absence timestamp.
                last_stamp[host] = rec_ab_time
            else:
                plan = read(f"plan-{host}-{action}.json")
                commit_field = "source_commit_sha" if action == "deploy" else "previous_approved_sha"
                digest_field = "platform_digests" if action == "deploy" else "rollback_platform_digests"
                if plan.get("action") != action or plan.get("host") != host:
                    errors.append(f"plan-{host}-{action} identity fields are inconsistent")
                if plan.get("source_commit_sha") != approval[commit_field]:
                    errors.append(f"plan-{host}-{action} binds the wrong approved commit")
                if plan.get("image_digest") != approval[digest_field][architecture]:
                    errors.append(f"plan-{host}-{action} binds the wrong approved digest")
                if action == "deploy" and plan.get("provenance_subdir_tree") != subtree_by_host.get(host):
                    errors.append(f"plan-{host}-deploy does not bind the measured source subtree")

            attest_name = f"attest-{host}-{action}.json"
            attest = read(attest_name)
            health = attest.get("health")
            expected_version = rollback_version if action == "rollback" else version
            endpoint_errors = runtime_attestation.validate_runtime_attestation(
                attest.get("inspect"), plan, health if isinstance(health, dict) else {}, expected_version
            )
            errors.extend(f"{host}/{action}: {item}" for item in endpoint_errors)
            _check_inspect_matches_plan(attest.get("inspect"), plan)
            if attest.get("inspect", [{}])[0].get("Image") != stage_digest:
                errors.append(f"{host}/{action}: attested image is not the staged digest")

            if action == "rollback" and preroll_stamp is None:
                pre_id = read(f"removal-identity-{host}-prerollback.json")
                if pre_id.get("schema_version") != "homeserver-synthetic-removal-identity/v1":
                    errors.append(f"{host}: pre-rollback removal schema is unsupported")
                if pre_id.get("container_name") != "homeserver-synthetic":
                    errors.append(f"{host}: pre-rollback removal names the wrong container")
                if pre_id.get("action") != "deploy":
                    errors.append(f"{host}: pre-rollback removal action does not match the deploy plan")
                if pre_id.get("image_digest") != approval["platform_digests"][architecture]:
                    errors.append(f"{host}: pre-rollback removal is not the deployed runtime")
                if pre_id.get("source_commit_sha") != approval["source_commit_sha"]:
                    errors.append(f"{host}: pre-rollback removal is not the deployed commit")
                pre_id_time = stamp(f"removal-identity/{host}-prerollback", pre_id.get("captured_at"))
                pre_ab = read(f"absence-proof-{host}-prerollback.json")
                if pre_ab.get("ps_matches") != 0 or pre_ab.get("inspect_not_found") is not True:
                    errors.append(f"{host}: pre-rollback absence proof does not prove emptiness")
                pre_ab_time = stamp(f"absence/{host}-prerollback", pre_ab.get("captured_at"))
                if pre_ab_time <= pre_id_time:
                    errors.append(f"{host}: pre-rollback absence does not follow removal")
                if pre_id_time < last_stamp.get(host, ""):
                    errors.append(f"{host}: pre-rollback fence precedes earlier stages")
                preroll_stamp = pre_ab_time
            plan_time = stamp(f"plan-{host}-{action}", plan.get("captured_at"))
            attest_time = stamp(f"attest-{host}-{action}", attest.get("captured_at"))
            previous = last_stamp.get(host)
            if previous and plan_time < previous and action == "deploy":
                errors.append(f"{host}: plan timestamp moves backwards before {action}")
            gate = max(filter(None, [plan_time, previous]))
            if attest_time <= gate:
                errors.append(f"{host}/{action}: attestation does not follow its plan and prior stages")
            if action == "rollback":
                # The fence that removed the recovered runtime must sit between
                # the recovery attestation and the rollback attestation.
                if preroll_stamp is None or not (
                    last_stamp.get(host, "") < preroll_stamp <= attest_time
                ):
                    errors.append(
                        f"{host}: pre-rollback fence receipts are missing or out of order"
                    )
            last_stamp[host] = attest_time

        identity = read(f"removal-identity-{host}.json")
        absence = read(f"absence-proof-{host}.json")
        if identity.get("schema_version") != "homeserver-synthetic-removal-identity/v1":
            errors.append(f"{host}: final removal schema is unsupported")
        if identity.get("container_name") != "homeserver-synthetic":
            errors.append(f"{host}: final removal names the wrong container")
        if identity.get("action") != "rollback":
            errors.append(f"{host}: final removal action does not match the rollback plan")
        if absence.get("schema_version") != "homeserver-synthetic-absence-proof/v1":
            errors.append(f"{host}: absence proof schema is unsupported")
        if absence.get("container_name") != "homeserver-synthetic":
            errors.append(f"{host}: absence proof names the wrong container")
        if absence.get("inspect_not_found") is not True:
            errors.append(f"{host}: absence proof must record docker no-such-object evidence")
        identity_time = stamp(f"removal-identity/{host}", identity.get("captured_at"))
        absence_time = stamp(f"absence/{host}", absence.get("captured_at"))
        if identity.get("image_digest") != approval["rollback_platform_digests"][architecture]:
            errors.append(f"{host}: removed identity is not the rollback runtime")
        if identity.get("source_commit_sha") != approval["previous_approved_sha"]:
            errors.append(f"{host}: removed identity is not the rollback commit")

        if identity_time < last_stamp[host]:
            errors.append(f"{host}: removal identity does not follow the final attestation")
        if absence_time < identity_time:
            errors.append(f"{host}: absence proof does not follow removal identity")

    findings = scan_repository_secrets.scan_path(bundle)
    for path, key in findings:
        errors.append(f"secret-scan: {Path(path).name}:{key}")

    if errors:
        raise ChainError("; ".join(errors))

    return {
        "bundle": str(bundle),
        "version": version,
        "rollback_version": rollback_version,
        "receipts_checked": len(stage_stamps),
        "approval_commit": approval["source_commit_sha"],
        "rollback_commit": approval["previous_approved_sha"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate one synthetic rollout receipt bundle")
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--rollback-version", required=True)
    args = parser.parse_args()
    try:
        summary = validate_bundle(args.bundle, version=args.version, rollback_version=args.rollback_version)
    except (ChainError, OSError) as exc:
        print(f"FAIL: {exc}")
        return 1
    print(json.dumps(summary, indent=2, sort_keys=True))
    print("PASS: receipt chain is complete, ordered, related and secret-free")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
