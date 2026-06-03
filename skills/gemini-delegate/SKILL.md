---
name: gemini-delegate
description: Use when Codex should consult the local Gemini CLI for a second opinion, adversarial critique, architecture review, diff review, or a persistent side session in tmux. Trigger this skill when the user asks to talk to Gemini directly, wants model-diversity feedback, wants bounded overflow work routed to Gemini, or wants an isolated Gemini worker in a separate git worktree. Default to read-only consult mode; use the worker session only when Gemini must edit code outside Codex's active worktree.
---

# Gemini Delegate

## Overview

Use Gemini as an external model with explicit boundaries. Prefer one-shot read-only calls for advice and reviews; use tmux only when continuity matters, and use a separate git worktree for any write-capable Gemini session.

On this machine, the wrappers default to a safe MCP allowlist that excludes local Gemini servers known to break API requests, notably `magic` and legacy search MCPs; use native `colgrep` for semantic search.

## Workflow

1. Choose the safest mode first.
   - `consult`: one-shot, read-only analysis.
   - `review`: one-shot, read-only review of a diff.
   - `session`: persistent tmux consultant, usually read-only.
   - `worker-session`: persistent tmux worker in a separate git worktree.
2. Package only the context Gemini actually needs.
   - Include the concrete question, desired output, and the smallest useful file or diff slices.
   - Read [references/prompt-contract.md](references/prompt-contract.md) for the packaging and output contract.
3. Use the wrappers instead of inventing raw CLI flags.
   - `python3 ~/.codex/skills/gemini-delegate/scripts/gemini_consult.py ...`
   - `python3 ~/.codex/skills/gemini-delegate/scripts/gemini_review.py ...`
   - `python3 ~/.codex/skills/gemini-delegate/scripts/gemini_tmux_session.py ...`
   - `python3 ~/.codex/skills/gemini-delegate/scripts/gemini_worker_session.py ...`
4. Reintegrate deliberately.
   - Treat Gemini output as advisory unless the worker session changed files inside its own worktree.
   - Review any Gemini-authored diff before merging it back.

## Rules

- Default to `consult` or `review`.
- Do not let Gemini edit the same worktree Codex is using.
- Do not send secrets, tokens, customer data, or `.env` contents.
- Keep delegation bounded. If the prompt needs half the repo, keep the task in Codex.
- Use `worker-session` only for explicit parallel implementation or when Codex context/usage is tight and the handoff cost is low.
- If Gemini contradicts repo reality, trust the repo and re-scope the prompt.

## Scripts

- [scripts/gemini_consult.py](scripts/gemini_consult.py): headless read-only consultation with structured JSON output.
- [scripts/gemini_review.py](scripts/gemini_review.py): headless read-only review of a git diff or working tree.
- [scripts/gemini_tmux_session.py](scripts/gemini_tmux_session.py): detached tmux consultant session.
- [scripts/gemini_worker_session.py](scripts/gemini_worker_session.py): detached tmux worker session in a separate git worktree.
- [scripts/common.py](scripts/common.py): shared helpers and the main patch point if Gemini CLI invocation changes.

## References

- [references/prompt-contract.md](references/prompt-contract.md): prompt shape, response contract, and safety rules.
- [references/local-cli-notes.md](references/local-cli-notes.md): local Gemini CLI flags and assumptions inspected from the installed package.

## Examples

Read-only second opinion:

```bash
python3 ~/.codex/skills/gemini-delegate/scripts/gemini_consult.py \
  --cwd /path/to/repo \
  --context-file /path/to/repo/PLAN.md \
  --prompt "Argue against this migration plan and surface the top risks."
```

Read-only review of current changes:

```bash
python3 ~/.codex/skills/gemini-delegate/scripts/gemini_review.py \
  --cwd /path/to/repo \
  --base origin/main \
  --prompt "Focus on behavioral regressions and missing tests."
```

Persistent consultant thread:

```bash
python3 ~/.codex/skills/gemini-delegate/scripts/gemini_tmux_session.py \
  architecture-consult \
  --cwd /path/to/repo \
  --prompt "Challenge the planned caching strategy before implementation."
```

Persistent worker in an isolated worktree:

```bash
python3 ~/.codex/skills/gemini-delegate/scripts/gemini_worker_session.py \
  sidebar-refactor \
  --repo /path/to/repo \
  --prompt "Implement the sidebar refactor and summarize changed files and risks before stopping."
```
