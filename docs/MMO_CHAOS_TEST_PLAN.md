# MMO Chaos Test Plan

## Purpose

This plan exists to test Mix Marriage Offline the way messy humans will.

Not just happy-path users.
Not just fixture-perfect pipelines.
Humans with:

- stale folders
- weird filenames
- missing stems
- duplicate refs
- malformed plugin ideas
- old artifacts lying around
- inconsistent output expectations
- almost-valid inputs that expose semantic drift

The goal is to catch failures where a truth-first, artifact-first,
cross-platform system is most likely to be embarrassed.

---

## Testing Philosophy

MMO is least likely to fail on the clean path.

MMO is most likely to fail where:

- state is stale
- semantics nearly match but not quite
- plugins are technically valid but operationally unsafe
- artifacts exist but disagree
- paths are weird
- compare inputs are malformed
- render preflight receives contradictory evidence

The test strategy should therefore focus on:

- deterministic failure
- useful receipts
- correct pass/warn/block policy behavior
- preservation of canonical truth
- prevention of silent drift

---

## Core Attack Surfaces

### 1. Workspace and artifact truth

Test cases:

- empty workspace folder
- workspace with `report.json` but missing dependent artifacts
- stale `scene.json` after stems changed
- stale `render_manifest.json` from older run
- compare folder without `report.json`
- compare path points to wrong folder shape
- output folders already contain stale files

Expected behavior:

- fail cleanly or skip explicitly
- do not silently reuse incompatible stale truth
- provide deterministic receipts/messages

### 2. Messy stem-folder input

Test cases:

- duplicate filenames that normalize to same semantic stem
- corrupt or empty audio files
- mixed sample rates
- inconsistent channel counts
- hidden junk files in stems folder
- weird unicode, punctuation, spaces, and long names
- partial stem sets
- ambiguous grouping names

Expected behavior:

- validation and analysis remain deterministic
- issues/recommendations are explicit
- no silent collapse into nonsense

### 3. Plugin safety and capability enforcement

Test cases:

- plugin manifest valid but unsupported layout
- bed-only plugin against object-capable scene
- max_channels lower than required channels
- unsupported group sizes
- duplicate plugin IDs across roots
- invalid ontology references in `declares`
- malformed entrypoint
- runtime instance missing expected interface
- layout-specific plugin without supported layouts

Expected behavior:

- early validation failure or precise skip
- plugins never escape declared fences
- no silent plugin takeover or contract weakening

### 4. Render plan stability

Test cases:

- empty render targets
- malformed targets
- duplicate targets
- missing source layout
- routing needed but routing plan absent
- malformed output formats
- invalid contexts
- mixed stereo and multichannel policy edge cases

Expected behavior:

- deterministic failure or deterministic normalization
- stable plan IDs
- no half-valid job generation

### 5. Preflight policy engine

Test cases:

- explicit scene with zero matching refs
- explicit scene with partial overlap below threshold
- duplicate scene stem bindings
- missing source layout
- unavailable matrix
- high correlation risk
- polarity inversion metadata
- very low confidence
- LRA out of range
- true-peak per channel too hot
- translation curve drift high
- rendered-file measured similarity blocks after predicted similarity passed

Expected behavior:

- correct gate ordering
- correct pass/warn/block result
- useful issue payloads
- no contradictory final decision

### 6. Render/transcode output behavior

Test cases:

- renderer returns non-dict manifest
- renderer outputs missing file path
- WAV exists but FFmpeg missing for requested transcodes
- unsupported output format requests
- source artifact missing after claimed success
- metadata embedding partially unavailable
- baseline renderer duplicate suppression regressions
- malformed transcode metadata receipt handling

Expected behavior:

- deterministic skipped entries
- coherent manifests
- no silent false success

### 7. Compare abuse tests

Test cases:

- compare against folder without `report.json`
- compare directory passed where file expected
- compare missing `render_qa`
- compare missing mix complexity
- compare missing downmix QA
- compare output-format mismatch
- compare large loudness compensation need
- compare translation risk shift upward
- compare extreme recommendation count jump

Expected behavior:

- notes and warnings stay honest
- unavailable data does not become fake precision
- compare hints remain useful

---

## Recommended Implementation Order

### Phase 1: Deterministic logic tests

1. Preflight gate tests
2. Renderer gating / plugin safety tests
3. Compare abuse tests

### Phase 2: Structured fixture chaos

1. Render plan edge-case tests
2. Workspace / stale-artifact fixture tests
3. Stem-folder fixture tests

### Phase 3: Real-world Linux run

1. Build MMO for Linux
2. Run against a real test folder
3. Execute `validate -> analyze -> scene -> preflight -> render -> compare`
4. Inspect artifacts and UX behavior for real-world drift

---

## First Test Batch To Implement

### A. Preflight tests

Cover:

- explicit scene overlap block/warn/pass
- confidence low / very low
- phase risk
- correlation risk
- translation curve bounds
- true-peak per channel
- measured similarity present vs absent

### B. Renderer gating tests

Cover:

- plugin max channel rejection
- topology unsupported rejection
- bed-only scene filtering
- layout-specific bypass
- baseline renderer duplicate suppression
- missing FFmpeg transcode skip behavior

### C. Compare abuse tests

Cover:

- missing `report.json`
- wrong compare input shape
- missing render QA behavior
- loudness-match unavailable path
- notes/warnings on translation risk and extreme count changes

---

## Success Criteria

The chaos suite is doing its job if it proves that MMO:

- fails loudly instead of lying quietly
- preserves canonical truth under messy input
- blocks render when policy says block
- records why work was skipped
- never lets plugins exceed declared authority
- does not fabricate compare confidence from missing data
- remains deterministic even when inputs are ugly

---

## Final Principle

MMO should not merely work when the user behaves well.

MMO should stay trustworthy when the user behaves like a tired, disorganized,
overly optimistic human who swears the folder is "basically right."
