# GUI design system contract

This document is the canonical GUI contract for MMO. It is normative and intended to prevent UX drift across future GUI work.

## Principles

- Musician-first: default language is sonic outcome, not implementation detail.
- Progressive disclosure: basic flow is visible first; advanced detail is optional.
- Explainable actions: each action must say what changes and why it helps.
- Safe defaults: default choices should bias toward reversible, low-risk outcomes.

## Layout model

- Primary layout: main canvas + right inspector.
- Optional 3-pane layout: left context rail, main canvas, right inspector.
- Main canvas is for current task focus; inspector is for details and rationale.
- Keep primary actions visible; avoid hidden actions inside deep menus.
- Maximum navigation depth is 2 levels. Do not build menus within menus.
- Prefer search and quick filters over nested navigation trees.

## Visual hierarchy rules

- Headline: one clear sentence describing state or outcome.
- Subtext: concise context line directly under the headline.
- Badges: short categorical status only (`EXTREME`, `BLOCKED`, `SAFE`, `INFO`).
- Warnings: explicit, actionable, and paired with the next safe step.
- Use spacing and typography hierarchy before adding more color emphasis.

## Nerd toggle behavior

- Nerd toggle defaults to off.
- Off: show outcome-first summaries, plain-language explanations, and core actions.
- On: reveal IDs, thresholds, policy references, and raw diagnostic detail.
- Toggling must never change analysis results, eligibility, or action ordering.
- Advanced fields appear inline or in the inspector; no separate hidden workflow.

## Copy rules

- Keep copy short, friendly, and concrete.
- Avoid jargon when a plain alternative exists.
- Include a "why" line for actions and warnings.
- Use musician language first, with technical detail behind Nerd toggle.
- Never show blameful or vague warnings.

## Interaction rules

- Never surprise: critical actions require clear intent and visible impact.
- Undo support is required for reversible GUI edits.
- Preview before commit for changes that alter output or recommendation state.
- Compare views must let users inspect before/after outcomes.
- If an action is blocked, show why and what can unblock it.

## Accessibility rules

- Contrast minimum: WCAG AA baseline (4.5:1 for normal text, 3:1 for large text).
- Do not rely on color alone; pair color with text labels or icons.
- Minimum body text size is 16 px; avoid critical text below 14 px.
- Full keyboard navigation required for primary workflow paths.
- Focus indicators must be visible on all interactive controls.
- Ensure readable spacing, predictable tab order, and screen-reader-friendly labels.
