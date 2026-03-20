#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Iterable

DEFAULT_TIMEOUT_SECONDS = int(os.environ.get("GEMINI_DELEGATE_TIMEOUT", "180"))
DEFAULT_BINARY_ENV = "GEMINI_DELEGATE_BINARY"
DEFAULT_ALLOWED_MCP = os.environ.get(
    "GEMINI_DELEGATE_ALLOWED_MCP",
    "context7,memory,sequential-thinking,stitch",
)


def ensure_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def find_binary() -> str:
    binary = os.environ.get(DEFAULT_BINARY_ENV) or shutil.which("gemini")
    if not binary:
        raise RuntimeError(
            "Gemini CLI not found. Install `gemini` or set GEMINI_DELEGATE_BINARY."
        )
    return binary


def require_command(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise RuntimeError(f"Required command not found: {name}")
    return path


def resolve_cwd(raw_cwd: str | None) -> Path:
    return Path(raw_cwd or os.getcwd()).expanduser().resolve()


def parse_csv_or_repeated(values: Iterable[str]) -> list[str]:
    parsed: list[str] = []
    for value in values:
        for item in value.split(","):
            stripped = item.strip()
            if stripped:
                parsed.append(stripped)
    return parsed


def read_prompt(prompt: str | None, prompt_file: str | None) -> str:
    if prompt and prompt_file:
        raise RuntimeError("Use either --prompt or --prompt-file, not both.")
    if prompt_file:
        return Path(prompt_file).expanduser().read_text()
    if prompt:
        return prompt
    if not sys.stdin.isatty():
        piped = sys.stdin.read()
        if piped.strip():
            return piped
    raise RuntimeError("No prompt provided. Use --prompt, --prompt-file, or stdin.")


def load_context_blocks(
    context_files: Iterable[str],
    inline_context: Iterable[str],
    max_chars_per_file: int,
) -> list[str]:
    blocks: list[str] = []
    for index, item in enumerate(inline_context, start=1):
        blocks.append(f"Inline context {index}:\n{item.strip()}")
    for item in context_files:
        path = Path(item).expanduser().resolve()
        text = path.read_text()
        if len(text) > max_chars_per_file:
            text = (
                text[:max_chars_per_file]
                + f"\n\n[truncated after {max_chars_per_file} chars]"
            )
        blocks.append(f"File: {path}\n{text}")
    return blocks


def build_command_display(command: Iterable[str]) -> str:
    return shlex.join(list(command))


def run_command(
    command: list[str],
    cwd: Path,
    timeout_seconds: int,
    extra_env: dict[str, str] | None = None,
) -> dict[str, Any]:
    started = time.monotonic()
    env = os.environ.copy()
    env.setdefault("NO_COLOR", "1")
    if extra_env:
        env.update(extra_env)
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        duration = round(time.monotonic() - started, 3)
        return {
            "exit_code": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "duration_seconds": duration,
            "timed_out": False,
        }
    except subprocess.TimeoutExpired as exc:
        duration = round(time.monotonic() - started, 3)
        stderr = ensure_text(exc.stderr)
        stderr += f"\nTimed out after {timeout_seconds} seconds.\n"
        return {
            "exit_code": 124,
            "stdout": ensure_text(exc.stdout),
            "stderr": stderr,
            "duration_seconds": duration,
            "timed_out": True,
        }


def parse_json_output(stdout: str | bytes) -> dict[str, Any] | None:
    try:
        payload = json.loads(ensure_text(stdout))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def truncate(text: str, limit: int = 280) -> str:
    stripped = text.strip()
    if len(stripped) <= limit:
        return stripped
    return stripped[:limit] + "..."


def print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def emit_failure(
    script: str,
    message: str,
    *,
    cwd: Path | None = None,
    extra: dict[str, Any] | None = None,
    exit_code: int = 1,
) -> None:
    payload: dict[str, Any] = {
        "ok": False,
        "script": script,
        "error": message,
    }
    if cwd is not None:
        payload["cwd"] = str(cwd)
    if extra:
        payload.update(extra)
    print_json(payload)
    raise SystemExit(exit_code)


def gemini_result_payload(
    *,
    mode: str,
    cwd: Path,
    prompt: str,
    command: list[str],
    result: dict[str, Any],
    dry_run: bool,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    stdout = ensure_text(result.get("stdout", ""))
    stderr = ensure_text(result.get("stderr", ""))
    parsed = parse_json_output(stdout)
    response = ""
    if parsed and isinstance(parsed.get("response"), str):
        response = parsed["response"]
    elif stdout:
        response = stdout
    payload: dict[str, Any] = {
        "ok": result.get("exit_code", 1) == 0 and not result.get("timed_out", False),
        "mode": mode,
        "cwd": str(cwd),
        "dry_run": dry_run,
        "command": command,
        "command_display": build_command_display(command),
        "prompt_preview": truncate(prompt),
        "exit_code": result.get("exit_code", 1),
        "duration_seconds": result.get("duration_seconds", 0),
        "timed_out": result.get("timed_out", False),
        "stdout": stdout,
        "stderr": stderr,
        "gemini_json": parsed,
        "response_text": response,
    }
    if extra:
        payload.update(extra)
    return payload
