# Quickstart: Stems to Project in Five Minutes

This is the golden-path walkthrough for new users.
Follow it top-to-bottom and you will have a classified project scaffold
with preview drafts ready for review.

For deeper detail on any step, see the cross-references at the end.

---

## 1. Install and verify

```powershell
pip install .
python -m mmo --help
```

You should see the top-level command list.
Optional extras (`pip install .[pdf]`, `pip install .[truth]`) are not needed for this guide.

---

## 2. One-command scaffold: `project init`

Point MMO at a folder of exported stems and an output directory:

```powershell
python -m mmo project init `
  --stems-root "D:\MySession\stems" `
  --out-dir "D:\MySession\project"
```

This runs the full pipeline in one shot:

1. Scans files into `stems/stems_index.json`.
2. Classifies each file into a role (`stems/stems_map.json`).
3. Writes a starter `stems/stems_overrides.yaml` for manual corrections.
4. Generates preview-only `drafts/scene.draft.json` and `drafts/routing_plan.draft.json`.

The output is a self-contained project directory:

```
project/
  stems/
    stems_index.json
    stems_map.json
    stems_overrides.yaml
  drafts/
    scene.draft.json
    routing_plan.draft.json
    README.txt
  README.txt
```

**`--bundle` flag (pointer bundle):**
You can pass `--bundle path/to/bundle.json` to also write a pointer bundle JSON.
This is a *scaffold-only* bundle built from the init artifacts alone (stems index, stems map, scene draft).
It does **not** contain a scan report, listen pack, or metering data.
For a complete GUI payload, see [section 5](#5-build-a-gui-payload-stems-arc) below.

**Important:** Draft files are preview-only.
They are never auto-loaded by any MMO workflow.
You must pass them explicitly to any command that consumes a scene or routing plan.

---

## 3. Edit overrides and refresh

Open `stems/stems_overrides.yaml` in any text editor and fix role assignments
that the classifier got wrong.
For example, if a file was classified as `ROLE.OTHER.UNKNOWN` but is actually a lead vocal,
add an override entry mapping that file to `ROLE.VOCAL.LEAD`.

Then re-run the pipeline and drafts in one step:

```powershell
python -m mmo project refresh `
  --project-dir "D:\MySession\project" `
  --stems-root "D:\MySession\stems"
```

This rewrites `stems_index.json`, `stems_map.json`, `scene.draft.json`, and
`routing_plan.draft.json` while preserving your edited `stems_overrides.yaml`.

To also reset overrides to the default template, add `--force`.

**Tip:** If you place your stems inside the project as `project/stems_source/`,
you can omit `--stems-root` and refresh will find them automatically.

---

## 4. Generate auditions (optional)

After classification, render short per-bus-group WAV bounces to spot-check
assignments by ear:

```powershell
python -m mmo stems audition `
  --stems-map "D:\MySession\project\stems\stems_map.json" `
  --stems-dir "D:\MySession\stems" `
  --out-dir "D:\MySession\project"
```

This creates `stems_auditions/<bus_group>.wav` plus a `manifest.json`.
Listen to each group to verify that the classifier put the right files together.

See [20-stems-audition.md](20-stems-audition.md) for options and limitations.

---

## 5. Build a GUI payload (stems arc)

After init, refresh, and optional auditions, you can produce a full
`ui_bundle.json` suitable for GUI consumption. This requires two additional
commands: `scan` (to generate a report) and `bundle` (to assemble the payload).

**Step 1 -- Generate a scan report:**

```powershell
python -m mmo scan "D:\MySession\stems" `
  --out "D:\MySession\project\report.json"
```

This writes `report.json` containing file metadata, issues, and validation
results. No meters or peak data are included unless you pass `--meters` or
`--peak`.

**Step 2 -- (Optional) Build a listen pack:**

If you ran `stems audition` in step 4, you can include the audition index in
the bundle. Otherwise, skip `--listen-pack` in step 3.

```python
# Minimal listen_pack.json (written by the test suite or your own tooling):
{
  "schema_version": "0.1.0",
  "stems_auditions": { ... }   # from stems_auditions/manifest.json
}
```

**Step 3 -- Assemble the UI bundle:**

```powershell
python -m mmo bundle `
  --report "D:\MySession\project\report.json" `
  --stems-index "D:\MySession\project\stems\stems_index.json" `
  --stems-map "D:\MySession\project\stems\stems_map.json" `
  --scene "D:\MySession\project\drafts\scene.draft.json" `
  --listen-pack "D:\MySession\project\listen_pack.json" `
  --out "D:\MySession\project\ui_bundle.json"
```

All flags except `--report` and `--out` are optional.
Each extra flag adds its payload to the bundle under a dedicated key.
The output is validated against `schemas/ui_bundle.schema.json`.

**Pointer bundle vs full UI bundle:**

| | Pointer bundle (`project init --bundle`) | Full UI bundle (`mmo bundle`) |
|---|---|---|
| Source | Built automatically during `project init` | Built explicitly by the user |
| Contains report | No | Yes (required `--report`) |
| Contains listen pack | No | Optional (`--listen-pack`) |
| Contains metering data | No | Only if the report includes it |
| Use case | Quick scaffold preview | Complete GUI payload |

---

## 6. Scan corpus and merge suggestions (optional)

If you have a large private stem library, you can scan it to generate
role-lexicon suggestions that improve classification accuracy:

```powershell
python tools/stem_corpus_scan.py `
  --root "D:\_Mix Projects_\Cambridge Multitracks" `
  --out "private\cambridge.corpus.jsonl" `
  --stats "private\cambridge.corpus.stats.json" `
  --redact-paths `
  --suggestions-out "private\cambridge.role_lexicon.suggestions.yaml"
```

Review the suggestions, then merge the good ones into a user lexicon:

```powershell
python -m mmo role-lexicon merge-suggestions `
  --suggestions "private\cambridge.role_lexicon.suggestions.yaml" `
  --out "ontology\role_lexicon.yaml"
```

Re-run `project refresh` (or `project init`) with `--role-lexicon ontology\role_lexicon.yaml`
to apply the improved lexicon.

**Privacy:** Corpus outputs (`*.corpus.jsonl`, `*.corpus.stats.json`,
`*.suggested.yaml`) must stay in ignored paths (`private/`, `corpus/`).
Never commit them.

See [18-corpus-scanning.md](18-corpus-scanning.md) for full flag reference and workflow.

---

## 7. Diff corpus runs (optional regression lens)

After re-scanning with updated lexicons or thresholds, compare two stats files
to see what changed:

```powershell
python tools/stem_corpus_diff.py `
  --before "private\run1.corpus.stats.json" `
  --after "private\run2.corpus.stats.json" `
  --top 20
```

The output is stable JSON showing token frequency deltas, per-role changes,
and summary counts. Use `--out diff.json` to write to a file.

---

## Common pitfalls

### OneDrive locks

OneDrive can hold file locks that prevent git operations.
If you see `.git/index.lock` errors, close OneDrive sync or wait for it to
finish, then delete the stale lock file manually.

### Temp hygiene

MMO tests and tools create repo-local temp directories.
Use the allowlist-only cleanup script to remove them safely:

```powershell
python tools/safe_cleanup.py
```

This removes only the canonical temp dirs listed in CLAUDE.md
(`.tmp_pytest/`, `.tmp_codex/`, `.tmp_claude/`, `sandbox_tmp/`, `.pytest_cache/`).
It never pattern-matches or sweeps unknown directories.

Add `--dry-run` to preview what would be removed without deleting anything.

### Draft files are preview-only

Draft files (`*.draft.json`) are never auto-discovered.
No MMO command will silently load them.
You must always pass scene or routing plan paths explicitly.

---

## Cross-references

- [17-stem-discovery.md](17-stem-discovery.md) -- step-by-step stem scan, classify, review, and override commands.
- [18-corpus-scanning.md](18-corpus-scanning.md) -- private corpus scan, stats, suggestions, merge workflow, and diff tool.
- [19-stems-drafts.md](19-stems-drafts.md) -- draft scene and routing plan format, fields, and explicit usage.
- [20-stems-audition.md](20-stems-audition.md) -- audition pack rendering, manifest format, and limitations.
