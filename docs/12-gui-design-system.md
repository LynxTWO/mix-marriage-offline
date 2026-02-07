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

## Screen templates

### Dashboard

Purpose: Dashboard is the default orientation screen. It should answer "how this mix feels," "is it safe," and "what should I do next" within a few seconds, without requiring technical interpretation.

Primary components:
- Vibe Signals
- Safety
- Deliverables
- Next Actions

Default view vs Nerd view:
- Default: summary cards for Vibe Signals, Safety status, deliverables readiness, and suggested next actions.
- Nerd: reveal technical diagnostics and policy-level detail behind the same cards.

States:
- Success: safety checks clear, deliverables are ready, and next action is optional refinement.
- Warning: one or more signals are risky; show targeted fix path and expected impact.
- Blocked: render or publish path is blocked; show exact blocker and shortest unblock sequence.

Example copy:
- "Safety looks good. Your vibe is intact and deliverables are ready to render."

### Presets

Purpose: Presets is the exploration and decision screen. It helps the user browse likely sonic directions, preview outcomes safely, and understand what each preset changes before applying it.

Primary components:
- Preset browse and filter controls
- Preset preview panel with inline help
- "What this changes" summary
- Apply and Run actions

Default view vs Nerd view:
- Default: outcome-first preset labels, short preview notes, and a plain-language impact summary.
- Nerd: reveal underlying parameter deltas, policy references, and threshold details.

States:
- Success: preset is previewed, understood, and ready to apply or run.
- Warning: preset may push a risky region; show the specific risk and safer alternatives.
- Blocked: preset cannot be applied due to hard constraints; show required preconditions.

Example copy:
- "This preset adds width and air while keeping vocals forward."

### Run

Purpose: Run is the execution control surface. It lets users choose steps and output formats, monitor progress, and understand whether cached results are being reused.

Primary components:
- Step toggles
- Output format selectors
- Progress timeline or meter
- Cache status indicators

Default view vs Nerd view:
- Default: clear run stages, high-level progress, and plain cache messaging.
- Nerd: reveal per-stage timings, cache keys, and detailed execution metadata.

States:
- Success: run completed with expected outputs and no blockers.
- Warning: run completed with caveats; show impacted outputs and mitigation steps.
- Blocked: run cannot continue; show the blocking condition and recovery action.

Example copy:
- "Run finished. We reused cached analysis so you can render faster."

### Results

Purpose: Results is the delivery and interpretation screen. It presents final outputs, guides listening checks, flags extreme states, and gives clear export actions.

Primary components:
- Deliverables cards
- Audition guidance
- Extreme flags
- Export buttons

Default view vs Nerd view:
- Default: highlight deliverables, listen guidance, and recommended export path.
- Nerd: reveal measurement traces, IDs, and threshold rationale behind each result.

States:
- Success: deliverables pass checks and are ready to export.
- Warning: outputs are usable with caveats; show what to review before release.
- Blocked: deliverable is not exportable; show exact fix path.

Example copy:
- "Try the reference chorus first; it is where width and punch changed most."

### Compare

Purpose: Compare is for A/B decision support. It should make differences visible quickly, summarize what changed objectively, and surface warnings without judging the user's taste.

Primary components:
- A/B selection controls
- Objective difference summary
- Warning indicators
- "What changed" narrative summary

Default view vs Nerd view:
- Default: plain-language change summary and key outcome differences.
- Nerd: reveal metric-level diffs, detector IDs, and threshold-level comparisons.

States:
- Success: differences are clear and decision is straightforward.
- Warning: differences include safety or translation risk; show specific context.
- Blocked: comparison cannot run due to missing or incompatible inputs.

Example copy:
- "Version B feels wider and brighter, with similar loudness and safer headroom."

## Copy glossary

Preferred terms:
- Vibe
- Signals
- Deliverables
- Safety
- Extreme
- Preview
- Compare
- Apply
- Render
- Why

Avoid or translate:
- `LUFS` -> `Loudness` (Nerd label: `LUFS`)
- `Correlation` -> `Stereo coherence` (Nerd label: `Correlation`)
- `Gate` -> `Safety check` (Nerd label: `Gate`)

Examples:
- Use: "Safety check blocked this."
- Avoid: "Gate failed."

## Micro-interactions

Hover help rules:
- Every help target must show a short definition and one "why it matters" line.
- Help text should be visible on hover and accessible by keyboard focus.

Animation rules:
- Keep transitions subtle and short (150-250 ms target).
- Never use animation that competes with primary task focus.
- Respect reduced-motion preferences by reducing or removing motion.

Feedback rules:
- Always show run progress for background or multi-step actions.
- Always show what changed after apply/run/compare actions.
- Always show why a warning or block happened.

Badge rules:
- `EXTREME`: output is intentionally or measurably pushed beyond normal-safe bounds.
- `BLOCKED`: action cannot continue until a hard precondition is resolved.
- `SAFE`: checks passed for the relevant action or deliverable.
- `INFO`: neutral context that is useful but not a warning.

Compare rules:
- Highlight objective differences instantly.
- Use non-judgment language; describe differences without calling one "better."

## Accessibility rules

- Contrast minimum: WCAG AA baseline (4.5:1 for normal text, 3:1 for large text).
- Do not rely on color alone; pair color with text labels or icons.
- Minimum body text size is 16 px; avoid critical text below 14 px.
- Full keyboard navigation required for primary workflow paths.
- Focus indicators must be visible on all interactive controls.
- Ensure readable spacing, predictable tab order, and screen-reader-friendly labels.
