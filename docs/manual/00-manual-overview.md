# MMO User Manual

If the steps are not repeatable, the tool is not helping.  
MMO is built for repeatable results.

This manual tracks the current repository build.

MMO has two audiences at once.
Beginners want a safe button that outputs clear next steps.
Pros want receipts, deterministic behavior, and export contracts that survive delivery.

This manual uses two rails in the same chapter.
“Quick path” is the shortest safe set of steps.
“Pro notes” adds the reasoning, gotchas, and knobs.

Conventions used here.
CLI examples use `mmo ...` (installed) and also work as
`python -m mmo ...` (repo checkout).
Paths are examples. Replace them with your own.
Targets can be written as full IDs (like `TARGET.STEREO.2_0`) or as
shorthands (like `stereo`, `5.1`, `7.1.4`).

MMO is offline-first.
If something needs an external tool like FFmpeg, MMO will tell you and gate the
feature instead of guessing.

MMO is deterministic by default.
Same stems + same config + same version should produce the same artifacts.

What this manual does not cover.
This is not a DAW training course.
This does not try to teach “taste.”
MMO does not claim to replace proprietary Atmos renderers.

Where to go deeper.
For DAW export recipes, read `docs/07-export-guides.md`.
For architecture and contracts, read `docs/02-architecture.md`,
`docs/15-target-selection.md`, and `docs/18-channel-standards.md`.
For plugin authoring, read `docs/13-plugin-authoring.md`.
