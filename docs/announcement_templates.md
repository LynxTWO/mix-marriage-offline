# MMO v1.1.0 Announcement Templates

Copy-paste templates for GitHub release, social, and email announcements.
Adjust names, links, and tone as needed.

---

## GitHub Release Notes (v1.1.0)

**Mix Marriage Offline v1.1.0 — Marketplace · Watch · Dashboard**

This release brings the offline plugin marketplace, smart watch-folder batch mode,
the cinematic Visualization Dashboard, binaural preview rendering, and a full
benchmark suite — all deterministic, all explainable, all offline.

### What's new

- **Offline plugin marketplace** — `mmo plugin list` / `mmo plugin update`.
  Browse and install community detectors, resolvers, and renderers without a network call.
- **Watch-folder automation** — `mmo watch <folder>`.
  Auto-runs deterministic `render-many` the moment new stems land.
- **Visualization Dashboard v1.1** — spectrum analyzer, vectorscope, correlation meter,
  cinematic 3D speaker layout, and per-object intent cards (what/why/where/confidence).
- **Binaural preview** — `safe-render --preview-headphones`.
  Deterministic conservative virtualization with source-layout traceability.
- **Benchmark suite** — `benchmarks/suite.py`.
  Repeatable timing baseline keyed to content hash.
- **Project session persistence** — `mmo project save/load`.
  Scene + history + receipts round-trip as strict-schema deterministic JSON.
- **New render targets** — `TARGET.STEREO.2_1`, `TARGET.FRONT.3_0/3_1`,
  `TARGET.SURROUND.4_0/4_1`, and first-class `LAYOUT.BINAURAL`.

### Install

One-click signed installers for Windows, macOS, and Linux:
https://github.com/LynxTWO/mix-marriage-offline/releases/tag/v1.1.0

From source:
```bash
pip install .
python -m mmo --help
```

### Upgrade note

Run `python tools/validate_contracts.py` after pulling to confirm schema mirrors are current.

---

## Twitter / X (280 chars)

> Mix Marriage Offline v1.1 is out.
> Offline plugin marketplace, watch-folder auto-batch, cinematic Dashboard,
> binaural preview, and a full benchmark suite.
> Deterministic. Explainable. Offline-first.
> https://github.com/LynxTWO/mix-marriage-offline/releases/tag/v1.1.0
> #audio #mixing #opensource

---

## Short Twitter / X (under 280 chars, no link)

> MMO v1.1 — offline marketplace, watch-folder automation, cinematic Dashboard,
> binaural preview. Mix once. Feel forever.

---

## LinkedIn / Long-form (email newsletter)

**Subject:** Mix Marriage Offline v1.1 — offline marketplace, watch mode, and more

---

Mix Marriage Offline (MMO) v1.1.0 is now available.

MMO is an offline, deterministic stem-folder mixing assistant. It captures mix
intent as a layout-agnostic scene, then renders to any of five channel standards
(SMPTE, FILM, Logic Pro, VST3, AAF) with strict downmix QA and fully explainable
reports. No black boxes. No network required.

**What's new in v1.1:**

🎛 **Offline plugin marketplace** — Browse and install community-contributed
detectors, resolvers, and renderers directly from the CLI or GUI, no internet
connection needed.

⏱ **Watch-folder automation** — Drop stems in a folder. MMO auto-runs
a deterministic multi-target render pass, waits for settle, and outputs
deliverables with QA receipts.

📊 **Visualization Dashboard v1.1** — Real-time spectrum analyzer, vectorscope,
phase/correlation meter, cinematic 3D speaker layout view, and per-object intent
cards showing what MMO found and why.

🎧 **Binaural headphone preview** — A deterministic, conservative virtualization
pass that produces `.headphones.wav` audition files linked back to their source
renders, so you can check your surround mix on any headphones.

📐 **New render targets** — 2.1, 3.0, 3.1, 4.0, 4.1, and first-class Binaural
join the target roster alongside Stereo, 5.1, 7.1, and 7.1.4.

📋 **Project session persistence** — Save and restore scene + history + receipts
as strict-schema deterministic JSON for long-running projects.

⚡ **Benchmark suite** — Repeatable timing baseline via `benchmarks/suite.py`,
content-hash-keyed so re-runs skip unchanged analysis.

**Install**

Signed one-click installers for Windows, macOS, and Linux:
https://github.com/LynxTWO/mix-marriage-offline/releases/tag/v1.1.0

From source: `pip install .`

**Docs**

Full user guide: `docs/user_guide.md`
Architecture and plugin API: `docs/02-architecture.md`, `docs/04-plugin-api.md`

---

Apache-2.0 · Offline-first · Deterministic
https://github.com/LynxTWO/mix-marriage-offline
