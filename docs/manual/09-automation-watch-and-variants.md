# Automation: watch folders and variants

If you do repeated work manually, you are teaching yourself to hate music. MMO
includes batch-friendly automation that stays deterministic.

Watch-folder mode is for drop boxes. It monitors a folder for new or updated
stem sets, then runs deterministic render-many batches.

Quick path. mmo watch ./incoming_stems --out ./watch_out

Useful flags. --once processes once and exits. --no-existing skips what already
exists. --settle-seconds debounces partial file copies. --visual-queue prints an
ASCII queue snapshot.

Variants are for A/B testing and preset comparison. You can run multiple presets
or configs and keep outputs separated.

Quick path. mmo variants run --stems ./stems --out out/variants --preset
PRESET.VIBE.WARM_INTIMATE --preset PRESET.VIBE.TRANSLATION_SAFE --export-csv
--export-pdf --bundle

What you get. A deterministic folder per variant. A variant_result.json that
indexes the outputs.

Pro notes. Caching is keyed by lockfile plus run_config hash. That makes
repeated variant runs much faster when stems do not change. If you are doing
client deliveries, variants plus compare is how you stay honest without redoing
work.
