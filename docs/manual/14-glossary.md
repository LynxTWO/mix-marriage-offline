# Glossary

MMO uses consistent terms so the tool stays explainable.

Artifact.
A file MMO writes that has a strict schema (report.json, scene.json, render_plan.json, receipt.json).

Authority mode.
A policy level that decides what can be auto-applied (Guide, Assist, Full Send, Turbo).

Bounded authority.
MMO can recommend anything, but only auto-applies low-risk actions unless you approve more.

Deliverables.
Output files intended for delivery, often in multiple layouts and channel-ordering standards.

Deterministic.
Same inputs plus settings produce the same outputs.

Downmix.
A deterministic fold-down from one layout to another using a known policy.

Gate.
A safety rule that can warn, block, or force fallback behavior.

Layout standard.
A named channel ordering convention (SMPTE, FILM, LOGIC_PRO, VST3, AAF).

Lock.
A “do not violate this intent” constraint stored in scene intent (example: preserve dynamics).

Preset.
A curated run_config patch that aims at a workflow goal or vibe direction.

Receipt.
A JSON log of what happened in a run, including what changed and what was blocked.

Render-many.
Analyze once, then render multiple targets and standards from the same source truth.

Scene.
A layout-agnostic intent artifact that can be rendered to multiple targets.

Stem.
An exported audio file representing a component of a mix, aligned in time with other stems.

Translation.
A set of checks that estimate how the mix behaves on playback systems (phone, earbuds, car, mono).