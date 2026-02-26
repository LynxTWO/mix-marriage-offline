# fixtures/public_session/

Public, deterministic session fixtures for end-to-end pipeline tests.

## Files

- `report.7_1_4.json` — 7.1.4 public example session with paired stem entries
  representing SMPTE and FILM channel-order exports.
- `stems/` — placeholder directory for optional demo audio assets.
  The full determinism harness runs in `--dry-run` mode and does not require
  checked-in audio files.

## Usage

- `tests/test_full_determinism.py` uses this fixture to assert byte-stable
  outputs across the full safe-render pipeline (receipt, manifest, UI bundle)
  for both `SMPTE` and `FILM` layout standards.
