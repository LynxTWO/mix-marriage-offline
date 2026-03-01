# Projects, sessions, and artifact files

Projects exist so you can return to a mix without guesswork.
A project is a set of allowlisted artifacts with known schema shapes.

Project scaffold workflow.
mmo project init --stems-root ./stems --out-dir ./project
mmo project refresh --project-dir ./project --stems-root ./stems

Session persistence.
Save a session (scene + history + receipts):
mmo project save ./project --session out/session.json

Reload it later:
mmo project load ./project --session out/session.json

Bundles.
A ui_bundle.json is a “pointer payload” that the GUI can consume.
You can build one from a report plus optional artifacts:
mmo bundle --report out/report.json --out out/ui_bundle.json

Scene and render-plan artifacts.
MMO can build a scene intent file and a render plan.
Those exist to support mix-once, render-many pipelines.
If you are not doing advanced delivery, you can ignore them.

Pro notes.
Schema validation is a feature.
If an artifact fails validation, that is MMO preventing silent drift.
Artifacts are deterministic so they can be diffed between commits and releases.