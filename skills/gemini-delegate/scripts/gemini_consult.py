#!/usr/bin/env python3
from __future__ import annotations

import argparse
import textwrap

from common import (
    DEFAULT_ALLOWED_MCP,
    DEFAULT_TIMEOUT_SECONDS,
    emit_failure,
    find_binary,
    gemini_result_payload,
    load_context_blocks,
    parse_csv_or_repeated,
    print_json,
    read_prompt,
    resolve_cwd,
    run_command,
)


def build_prompt(task: str, context_blocks: list[str], stance: str, cwd: str) -> str:
    stance_instruction = {
        "balanced": "Balance criticism with practical recommendation.",
        "adversarial": "Actively challenge the proposed approach and prioritize what could fail.",
        "security": "Prioritize trust boundaries, input handling, auth, secrets, and abuse paths.",
        "performance": "Prioritize latency, throughput, scaling risks, and wasted work.",
    }[stance]
    context = "\n\n".join(context_blocks) if context_blocks else "No extra context provided."
    return textwrap.dedent(
        f"""\
        You are Gemini, acting as an external consultant to another coding agent.

        Mode: consult
        Working directory: {cwd}

        Task:
        {task}

        Constraints:
        - Treat this as read-only analysis.
        - Use only the context provided here; call out uncertainty when repo context is missing.
        - Do not ask for secrets or sensitive data.
        - {stance_instruction}

        Return exactly these Markdown sections:
        ## Recommendation
        ## Why
        ## Risks
        ## Open Questions
        ## Next Steps

        Context:
        {context}
        """
    ).strip()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a read-only Gemini consultation.")
    parser.add_argument("--cwd", help="Working directory for Gemini.")
    parser.add_argument("--prompt", help="Prompt text.")
    parser.add_argument("--prompt-file", help="File containing the prompt.")
    parser.add_argument(
        "--context-file",
        action="append",
        default=[],
        help="Additional context file to inline into the prompt. Repeatable.",
    )
    parser.add_argument(
        "--context",
        action="append",
        default=[],
        help="Additional inline context block. Repeatable.",
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
    parser.add_argument("--model", default="gemini-3.1-pro-preview", help="Gemini model override.")
    parser.add_argument(
        "--stance",
        choices=["balanced", "adversarial", "security", "performance"],
        default="balanced",
        help="Review stance.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="Timeout in seconds.",
    )
    parser.add_argument(
        "--max-context-chars-per-file",
        type=int,
        default=12000,
        help="Max characters to inline from each context file.",
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
        task = read_prompt(args.prompt, args.prompt_file)
        context_blocks = load_context_blocks(
            args.context_file,
            args.context,
            args.max_context_chars_per_file,
        )
        prompt = build_prompt(task, context_blocks, args.stance, str(cwd))
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
        for item in args.include_directory:
            command.extend(["--include-directories", item])
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
            mode="consult",
            cwd=cwd,
            prompt=prompt,
            command=command,
            result=result,
            dry_run=args.dry_run,
            extra={"stance": args.stance, "allowed_mcp_server_names": allowed_mcp},
        )
        print_json(payload)
    except Exception as exc:
        emit_failure("gemini_consult.py", str(exc), cwd=cwd)


if __name__ == "__main__":
    main()
