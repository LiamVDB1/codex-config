---
name: html-artifact
description: |
  You MUST use this skill EVERY TIME the user asks you to make, generate, create, build,
  draft, write, or produce an HTML file — including phrases like "make a html file",
  "html artifact", "html report", "html visualization", "html page", "html dashboard",
  "html cheatsheet", "html one-pager", "html study notes", "html summary", or any
  variant referencing `.html` output. Defines the SecondBrain HTML library directory
  convention, required `nexus:*` meta tags, and best practices for AI-generated HTML
  as an information medium. Liam values visualizations highly — but content
  completeness and fidelity come first; visualizations are an additive layer, never
  a replacement for prose, code, examples, or exact outputs.
---

# HTML Artifact Skill

You are generating an HTML file for Liam's HTML library at `~/SecondBrain/artifacts/html/`. HTML is chosen here because it can carry both **content and visualization in the same document**. Use that range — don't reduce every artifact to a dashboard, and don't reduce every artifact to a wall of text.

## When This Skill Activates

This skill MUST run whenever the user requests an HTML file in any form — reports, dashboards, study notes, references, cheatsheets, infographics, explainers, deep technical writeups, one-pagers. Do not skip it because the request seems simple. A short artifact still needs the directory convention, meta tags, and the content/visual balance.

## Hard Requirements (non-negotiable)

### 1. Directory + filename convention

Save every HTML artifact under:

```
~/SecondBrain/artifacts/html/<project>/<slug>.html
```

It will be served at `/html-library/<project>/<slug>.html`.

- `<project>` — kebab-case project or topic bucket (e.g., `claude-config`, `truth-engine`, `coursework`, `weekly-reports`). Reuse existing buckets when one fits — `ls ~/SecondBrain/artifacts/html/` first to check.
- `<slug>` — kebab-case, descriptive, no dates in the slug (the `nexus:created` meta tag carries the date).
- If the user does not specify a project, infer from context. If genuinely ambiguous, pick `scratch/`.

### 2. Required meta tags (must appear in every artifact)

```html
<title>Artifact title</title>
<meta name="description" content="one-line description">
<meta name="nexus:project" content="project-name">
<meta name="nexus:tags" content="agent, prototype, ui">
<meta name="nexus:author" content="codex">
<meta name="nexus:created" content="2026-05-09T12:00:00.000Z">
```

Rules:
- `nexus:created` MUST be the actual current UTC ISO-8601 timestamp at generation time. Run `date -u +"%Y-%m-%dT%H:%M:%S.000Z"` via Bash — do not hardcode the example value.
- `nexus:project` MUST match the `<project>` directory name exactly.
- `nexus:tags` — 3–7 comma-separated lowercase tags drawn from the artifact's actual subject and shape (e.g., `report`, `study-notes`, `reference`, `cheatsheet`, `dashboard`, `comparison`, `timeline`, `tutorial`, `infographic`, plus topic-specific tags).
- `description` — one sentence (≤ 160 chars) that someone scanning the library would understand cold.
- Include standard meta as well: `<meta charset="utf-8">`, `<meta name="viewport" content="width=device-width, initial-scale=1">`.

### 3. Single-file, self-contained

Everything inline or via public CDN — no build step, no separate asset files.
- Styles inline or in a `<style>` block. Tailwind via the Play CDN is allowed.
- Scripts inline or via CDN (Chart.js, D3, Mermaid, Alpine.js, KaTeX, highlight.js, etc.).
- Images: prefer inline SVG; data URIs for small icons; public URLs only for larger raster.
- No `node_modules`, no build artifacts.

### 4. Use Codex UI guidance for visual quality

Before writing the file, use the available Codex UI guidance when the artifact has meaningful visual design. Prefer `$ui-ux-pro-max` when available, and apply its aesthetic guidance to the artifact. Without a visual-quality pass, output drifts toward generic AI-slop aesthetics.

---

## Core Tension: Completeness vs. Visual Elegance

The single most common failure mode of AI-generated HTML is **being too sparse** — pretty layout, beautiful chart, but the actual content has been compressed, paraphrased, summarized, or replaced by the visual. That is wrong.

**The order of priorities, when they conflict:**

