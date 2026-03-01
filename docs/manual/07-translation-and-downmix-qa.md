# Translation checks and downmix QA

Translation is where a mix gets humbled.
MMO’s translation checks are designed to catch predictable failure modes across playback systems.

Translation profiles available in v1.1.0.
Phone, earbuds, car, small speaker, mono collapse.

List profiles.
mmo translation list --format json

Show one profile.
mmo translation show TRANS.MONO.COLLAPSE

When translation runs automatically.
In `run --render-many` workflows, translation checks run when a stereo deliverable exists.

Downmix is a contract.
MMO includes downmix policy inventory and deterministic matrices.

Show a downmix matrix.
mmo downmix show --source LAYOUT.5_1 --target LAYOUT.2_0 --format csv

List available paths and policies.
mmo downmix list
mmo downmix list --policies

QA a downmix against a reference.
mmo downmix qa --src your_5_1.wav --ref your_stereo_ref.wav --source-layout LAYOUT.5_1 --format json

How to interpret QA.
A high similarity score means your fold-down behaves like your intended stereo.
A low score means your surround balance is not collapsing the way you think.
A “warn” is a prompt to listen and verify.
A “block” is a strong indicator of translation risk.

Pro notes.
Correlation failures often show up as “impressive” width that disappears in mono.
Harshness failures often show up as “clarity” that becomes fatigue in earbuds.
Low-end translation failures often show up as “big” bass that vanishes on small speakers.