# Authority profiles

This document defines *authority profiles* (modes) for MMO. Profiles change what the tool is allowed to auto-apply or auto-render, while keeping the truth layer unchanged.

Truth stays truth. Profiles only change *authority*.

## 1) Why profiles exist
Different users want different levels of help:
- Some want coaching and a recall sheet.
- Some want conservative auto-fixes.
- Some want a “just make it sane” autopilot.

Without profiles, the tool either becomes:
- too timid to be useful, or
- too aggressive to be trusted.

Profiles make the tradeoffs explicit.

## 2) Core vocabulary (how MMO expresses authority)
MMO already separates enforcement by **context**:

- **suggest**: show recommendations
- **auto_apply**: apply changes automatically (low risk by default)
- **render**: render variants (must be explicitly invoked)

Gates produce outcomes per context:
- allow
- reject
- suggest_only

Reports expose eligibility flags:
- `eligible_auto_apply`
- `eligible_render`

Profiles should primarily determine how gates behave in each context, plus user-set limits.

## 3) Two classes of rules
To stay safe and predictable, treat rules as two categories:

### 3.1 Hard stops (integrity rules)
These protect the session and outputs. They should remain strict in every profile unless the user explicitly forces unsafe behavior.

Examples:
- invalid schema or registry
- corrupt audio decode
- mismatched sample rates where processing would be misleading
- render would clip and no limiter policy is allowed
- actions that would break alignment or length guarantees

### 3.2 Taste gates (character rules)
These are not “wrong” in art, but can be extreme or style-dependent.

Examples:
- large EQ moves
- heavy broadband compression
- major stereo width changes
- loudness chasing that harms dynamics

Taste gates should be:
- visible
- configurable
- clearly labeled when changes are extreme

## 4) Profiles

### 4.1 Guide (default)
Intent: “Coach me, do not touch anything.”

Behavior:
- All recommendations are produced normally.
- `eligible_auto_apply` is effectively false for everything.
- Render is opt-in, and only allowed when safe and conservative.

User experience:
- clean report
- strong explanations
- recall sheet is the primary output

Best for:
- learning
- sensitive mixes
- professional workflows where the engineer wants manual control

### 4.2 Assist
Intent: “Fix the boring stuff safely.”

Behavior:
- Auto-apply only low-risk actions within strict limits.
- If something exceeds limits, it becomes suggest-only.
- Render is allowed when gated as safe.

Examples of “safe” auto-apply candidates (project-specific and configurable):
- modest gain trims
- DC offset removal
- small surgical moves with strict caps
- metadata fixes that do not touch audio

Best for:
- speeding up routine prep
- consistent safety checks
- quick iteration

### 4.3 Full send
Intent: “Auto-correct broadly, but do not hide the cost.”

Behavior:
- Auto-apply and/or render a wide range of actions.
- Still respects hard stops unless the user explicitly forces unsafe behavior.
- Labels “extreme” changes clearly and records them in an audit trail.
- Preserves originals and supports undo (via manifests and non-destructive outputs).

Best for:
- quick drafts
- idea exploration
- users who want strong defaults and fast results

## 5) Extreme change warnings
Even in Full send, the tool should not pretend extremes are harmless.

Define “extreme” as any recommendation that crosses a configured threshold, for example:
- gain changes beyond X dB
- EQ boosts/cuts beyond Y dB
- compression ratio above Z
- loudness target shifts beyond N LU

Extreme handling should be consistent:
- Always visible in the report (flag + reason + parameter values).
- Always logged in the render manifest when rendering.
- Optional: require explicit confirmation unless the user toggles “allow extremes”.

## 6) How profiles should map onto gates (implementation guidance)
A clean implementation approach is:

- Keep a single canonical `ontology/policies/gates.yaml` as the baseline.
- Add **profile overlays** that modify:
  - enforcement per context (suggest / auto_apply / render)
  - thresholds (or threshold multipliers) for taste gates

This can be expressed as one of:
- a profile YAML that patches gates
- a config file that selects a gate pack
- a “limits” object passed into gating

Important constraints:
- Same inputs/settings must still be deterministic.
- Profile identity must be recorded in the report metadata.
- Gate outcomes must remain traceable to gate IDs and reason IDs.

## 7) Non-destructive guarantee (safety rule)
All profiles should preserve:
- original input files unchanged
- alignment and duration guarantees
- reproducible hashes and manifests

Any applied processing should be:
- rendered as new outputs (variants), not destructive edits
- fully described in a manifest
- reversible by choosing the original stems

## 8) UI expectations (ties into GUI vision)
Profiles must be simple to understand:
- a single mode selector with short descriptions
- a “nerd” view that exposes:
  - per-gate thresholds
  - enforcement mapping
  - which rules are hard stops vs taste gates

See `docs/11-gui-vision.md`.
