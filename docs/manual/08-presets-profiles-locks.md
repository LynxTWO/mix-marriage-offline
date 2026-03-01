# Presets, authority modes, user profiles, and locks

You want speed without chaos.
MMO gives you knobs that are explicit and auditable.

Presets are workflow or vibe bundles.
List presets.
mmo presets list --format json

Preview what a preset does.
mmo presets preview PRESET.VIBE.TRANSLATION_SAFE

Authority modes control how aggressive automation is allowed to be.
These are the built-in modes described in the help registry:
Guide (no auto-apply), Assist (conservative default), Full Send (more permissive), Turbo (fast and aggressive).

Read the mode help text.
mmo help show HELP.MODE.ASSIST --format text
mmo help show HELP.MODE.TURBO --format text

User style and safety profiles are separate from authority modes.
These profiles tune thresholds and tolerances for different delivery contexts.
List profiles.
mmo profile list --format json

Locks are “do not violate this intent” guardrails.
Current locks include: preserve dynamics, preserve center image, no stereo widening, and more.

List locks.
mmo locks list --format json

Locks live inside the scene intent model.
You can add or remove locks in a scene file using the CLI.

Example: add a hard lock to preserve dynamics at scene scope.
mmo scene locks add --scene out/scene.json --scope scene --lock LOCK.PRESERVE_DYNAMICS --out out/scene.json

Example: remove a lock.
mmo scene locks remove --scene out/scene.json --scope scene --lock LOCK.PRESERVE_DYNAMICS --out out/scene.json

Pro notes.
Locks exist because “taste” changes are high-risk in automation.
If you know a boundary is non-negotiable, make it explicit as a lock.
Use Assist mode plus a conservative user profile when you are working on unfamiliar stems.
Use Turbo only when you accept that you are trading subtlety for momentum.