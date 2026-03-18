#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from common import (
    DEFAULT_ALLOWED_MCP,
    build_command_display,
    emit_failure,
    find_binary,
    parse_csv_or_repeated,
    print_json,
    require_command,
    resolve_cwd,
)


def tmux_session_exists(session_name: str) -> bool:
    completed = subprocess.run(
        ["tmux", "has-session", "-t", session_name],
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.returncode == 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start a detached Gemini tmux session.")
    parser.add_argument("session_name", help="tmux session name.")
    parser.add_argument("--cwd", help="Working directory for the session.")
    parser.add_argument("--prompt", help="Initial prompt.")
    parser.add_argument("--prompt-file", help="File containing the initial prompt.")
    parser.add_argument("--model", default="gemini-3.1-pro-preview", help="Gemini model override.")
    parser.add_argument(
        "--approval-mode",
        choices=["default", "auto_edit", "yolo", "plan"],
        default="plan",
        help="Gemini approval mode inside tmux.",
    )
    parser.add_argument(
        "--resume",
        nargs="?",
        const="latest",
        help="Resume an existing Gemini session. Pass no value for latest.",
    )
    parser.add_argument(
        "--include-directory",
        action="append",
        default=[],
        help="Extra workspace directory for Gemini. Repeatable.",
    )
    parser.add_argument(
        "--allowed-mcp-server-name",
        action="append",
        default=[DEFAULT_ALLOWED_MCP],
        help=(
            "Allowed MCP server names. Repeatable or comma-separated. "
            "Defaults to a safe allowlist that excludes known-broken local servers."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print tmux and Gemini commands without executing them.",
    )
    return parser.parse_args()


def read_optional_prompt(prompt: str | None, prompt_file: str | None) -> str | None:
    if prompt and prompt_file:
        raise RuntimeError("Use either --prompt or --prompt-file, not both.")
    if prompt_file:
        return Path(prompt_file).expanduser().read_text()
    return prompt


def main() -> None:
    args = parse_args()
    cwd = resolve_cwd(args.cwd)
    try:
        require_command("tmux")
        if tmux_session_exists(args.session_name):
            raise RuntimeError(f"tmux session already exists: {args.session_name}")
        prompt = read_optional_prompt(args.prompt, args.prompt_file)
        gemini_command = [
            find_binary(),
            "--approval-mode",
            args.approval_mode,
        ]
        allowed_mcp = parse_csv_or_repeated(args.allowed_mcp_server_name)
        if allowed_mcp:
            gemini_command.extend(["--allowed-mcp-server-names", ",".join(allowed_mcp)])
        if args.model:
            gemini_command.extend(["--model", args.model])
        if args.resume:
            gemini_command.extend(["--resume", args.resume])
        for item in args.include_directory:
            gemini_command.extend(["--include-directories", item])
        if prompt:
            gemini_command.extend(["--prompt-interactive", prompt])
        tmux_command = [
            "tmux",
            "new-session",
            "-d",
            "-s",
            args.session_name,
            "-c",
            str(cwd),
            build_command_display(gemini_command),
        ]
        if not args.dry_run:
            completed = subprocess.run(
                tmux_command,
                capture_output=True,
                text=True,
                check=False,
            )
            if completed.returncode != 0:
                raise RuntimeError(completed.stderr.strip() or "tmux new-session failed")
        print_json(
            {
                "ok": True,
                "mode": "session",
                "dry_run": args.dry_run,
                "cwd": str(cwd),
                "session_name": args.session_name,
                "allowed_mcp_server_names": allowed_mcp,
                "attach_command": f"tmux attach -t {args.session_name}",
                "gemini_command": gemini_command,
                "gemini_command_display": build_command_display(gemini_command),
                "tmux_command": tmux_command,
                "tmux_command_display": build_command_display(tmux_command),
            }
        )
    except Exception as exc:
        emit_failure(
            "gemini_tmux_session.py",
            str(exc),
            cwd=cwd,
            extra={"session_name": args.session_name},
        )


if __name__ == "__main__":
    main()
