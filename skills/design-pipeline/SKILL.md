---
name: design-pipeline
description: "Use when the user wants to go from idea to polished UI through a combined workflow: prompt refinement, design generation, component sourcing, implementation, and visual verification."
---

# Design Pipeline

This skill orchestrates the design stack instead of treating each tool as an island.

## When to use

- turning rough product ideas into concrete UI direction
- generating first-pass screens or flows
- extracting a reusable design system from generated work
- sourcing polished components for implementation
- implementing or refining UI with visual validation

## Tool roles

- `stitch` MCP: generate screens, inspect projects/screens, retrieve HTML and images
- `ui-ux-pro-max`: choose style direction, palettes, typography, layout patterns, and anti-patterns
- `magic` MCP: source or generate polished production-facing components
- Figma tools: capture screenshots, compare design context, and document design-system rules when Figma is involved
- `playwright-interactive`: verify the rendered UI visually after implementation

## Default workflow

1. Clarify the job to be done.
   Decide whether the user needs exploration, implementation, or both.

2. Establish the design direction first.
   Use `ui-ux-pro-max` guidance to select:
   - page or product pattern
   - visual style
   - color direction
   - typography direction
   - anti-patterns to avoid

3. Generate or inspect UI in Stitch.
   Use Stitch to:
   - refine prompts
   - generate initial screens
   - inspect screen metadata
   - retrieve screenshots and HTML for follow-on work

4. Convert direction into implementation primitives.
   Use 21st.dev Magic when the UI should become reusable components instead of a one-off mockup.
   Prefer existing project conventions over literal output from generators.

5. Implement with discipline.
   Reuse existing components where possible.
   Keep styles token-driven and avoid hardcoded magic values when a system can be established.

6. Validate visually before completion.
   Use Playwright or screenshot-based comparison when implementation fidelity matters.

## Decision rules

- Use Stitch first when the user needs ideation, multi-screen generation, or visual exploration.
- Use Magic first when the user already knows the target UI and needs component-level implementation speed.
- Use UI UX Pro Max before either one when the visual direction is still vague.
- If the user already has Figma designs, prefer Figma context over regenerating in Stitch.
- If the generated output is generic, push for a sharper art direction before coding.

## Output expectations

- State which layer is being used: design direction, generation, components, or implementation.
- Separate fact from recommendation when comparing multiple design directions.
- When moving to code, summarize the chosen visual system in a few concrete rules.

## Anti-patterns

- Do not treat generated HTML as production-ready by default.
- Do not combine conflicting style directions in one pass.
- Do not skip visual verification for UI tasks that depend on fidelity.
- Do not let component-library output override the product's visual identity.
