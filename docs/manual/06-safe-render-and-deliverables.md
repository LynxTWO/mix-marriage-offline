# Safe-render, deliverables, and layout standards

Rendering is where tools can hurt people.
MMO treats rendering as a gated, receipt-driven action.

MMO has three related concepts.
“Apply” is for low-risk fix-ups that can be written back out.
“Render” is for render-eligible recommendations.
“Safe-render” is the full bounded chain: detect, resolve, gate, then render.

Quick path (safe-render).
mmo safe-render --report out/report.json --target stereo --out-dir out/render --receipt-out out/receipt.json

Render-many (mix-once, render-many).
mmo safe-render --report out/report.json --render-many --render-many-targets stereo,5.1,7.1.4 --out-dir out/deliverables --receipt-out out/receipt.json

Baseline outputs are always produced.
Even when zero recommendations are render-eligible, safe-render writes a conservative baseline WAV master for supported layout targets.

Channel-ordering standards.
MMO processes internally using SMPTE ordering.
MMO can export in SMPTE, FILM, LOGIC_PRO, VST3, or AAF ordering.

Example.
mmo safe-render --report out/report.json --render-many --layout-standard FILM --out-dir out/deliverables_film --receipt-out out/receipt_film.json

Output formats.
Lossless formats are supported: wav, flac, wv, aiff, alac.
(Some formats depend on FFmpeg availability.)

Headphone preview.
Use `--preview-headphones` to create deterministic headphone preview files alongside renders.

Dry-run is your friend.
Use `--dry-run` to generate the plan and receipt without writing audio.

Approvals are explicit.
Use `--approve` to override blocks when you intentionally want to cross a safety boundary.
You can approve none, all, or a comma-separated list of recommendation IDs.

Pro notes.
LFE is treated as a creative send plus bass management rules, not as a mandatory “content must exist” channel.
If you are delivering “.2” targets, treat that as a playback management detail unless a spec explicitly requires dual-LFE program content.
Keep the receipt JSON with the deliverables. That is your defensible audit trail.
