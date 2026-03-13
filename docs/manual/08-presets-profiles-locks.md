# Presets, authority modes, user profiles, and locks

You want speed without chaos. MMO gives you knobs that are explicit and
auditable.

Presets are workflow or vibe bundles. List presets. mmo presets list --format
json

Preview what a preset does. mmo presets preview PRESET.VIBE.TRANSLATION_SAFE

Preview it with measured report context so MMO can explain any bounded
feature-driven preview safety adjustments. mmo presets preview
PRESET.VIBE.DENSE_GLUE --report out/report.json

Authority modes control how aggressive automation is allowed to be. These are
the built-in modes described in the help registry: Guide (no auto-apply), Assist
(conservative default), Full Send (more permissive), Turbo (fast and
aggressive).

Read the mode help text. mmo help show HELP.MODE.ASSIST --format text mmo help
show HELP.MODE.TURBO --format text

User style and safety profiles are separate from authority modes. These profiles
tune thresholds and tolerances for different delivery contexts. List profiles.
mmo profile list --format json

Locks are “do not violate this intent” guardrails. Current locks include:
preserve dynamics, preserve center image, no stereo widening, and more.

List locks. mmo locks list --format json

Locks live inside the scene intent model. You can add or remove locks in a scene
file using the CLI.

Example: add a hard lock to preserve dynamics at scene scope. mmo scene locks
add --scene out/scene.json --scope scene --lock LOCK.PRESERVE_DYNAMICS --out
out/scene.json

Example: remove a lock. mmo scene locks remove --scene out/scene.json --scope
scene --lock LOCK.PRESERVE_DYNAMICS --out out/scene.json

Locks cookbook.

Force role and bus for one stem during scene build.

```yaml
# scene_locks.yaml
version: "0.1.0"
overrides:
  STEM.KICK:
    role_id: "ROLE.DRUM.KICK"
    bus_id: "BUS.DRUMS.KICK"
```

Then apply: mmo scene build --map stems_map.json --bus bus_plan.json --profile
PROFILE.ASSIST --locks scene_locks.yaml --out out/scene.json

Force front-only safety for a stem (surround caps 0).

```yaml
# scene_locks.yaml
version: "0.1.0"
overrides:
  STEM.KICK:
    surround_send_caps:
      side_max_gain: 0.0
      rear_max_gain: 0.0
```

Force no heights globally (scene lock). mmo scene locks add --scene
out/scene.json --scope scene --lock LOCK.NO_HEIGHT_SEND --out out/scene.json

Force no heights for one stem (height caps 0 in overrides).

```yaml
# scene_locks.yaml
version: "0.1.0"
overrides:
  STEM.KICK:
    height_send_caps:
      top_max_gain: 0.0
```

Request “in band” perspective (machine-readable). mmo scene intent set --scene
out/scene.json --scope scene --key perspective --value in_band --out
out/scene.json

Pro notes. Locks exist because “taste” changes are high-risk in automation. If
you know a boundary is non-negotiable, make it explicit as a lock. Use Assist
mode plus a conservative user profile when you are working on unfamiliar stems.
Use Turbo only when you accept that you are trading subtlety for momentum.
Preset preview loudness compensation is evaluation-only unless you explicitly
run or apply the preset. Shipped preset packs declare a preview loudness guard,
and report-driven preview initialization must stay bounded and disclosed.
