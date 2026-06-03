---
name: observer
description: Monitor one long-running task, workflow, agent run, test session, or pipeline execution in sleep/wake cycles, append targeted observations to a run-specific notes file, distinguish runtime failures from behavioral or product issues, fix concrete execution bugs during the same session, and finish with a prioritized improvement summary. The observer may stop early once it has enough evidence for the specific issue it is targeting and continuing the run is unlikely to change the diagnosis. Use when a user wants continuous observation, attach-and-monitor behavior, cycle-based diagnostics, or a post-run assessment grounded in one real execution.
---

# Observer

## Overview

Observe one real execution. Watch it in sleep/wake batches, append decision-relevant findings to a
run-specific notes file, fix concrete runtime failures without switching targets, and finish with
a prioritized assessment of what should improve next.

Stay anchored to one target only unless the user explicitly asks for multiple runs. You do not
need to wait for full completion if the targeted issue is already well understood and further
waiting is unlikely to add meaningful signal.

## Workflow

### 1. Start or attach to one target

- If the user names a run id, workflow id, test session, job, or process, use it.
- Otherwise start the canonical repo command for one live target and capture the identifier from
  its output if one exists.
- Prefer the repository's own documented run command and environment.
- If the target is already running, reattach or tail it instead of starting a second one.

Examples:

- a workflow execution
- a long-running integration test
- a scraper job
- a background worker
- an agent pipeline

### 2. Create the monitor file immediately

- Write a notes file as early as possible.
- Prefer a repo-local path such as:
  - `out/<run_id>.monitor.md`
  - `logs/<run_id>.monitor.md`
  - `tmp/<run_id>.monitor.md`
- Include:
  - target id or label
  - local start time
  - purpose
  - monitoring protocol
  - default sleep cadence
  - short cycle checklist

Recommended protocol structure:

- Default sleep cycle:
  - `120-180s` during active steady-state work when nothing is broken
  - `30-60s` after errors, stage transitions, or suspicious outputs
  - shorten adaptively when a stage looks close to finishing
- Cycle checklist:
  - Did the target advance, stall, or crash?
  - Did quality improve, or only volume?
  - Which tools, sources, or subsystems dominated this cycle?
  - Is this a runtime/tool failure, a content-quality issue, or a behavioral/product issue?
  - If there is a concrete runtime failure, should it be fixed before continuing?

### 3. Monitor in wake cycles

- Poll in batches instead of constantly.
- After each wake cycle:
  - summarize only the highest-signal observations
  - append them to the monitor file under a new cycle heading
  - state what you think each observation means
- Prefer real artifacts over guesswork:
  - stdout or stderr
  - traces
  - logs
  - generated files
  - database state
  - screenshots or reports

### 4. Stop early when the evidence is sufficient

- Do not keep waiting just because the target is still alive.
- If you have enough evidence for the specific issue you are targeting, you may stop observation
  mid-run and move directly into changes.
- Good early-stop conditions:
  - the failure mode or behavioral issue is already clear
  - the relevant stage has repeated the same pattern multiple times
  - additional wake cycles are only adding more examples, not new understanding
  - you already know the concrete fix or prompt/runtime change to make
- When stopping early:
  - record the stop point and reason in the monitor file
  - state what evidence was sufficient
  - note what further evidence you are intentionally not waiting for
  - make the change immediately if that is the next useful step

### 5. Separate issue types cleanly

Always classify findings clearly. Common buckets:

- Runtime/system issue:
  - crash
  - timeout
  - deadlock
  - DB collision
  - state resume bug
- Transport/integration issue:
  - upstream `403`
  - network failure
  - provider outage
  - malformed API response
- Content-quality issue:
  - empty extract
  - boilerplate output
  - junk text
  - duplicated sections
  - invalid parse
- Agent or behavior issue:
  - wrong search strategy
  - poor stopping behavior
  - repeated unhelpful loops
  - weak evidence selection
- Gate/control issue:
  - target advances when it should not
  - failure reasons are too generic
  - retries add cost without adding signal

Do not misclassify blocked external systems as internal runtime bugs unless the local stack is
actually malfunctioning.

### 6. Fix concrete runtime failures during the same session

- If the observed execution fails for a concrete engineering reason, fix it during the monitoring
  session when feasible.
- Add focused verification for the fix before resuming observation.
- Reattach to the same target after the fix. Do not silently switch to a new run.
- Record the failure, diagnosis, fix, and verification in the monitor file.

Examples of fixes that belong here:

- resume-state hydration bugs
- uniqueness / migration bugs
- wait or polling robustness
- parser crashes
- bad retry handling

Examples that usually do not require immediate code changes mid-run:

- upstream access denied
- poor data quality from a reachable source
- weak prompting or product logic that does not block execution

Record those as improvement opportunities unless they prevent the run from continuing.

### 7. End with a real synthesis

When the target finishes, or when you intentionally stop observation early:

- append a final assessment section to the monitor file
- summarize:
  - what worked
  - what is still weak
  - what improved versus earlier runs, if relevant
  - the highest-priority changes to make next
  - whether the run was observed to completion or stopped early on purpose

Prefer a short prioritized list over a long brainstorm.

## What Good Observation Looks Like

- Stay anchored to one real execution.
- Use real artifacts as the source of truth.
- Prefer strong, specific observations over transcript copying.
- Treat cost, latency, retry churn, and repeated weak loops as real findings.
- Separate execution failures from product-quality failures.
- Stop as soon as the targeted diagnosis is stable enough to act on; do not wait for ceremonial
  completion.

## Output Expectations

Leave behind a monitor file that another engineer can open cold and still understand:

- what happened
- where the system is weak
- which issues were runtime bugs versus behavioral/product issues
- what should change next, in priority order
- whether observation ended because the run completed or because you had enough evidence already
