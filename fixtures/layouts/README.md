# fixtures/layouts/

Public YAML layout descriptors for regression testing and documentation.

Each file describes a specific layout ID + standard combination with
per-slot channel assignments. These are reference fixtures — authoritative
channel-order documentation that is also machine-readable.

## Files

| File                | Layout ID      | Standard   | Channels |
|---------------------|----------------|------------|----------|
| `smpte_7_1_4.yaml`  | LAYOUT.7_1_4   | SMPTE      | 12       |
| `film_7_1_4.yaml`   | LAYOUT.7_1_4   | FILM       | 12       |

## Channel order comparison: 7.1.4

| Slot | SMPTE         | FILM          |
|------|---------------|---------------|
| 0    | FL            | FL            |
| 1    | FR            | FC            |
| 2    | FC            | FR            |
| 3    | LFE           | SL (Ls)       |
| 4    | SL (Ls)       | SR (Rs)       |
| 5    | SR (Rs)       | BL (Lrs)      |
| 6    | BL (Lrs)      | BR (Rrs)      |
| 7    | BR (Rrs)      | LFE           |
| 8    | TFL           | TFL           |
| 9    | TFR           | TFR           |
| 10   | TBL (TRL)     | TBL (TRL)     |
| 11   | TBR (TRR)     | TBR (TRR)     |

Key difference: FILM puts FC at slot 1 (before FR) and LFE at slot 7
(after all surrounds). SMPTE puts FC at slot 2 and LFE at slot 3.

## MMO canonical standard

The internal canonical standard is always **SMPTE**.
Import from FILM/LOGIC_PRO/VST3/AAF remaps to SMPTE at the boundary.
Export from SMPTE to any target standard remaps at the boundary.

See `src/mmo/core/speaker_layout.py` for the implementation.
