# MMO Release Announcement Templates

Copy-paste templates for GitHub release notes, social posts, and longer release
announcements.

These templates are intentionally generic so future releases do not drift back
into outdated "foundation only" language.

## Release Writer Guardrails

Always lead with shipped behavior from the current repo, not old roadmap text.

Good claims to reuse when they are still true:

- deterministic analysis and delivery artifacts
- scene-first, mix-once/render-many workflows
- compare workflow with `compare_report.json`
- supported channel-ordering standards: `SMPTE`, `FILM`, `LOGIC_PRO`, `VST3`,
  `AAF`
- binaural/headphone preview and first-class headphone target
- Tauri desktop app as the packaged desktop app path
- legacy `mmo-gui` as a deprecated compatibility shell only

Do not claim these are complete unless the repo status says so:

- complete packaged desktop smoke coverage
- replacement of proprietary/licensed Atmos renderers

## GitHub Release Notes Template

Release title: `Mix Marriage Offline v[VERSION] - [SHORT TAGLINE]`

Mix Marriage Offline is an offline, deterministic mixing assistant for analysis,
scene-first delivery, compare, and mix-once/render-many workflows.

### What ships today

- **Deterministic contracts** - analysis, scene, render, receipt, and compare
  artifacts stay explainable and automation-friendly.
- **Mix-once/render-many delivery** - one scene can drive multiple targets and
  channel-ordering standards in a bounded render flow.
- **Compare workflow** - `mmo compare` writes `compare_report.json`, and when
  sibling render QA artifacts exist it also discloses evaluation-only
  loudness-match context for fair listening.
- **Supported target families** - stereo, surround, immersive, and first-class
  binaural/headphone workflows.
- **Desktop path** - the packaged Tauri desktop app is the shipped desktop app
  path, and the legacy `mmo-gui` shell remains only as a deprecated
  compatibility option for bounded existing workflows.

### What's new in this release

- [NEW ITEM 1]
- [NEW ITEM 2]
- [NEW ITEM 3]

### Still in progress

- [ONLY LIST REAL OPEN ITEMS THAT STILL APPLY]
- Example: packaged desktop smoke coverage is still being expanded.

### Install

Packaged desktop releases for Windows, macOS, and Linux: [RELEASE URL]

Source install:

```bash
pip install .
mmo env doctor --format text
```

### Docs

- User manual: `docs/manual/00-manual-overview.md`
- Quickstart: `docs/00-quickstart.md`
- Architecture: `docs/02-architecture.md`
- Targets and ordering standards: `docs/15-target-selection.md`,
  `docs/18-channel-standards.md`

## Short Social Template

> MMO v[VERSION] is out: deterministic analysis, compare, scene-first
> render-many delivery, five channel-ordering standards, and shipped desktop
> workflows. Offline-first, explainable, and honest about its limits.
> [RELEASE URL]

## Longer Announcement Template

**Subject:** Mix Marriage Offline v[VERSION] - [SHORT TAGLINE]

Mix Marriage Offline (MMO) v[VERSION] is now available.

MMO is an offline, deterministic mixing assistant that analyzes stems, captures
layout-agnostic scene intent, renders one scene to many delivery targets, and
keeps the resulting compare and receipt artifacts explainable.

What readers should know about the product today:

- MMO already ships deterministic report, scene, render, and compare artifacts.
- `mmo compare` is a first-class workflow, not a side tool.
- Render-many, channel-ordering standards, downmix QA, and headphone preview are
  part of the shipped surface.
- The packaged Tauri app is the desktop app path today.
- The legacy `mmo-gui` shell still exists as a deprecated compatibility path
  for bounded existing workflows.

What changed in this release:

- [NEW ITEM 1]
- [NEW ITEM 2]
- [NEW ITEM 3]

Current limits:

- [REAL OPEN ITEM 1]
- [REAL OPEN ITEM 2]

Install:

- Packaged desktop release: [RELEASE URL]
- Source install: `pip install .`

Docs:

- `docs/manual/00-manual-overview.md`
- `docs/00-quickstart.md`
- `docs/02-architecture.md`
- `docs/11-gui-vision.md`

Apache-2.0 · Offline-first · Deterministic
