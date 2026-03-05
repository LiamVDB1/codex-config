## Global Working Defaults

This file defines global defaults across repositories. 

## Security Baseline (Always Apply)

Before finalizing code changes:
- [ ] No hardcoded secrets (keys, tokens, passwords)
- [ ] Validate untrusted input
- [ ] Prevent injection risks (SQL/command/template)
- [ ] Prevent XSS when rendering HTML/content
- [ ] Ensure authz/authn checks are correct where relevant
- [ ] Ensure endpoints handling user traffic have rate-limit strategy
- [ ] Avoid leaking sensitive internals in error messages

Secret handling pattern:

```ts
const apiKey = process.env.OPENAI_API_KEY
if (!apiKey) throw new Error('OPENAI_API_KEY not configured')
```

If a critical security issue is found:
1. Stop and fix it first.
2. Rotate exposed secrets if any.
3. Check for similar patterns in related files.

## Engineering Style Defaults

- Prefer immutable updates over in-place mutation.
- Prefer small, cohesive functions and files.
- Use clear names and avoid deep nesting.
- Add concise, actionable error handling.
- Avoid leaving `console.log` in committed code.

## Testing and Verification Defaults

- Add or update tests for changed behavior.
- For higher-risk changes, cover unit + integration; include E2E for critical user flows when touched.
- Follow repo test/lint/typecheck scripts first.
- Use 80%+ coverage as a target where the project already enforces it.

## Git and PR Defaults

Commit message format:

```text
<type>: <description>

<optional body>
```

Types: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `perf`, `ci`

For PRs:
1. Review full diff against base (`git diff <base>...HEAD`).
2. Summarize behavior changes and risks.
3. Include a concrete test plan.

## Search and Skills

- For local code search, prefer `mgrep` with natural-language queries.
- Keep skill usage task-driven: use specialized skills only when the task clearly matches.
