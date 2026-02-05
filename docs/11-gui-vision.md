# GUI vision

This document sketches a musician-friendly GUI for MMO. The goal is an interface that feels intuitive, visual, and fast, without burying users in menus.

MMO remains offline-first and deterministic. The GUI is a front-end to the same contracts:
- report JSON (schema-valid)
- exports (PDF/CSV)
- render manifest JSON (schema-valid)

## 1) Design goals
- **Musician-first:** speak in outcomes, not internals.
- **Fast feedback:** show “what matters now” in one screen.
- **Progressive disclosure:** power is available, not forced.
- **No menu labyrinth:** avoid menus within menus.
- **Trustable:** every suggestion is explainable and traceable.
- **Offline:** no accounts, no cloud dependency.
- **Deterministic:** UI does not change meaning, only presentation and configuration.

## 2) Primary user flow (happy path)
1) Select stem folder
2) Validate + assign roles/layout (if needed)
3) Run analysis (meters, checks, issues)
4) Review “Fix plan” (recommendations + gates)
5) Export recall sheet and report
6) Optional: render variants (only if eligible) and export render manifest

## 3) Core screens

### 3.1 Project setup
- Choose stem folder
- Quick validation summary:
  - lossless status
  - sample rate consistency
  - length alignment
  - channel layout detection
- “Fix input problems” guidance when validation fails

### 3.2 Roles and layout
- Drag-and-drop role assignment (DRUMS, BASS, VOCALS, etc.)
- Layout picker for multichannel assets (with safe defaults)
- Preview of inferred mapping with a “confirm” step

### 3.3 Dashboard (one-screen truth)
A single overview should answer:
- Is this safe? (clipping, loudness risk)
- Will it translate? (mono, phone, earbuds, car)
- What are the top issues? (ranked)
- What is safe to auto-apply in my mode?

Suggested widgets:
- Health bar (validation pass/fail + key warnings)
- Loudness + true peak tiles
- Translation grid (rows: profiles, columns: scores / flags)
- Top issues list with severity and confidence
- “Next action” strip (what to do first)

### 3.4 Issue detail
Clicking an issue shows:
- what / why / where / confidence
- evidence breakdown (time ranges, bands, stems involved)
- related recommendations
- “what to listen for” text (practical, short)

### 3.5 Plan view (recommendations + gates)
This is the heart of trust.

Each recommendation card shows:
- action name and risk
- parameters with units
- expected effect + tradeoff
- gate outcomes per context (suggest / auto_apply / render)
- eligibility badges (eligible_auto_apply, eligible_render)

The user can:
- accept/reject suggestions (Guide mode)
- adjust limits (Assist / Full send)
- re-run gating and see eligibility change

### 3.6 Render + variants
Render should feel like exporting variants in a video editor:
- choose which eligible recommendations to render
- choose output folder
- show progress and a final summary
- always write a render manifest
- list skipped items clearly (blocked by gates, with gate IDs)

## 4) Mode selector (authority profiles)
A simple mode switch in the top bar:
- Guide
- Assist
- Full send

Each mode has:
- one-line promise
- a small “what changes” disclosure
- a “learn more” link to the profiles doc (or in-app help)

## 5) Nerd toggle (advanced view)
A single toggle reveals technical detail without cluttering the main UI.

When enabled, show:
- gate IDs and reason IDs
- exact thresholds and current limit values
- policy pack IDs and matrix IDs for downmix
- plugin versions and hashes
- raw meter values and algorithm metadata
- full JSON export links (report and render manifest)

Principle:
- musician view stays clean
- nerd view is transparent and auditable

## 6) Interaction rules (to avoid “menus within menus”)
- Prefer inline panels over nested menus.
- Keep “deep” settings on one dedicated Advanced screen.
- Use search instead of drilling through trees.
- Use “explain” affordances (tooltips or side panels) instead of separate screens.
- Make important actions visible:
  - Export report
  - Export recall
  - Render variants

## 7) Visual language
- Clear status colors and icons for:
  - pass / warn / fail
  - suggest-only vs eligible
- Don’t rely on color alone (accessibility).
- Use consistent scales (0–100 severity, confidence labels).

## 8) Technical architecture (implementation guidance)
A robust approach is a split system:

- **Backend:** existing CLI and core engine (Python)
- **Frontend:** desktop UI that:
  - launches analyses (or calls backend as a subprocess)
  - reads report JSON and render manifest JSON
  - presents results and exports

Keep contracts strict:
- UI should treat JSON schemas as source of truth.
- UI should not invent meaning not present in the report.

## 9) GUI milestones (suggested)
- v1: folder picker + run analysis + show dashboard + export
- v2: role/layout assignment UI + issue drill-down
- v3: plan view + gating visibility + mode selector
- v4: render screen + manifest viewer + skipped explanations
- v5: nerd toggle + full advanced limits editor

## 10) Non-goals (GUI)
- Full DAW timeline editing
- Real-time plugin hosting
- Cloud collaboration requirements