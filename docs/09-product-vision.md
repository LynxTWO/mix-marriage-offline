# Product vision

This document describes the long-term product goal for Mix Marriage Offline (MMO): make mixing feel as approachable as modern video editing tools, while staying offline, deterministic, and explainable.

MMO is not “AI that mixes your song for you.”  
MMO is a technical co-pilot that makes *good engineering* easier, so humans can stay focused on vibe and intent.

## Scene-first / render-many note

MMO stores mix intent as a scene, then renders that scene to one or more targets (stereo, 5.1, and beyond). Stereo is one target in the render set rather than a universal source of truth when stems plus intent exist.

See:
- [PROJECT_INSTRUCTIONS.md](PROJECT_INSTRUCTIONS.md)
- [SCENE_AND_RENDER_CONTRACT_OVERVIEW.md](SCENE_AND_RENDER_CONTRACT_OVERVIEW.md)

## 1) The promise: “vibe mixing”
Mixing is two jobs:
- **Engineering:** gain staging, loudness safety, masking, translation, downmix integrity, phase risk
- **Art:** story, emotion, hierarchy, texture, space, taste

MMO’s product promise:
- The tool relentlessly handles the technical math.
- The user stays in control of meaning and style.
- The tool can run in different **modes**, from “coach me” to “just fix it”, without becoming a black box.

The outcome should feel like what video editing did for non-editors:
- fast feedback
- clear visuals
- safe defaults
- powerful options available when you want them
- no hidden actions

## 2) Target users
MMO should work for a spectrum of users:

- **Musician / producer (not a mix engineer yet)**
  - wants a clear path to “this translates”
  - wants simple, understandable choices
  - wants fast wins without learning 100 plugins first

- **Intermediate mixer**
  - wants rigorous checks and a structured plan
  - wants to move faster and miss fewer mistakes
  - wants DAW-agnostic recall that is easy to apply

- **Experienced engineer**
  - wants a second set of meters and validation that does not lie
  - wants reproducible workflows and regression-safe checks
  - wants downmix translation QA and layout-aware sanity checks

- **Surround / immersive workflows**
  - wants deterministic downmix matrices and QA
  - wants “will this fold correctly?” answered with evidence
  - wants policy packs and known conversions that are testable

## 3) What users should be able to do (user stories)

### 3.1 Session health (stems in, truth out)
- As a user, I can point MMO at a stem folder and quickly learn:
  - are files aligned, same length, same sample rate, lossless
  - what’s clipping or close to clipping
  - what’s loudness-risky or translation-risky
  - where the obvious technical problems are (with evidence)

### 3.2 A plan I can trust (issues → actions → gates)
- As a user, I get a ranked list of issues with:
  - what, why, where, confidence
- As a user, I get action recommendations with:
  - explicit parameters + units
  - expected effect + tradeoffs
  - risk level
  - gate outcomes per context (suggest / auto-apply / render)

### 3.3 Translation checks that feel practical
- As a user, I can run translation profiles (mono, phone-like, earbuds-like, car-like) and see:
  - what got worse, what improved
  - where the problem shows up
  - what actions would help (without forcing them)

### 3.4 Downmix integrity (surround → stereo reference)
- As a user, I can compare a downmix fold against a stereo reference and get:
  - LUFS / true peak / correlation deltas
  - issues if deltas exceed thresholds
  - a clear indication if a render should be blocked (fail) vs allowed (warn)

### 3.5 Render variants without breaking trust
- As a user, I can optionally render conservative variants:
  - only when eligible under gates
  - never clipping by default
  - always keeping originals intact
  - always producing a manifest that says what happened

## 4) Modes (high level)
MMO should support clear modes that change *authority*, not truth.

- **Guide:** measure + explain + suggest only  
- **Assist:** auto-apply low-risk fixes within strict limits, suggest the rest  
- **Full send:** auto-apply broadly, warn when changes are extreme, still preserve audit + undo

Details live in `docs/10-authority-profiles.md`.

## 5) What “done” looks like (product outcomes)
A successful MMO run should produce:

- **Report JSON** (schema-valid, deterministic)
- **Human exports**
  - PDF report
  - CSV recall sheet
- **Optional rendering outputs**
  - rendered stem variants (opt-in)
  - render manifest JSON (what ran, what was skipped, why)

The user should be able to answer:
- “What is wrong?”
- “How sure are you?”
- “What do you recommend?”
- “What is safe to apply automatically in my chosen mode?”
- “What should I check next if something is blocked?”

## 6) Product principles
These are non-negotiable:

- **Offline-first:** no cloud dependency
- **Deterministic:** same inputs + settings → same outputs
- **Explainable:** every decision cites evidence and IDs
- **Bounded authority:** defaults are conservative
- **No silent character changes:** big moves must be explicit (or clearly opted into)
- **DAW-agnostic:** recall sheet is the bridge back to any workflow

## 7) Non-goals (for now)
- Becoming a DAW
- Proprietary Atmos replacement claims
- “One button makes it a hit”
- Black-box ML that overrides meters, gates, or schema contracts

## 8) Glossary (product language)
- **Issue:** a measurable problem with evidence
- **Recommendation:** an action with explicit parameters
- **Gate:** a rule that determines eligibility in a context
- **Context:** suggest / auto_apply / render
- **Mode:** a user-facing authority profile that changes what the tool may auto-do
