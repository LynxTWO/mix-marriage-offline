# stems_small fixture set

This folder contains compact, redistributable stem-name sessions used for
regression testing:

- `stems -> bus plan -> scene` determinism
- naming-pattern coverage from real-world inventories
- render-target chain coverage for:
  - stereo (`2.0`)
  - surround (`5.1`, `7.1`)
  - immersive (`7.1.4`, `9.1.6`)

These fixtures intentionally use tiny placeholder audio files (empty `.wav`
files). Classification and planning rely on deterministic filename patterns, not
on distributable source media.

The naming corpus emphasizes patterns observed in the source inventory:

- numeric prefixes and suffixes (`01_...`, `...1`, `...2`)
- compound tokens (`ElecGtr`, `BackingVox`, `LeadVox`, `BassDI`, `DrumsRoom`)
- synth sections and variants (`Synth`, `SynthPad`, `SynthLead`, `SynthSFX`)
- SFX variants (`SFX`, `VocalSFX`, `PianoSFX`)

Expected snapshot outputs are stored in:

- `fixtures/expected_bus_plan.json`
- `fixtures/expected_scene.json`
