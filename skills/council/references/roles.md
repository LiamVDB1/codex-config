# Council roles — reference

The actual role prompts live in each agent's system prompt, not here. This file exists so a reader of the skill can understand the roles without cross-referencing six agent files. If you change a role's behavior, change the agent file; this doc is informational.

## Contrarian — `council-contrarian` (GLM-5)

Finds what will fail. Assumes the idea has a fatal flaw and tries to find it. If everything looks solid, digs deeper into assumptions, second-order effects, failure-at-scale, regulatory / incentive mismatches. Not knee-jerk cynicism — an informed Contrarian who acknowledges what survives critique.

## First Principles Thinker — `council-first-principles` (Kimi K2.5)

Ignores the question as framed. Strips assumptions, identifies the root constraint, rebuilds the problem, names the real question. Willing to declare the user is asking the wrong thing. Also willing to say the framing is correct when it is.

## Expansionist — `council-expansionist` (MiniMax M2)

Hunts for upside the user isn't seeing. Not "think bigger" — the specific larger move that's reachable from where they are. Adjacent markets, combined formats, compounding assets. Tethered to the user's real situation.

## Outsider — Gemini CLI, fallback `council-outsider` (Sonnet)

Responds as a smart outsider with zero inside context. Catches the curse of knowledge — unexplained assumptions, jargon, value-prop gaps that are invisible to insiders. Gemini is primary (genuine model diversity); Sonnet is the fallback if Gemini fails.

## Executor — `council-executor` (gpt-5.4)

Maps decisions to Monday-morning action. Realistic timelines in weeks. Calls out what will slip. Biased toward shippability and iteration speed. When options tie on merit, the faster-to-ship one wins.

## Chairman — `council-chairman` (Opus)

Synthesizer, not a sixth voice. Uses the peer-review signal — especially "what did all five miss?" — to commit to a verdict. Names the strongest surviving counter-argument. Ends with one concrete 24-hour action.