1. **Correctness** — facts, numbers, code, outputs, terminology.
2. **Completeness** — everything the user needs to understand the topic from this artifact alone, without the source material.
3. **Fidelity** — code, queries, formulas, quotes appear verbatim where the exact form matters.
4. **Clarity** — structure, naming, sequencing that makes the content followable.
5. **Visualization** — diagrams, charts, flows that genuinely raise understanding.
6. **Aesthetic polish** — typography, palette, spacing.

Visualization sits *above* aesthetic polish but *below* completeness and fidelity. If a visualization would force you to abbreviate code, hide outputs, or simplify a definition, the visualization loses — keep the content, drop or shrink the visual.

**A good artifact is fully readable as prose+code+examples alone.** The visualizations are an additive layer that makes the dense parts more intuitive — they don't carry the load on their own.

---

## Artifact Density Spectrum

Pick the density that matches the *purpose*, not a template. The same skill handles all of these:

| Purpose | Density profile | What to lean on |
|---|---|---|
| **Dashboard / status report** | Sparse, high signal-to-prose ratio. Lead with headline metrics and charts. | Charts, KPI tiles, sparklines, comparisons. Short captions. |
| **One-page cheatsheet / reference card** | Compressed, scannable. Tables, grids, short labelled examples. | Code snippets, syntax tables, lookup grids. Minimal prose. |
| **Explainer / tutorial / walkthrough** | Medium. Worked examples with diagrams between them. | Step-by-step prose + diagram per concept + executable examples. |
| **Study summary / course notes** | Dense. Full definitions, complete code, mental traces, no abbreviation. | Prose + verbatim code + worked traces + diagrams for hard concepts. |
| **Technical deep-dive / spec** | Dense. Authoritative, exhaustive on the parts that matter. | Prose + diagrams + tables + verbatim examples + edge cases. |
| **Infographic / comparison** | Sparse, visual-led. | Annotated illustrations, side-by-side comparisons. |
| **Decision / proposal doc** | Medium. Argument-led with supporting visuals. | Prose argument + one or two key visuals + tradeoff table. |

When the user's request is ambiguous about which kind they want, infer from the subject:
- "Notes / summary / cheatsheet on X" with technical content → lean **dense**.
- "Report / dashboard / overview" → lean **sparse**.
- "Explain / show me how X works" → lean **medium with diagrams**.

If you're unsure between two profiles, **err denser**. A too-thorough artifact is a minor annoyance; a too-sparse one fails its purpose.

---

## Visualizations: Real vs. Structural

There's a distinction worth keeping clear:

**Structural elements** — cards, grids, tables, callout boxes, accordions, badges, side-by-side panels. These organize content. They are not visualizations; they are layout.

**Real visualizations** carry information that the prose alone doesn't convey efficiently:
- **Charts** — quantitative data, comparisons, distributions, trends (Chart.js, ECharts, D3).
- **Diagrams** — relationships, flows, hierarchies, architectures, state machines (Mermaid for sequence/flow/class/ER/state/gantt/timeline; raw SVG for bespoke).
- **Trees** — recursion trees, parse trees, term trees, decision trees, file/object hierarchies.
- **Process / algorithm flows** — step-by-step execution traces, backtracking searches, state transitions.
- **Stack / queue / data structure visuals** — showing the structure changing over time.
- **Pipeline / system diagrams** — components and the data flowing between them.
- **Annotated illustrations** — labelled SVG with callouts, used to explain a UI, an architecture, or a concept.
- **Number-bearing visuals** — sparklines, bullet charts, distribution strips, where the number *and* its visual context both appear.

**Guideline for dense / technical artifacts:** include multiple real visualizations where the content has visualizable structure (algorithms, processes, hierarchies, state changes, relationships). A rough target for a substantial topic is 4–8 real visualizations, but scale to the content — never invent visuals just to hit a count.

**Guideline for sparse / report artifacts:** lead with one or two strong primary visuals; supporting tiles and charts as needed.

**A common bug:** putting concepts in cards/tables when they actually need a diagram. If an idea involves a *process*, *hierarchy*, *traversal*, or *transformation*, it almost certainly wants a real visualization, not a card with bullet points.

---

## Content Fidelity (especially for technical/educational artifacts)

