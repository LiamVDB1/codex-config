---
name: council
description: Run a high-stakes decision council on demand. Use only when the user says "council this", "council it", asks for a council, or is stuck on a decision where being wrong is expensive. Not for validation-seeking or low-stakes choices.
---

# Council

## Overview

The council is an on-demand decision workflow, not a globally loaded agent roster. When invoked, read the role prompts in `references/roles/`, run the roles against the same framed question, optionally run an anonymous peer-review round, and synthesize a committed verdict.

The point is to create real cognitive diversity without keeping `council-*` agents in global Codex context.

## When To Run

Run when:

- The user says "council this", "council it", or explicitly asks for a council.
- The decision is high-stakes, expensive to redo, or has several plausible paths.
- The user is circling and needs disagreement, not reassurance.

Do not run for low-stakes choices. Say the council is overkill and offer a shorter answer instead.

## Role Prompts

Load these only after the skill activates:

- `references/roles/council-contrarian.md`
- `references/roles/council-first-principles.md`
- `references/roles/council-expansionist.md`
- `references/roles/council-outsider.md`
- `references/roles/council-executor.md`
- `references/roles/council-chairman.md`

Supporting templates:

- `references/peer-review-prompt.md`
- `references/outsider-gemini-prompt.md`
- `references/transcript-template.md`
- `references/roles.md`

## Protocol

### Phase 0 - Frame

Frame the decision in-thread before spawning or simulating roles:

1. Restate the decision in 1-3 sentences.
2. Name the options, stakes, constraints, and any relevant user context.
3. Ask at most one clarifying question if missing context would make every role answer off-target.
4. Create a transcript at `~/.codex/council-runs/<timestamp>-<slug>.md`.

### Phase 1 - Advisor Pass

Run five independent advisors:

- Contrarian
- First Principles
- Expansionist
- Outsider
- Executor

Preferred execution:

- If Codex has an available subagent/worker mechanism that accepts custom instructions, run each role in a fresh context using the matching role prompt file.
- If custom-instruction subagents are unavailable, run the five roles sequentially in-thread, but keep each role response separated and do not let later roles revise earlier roles.
- For the Outsider, optionally use `$gemini-delegate` with `references/outsider-gemini-prompt.md` if Gemini is available and the decision warrants external model diversity.

Do not use generic `*-worker` agents for council roles unless you can pass the role prompt and keep them read-only. Generic code workers drift off-task.

Append all advisor outputs to the transcript.

### Phase 2 - Peer Review

For high-stakes decisions, run an anonymous peer-review pass:

1. Assign letters A-E to the five advisor responses.
2. Hide role labels from reviewers.
3. Use `references/peer-review-prompt.md`.
4. Ask each role to answer:
   - Which response is strongest and why?
   - Which has the biggest blind spot, and what is it?
   - What did all five miss?

For medium-stakes decisions, skip peer review and say in the transcript that the shortened council was used.

### Phase 3 - Chairman

Read `references/roles/council-chairman.md` and synthesize from:

- Framed question and context
- Five advisor responses
- Peer reviews, if run
- Role-letter map, if peer review was run

The chairman must commit. No vague "it depends" verdict unless the missing fact is explicitly named and genuinely decisive.

### Phase 4 - Report

Return only:

```text
## Verdict
<chairman verdict>

## Strongest counter-argument
<strongest case against the verdict>

## Concrete next step
<one literal action within 24 hours>

Full transcript: <absolute path>
```

Do not summarize every advisor inline. The transcript is where the full council lives.

## Guardrails

- Keep council invocation explicit and rare.
- Keep all role prompts lazy-loaded under this skill.
- Prefer one strong council over repeated rounds.
- Maximum: five advisors, five peer reviews, one chairman.
- If the task is code review, use `reviewer` or `security_reviewer`, not council.
