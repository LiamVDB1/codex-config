#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re


HOSTS = {
    "homeserver": {"architecture": "linux/amd64", "target": "/srv/homeserver/repo"},
    "oserver": {"architecture": "linux/arm64", "target": "/home/opc/server-platform"},
}
REMOTE = "https://github.com/LiamVDB1/codex-config.git"
SUBDIR = "planning/macbook-oserver-migration/platform-repository"


def build_plan(host: str, approved_sha: str, *, target: str) -> dict:
    if host not in HOSTS:
        raise ValueError("unknown host")
    if not re.fullmatch(r"[0-9a-f]{40}", approved_sha):
        raise ValueError("approved SHA must be a 40-character lowercase Git SHA")
    expected = HOSTS[host]
    if target != expected["target"]:
        raise ValueError(f"target must be the approved durable path {expected['target']}")
    return {
        "schema_version": "homeserver-bootstrap-plan/v1",
        "dry_run": True,
        "host": host,
        "architecture": expected["architecture"],
        "target": target,
        "repository": REMOTE,
        "source_subdir": SUBDIR,
        "approved_sha": approved_sha,
        "preconditions": [
            "target absent or matching git origin",
            "approved commit reachable",
            "no secret values in repository",
            "no live deployment authority replaced",
        ],
        "actions": [
            "create durable parent directory",
            "clone or fetch canonical repository",
            "checkout approved commit detached",
            "enable sparse checkout for platform source subdirectory",
            "run repository validator",
            "write deployment-clone receipt",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", required=True, choices=sorted(HOSTS))
    parser.add_argument("--approved-sha", required=True)
    parser.add_argument("--target", required=True)
    args = parser.parse_args()
    try:
        plan = build_plan(args.host, args.approved_sha, target=args.target)
    except ValueError as exc:
        print(f"FAIL: {exc}")
        return 1
    print(json.dumps(plan, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
