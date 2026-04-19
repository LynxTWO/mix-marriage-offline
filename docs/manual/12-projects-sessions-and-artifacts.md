# Projects, sessions, and artifact files

Projects exist so you can return to a mix without guesswork. A project is a set
of allowlisted artifacts with known schema shapes.

Project scaffold workflow. mmo project init --stems-root ./stems --out-dir
./project mmo project refresh --project-dir ./project --stems-root ./stems

Session persistence. Save a session (scene + history + allowlisted receipt
snapshots): mmo project save ./project --session out/session.json

Reload it later: mmo project load ./project --session out/session.json

The current session receipt scaffold is `renders/render_execute.json`,
`renders/render_preflight.json`, and `renders/render_qa.json`.

Shell use now defaults to the shared-safe session summary. Use `--format json`
only when local tooling truly needs full machine-local paths in the save or
load output.

Project metadata. Shell use now defaults to the shared-safe project summary.
Use mmo project show ./project --format json only when local tooling needs the
full allowlisted path receipts and artifact `absolute_path` fields.

Bundles. A ui_bundle.json is a “pointer payload” that the GUI can consume. You
can build one from a report plus optional artifacts: mmo bundle --report
out/report.json --out out/ui_bundle.json

For the desktop-app view of these files, see the
[Desktop GUI walkthrough](10-gui-walkthrough.md). That chapter maps projects,
sessions, receipts, and compare inputs onto canonical GUI states such as the
loaded compact workspace shell, Results loaded state, and Compare loaded state
instead of assuming one static screen layout.

Scene and render-plan artifacts. MMO can build a scene intent file and a render
plan. Those exist to support mix-once, render-many pipelines. If you are not
doing advanced delivery, you can ignore them.

Stems map vs bus plan. `stems_map.json` answers "what role is each file?"
`bus_plan.json` answers "which deterministic bus path does each file feed?"
Build it from an existing stems map: mmo stems bus-plan --map out/stems_map.json
--out out/bus_plan.json --csv out/bus_plan.csv The bus plan is deterministic by
design: stable stem ordering, stable bus-group ordering, and fixed consolidation
rules (for example kick/snare/toms/perc/cyms under drums).

Scene intent scaffolding from stems artifacts. When you have `stems_map.json` +
`bus_plan.json`, you can scaffold a conservative scene intent: mmo scene build
--map out/stems_map.json --bus out/bus_plan.json --out out/scene.json --profile
PROFILE.ASSIST This pass classifies likely objects vs beds, adds width/depth
proxies, and records layout-safety defaults. Important: `scene.json` is intent
metadata, not an audio bounce. It does not render audio by itself.

Pro notes. Schema validation is a feature. If an artifact fails validation, that
is MMO preventing silent drift. Artifacts are deterministic so they can be
diffed between commits and releases. `compare_report.json` is one of those
deterministic artifacts; when paired `render_qa.json` files are present beside
the compared reports, it records a `loudness_match` block so fair-listen compare
context travels with the artifact.
