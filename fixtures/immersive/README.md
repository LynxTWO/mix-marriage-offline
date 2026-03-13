# fixtures/immersive/

Deterministic fixture data for immersive (7.1.4, 5.1.4, etc.) demo and CI flows.

## Files

- `report.7_1_4.json` — Minimal valid report for a 7.1.4 SMPTE source session
  with one SMPTE-ordered bed stem and one FILM-ordered bed stem. Used by
  `mmo safe-render --demo` to demonstrate render-many-standards flow.

- `stems/` — Placeholder directory for demo WAV stems. Actual WAV files are
  generated on demand by the demo flow or omitted when running in `--dry-run`
  mode.

## Layout standards

The fixture covers a 7.1.4 session with two reference stems:

| Stem ID        | Layout       | Standard |
| -------------- | ------------ | -------- |
| bed_7_1_4      | LAYOUT.7_1_4 | SMPTE    |
| bed_7_1_4_film | LAYOUT.7_1_4 | FILM     |

Channel order for 7.1.4 SMPTE: L R C LFE Ls Rs Lrs Rrs TFL TFR TRL TRR Channel
order for 7.1.4 FILM: L C R Ls Rs Lrs Rrs LFE TFL TFR TRL TRR
