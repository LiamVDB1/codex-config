## Global Working Defaults

This file defines Liam's global Codex defaults across repositories. Keep it lean. Project-specific behavior belongs in the repo's own `AGENTS.md` or skills.

## Core Operating Style

- Be pragmatic, direct, and evidence-driven.
- Read the codebase before making architectural assumptions.
- Clarify material ambiguity early when the answer changes the implementation; otherwise make a conservative assumption and continue.
- For non-trivial work, separate exploration from execution: map the existing system, summarize the plan, then implement.
- Prefer native `/goal` for long-running implementation with a verifiable stopping condition.
- For large work, create or maintain a compact spec before `/goal`: objective, non-goals, invariants, affected surfaces, acceptance checks, and deferred items.
- Do not recreate Claude-style top-down orchestration by default. Use subagents selectively to isolate context, not to manage every implementation task.

## Subagent Policy

Use subagents when a bounded task benefits from a fresh context window or independent judgment:

- `explorer`: map unfamiliar code, find relevant files, summarize architecture, or gather evidence without polluting the main thread.
- `reviewer`: inspect a diff or risky surface after implementation; focus on bugs, regressions, and missing tests.
- `security_reviewer`: review auth, secrets, user input, API boundaries, shell/file/network/database access, payments, or other trust boundaries.
- `build_fixer`: isolate build, typecheck, lint, dependency, or test-environment failures.
- Model-diverse consults: use one consultant when architecture, product direction, or risk tradeoffs are unclear and a second opinion is worth the context/cost.

Do not use subagents merely because a task is large. Prefer one `/goal` agent for cohesive implementation. Split into parallel branches/specs only when the work is independently mergeable.

## SecondBrain

`~/SecondBrain/` is Liam's durable personal knowledge vault. Use it as a first-class source when the question is about Liam, his work, projects, preferences, history, tools, courses, or prior decisions.

- Query SecondBrain before answering from memory on those topics.
- Start with `~/SecondBrain/index.md` when locating candidate pages, then follow relevant wikilinks.
- Cite SecondBrain pages inline with `[[Page]]` when using them.
- When durable knowledge surfaces in chat, offer to file it in SecondBrain; do not silently store it.
- If working inside `~/SecondBrain/`, read its local instructions first. Its `raw/` area is read-only unless the user explicitly says otherwise.

## Local Environment

Docker often runs on the remote `oserver` context, not locally. Before connecting to containerized services via localhost, open the needed tunnel with `tunnel <port>`.

- Example: `tunnel 7234` for Truth Engine Postgres, `tunnel 7233` for Temporal.
- From a non-interactive shell, use `bash -lc 'tunnel <port>'`.
- If localhost refuses a DB/service connection but `docker compose exec` works, the missing tunnel is the likely issue.

## Security Baseline

Before finalizing code changes:

- No hardcoded secrets, API keys, tokens, or passwords.
- Validate untrusted input.
- Prevent SQL, command, template, and path injection risks.
- Prevent XSS when rendering HTML/content.
- Ensure authn/authz checks are correct where relevant.
- Ensure endpoints handling user traffic have a rate-limit strategy.
- Avoid leaking sensitive internals in error messages.

Secret handling pattern:

```ts
const apiKey = process.env.OPENAI_API_KEY
if (!apiKey) throw new Error('OPENAI_API_KEY not configured')
```

If a critical security issue is found, stop and fix it first. Rotate exposed secrets if any and check related files for the same pattern.

## Engineering Style

- Prefer immutable updates over in-place mutation.
- Prefer small, cohesive functions and files.
- Use clear names and avoid deep nesting.
- Add concise, actionable error handling.
- Avoid leaving `console.log` in committed code.
- Preserve existing project patterns unless there is a concrete defect.

## Testing And Verification

- Add or update tests for changed behavior.
- For higher-risk changes, cover unit and integration; include E2E for critical user flows when touched.
- Follow repo test, lint, and typecheck scripts first.
- Use 80%+ coverage as a target where the project already enforces it.
- Before finishing substantial work, report what was verified and what was not.

## Git And PRs

Commit message format:

```text
<type>: <description>

<optional body>
```

Types: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `perf`, `ci`.

For PRs:

- Review full diff against base with `git diff <base>...HEAD`.
- Summarize behavior changes and risks.
- Include a concrete test plan.

## Search And Skills

- For local semantic code search, prefer `colgrep` when available.
- For exact file/text search, use `rg` or `rg --files`.
- Keep skill usage task-driven: use specialized skills only when the task clearly matches.
- Use `$html-artifact` for requested HTML artifacts and `$living-document` for continuously edited documents.
