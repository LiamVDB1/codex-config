---
name: living-document
description: |
  You MUST use this skill EVERY TIME a document is referred to as a "living document",
  "living doc", "running document", "evolving document", or the user asks you to
  "keep editing this in place", "treat X as a living document", "update this as we go",
  or similar continuously-edited-document patterns. Defines the two-pass edit workflow:
  compress prior content into a stable Core that a fresh agent could pick up cold, then
  write current-turn answers and visualizations into a clearly-labeled Additions section
  that is wiped at the start of every turn. Format-agnostic — works for HTML, Markdown,
  or plain text — and composes with the html-artifact skill when the living document
  is an HTML artifact.
---

# Living Document Skill

A living document is **one continuous document edited in place** across a session (and sometimes across sessions). It carries forward as it grows: yesterday's settled answers fold into the document's knowledge base, and today's questions get fresh space to be worked in. Nothing is "appended forever" and nothing is "rewritten from scratch."

## When This Skill Activates

Activate whenever the user describes a document as living / continuously updated / edited-in-place. Trigger phrases include:
- "this is a living document"
- "make this a living doc"
- "treat X as a living document"
- "keep editing this in place"
- "running document" / "evolving document"
- "update this as we go"

The skill **composes** with other document skills. If the living document is an HTML artifact, apply both `html-artifact` (for shape, content, and visualizations) and this skill (for the edit workflow) on every turn.

---

## The Two-Pass Structure

At every point in time, the document has exactly two parts:

### 1. Core (stable, growing, self-sufficient)

The top of the document. Contains:
- A short **Overview** — what this document is and what it carries.
- The **main sections** — established information, settled decisions, distilled answers from previous turns, verbatim source material that must persist.

**Core must be complete enough that a fresh agent reading only the Core understands the state of the work.** That is the load-bearing invariant. Verbatim code, exact terminology, source citations, agreed-on decisions all live here.

### 2. Additions (volatile, current-turn-only)

Below a clearly visible divider, in its own labelled section (e.g., `## Current Additions`, `## This Turn`, or in HTML a `<section id="additions">` with a heading). Contains:
- New explanations, visualizations, examples, side-discussions the user asked for **this turn**.
- Exploratory or partial answers not yet promoted to Core.

**The Additions section is wiped at the start of every turn before you write new material into it.** That is the second load-bearing invariant.

---

## Workflow — Every Turn

Before responding to the user's current request:

1. **Read the document.** See what's currently in Core and what's in Additions.
2. **Compression pass — process last turn's Additions:**
   - If an item is a settled answer, a durable decision, or genuine new knowledge → **fold it into Core**. Distill the *conclusion* and *why*, not the back-and-forth that got there. Add it to the right Core section or create a new one.
   - If it was a one-off explanation or working-out that the user no longer needs visible → **drop it**.
   - Items the user explicitly asked to keep visible → leave a brief note in Core (or hold over with a flag), don't silently delete.
   - Preserve verbatim what must stay verbatim (code, exact quotes, formulas, statute text, named decisions).
3. **Clean the Additions section.** Empty the body. Keep the heading and divider so the document keeps its shape.
4. **Addition pass — write the response:** put the new content (explanation, diagram, walkthrough, partial answer) into the now-empty Additions section. This is where today's work lives until next turn decides what to keep.
5. **Verify Core is fresh-agent-sufficient.** A reader landing on the document cold should be able to read only the Core and know what's going on. If your compression left a gap, fix it before reporting done.

---

## What Belongs Where

| Belongs in Core | Belongs in Additions |
|---|---|
| Settled decisions, agreed approach | Exploration of an option not yet chosen |
| Verbatim source material (code, quotes, statute text, formulas) | Today's explanation of how part of it works |
| Distilled definitions and key terminology | The walkthrough the user asked for this turn |
| Diagrams that visualize stable structure | A one-off diagram answering today's question |
| Citations, sources | Side-discussions, asides |
| "We ended up with X because Y" summaries | The thinking process that got there |

**Default when in doubt:** leave it in Additions one more turn. Things that survive two or three turns of Additions are clearly Core material. Things that only mattered for one question are clearly disposable.

---

## First-Turn Creation

If the document doesn't exist yet when "living document" is invoked:
- Create it with both sections present from the start.
- Core gets a placeholder Overview and whatever has already been established in the conversation.
- Additions holds this turn's response.

---

## Compression Rules

- **Compress conclusions, not transcripts.** "Decided X because Y" — not "User asked about A, I proposed B, user objected, we converged on X."
- **Preserve fidelity-critical content verbatim.** Code, exact quotes, statute text, formulas, named decisions don't get paraphrased on the way into Core.
- **Promote stable visualizations.** If a diagram from Additions accurately represents Core knowledge, move it into Core — don't redraw a worse version.
- **Reorganize Core when it fragments.** A growing document occasionally needs sections merged or split. Do it proactively, not when it's already a mess.
- **Update, don't append, when state changes.** If a decision in Core was superseded, rewrite the Core section to reflect the new state — don't leave both versions side-by-side.

---

## Cleaning Rules for Additions

- **Empty the body at the start of every turn** before writing new material. Never append to last turn's Additions — that is the primary bloat failure mode.
- **Keep the structural shell** — heading, divider, empty container — so the document's shape is stable across turns.
- **Honour explicit "keep" requests.** If the user says "keep that addition there" or "don't compress that yet," leave it for one more turn and mark it `(held over at user request)`.

---

## Visual Markers (use real, visible ones)

The Core/Additions split must be obvious to the user at a glance.

- **Markdown:** an `## Overview` and content sections at top; a horizontal rule (`---`); then `## Current Additions` near the bottom.
- **HTML:** a `<main>` or `<section id="core">` block with the stable content; a visually distinct divider (a horizontal rule, a colored band, a labelled banner); then `<section id="additions">` with its own heading style. Mark the additions section visually (different background tint, a "scratchpad / current turn" label, a distinct accent color) so the user instantly sees which is which. Keep it readable, not gimmicky.
- **Plain text:** a clearly labelled separator line.

---

## Anti-Patterns

- Treating the whole document as one growing scratchpad with no Core/Additions split.
- Leaving last turn's Additions in place "just in case" — that's the bloat failure mode.
- Compressing too aggressively too early — folding an exploratory answer into Core before it's actually settled.
- Letting Core fall out of sync with reality — if a decision changed, Core must reflect the new state.
- Duplicating content across Core and Additions — pick one home for each piece of information.
- Hiding Core under collapsibles or below Additions to "clean up" — Core is the primary surface, it appears first and is the first thing the reader sees.
- Quietly dropping content the user expected to find again — when in doubt, fold to Core.
