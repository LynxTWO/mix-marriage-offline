# docs/00-proposal.md

## Mix Marriage Offline
### An open-source, offline mixing assistant that handles the technical math so humans can focus on vibe, intent, and performance.

---

## 1) What this is
Mix Marriage Offline is a standalone desktop tool that analyzes exported stems in a folder and outputs:

- A ranked list of technical issues (with evidence).
- Clear, DAW-agnostic recommendations (a recall sheet you can apply anywhere).
- Optional “safe” rendered stem variants (conservative by default).
- Translation checks (stereo, mono, phone, earbuds, car-like curves).
- A modular plugin system so the community can swap in better detectors, strategies, and renderers over time.

This is not a DAW plugin. This is not “AI that mixes your song for you.”  
It’s a **technical co-pilot** that keeps the engineering side honest, so the human can stay artistic.

---

## 2) Why this matters
Mixing is two jobs wearing one hat:

**Objective engineering**  
Gain staging, loudness, clipping safety, masking, resonances, dynamics control, translation.

**Subjective art**  
Mood, texture, space, hierarchy, energy, emotional story.

When one person must do both, something gets compromised. Usually it’s the technical details or the creative intent. Sometimes both.

The goal here is simple:

**Never compromise on technical quality.**  
Let the machine do the math chores relentlessly.  
Let the human decide what the music means.

---

## 3) What problem we are solving

### The pain
- DAW integration is fragile and slow to build.
- Many “auto” tools chase a curve or a loudness target and flatten character.
- Technical quality control is tiring and repetitive.
- Surround mixing is a steep learning curve and feels inaccessible to most creators.

### The opportunity
If we make the technical layer:

- repeatable,
- transparent,
- conservative by default,
- and easy to extend,

then mixing becomes more about intent and less about fighting the process.

---

## 4) Key principles

### 4.1 Objective core vs subjective strategy
We separate the system into two worlds:

**Objective Core (truth layer)**  
Meters, validation, analysis, translation checks, safety gates. This is deterministic and heavily tested.

**Subjective Plugins (strategy layer)**  
Detectors, resolvers, renderers, profiles. These can evolve fast and be swapped without breaking the core.

### 4.2 Bounded authority
The tool can recommend anything, but it only auto-applies low-risk actions inside user-defined limits. High-impact moves require explicit approval.

### 4.3 Explainability
Every issue and recommendation must include:
- what it is,
- why it matters,
- where it happens (time + frequency + tracks),
- how confident the system is.

No black box vibes.

### 4.4 Reproducibility
Given the same stems and settings, the system should produce the same results. Reports include:
- engine version,
- ontology version,
- plugin versions/hashes,
- settings,
- stem checksums.

### 4.5 Open source by design
This is meant to be a “living instrument.”
- DSP experts improve meters and analysis.
- Mix engineers improve strategies and profiles.
- QA people harden fixtures and regression tests.
- Surround nerds contribute downmix policies and immersive checks.

---

## 5) How it works (high level)

### Input
You export stems from any DAW, using simple rules:
- all stems start at 0:00
- same sample rate/bit depth
- consistent length
- consistent naming roles (or assign roles in-app)

Put stems in a folder and point the tool at it.

### Pipeline
1) Validate stems and metadata.
2) Assign roles and build virtual buses (drums, vocals, music, mix).
3) Measure core features (LUFS, true peak, spectral bands, dynamics stats).
4) Detect issues (mud, harshness, resonances, masking, mono risks, etc.).
5) Generate recommendations (multiple options when appropriate).
6) Apply safety gates (reject unsafe plans by default).
7) Export results (PDF/JSON + recall CSV). Optional: render safe stem variants.

---

## 6) Outputs

### 6.1 Report (PDF + JSON)
- Ranked issue list with evidence
- Stem and bus diagnostics
- Recommendations with parameters, risk level, and rationale
- Translation test results and “most likely failures”

### 6.2 Recall sheet (CSV/TXT)
DAW-agnostic instruction list:
- track/stem identifier
- action type (e.g., EQ bell cut)
- parameters (freq/Q/gain)
- time/frequency evidence
- priority and risk level

### 6.3 Optional rendered stems
Conservative processing variants:
- `<original>__MMO_v1.wav`
- sample-aligned and length-matched
- no clipping by default
- intended for audition and fast iteration

---

## 7) Surround and immersive audio (long-term goal)
Surround mixing is powerful but technically intimidating. This tool aims to reduce the barrier by baking in:
- channel layout awareness (2.1, 5.1, 7.1, 7.1.4, etc.)
- channel-group measurement (front stage, surrounds, heights, LFE)
- downmix translation checks (surround → stereo/mono)
- common immersive risks (dialogue focus, LFE misuse, phase/cancellation, height smear)

Important note: Dolby Atmos itself involves licensing and proprietary tooling. This project will focus on open, practical workflows (channel-based layouts, downmix QA, metadata-friendly interchange where feasible) without claiming to replace official renderers.

---

## 8) What makes this different from “auto mastering” tools
- It is mix-first and stem-aware, not just a final stereo file processor.
- It is intent-constrained, not curve-chasing.
- It is transparent and testable.
- It is modular so the community can swap strategies.
- It supports surround thinking as a first-class concept.

---

## 9) Who this is for
- Mixers who want faster technical QA and better translation.
- Artists who want the technical layer handled so they can focus on performance and vibe.
- Developers and DSP nerds who want to build something meaningful and measurable.
- Surround-curious creators who want guardrails and truth meters.

---

## 10) Planned milestones (short version)
- **M0:** Repo, docs, ontology YAML, schemas, plugin host skeleton.
- **M1:** Validation + metering truth layer.
- **M2:** Core stereo issue detectors + conservative recommendations + recall export.
- **M3:** Translation profiles + scoring.
- **M4:** Optional safe stem rendering.
- **M5:** Surround foundation (layouts + downmix QA + first immersive detectors).

See `docs/06-roadmap.md` for the detailed plan.

---

## 11) How to contribute
This project welcomes:
- New detectors (issues + evidence + severity scoring).
- New resolvers (strategy plugins that turn issues into action plans).
- Better meters and analysis (core changes require strong review).
- Fixture sessions and regression tests.
- Documentation and export guides.

Start here:
- `docs/04-plugin-api.md`
- `docs/05-fixtures-and-ci.md`
- `CONTRIBUTING.md`

---

## 12) Status
Early-stage design and scaffolding. We are building the foundation first:
- shared ontology (YAML source of truth)
- strict schemas and validators
- test fixtures
- deterministic analysis pipeline

If you’re reading this early: perfect. This is the time to shape it.
