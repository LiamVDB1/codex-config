#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import textwrap
from pathlib import Path

from common import (
    DEFAULT_ALLOWED_MCP,
    DEFAULT_TIMEOUT_SECONDS,
    emit_failure,
    find_binary,
    gemini_result_payload,
    parse_csv_or_repeated,
    print_json,
    read_prompt,
    resolve_cwd,
    run_command,
    truncate,
)


def git_output(cwd: Path, args: list[str]) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or f"git {' '.join(args)} failed")
    return completed.stdout


def build_diff_bundle(cwd: Path, base: str | None, max_diff_chars: int) -> tuple[str, str, str]:
    inside_repo = git_output(cwd, ["rev-parse", "--is-inside-work-tree"]).strip()
    if inside_repo != "true":
        raise RuntimeError(f"{cwd} is not inside a git worktree.")
    if base:
        stat = git_output(cwd, ["diff", "--stat", "--find-renames", f"{base}...HEAD"])
        diff = git_output(
            cwd,
            ["diff", "--find-renames", "--unified=3", f"{base}...HEAD"],
        )
        label = f"{base}...HEAD"
    else:
        stat = git_output(cwd, ["diff", "--stat", "--find-renames", "HEAD"])
        diff = git_output(cwd, ["diff", "--find-renames", "--unified=3", "HEAD"])
        label = "HEAD"
    if not diff.strip():
        raise RuntimeError("No diff found for review.")
    truncated = False
    if len(diff) > max_diff_chars:
        diff = diff[:max_diff_chars] + f"\n\n[truncated after {max_diff_chars} chars]\n"
        truncated = True
    return label, stat, diff if not truncated else diff


def build_prompt(user_prompt: str, diff_target: str, stat: str, diff: str, cwd: str) -> str:
    return textwrap.dedent(
        f"""\
        You are Gemini, acting as a read-only reviewer for another coding agent.

        Mode: review
        Working directory: {cwd}
        Diff target: {diff_target}

        Review focus:
        {user_prompt}

        Constraints:
        - Review only. Do not propose speculative repo-wide rewrites.
        - Prioritize correctness, regressions, edge cases, and missing tests.
        - Use file paths and changed behavior as concrete anchors when possible.
        - If something is uncertain because context is missing, say so plainly.

        Return exactly these Markdown sections:
        ## Findings
        ## Risks
        ## Missing Tests
        ## Recommendation

        Diff stat:
        {stat or "[no diff stat available]"}

        Unified diff:
        {diff}
        """
    ).strip()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Gemini against a git diff.")
    parser.add_argument("--cwd", help="Git working directory.")
    parser.add_argument(
        "--base",
        help="Base ref for diff review. If omitted, review current changes against HEAD.",
    )
    parser.add_argument(
        "--prompt",
        help="Extra review instruction.",
    )
    parser.add_argument("--prompt-file", help="File containing extra review instruction.")
    parser.add_argument("--model", default="gemini-3.1-pro-preview", help="Gemini model override.")
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
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="Timeout in seconds.",
    )
    parser.add_argument(
        "--max-diff-chars",
        type=int,
        default=30000,
        help="Max diff characters to inline into the prompt.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the wrapped Gemini command without executing it.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cwd = resolve_cwd(args.cwd)
    try:
        if args.prompt or args.prompt_file:
            user_prompt = read_prompt(args.prompt, args.prompt_file)
        else:
            user_prompt = "Focus on bugs, regressions, and missing tests."
        diff_target, stat, diff = build_diff_bundle(cwd, args.base, args.max_diff_chars)
        prompt = build_prompt(user_prompt, diff_target, stat, diff, str(cwd))
        command = [
            find_binary(),
            "--approval-mode",
            "plan",
            "--output-format",
            "json",
            "--prompt",
            prompt,
        ]
        allowed_mcp = parse_csv_or_repeated(args.allowed_mcp_server_name)
        if allowed_mcp:
            command.extend(["--allowed-mcp-server-names", ",".join(allowed_mcp)])
        if args.model:
            command.extend(["--model", args.model])
        result = {
            "exit_code": 0,
            "stdout": "",
            "stderr": "",
            "duration_seconds": 0,
            "timed_out": False,
        }
        if not args.dry_run:
            result = run_command(command, cwd, args.timeout)
        payload = gemini_result_payload(
            mode="review",
            cwd=cwd,
            prompt=prompt,
            command=command,
            result=result,
            dry_run=args.dry_run,
            extra={
                "diff_target": diff_target,
                "diff_stat_preview": truncate(stat, 400),
                "allowed_mcp_server_names": allowed_mcp,
            },
        )
        print_json(payload)
    except Exception as exc:
        emit_failure("gemini_review.py", str(exc), cwd=cwd)


if __name__ == "__main__":
    main()
