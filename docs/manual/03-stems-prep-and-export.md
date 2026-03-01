# Stems prep and export rules

MMO assumes stems can be aligned, summed, and compared.
If stems are not aligned, every “issue” becomes untrustworthy.

Quick checklist.
All stems start at 0:00.
All stems are the same length, including reverb and delay tails.
All stems share sample rate and bit depth.
No clipping. Leave headroom.
Use clear naming so roles can be inferred or assigned.

Recommended formats.
WAV is always supported.
FLAC and WavPack are supported when ffprobe is available.
AIFF input is not supported yet. Export WAV for analysis.

Avoid these inputs.
MP3/AAC/Ogg/Opus will trigger warnings.
Lossy exports add artifacts and make comparisons less reliable.

Naming rules that help.
Role-first naming is the most deterministic approach.
Example: 01_ROLE.DRUM.KICK.wav, 10_ROLE.VOCAL.LEAD.wav

If you prefer human names (Kick In.wav, Lead Vox.wav), that is fine.
You will more likely need to use classification review and overrides.

Pro notes.
A reference track is useful, but it should not be baked into the stem set unless you label it clearly (ROLE.REFERENCE.TRACK).
Do not normalize exports.
Do not apply per-stem limiting that changes the performance unless you are intentionally printing that sound.
If your DAW exports channel-ordered surround stems, keep track of the standard (SMPTE vs FILM vs LOGIC_PRO vs VST3 vs AAF).
MMO can remap, but only if you tell it the target standard at render time.