- **Include code verbatim.** Do not silently reformat, rename, or simplify. If a snippet has a typo or bug worth noting, show the original and the corrected form, and say which is which.
- **Preserve outputs as written.** Don't replace meaningful output with `...` if the exact behavior carries learning value. Truncate only stylistic boilerplate.
- **Define every non-obvious term, symbol, and notation.** If a definition is implicit in the source, make it explicit here.
- **Walk through executions.** For algorithms, queries, or operations whose behavior is non-obvious, include a step-by-step trace (table, list, or diagram). The reader should not need to mentally execute things you could have shown.
- **Surface edge cases, side effects, gotchas.** Things that "everyone knows" usually aren't, and the source material often skips them.
- **Cite sources / sections / pages** when summarizing from a known source — even briefly, so the reader can verify.
- **Preserve domain language.** If the source is in a specific natural language (e.g., the user is studying in Dutch), keep terminology in that language unless asked otherwise.

---

## No Rigid Structure

There is no required structure for the artifact. No mandatory intro, no mandatory TL;DR, no mandatory section order, no "hero / overview / details" template. Choose the structure that fits the question, the subject, and the use case — the same skill produces a chart-led dashboard, a question-and-answer reference, a chapter-style study summary, a single-screen cheatsheet, or a side-by-side comparison, and the right shape for each is different.

Use whatever opening (or no opening), whatever section order, whatever endings (or no ending) the content actually needs. The only structural absolutes are the `nexus:*` meta tags and the file location.

## Information Design Principles (general, content-level)

- **Hierarchical headings.** Real `<h1>`/`<h2>`/`<h3>`, not styled divs. The heading outline should be readable on its own.
- **Captions describe findings, not chart types.** "Revenue tripled across the year" beats "Bar chart of monthly revenue."
- **Color encodes meaning when it encodes anything.** Pick one neutral structural palette and reserve one or two accent colors for emphasis, anomalies, or category distinction. Avoid rainbow palettes unless ordinal.
- **Annotate visuals.** Title, axis labels, units, a callout where appropriate, source/footnote. Bare visuals are half-visuals.
- **Whitespace and rhythm.** Crowded artifacts read worse than they look in a screenshot. Group related items, separate unrelated sections.
- **Progressive disclosure when useful.** `<details>` for tangents, appendices, or proofs — but never hide content the artifact depends on.
- **Print-survivable.** Avoid solid dark backgrounds by default; if you use a dark theme, add a `@media print` block that switches to readable print colors.

---

## Technical Best Practices

### Semantic HTML (mechanics, not structure)

These are markup conventions — they don't dictate what the artifact contains or in what order.

- Use real `<h1>` / `<h2>` / `<h3>` for headings, not styled divs.
- Use `<section>` for top-level content groupings when you have them; `<article>` for a self-contained piece; `<aside>` for tangential content. None of these are required — use them when they fit.
- Wrap each visualization in `<figure>` with a `<figcaption>` and an `aria-label` describing the finding (not the chart type).
- Use `<pre><code>` for multi-line code; consider highlight.js or Prism via CDN for syntax highlighting on technical artifacts.
- For math, use KaTeX via CDN (`<link>` + `<script defer>` + `renderMathInElement`).
- Provide a text alternative for every non-decorative visual.

### Accessibility (WCAG 2.2 AA floor)

- Contrast ≥ 4.5:1 for body text, ≥ 3:1 for large text and meaningful graphics.
- Don't encode meaning by color alone — pair with shape, label, or pattern.
- Keyboard-operable interactive elements with visible focus.
- Respect `prefers-reduced-motion`:
  ```css
  @media (prefers-reduced-motion: reduce) { * { animation: none !important; transition: none !important; } }
  ```

### Performance / footprint

- One charting library per artifact unless you genuinely need more.
- SVG over canvas for charts with under ~1k points (sharper, accessible, inspectable).
- Inline small SVG icons; skip icon-font CDNs for a few glyphs.

### Responsive + dark mode

- Mobile-first. Use CSS grid / flexbox; test mentally at 375px.
- Support `prefers-color-scheme` if relevant; recompute chart colors so they hold contrast in both themes.

### Things to actively avoid (the "AI slop" tells)

- Purple→pink→blue gradient hero blocks
- Everything centered, full-width, no rhythm
- Uniform `rounded-2xl` on every element
- Inter as default — pick a font that suits the subject (serif for editorial/educational, mono for technical, humanist sans for product)
- "Hero / Features / CTA" landing-page structure for things that are not landing pages
- Lorem-ipsum-flavored filler, vague headlines like "Empowering insights through data"
- Replacing code with screenshots of code
- Replacing exact output with "…"
- Decorative emojis (unless the user uses them)
- Chart.js defaults left untouched (gridlines everywhere, no titles, dataset label `dataset 1`)

