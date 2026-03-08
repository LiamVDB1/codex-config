#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import textwrap
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


def git_output(repo: Path, args: list[str]) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or f"git {' '.join(args)} failed")
    return completed.stdout.strip()


def tmux_session_exists(session_name: str) -> bool:
    completed = subprocess.run(
        ["tmux", "has-session", "-t", session_name],
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.returncode == 0


def branch_exists(repo: Path, branch_name: str) -> bool:
    completed = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--verify", branch_name],
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.returncode == 0


def build_initial_prompt(user_prompt: str, repo_root: Path, worktree: Path) -> str:
    return textwrap.dedent(
        f"""\
        You are Gemini, running as an isolated worker in a dedicated git worktree.

        Repo root: {repo_root}
        Worktree: {worktree}

        Task:
        {user_prompt}

        Constraints:
        - Work only inside this dedicated worktree.
        - Keep the scope bounded to the stated task.
        - Do not read or reveal secrets, tokens, or .env contents.
        - Summarize changed files, remaining risks, and recommended validation before stopping.
        """
    ).strip()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Start an isolated Gemini worker session in a git worktree."
    )
    parser.add_argument("session_name", help="tmux session name.")
    parser.add_argument("--repo", help="Git repository path. Defaults to current directory.")
    parser.add_argument("--worktree", help="Explicit worktree path.")
    parser.add_argument("--branch", help="Branch name. Defaults to gemini/<session-name>.")
    parser.add_argument("--prompt", help="Initial worker prompt.")
    parser.add_argument("--prompt-file", help="File containing the initial worker prompt.")
    parser.add_argument("--model", help="Gemini model override.")
    parser.add_argument(
        "--approval-mode",
        choices=["default", "auto_edit", "yolo", "plan"],
        default="auto_edit",
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
        "--reuse-existing",
        action="store_true",
        help="Reuse an existing worktree path if it already exists.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print git, tmux, and Gemini commands without executing them.",
    )
    return parser.parse_args()


def read_optional_prompt(prompt: str | None, prompt_file: str | None) -> str:
    if prompt and prompt_file:
        raise RuntimeError("Use either --prompt or --prompt-file, not both.")
    if prompt_file:
        return Path(prompt_file).expanduser().read_text()
    if prompt:
        return prompt
    raise RuntimeError("Worker session requires --prompt or --prompt-file.")


def main() -> None:
    args = parse_args()
    repo = resolve_cwd(args.repo)
    try:
        require_command("git")
        require_command("tmux")
        if tmux_session_exists(args.session_name):
            raise RuntimeError(f"tmux session already exists: {args.session_name}")
        repo_root = Path(git_output(repo, ["rev-parse", "--show-toplevel"]))
        branch_name = args.branch or f"gemini/{args.session_name}"
        worktree = (
            Path(args.worktree).expanduser().resolve()
            if args.worktree
            else repo_root / ".codex-gemini" / "worktrees" / args.session_name
        )
        prompt = build_initial_prompt(
            read_optional_prompt(args.prompt, args.prompt_file),
            repo_root,
            worktree,
        )
        if worktree.exists() and not args.reuse_existing:
            raise RuntimeError(
                f"Worktree path already exists: {worktree}. Use --reuse-existing to reuse it."
            )
        worktree_command: list[str]
        if worktree.exists():
            worktree_command = []
        else:
            if branch_exists(repo_root, branch_name):
                worktree_command = [
                    "git",
                    "-C",
                    str(repo_root),
                    "worktree",
                    "add",
                    str(worktree),
                    branch_name,
                ]
            else:
                worktree_command = [
                    "git",
                    "-C",
                    str(repo_root),
                    "worktree",
                    "add",
                    "-b",
                    branch_name,
                    str(worktree),
                    "HEAD",
                ]
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
        gemini_command.extend(["--prompt-interactive", prompt])
        tmux_command = [
            "tmux",
            "new-session",
            "-d",
            "-s",
            args.session_name,
            "-c",
            str(worktree),
            build_command_display(gemini_command),
        ]
        if not args.dry_run:
            worktree.parent.mkdir(parents=True, exist_ok=True)
            if worktree_command:
                completed = subprocess.run(
                    worktree_command,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if completed.returncode != 0:
                    raise RuntimeError(
                        completed.stderr.strip() or "git worktree add failed"
                    )
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
                "mode": "worker-session",
                "dry_run": args.dry_run,
                "repo_root": str(repo_root),
                "worktree": str(worktree),
                "branch_name": branch_name,
                "session_name": args.session_name,
                "allowed_mcp_server_names": allowed_mcp,
                "attach_command": f"tmux attach -t {args.session_name}",
                "worktree_command": worktree_command,
                "worktree_command_display": build_command_display(worktree_command)
                if worktree_command
                else "",
                "gemini_command": gemini_command,
                "gemini_command_display": build_command_display(gemini_command),
                "tmux_command": tmux_command,
                "tmux_command_display": build_command_display(tmux_command),
            }
        )
    except Exception as exc:
        emit_failure(
            "gemini_worker_session.py",
            str(exc),
            cwd=repo,
            extra={"session_name": args.session_name},
        )


if __name__ == "__main__":
    main()
