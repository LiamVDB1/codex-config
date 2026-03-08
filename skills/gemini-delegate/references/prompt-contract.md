# Gemini Delegate Prompt Contract

## Default mode selection

- Use `consult` for architecture questions, debugging hypotheses, adversarial critique, or general second opinions.
- Use `review` for code review against a git diff.
- Use `session` for persistent back-and-forth when continuity matters more than machine-readable output.
- Use `worker-session` only when Gemini must edit code and only in a separate git worktree.

## Packaging rules

1. State the task in one or two sentences.
2. State the desired output shape.
3. Include only the smallest useful context.
4. Explicitly say whether Gemini is read-only or allowed to edit.
5. Include repo-specific constraints that matter.

Minimal prompt frame:

```text
Task:
<what Gemini should do>

Mode:
<consult | review | session | worker-session>

Constraints:
- <read-only or isolated worker>
- <repo-specific constraints>
- <what not to do>

Return:
- <required sections or artifact>

Context:
<small file excerpt, plan, or diff>
```

## Default response contract

For `consult`:

- `## Recommendation`
- `## Why`
- `## Risks`
- `## Open Questions`
- `## Next Steps`

For `review`:

- `## Findings`
- `## Risks`
- `## Missing Tests`
- `## Recommendation`

Require concise, concrete output. Ask for uncertainty to be stated explicitly instead of padded prose.

## Safety rules

- Never send secrets, tokens, credentials, private customer data, or `.env` contents.
- Keep Gemini read-only unless a separate worktree is in use.
- Avoid concurrent edits in the same worktree.
- Prefer Gemini for model diversity, dissent, or bounded overflow work.
- Prefer Codex local analysis when the task requires heavy repo context or tight coupling to current edits.

## Reintegrating output

- Treat `consult` and `review` outputs as advisory.
- Inspect any Gemini-authored diff before cherry-picking or merging.
- If Gemini suggests a repo-wide change from limited context, reduce scope and re-run with tighter context.
