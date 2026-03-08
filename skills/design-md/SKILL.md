---
name: design-md
description: Analyze Stitch projects and synthesize a semantic design system into DESIGN.md files
allowed-tools:
  - "stitch*:*"
  - "Read"
  - "Write"
  - "web_fetch"
---

# Stitch DESIGN.md Skill

You are an expert Design Systems Lead. Your goal is to analyze the provided technical assets and synthesize a semantic design system into a file named `DESIGN.md`.

## Overview

This skill helps you create `DESIGN.md` files that serve as the source of truth for prompting Stitch to generate new screens that align with an existing design language. Stitch interprets design through visual descriptions supported by specific color values.

## Prerequisites

- Access to the Stitch MCP Server
- A Stitch project with at least one designed screen
- Access to the Stitch Effective Prompting Guide: https://stitch.withgoogle.com/docs/learn/prompting/

## Retrieval and Networking

To analyze a Stitch project, retrieve screen metadata and assets using Stitch MCP tools:

1. Discover the Stitch MCP namespace and use that prefix consistently.
2. If project ID is unknown, list projects and identify the target project.
3. If screen ID is unknown, list screens for the project and identify the target screen.
4. Fetch screen metadata including screenshot URLs, HTML download URLs, dimensions, and project design theme data.
5. Download the HTML and, when useful, the screenshot for inspection.
6. Fetch project-level metadata for design theme, color mode, fonts, and guidelines.

## Analysis Instructions

### 1. Extract Project Identity

- Capture the project title.
- Capture the project ID.

### 2. Define the Atmosphere

Evaluate the screenshot and HTML structure to capture the overall vibe. Use evocative adjectives such as airy, dense, minimalist, utilitarian, gallery-like, or editorial.

### 3. Map the Color Palette

For each meaningful color:
- assign a descriptive, natural-language name
- include the exact hex code
- explain its functional role

### 4. Translate Geometry and Shape

Convert technical styling into physical descriptions:
- `rounded-full` -> pill-shaped
- `rounded-lg` -> subtly rounded corners
- `rounded-none` -> sharp, squared-off edges

### 5. Describe Depth and Elevation

Explain how the interface uses layers, shadows, and contrast:
- flat
- whisper-soft diffused shadows
- heavy, high-contrast drop shadows

## Output Format

Create `DESIGN.md` with this structure:

```markdown
# Design System: [Project Title]
**Project ID:** [Project ID]

## 1. Visual Theme & Atmosphere

## 2. Color Palette & Roles

## 3. Typography Rules

## 4. Component Stylings
* **Buttons:**
* **Cards/Containers:**
* **Inputs/Forms:**

## 5. Layout Principles
```

## Best Practices

- Use descriptive design terminology and natural language.
- Include exact hex codes for precision.
- Explain the why behind the design, not just the what.
- Name colors by purpose where possible.
- Keep terminology consistent throughout the document.

## Common Pitfalls

- Don't leave raw technical jargon untranslated.
- Don't omit color codes.
- Don't skip the functional role of each visual element.
- Don't ignore subtle spacing or shadow patterns.
