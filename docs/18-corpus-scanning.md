# 18. Corpus Scanning (Private, Names-Only)

Use `tools/stem_corpus_scan.py` to scan private stem folders and build a names-only corpus for lexicon tuning.

This is intended for local use on private libraries such as:

`D:\_Mix Projects_\Cambridge Multitracks`

## Safety and privacy

- Do not commit audio files.
- Do not commit corpus outputs.
- Keep generated artifacts in ignored paths such as `private/` or `corpus/`.

## Command

```powershell
python tools/stem_corpus_scan.py `
  --root "D:\_Mix Projects_\Cambridge Multitracks" `
  --out "private\cambridge.corpus.jsonl" `
  --stats "private\cambridge.corpus.stats.json" `
  --redact-paths `
  --suggestions-out "private\cambridge.role_lexicon.suggestions.yaml"
```

### Flags

- `--root`: directory to scan for stems.
- `--out`: output JSONL corpus (one row per file).
- `--stats`: output stats JSON.
- `--redact-paths`: store `basename` + hashed `rel_dir` instead of raw `rel_path`.
- `--max-files`: optional deterministic cap for fast sampling.
- `--role-lexicon`: optional role lexicon YAML used during classification.
- `--suggestions-out`: optional starter role-lexicon draft.

## Stats output

The stats file includes:

- `total_files`
- `token_frequency_top` (top 200)
- `unknown_token_frequency_top` (top 200)
- `per_role_token_top` (high-confidence assignments only)
- `ambiguous_cases` (token -> candidate role counts)

## Suggested workflow

1. Run `stem_corpus_scan.py` on the private corpus.
2. Inspect `*.corpus.stats.json` for unknown and ambiguous tokens.
3. Curate `role_lexicon.yaml` updates manually.
4. Re-run classification:
   `python -m mmo stems classify --root <stems_root> --role-lexicon ontology/role_lexicon.yaml --out stems_map.json`

## Suggestions file warning

`--suggestions-out` writes a starter YAML file that is explicitly marked:

`HUMAN REVIEW REQUIRED`

Treat it as a draft only. Review each token before using it in production lexicon rules.