---

## Required `<head>` block

The only piece that's prescribed. Everything else about the document — layout, sections, body shape, whether there's a header or footer at all — is up to the model.

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{{TITLE}}</title>
  <meta name="description" content="{{ONE_LINE_DESCRIPTION}}">
  <meta name="nexus:project" content="{{PROJECT}}">
  <meta name="nexus:tags" content="{{TAG1, TAG2, TAG3}}">
  <meta name="nexus:author" content="codex">
  <meta name="nexus:created" content="{{ISO_UTC_NOW}}">
  <!-- Styling — Tailwind Play CDN is one option; plain <style> or another framework is fine too. -->
  <!-- Pull in libraries only if the artifact uses them (Chart.js, Mermaid, KaTeX, highlight.js, etc.). -->
  <style>
    @media (prefers-reduced-motion: reduce) { * { animation: none !important; transition: none !important; } }
    /* Define a palette and typography scale that suits the subject — don't ship raw framework defaults. */
  </style>
</head>
<body>
  <!-- Body shape, sections, container widths, whether there's a header/footer — all up to you. -->
</body>
</html>
```

Body width, container, whether you center, whether you have a header or just dive in — pick what suits the artifact. A study summary with prose typically wants a narrower reading column; a multi-panel dashboard wants width; a cheatsheet may want a grid that fills the viewport. Decide per artifact.

---

## Workflow Checklist

For every HTML artifact request:

1. **Read the source first.** If the user supplies PDFs, files, links, or pasted content, ingest all of it before designing. Don't sketch the artifact from the title alone.
2. **Identify the density profile** (see spectrum) from the user's intent and the subject — but do not pre-commit to a structural template.
3. **Decide the shape.** Based on the actual content, choose the structure: what comes first, what comes last, what gets a real visualization (process/hierarchy/data/state), what's structural layout (cards/tables for collections/comparisons), what's prose+code. The shape follows the content, not the other way around.
4. **Use `$ui-ux-pro-max` when available** for aesthetic guidance.
5. **Generate `nexus:created`** via Bash: `date -u +"%Y-%m-%dT%H:%M:%S.000Z"`.
6. **Pick path** `~/SecondBrain/artifacts/html/<project>/<slug>.html`. `ls` the artifacts dir to reuse existing project buckets.
7. **Write the file** — required `<head>` block with all meta tags, then the body in whatever shape fits. Content carries the load; visualizations are additive.
8. **Coverage check before reporting done:**
   - Is everything from the source covered? Nothing essential silently dropped?
   - Is code verbatim, with no silent rewrites?
   - Are exact outputs preserved where behavior matters?
   - Are non-obvious terms, symbols, and notation defined?
   - Do the visualizations carry information (not just decorate)?
   - Are concepts that involve process/hierarchy/state given real visualizations, not just cards?
   - All five `nexus:*` meta tags present and correct, with a real current UTC timestamp?
   - `nexus:project` matches the folder name?
   - Mobile width holds together?
9. **Report**: relative path under `~/SecondBrain/artifacts/html/` and the public URL `/html-library/<project>/<slug>.html`. For dense artifacts, briefly note what's covered and what was deliberately not included.

---

## Living Documents

If the user calls the artifact a "living document" / "living doc" / "running document" / asks to "keep editing this in place" / "update this as we go", also use `$living-document` and apply both skills together. `html-artifact` governs shape, content depth, and visualizations; `living-document` governs the two-pass edit workflow: compress prior content into a stable **Core**, then write current-turn material into a clearly-labeled **Additions** section that gets wiped each turn. Preserve all the `nexus:*` meta tags across edits as described below; `nexus:created` is the origin date and does not change on living-document updates. Add `nexus:updated` when the document changes substantively.

---

## Library Goes Both Ways

When asked to *update*, *extend*, or *reference* an existing artifact, first `ls ~/SecondBrain/artifacts/html/<project>/` and read the existing file. Preserve its `nexus:created` timestamp on edits — that field marks origin, not last-modified. For significant edits, add `<meta name="nexus:updated" content="{{ISO_NOW}}">` alongside, rather than overwriting `nexus:created`.
