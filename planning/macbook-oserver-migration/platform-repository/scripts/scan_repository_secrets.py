#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any


SCANNED_SUFFIXES = {".json", ".md", ".txt", ".yaml", ".yml", ".py", ".sh", ".toml", ".env"}
SENSITIVE_KEY = re.compile(
    r"(?:password|passwd|pwd|token|secret|api[_-]?key|apikey|authorization|cookie|private[_-]?key|access[_-]?key)",
    re.IGNORECASE,
)
SAFE_KEY_SUFFIXES = ("_ref", "_refs", "_file", "_path", "_enabled", "_required")
CREDENTIAL_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\btskey-[A-Za-z0-9_-]{20,}\b"),
)


def _json_findings(value: Any, path: Path, prefix: str = "$") -> list[tuple[str, str]]:
    findings: list[tuple[str, str]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = key.lower()
            if SENSITIVE_KEY.search(key) and not normalized.endswith(SAFE_KEY_SUFFIXES):
                findings.append((str(path), key))
            findings.extend(_json_findings(child, path, f"{prefix}.{key}"))
    elif isinstance(value, list):
        for child in value:
            findings.extend(_json_findings(child, path, prefix))
    return findings


def _files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    return sorted(item for item in path.rglob("*") if item.is_file())


def scan_path(path: Path) -> list[tuple[str, str]]:
    findings: list[tuple[str, str]] = []
    for item in _files(path):
        if item.suffix.lower() not in SCANNED_SUFFIXES:
            continue
        text = item.read_text(errors="replace")
        for pattern in CREDENTIAL_PATTERNS:
            if pattern.search(text):
                findings.append((str(item), "credential-pattern"))
        if item.suffix.lower() != ".json" or item.name.endswith(".schema.json"):
            continue
        try:
            raw = json.loads(text)
        except json.JSONDecodeError:
            findings.append((str(item), "invalid-json"))
            continue
        findings.extend(_json_findings(raw, item))
    return findings


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: scan_repository_secrets.py PATH [...]", file=sys.stderr)
        return 2
    findings: list[tuple[str, str]] = []
    for raw_path in argv:
        findings.extend(scan_path(Path(raw_path)))
    for path, key in findings:
        print(f"{path}:{key}")
    if findings:
        print(f"FAIL: {len(findings)} secret-like location(s); values withheld")
        return 1
    print("PASS: no secret values detected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
