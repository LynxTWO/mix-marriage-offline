# MMO User Manual

If the steps are not repeatable, the tool is not helping.  
MMO is built for repeatable results.

This manual tracks the current repository build.

MMO has two audiences at once. Beginners want a safe button that outputs clear
next steps. Pros want receipts, deterministic behavior, and export contracts
that survive delivery.

This manual uses two rails in the same chapter. “Quick path” is the shortest
safe set of steps. “Pro notes” adds the reasoning, gotchas, and knobs.

Plain-language glossary:

- `stems folder`: the exported audio tracks from your DAW
- `workspace`: MMO's notebook folder for reports, scenes, renders, and receipts
- `scene`: the placement plan, like a stage plot for your mix
- `receipt`: the render packing slip that explains what changed and why

Conventions used here. CLI examples use `mmo ...` (installed) and also work as
`python -m mmo ...` (repo checkout). Paths are examples. Replace them with your
own. Targets can be written as full IDs (like `TARGET.STEREO.2_0`) or as
shorthands (like `stereo`, `5.1`, `7.1.4`).

GUI screenshots in this manual are canonical captured states. They orient you
to one stable app moment, not every possible sidebar or panel arrangement.
Native OS dialogs such as folder pickers and file pickers are described in text
because they vary by platform and are not part of the canonical app baseline.
Contributor refresh policy and screenshot inventory live in
[assets/screenshots/README.md](assets/screenshots/README.md).
The desktop app also includes a documented keyboard path with visible focus
states; see [Desktop GUI walkthrough](10-gui-walkthrough.md) for the current
shortcut list and panel-navigation rules.

MMO is offline-first. If something needs an external tool like FFmpeg, MMO will
tell you and gate the feature instead of guessing.

MMO is deterministic by default. Same stems + same config + same version should
produce the same artifacts.

What this manual does not cover. This is not a DAW training course. This does
not try to teach “taste.” MMO does not claim to replace proprietary Atmos
renderers.

Where to go deeper. For DAW export recipes, read `docs/07-export-guides.md`. For
architecture and contracts, read `docs/02-architecture.md`,
`docs/15-target-selection.md`, and `docs/18-channel-standards.md`. For plugin
authoring, read `docs/13-plugin-authoring.md`.
