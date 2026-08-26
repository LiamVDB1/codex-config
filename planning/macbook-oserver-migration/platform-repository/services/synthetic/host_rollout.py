#!/usr/bin/env python3
"""Deterministic per-host executor for the synthetic rollout ceremony.

Run on the target host against the durable clone. Every subcommand emits one
timestamped JSON receipt; no ad hoc shell commands participate in the proof.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import deployment  # noqa: E402
import git_provenance  # noqa: E402
import removal  # noqa: E402


CONTAINER = "homeserver-synthetic"
HEALTH_PATHS = {
    "liveness": "/healthz",
    "readiness": "/readyz",
    "user_flow": "/synthetic",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _run(command: list[str], *, timeout: int = 900) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, timeout=timeout)


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _repository_metadata() -> dict[str, Any]:
    """Read the canonical remote/branch/subdir from the running tooling tree."""
    return json.loads((Path(__file__).resolve().parents[2] / "repository.json").read_text())


def cmd_provenance(args: argparse.Namespace) -> int:
    repository = _repository_metadata()
    receipt = git_provenance.collect_git_provenance(
        args.clone,
        expected_remote=repository["canonical_remote"],
        allowed_branches=[repository["canonical_branch"], "codex/homeserver-platform"],
        source_subdir=repository["source_subdir"],
    )
    _write(args.output, receipt)
    print(f"provenance head={receipt['head']} clean={receipt['clean']}")
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    repository = _repository_metadata()
    provenance = git_provenance.collect_git_provenance(
        args.clone,
        expected_remote=repository["canonical_remote"],
        allowed_branches=[repository["canonical_branch"], "codex/homeserver-platform"],
        source_subdir=repository["source_subdir"],
    )
    if provenance["clean"] is not True:
        print("FAIL: refusing to build from a dirty clone")
        return 1
    server_arch = _run(
        ["docker", "version", "--format", "{{.Server.Architecture}}"]
    ).stdout.strip()
    derived_arch = {"amd64": "linux/amd64", "arm64": "linux/arm64"}.get(server_arch)
    if derived_arch is None:
        print(f"FAIL: unsupported server architecture {server_arch!r}")
        return 1
    if args.architecture != derived_arch:
        print(
            f"FAIL: claimed architecture {args.architecture} does not match "
            f"docker server architecture {derived_arch}"
        )
        return 1
    context = args.clone / repository["source_subdir"]
    tag = f"homeserver-synthetic:candidate-{provenance['head'][:12]}"
    result = _run(
        [
            "docker", "build",
            "--build-arg", f"SOURCE_COMMIT={provenance['head']}",
            "--build-arg", f"APP_VERSION={args.version}",
            "-f", str(context / "services/synthetic/Dockerfile"),
            "-t", tag,
            str(context / "services/synthetic"),
        ],
        timeout=1800,
    )
    if result.returncode != 0:
        tail = (result.stderr or result.stdout).strip().splitlines()[-5:]
        print("FAIL: docker build failed:\n" + "\n".join(tail))
        return 1
    image_id = _run(["docker", "image", "inspect", "--format", "{{.Id}}", tag]).stdout.strip()
    if not image_id.startswith("sha256:") or len(image_id) != 71:
        print(f"FAIL: built image id is malformed: {image_id!r}")
        return 1
    _write(
        args.output,
        {
            "schema_version": "homeserver-synthetic-build/v1",
            "architecture": args.architecture,
            "image_id": image_id,
            "tag": tag,
            "source_subdir_tree": provenance["subdir_tree"],
            "captured_at": _utc_now(),
        },
    )
    print(f"built {image_id}")
    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    approval = deployment.load_approval(args.approval)
    # Provenance is always re-derived from the live clone at plan time;
    # caller-supplied receipts are never trusted for an executable plan.
    repository = _repository_metadata()
    provenance = git_provenance.collect_git_provenance(
        args.clone,
        expected_remote=repository["canonical_remote"],
        allowed_branches=[repository["canonical_branch"], "codex/homeserver-platform"],
        source_subdir=repository["source_subdir"],
    )
    _write(args.out_dir / f"provenance-{args.host}.json", provenance)
    plan = deployment.build_runtime_plan(
        approval,
        host=args.host,
        architecture=args.architecture,
        provenance=provenance,
        verify_clone=args.clone,
        image_digest=args.image_digest,
        action=args.action,
    )
    _write(args.out_dir / f"plan-{args.host}-{args.action}.json", plan)
    print(f"plan {args.host}/{args.action} digest={plan['image_digest'][:20]}")
    return 0


def _capture_attestation(plan_path: Path, version: str) -> dict[str, Any]:
    plan = json.loads(plan_path.read_text())
    require_docker_healthy = plan.get("action") != "rollback"
    endpoints: dict[str, Any] = {}
    deadline = time.time() + 120
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            for key, path in HEALTH_PATHS.items():
                with urllib.request.urlopen(
                    f"http://127.0.0.1:18180{path}", timeout=2
                ) as response:
                    endpoints[key] = json.loads(response.read().decode())
            state = json.loads(_run(["docker", "inspect", CONTAINER]).stdout)[0]["State"]
            healthy = (state.get("Health") or {}).get("Status") == "healthy"
            if healthy or (not require_docker_healthy and state.get("Running")):
                break
            last_error = RuntimeError("runtime has not converged to its health contract yet")
        except (urllib.error.URLError, json.JSONDecodeError, OSError, KeyError) as exc:
            last_error = exc
        time.sleep(2)
    else:
        raise RuntimeError(f"health endpoints never became ready: {last_error}")

    inspect_result = _run(["docker", "inspect", CONTAINER])
    if inspect_result.returncode != 0:
        raise RuntimeError("docker inspect failed for the running container")
    inspect_payload = json.loads(inspect_result.stdout)

    errors = __import__("runtime_attestation").validate_runtime_attestation(
        inspect_payload, json.loads(plan_path.read_text()), endpoints, version
    )
    if errors:
        raise RuntimeError("runtime attestation failed: " + "; ".join(errors))

    return {"inspect": inspect_payload, "health": endpoints, "captured_at": _utc_now()}


def cmd_execute(args: argparse.Namespace) -> int:
    # Reconstruct the plan from authoritative inputs; a stored plan file is
    # never executed on trust.
    approval = deployment.load_approval(args.approval)
    repository = _repository_metadata()
    provenance = git_provenance.collect_git_provenance(
        args.clone,
        expected_remote=repository["canonical_remote"],
        allowed_branches=[repository["canonical_branch"], "codex/homeserver-platform"],
        source_subdir=repository["source_subdir"],
    )
    plan = deployment.build_runtime_plan(
        approval,
        host=args.host,
        architecture=args.architecture,
        provenance=provenance,
        image_digest=args.image_digest,
        action=args.action,
        verify_clone=args.clone,
    )
    _write(args.out_dir / f"plan-{args.host}-{args.action}.json", plan)
    existing = _run(["docker", "ps", "-a", "--filter", f"name=^{CONTAINER}$", "--format", "{{.ID}}"])
    if existing.stdout.strip():
        print("FAIL: managed container already exists")
        return 1
    started = _run(plan["command"])
    if started.returncode != 0:
        tail = (started.stderr or started.stdout).strip().splitlines()[-3:]
        print("FAIL: docker run failed:\n" + "\n".join(tail))
        return 1
    try:
        attestation = _capture_attestation(args.plan, args.version)
    except RuntimeError as exc:
        _run(plan["remove_command"])
        print(f"FAIL: {exc}")
        return 1
    _write(args.output, attestation)
    print(f"attested {plan['action']} on {plan['host']}")
    return 0


def cmd_remove(args: argparse.Namespace) -> int:
    plan = json.loads(args.plan.read_text())
    suffix = args.suffix
    live = _run(["docker", "inspect", CONTAINER])
    if live.returncode != 0:
        print("FAIL: container to remove is not running")
        return 1
    identity = removal.capture_removal_identity(json.loads(live.stdout), plan)
    _write(args.out_dir / f"removal-identity-{plan['host']}{suffix}.json", identity)

    removed = _run(plan["remove_command"])
    if removed.returncode != 0:
        print("FAIL: docker rm failed")
        return 1

    ps_probe = _run(
        ["docker", "ps", "-a", "--filter", f"name=^{CONTAINER}$", "--format", "{{.ID}}"]
    )
    if ps_probe.returncode != 0:
        print("FAIL: docker ps probe failed during absence verification")
        return 1
    ps_after = ps_probe.stdout.splitlines()
    inspect_after = _run(["docker", "inspect", CONTAINER])
    inspect_not_found = (
        inspect_after.returncode != 0
        and "no such object" in (inspect_after.stderr or "").lower()
    )
    try:
        absence = removal.verify_absence(
            ps_lines=ps_after,
            ps_probe_ok=ps_probe.returncode == 0,
            inspect_not_found=inspect_not_found,
            container_name=CONTAINER,
        )
    except removal.RemovalError as exc:
        print(f"FAIL: {exc}")
        return 1
    _write(args.out_dir / f"absence-proof-{plan['host']}{suffix}.json", absence)
    print(f"removed and proved absence on {plan['host']}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("provenance")
    p.add_argument("--clone", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.set_defaults(func=cmd_provenance)

    p = sub.add_parser("build")
    p.add_argument("--clone", type=Path, required=True)
    p.add_argument("--architecture", choices=sorted(deployment.HOST_ARCHITECTURES.values()), required=True)
    p.add_argument("--version", required=True)
    p.add_argument("--output", type=Path, required=True)
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("plan")
    p.add_argument("--approval", type=Path, required=True)
    p.add_argument("--clone", type=Path, required=True)
    p.add_argument("--host", required=True)
    p.add_argument("--architecture", required=True)
    p.add_argument("--image-digest", required=True)
    p.add_argument("--action", choices=("deploy", "rollback"), required=True)
    p.add_argument("--out-dir", type=Path, required=True)
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("execute")
    p.add_argument("--approval", type=Path, required=True)
    p.add_argument("--clone", type=Path, required=True)
    p.add_argument("--host", required=True)
    p.add_argument("--architecture", required=True)
    p.add_argument("--image-digest", required=True)
    p.add_argument("--action", choices=("deploy", "rollback"), required=True)
    p.add_argument("--version", required=True)
    p.add_argument("--out-dir", type=Path, required=True)
    p.set_defaults(func=cmd_execute)

    p = sub.add_parser("remove")
    p.add_argument("--plan", type=Path, required=True)
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--suffix", default="")
    p.set_defaults(func=cmd_remove)

    args = parser.parse_args()
    try:
        return args.func(args)
    except (deployment.DeploymentError, git_provenance.ProvenanceError, OSError, json.JSONDecodeError) as exc:
        print(f"FAIL: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
