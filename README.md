# Mix Marriage Offline (MMO)

An open-source, offline mixing assistant that handles the technical math so humans can focus on vibe, intent, and performance.

MMO is a standalone tool that analyzes exported stems in a folder and produces:
- A ranked list of technical issues with evidence
- DAW-agnostic recommendations (a recall sheet you can apply anywhere)
- Translation checks (stereo, mono, phone, earbuds, car-like curves)
- Optional conservative rendered stem variants (explicit invoke only)
- A modular plugin system so strategies can evolve without breaking the core

This is not a DAW plugin. This is not “AI that mixes your song for you.”  
It is a technical co-pilot that keeps the engineering side honest, so the human can stay artistic.

---

## Why this exists
Mixing is two jobs wearing one hat:
- Objective engineering: gain staging, loudness safety, masking, resonances, dynamics, translation
- Subjective art: mood, texture, space, hierarchy, energy, emotional story

When one person must do both, something gets compromised. Usually it is the technical details or the creative intent. Sometimes both.

MMO’s promise:
- The machine handles the technical chores relentlessly
- The human decides what the music means

## Install
Core install:
```
pip install .
```

Optional extras:
```
pip install .[pdf]
pip install .[truth]
```

---

## Supported formats
- WAV (.wav/.wave) is always supported.
- FLAC (.flac) and WavPack (.wv) are supported when ffprobe/FFmpeg is available (or MMO_FFPROBE_PATH is set).
- AIFF (.aif/.aiff) is not supported yet; export WAV for now.
- Lossy formats (MP3/AAC/Ogg/Opus) will trigger warnings; re-export lossless for reliable analysis.

---

## Start here
- Proposal: `docs/00-proposal.md`
- Philosophy: `docs/01-philosophy.md`

If you want to contribute early, these two docs define the spine of the project.

---

## Core ideas
### Objective core vs subjective plugins
MMO keeps two worlds separate on purpose:

**Objective Core (truth layer)**
- metering, validation, translation checks, safety gates, strict schemas
- deterministic and heavily tested

**Subjective Plugins (strategy layer)**
- detectors, resolvers, renderers, profiles
- fast-evolving and swappable

### Ontology-first
Open source projects fall apart when contributors cannot agree on terms. MMO uses a shared vocabulary defined in YAML:
- roles, features, issues, actions, parameters, units, evidence fields

Internal variable names can vary, but anything leaving a plugin uses canonical IDs.

### Bounded authority
The tool can recommend anything, but it only auto-applies low-risk actions within user limits. High-impact moves require explicit approval.

---

## Workflow (planned)
1) Export stems from any DAW using simple rules:
   - all stems start at 0:00
   - same sample rate and bit depth
   - consistent length
   - consistent naming roles (or assign roles in-app)
2) Point MMO at the folder
3) MMO validates, measures, detects issues, proposes actions, applies safety gates
4) MMO exports:
   - report (PDF + JSON)
   - recall sheet (CSV/TXT)
   - optional rendered stem variants

Optional conservative render (explicit invoke):
```
PYTHONPATH=src python tools/analyze_stems.py ./stems --out-report examples/demo_run/out.json --peak --render-gain-trim-out rendered
```

---

## Surround and immersive audio
Surround is a long-term goal. MMO aims to reduce the learning curve by baking in:
- channel layout awareness (2.1, 5.1, 7.1, 7.1.4, etc.)
- channel-group measurement (front stage, surrounds, heights, LFE)
- downmix translation checks (surround to stereo/mono)
- common immersive risk detection

Note: Dolby Atmos involves licensing and proprietary tooling. MMO will focus on open, practical workflows and translation QA without claiming to replace official renderers.

---

## Downmix matrices
Resolve downmix matrices deterministically from the policy registry:
```
mmo downmix show --source LAYOUT.5_1 --target LAYOUT.2_0 --format csv
```
This command only computes the matrix; it does not render audio.
List available layouts, policies, and conversions:
```
mmo downmix list
mmo downmix list --policies
```

## Downmix QA
Compare a folded downmix against a stereo reference:
```
mmo downmix qa --src path/to/5.1.flac --ref path/to/ref_stereo.flac --source-layout LAYOUT.5_1 --format json
mmo downmix qa --src path/to/5.1.flac --ref path/to/ref_stereo.flac --source-layout LAYOUT.5_1 --format csv > qa.csv
mmo downmix qa --src path/to/5.1.flac --ref path/to/ref_stereo.flac --source-layout LAYOUT.5_1 --format pdf --out qa.pdf
```
Emit a standard MMO report that embeds the QA payload and then export it:
```
mmo downmix qa --src 5.1.flac --ref ref_stereo.flac --source-layout LAYOUT.5_1 --meters truth --emit-report qa_report.json
mmo export --report qa_report.json --pdf qa_report.pdf
```
This produces a standard MMO report with an extra Downmix QA section.
Setting `--max-seconds <= 0` compares the full overlap, which can be heavy for truth meters on long files.
PDF export requires `pip install .[pdf]`.

---

## Repo layout (planned)
Right now we are building docs and the ontology first.

```
docs/       Project docs (proposal, philosophy, architecture, roadmap)
ontology/   YAML source of truth (roles, features, issues, actions, policies)
schemas/    JSON schemas for project/report/plugin I/O
src/        Core engine and CLI (later)
plugins/    Community detectors/resolvers/renderers (later)
fixtures/   Test sessions for regression testing (later)
tests/      Automated tests (later)
```

---

## Status
Early-stage design and scaffolding. We are building the foundation first:
- shared ontology (YAML source of truth)
- strict schemas and validators
- fixtures and deterministic pipeline

If you are reading this early: perfect. This is the time to shape it.

---

## Contributing
Contributions we expect to need (soon):
- ontology additions and cleanup (IDs, definitions, policies)
- fixture sessions and regression tests
- detectors and resolvers (as plugins)
- documentation, especially export guides for common DAWs

When the contributor docs land, start with:
- `CONTRIBUTING.md`
- `docs/04-plugin-api.md`
- `docs/05-fixtures-and-ci.md`

---

## License
Apache-2.0. See `LICENSE`.
