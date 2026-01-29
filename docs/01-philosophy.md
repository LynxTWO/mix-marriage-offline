# docs/01-philosophy.md

## Mix Marriage Offline Philosophy
### Truth meters in the core. Taste in the plugins. Humans keep the meaning.

---

## 1) The north star
Mixing is both **engineering** and **art**.

- Engineering answers: “Is this stable, safe, and translating?”
- Art answers: “What does this feel like? What story does it tell?”

When one person has to hold both jobs at once, something gets compromised.  
This project exists to make that compromise optional.

**North star:**  
The machine handles the technical math relentlessly.  
The human focuses on intent, vibe, and performance.  
No guesswork. No magical black boxes. No silent changes.

---

## 2) What this project believes (and enforces)

### 2.1 Objective core vs subjective strategy
We keep two worlds separate on purpose:

**Objective Core (truth layer)**
- Metering (LUFS, true peak, spectral energy, correlation, etc.)
- Validation (stem alignment, sample rate consistency, length checks)
- Translation checks (downmix, mono, phone, etc.)
- Safety gates (no clipping, bounded processing, required evidence)
- Schemas (strict, validated I/O)

**Subjective Strategy (plugin layer)**
- Detectors (how to interpret features into “issues”)
- Resolvers (how to propose fixes)
- Renderers (how to apply actions to produce variants)
- Profiles (genre and taste preferences, intent mappings)

The core is conservative, deterministic, and heavily tested.  
Plugins are where experimentation and style can evolve.

This separation is how we avoid “one house sound” while still keeping quality high.

---

## 3) Bounded authority
The tool is an assistant, not a dictator.

It can:
- measure
- warn
- explain
- propose
- and optionally render conservative variants

It must not:
- rewrite the user’s artistic intent
- apply large changes silently
- chase a curve at all costs
- optimize for loudness while sacrificing meaning

### Default rule
- Low-risk changes may be auto-applied *inside strict user limits*.
- High-impact changes always require approval.

“High impact” includes, by default:
- large EQ moves
- broadband tonal shifts
- heavy compression
- mix-bus processing
- anything that is likely to change character rather than stability

---

## 4) Explainability is non-negotiable
Every issue must have:
- **what**: name and type
- **why**: a plain-English rationale
- **where**: evidence (time range, frequency range, involved stems)
- **confidence**: low/medium/high
- **impact**: what it affects (fatigue, intelligibility, translation, etc.)

Every recommendation must have:
- **parameters**: explicit values with units
- **risk**: low/medium/high
- **expected effect**: what should improve and what tradeoff might occur
- **gates**: whether it is allowed under the user’s current safety limits

If the tool cannot explain it, it should not do it.

---

## 5) Determinism and reproducibility
This is a technical tool. It has to be repeatable.

Given the same stems and the same settings, the system should produce the same output.

Reports include:
- core engine version
- ontology version
- plugin versions and hashes
- settings
- stem checksums

This prevents:
- “works on my machine”
- argument-by-vibes
- invisible regressions
- support chaos

---

## 6) Ontology-first: a shared language
Open source projects fail when contributors can’t agree on terms.

We solve that by defining a canonical vocabulary:
- roles
- features
- issues
- actions
- parameters
- units
- evidence fields

Internal variable names can vary.  
But anything leaving a plugin must use the canonical IDs.

Why this matters:
- plugins interoperate
- reports stay consistent
- fixtures stay testable
- contributors don’t fight over naming

---

## 7) Fixtures and gates: how quality stays high
### 7.1 Fixtures
We maintain a library of known test sessions (fixtures) that intentionally contain:
- mud
- harshness
- masking
- mono collapse
- sub-only bass (phone translation fail)
- surround downmix intelligibility loss
- etc.

They function as:
- regression tests
- benchmarks
- contributor onboarding tools

### 7.2 Safety gates
Gates are non-negotiable rules enforced by the core, regardless of plugin creativity.

Examples:
- don’t clip rendered stems by default
- don’t exceed user-defined max EQ change
- don’t apply mix-bus actions unless explicitly enabled
- require evidence fields for every issue
- reject action plans that violate the schema

This is how we can welcome experimental plugins without ruining trust.

---

## 8) The tool doesn’t chase perfection. It chases coherence.
Perfection is genre-dependent, context-dependent, and taste-dependent.

This tool is not trying to create “the correct mix.”

It’s trying to create:
- stable gain structure
- reduced fatigue
- clear hierarchy (when requested)
- fewer translation surprises
- consistent loudness behavior
- fewer technical landmines

The human decides whether the mix should feel:
- intimate or cinematic
- clean or gritty
- restrained or violent
- warm or clinical
- wide or focused

The machine helps the mix stay coherent inside those decisions.

---

## 9) Surround and immersive philosophy
Surround becomes manageable when:
- layouts are first-class metadata
- channel groups are measured explicitly
- downmix survival is tested automatically
- common pitfalls are flagged early

The goal is not “surround purity.”  
The goal is **immersive intent that still survives real-world playback**.

We treat downmix checks as translation checks:
- 5.1 → stereo
- 7.1.4 → 5.1
- immersive → headphones

If a surround mix collapses into nonsense when folded down, the tool should catch it.

Note: We aim to support practical, open workflows. Dolby Atmos rendering and licensing constraints are respected. The tool can be Atmos-friendly without pretending to replace Dolby’s ecosystem.

---

## 10) The role of ML (if used at all)
Machine learning can help later with:
- better ranking
- better masking prediction
- better “what fix is least destructive” estimation

But the foundation is:
- deterministic DSP
- validated meters
- measurable fixtures
- transparent logic

ML should be additive, not required, and never a black box that overrides the truth layer.

---

## 11) Community values
- Be rigorous and humble.
- Prefer testable changes over cleverness.
- Keep the core stable.
- Let plugins be creative.
- Document everything that affects output.
- Don’t ship “cool,” ship “trustworthy.”

---

## 12) Summary
Mix Marriage Offline is built around a simple promise:

**Truth meters in the core. Taste in the plugins. Humans keep the meaning.**

If we protect that separation, this can become a living, open tool that helps thousands of creators make better mixes without burning their taste-budget on technical chores.
