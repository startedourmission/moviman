---
name: Moviman Operator Console
version: 0.1.0
colors:
  canvas: "#f3f4f1"
  surface: "#ffffff"
  surfaceRaised: "#fafaf7"
  text: "#151a1e"
  muted: "#66707a"
  border: "#d8ddd7"
  primary: "#006c5b"
  primaryHover: "#004f44"
  accent: "#d59b2d"
  info: "#2f6f9f"
  danger: "#b42318"
  success: "#16794c"
typography:
  family: "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
  mono: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"
spacing:
  xs: 4px
  sm: 8px
  md: 12px
  lg: 16px
  xl: 24px
  xxl: 32px
radii:
  sm: 4px
  md: 6px
  lg: 8px
---

# Moviman Design System

## Overview

Moviman is a local operator console for video/audio automation. The UI should feel like a compact production tool: fast to scan, restrained, durable, and focused on repeated upload/process/download workflows.

## Visual Direction

- Use light neutral surfaces with sharp information hierarchy.
- Prefer dense, aligned form controls over decorative hero sections.
- Use green for primary execution, amber for tuning/attention, blue for status details, red only for failures.
- Avoid gradient backgrounds, decorative blobs, oversized marketing copy, and nested cards.

## Layout

- Header: compact app bar with product name, local server badge, and primary context.
- Main screen: two-column workspace on desktop; single column on mobile.
- Left column: main edit job form.
- Right column: extraction form and run notes.
- Progress screen: centered single task panel with progress, elapsed time, current stage, downloads, and logs.

## Components

### Buttons

- Primary: filled `primary`, white text, 6px radius, 42px minimum height.
- Secondary: white background, `border`, `primary` text.
- Button text must be short command verbs.

### Inputs

- 1px solid border, white background, 6px radius, 42px minimum height.
- Labels are 13px semibold, placed above controls.
- Hints are 12-13px muted text and should be operational, not promotional.

### Panels

- Panels use `surface`, 1px `border`, 8px radius.
- Do not place panels inside panels.
- Section headers are compact: 16-18px semibold.

### Progress

- Progress bar height 12-16px.
- Use primary fill.
- Show numeric percent and elapsed time near the bar.
- Logs use mono font, dark background, small text, and fixed max height.

## Do's and Don'ts

- Do keep all controls visible without a landing page.
- Do make upload state and output state obvious.
- Do show errors inline with logs.
- Don't use one-color green-only styling.
- Don't use huge headings inside tool panels.
- Don't hide advanced tuning behind vague labels.
