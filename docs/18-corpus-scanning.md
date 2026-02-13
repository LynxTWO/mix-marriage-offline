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
  --suggestions-out "private\cambridge.role_lexicon.suggestions.yaml" `
  --min-count 10 `
  --min-set-count 3 `
  --min-precision 0.85 `
  --min-confidence 0.80
```

### Flags

- `--root`: directory to scan for stems.
- `--out`: output JSONL corpus (one row per file).
- `--stats`: output stats JSON.
- `--redact-paths`: store `basename` + hashed `rel_dir` instead of raw `rel_path`.
- `--max-files`: optional deterministic cap for fast sampling.
- `--include-folder-tokens`: include folder tokens in stats/suggestions (default: off; basename tokens only).
- `--min-count`: suggestions minimum token occurrence count (default: `10`).
- `--min-set-count`: suggestions minimum distinct stem-set count (default: `3`).
- `--min-precision`: suggestions minimum best-role precision (default: `0.85`).
- `--min-confidence`: suggestions/per-role stats confidence floor (default: `0.80`).
- `--stopwords`: optional comma-separated extra stopwords merged with built-ins.
- `--role-lexicon`: optional role lexicon YAML used during classification.
- `--suggestions-out`: optional starter role-lexicon draft.

By default, both stats and suggestions:

- use basename tokens only,
- ignore digit-only tokens,
- ignore tokens with length `< 2`,
- ignore built-in low-signal stopwords (`track`, `stem`, `mix`, `master`, `print`, `take`, `alt`, `ver`, `version`, etc).

## Stats output

The stats file includes:

- `total_files`
- `scan_params` (threshold/filter knobs used for this run)
- `token_frequency_top` (top 200)
- `unknown_token_frequency_top` (top 200)
- `per_role_token_top` (high-confidence assignments only)
- `ambiguous_cases` (token -> candidate role counts)

## Suggested workflow

1. Run `stem_corpus_scan.py` on the private corpus.
2. Inspect `*.corpus.stats.json` for unknown and ambiguous tokens.
3. Review the suggestions YAML (if generated with `--suggestions-out`).
4. Merge suggestions into a user role lexicon:
   ```powershell
   python -m mmo role-lexicon merge-suggestions `
     --suggestions "private\cambridge.role_lexicon.suggestions.yaml" `
     --out "ontology\role_lexicon.yaml" `
     --deny "bad_token1,bad_token2"
   ```
5. Re-run the stems pipeline with the new lexicon:
   ```powershell
   python -m mmo stems pipeline `
     --root <stems_root> `
     --out-dir <out_dir> `
     --role-lexicon "ontology\role_lexicon.yaml"
   ```

### Merge-suggestions flags

| Flag | Default | Description |
|------|---------|-------------|
| `--suggestions` | (required) | Path to suggestions YAML |
| `--base` | none | Existing user role lexicon YAML to merge into |
| `--out` | (required) | Output path for the merged lexicon |
| `--deny` | none | Comma-separated tokens to exclude |
| `--allow` | none | Comma-separated tokens to include exclusively (overrides validity filters) |
| `--max-per-role` | 100 | Cap on new keywords per role (deterministic selection) |
| `--dry-run` | off | Print summary without writing |
| `--format` | json | Summary output format (json or text) |

## Suggestions file warning

`--suggestions-out` writes a starter YAML file that is explicitly marked:

`HUMAN REVIEW REQUIRED`

Treat it as a draft only. Review each token before using it in production lexicon rules.
The merge-suggestions command never modifies the built-in common lexicon — it only writes user lexicons.

## How to diff runs

After re-scanning with updated lexicons or thresholds, compare two stats JSON files to see what changed:

```powershell
python tools/stem_corpus_diff.py `
  --before "private\run1.corpus.stats.json" `
  --after "private\run2.corpus.stats.json" `
  --top 20
```

The output is stable JSON with:

- `token_frequency_top_delta` — tokens with changed counts, sorted by abs(delta) desc
- `unknown_token_frequency_top_delta` — same for unknown tokens
- `per_role_token_top_delta` — per-role breakdowns, roles sorted by ID
- `increased_count`, `decreased_count`, `unchanged_count` — summary counts
- `warnings` — sorted list of issues (e.g., missing keys in either input)

Write to a file with `--out diff.json` instead of printing to stdout.
