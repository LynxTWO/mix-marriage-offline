# 18) Channel layout standards (I/O boundary contract)

MMO supports five channel-ordering standards at file/plugin boundaries:
`SMPTE`, `FILM`, `LOGIC_PRO`, `VST3`, and `AAF`.

## Quick definitions

- `SMPTE`: Broadcast/streaming/default WAV/FLAC/FFmpeg ordering (`L R C LFE Ls Rs ...`).
- `FILM`: Pro Tools/cinema dub-stage ordering (`L C R Ls Rs LFE ...`).
- `LOGIC_PRO`: Logic Pro / DTS ordering (`L R Ls Rs C LFE ...` for 5.1).
- `VST3`: Cubase/Nuendo 7.1+ ordering with rears before sides (`... Lrs Rrs Ls Rs ...`).
- `AAF`: Interchange metadata-driven ordering from AAF/OMF/XML labels; if no explicit variant is declared for a layout, MMO uses canonical SMPTE ordering.

## Rule: boundary convert, internal SMPTE

MMO processing is always canonical `SMPTE` internally.

- Import boundary: incoming buffers declared/inferred as `FILM`, `LOGIC_PRO`, `VST3`, or `AAF` are remapped to SMPTE channel order before internal DSP/routing.
- Internal processing: all semantic speaker operations run against SMPTE-ordered channel slots.
- Export boundary: output buffers are remapped from SMPTE to the requested output standard.

This prevents swaps (for example center/surround/LFE slot mistakes) while keeping internal logic deterministic and standard-agnostic.

## How `--layout-standard` affects I/O

`mmo safe-render --layout-standard <STANDARD>` controls boundary channel ordering for render output contracts.

- Default: `SMPTE`.
- Accepted values: `SMPTE`, `FILM`, `LOGIC_PRO`, `VST3`, `AAF`.
- Effect on output: target contract `channel_order` and rendered channel slot order follow the selected standard for that layout.
- Effect on internal processing: none; internal routing remains SMPTE.
- If a layout does not define an explicit `ordering_variants[STANDARD]`, MMO falls back to that layout's canonical SMPTE `channel_order`.
