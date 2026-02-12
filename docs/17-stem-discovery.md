# 17. Stem Discovery And Overrides

This guide describes the conservative stem workflow:

1. Scan files into `stems_index`.
2. Classify files into `stems_map`.
3. Review assignments.
4. Apply explicit user overrides without renaming files.

## Commands

### 1) Discover stem sets

```powershell
python -m mmo stems scan --root <stems_root> --out stems_index.json
```

`stems_index` captures discovered files, normalized relative paths, and stem-set candidates.

### 2) Classify stems

```powershell
python -m mmo stems classify --index stems_index.json --out stems_map.json
```

`stems_map` assigns each file to a role with `confidence`, `bus_group`, and `reasons`.

### 3) Review assignments

```powershell
python -m mmo stems review --map stems_map.json --format text
```

Use review mode before rendering if confidence is low or files land in `ROLE.OTHER.UNKNOWN`.

### 4) Generate and edit overrides

```powershell
python -m mmo stems overrides default --out stems_overrides.yaml
python -m mmo stems overrides validate --in stems_overrides.yaml
```

Override entries are deterministic:

- `override_id` values must be sorted lexicographically.
- `match` is exactly one of:
  - exact `rel_path`
  - `regex`
- `role_id` is the forced target role.

If multiple overrides match one file, MMO picks the first sorted `override_id` and records:

`override:<override_id>`

### 5) Apply overrides

```powershell
python -m mmo stems apply-overrides --map stems_map.json --overrides stems_overrides.yaml --out stems_map.json
```

The patched map keeps existing file identity and path fields unchanged; only assignment role metadata is updated.

## Conservative behavior

- Classifier output is a recommendation, not a rename operation.
- Overrides are explicit, reviewable artifacts checked by schema and regex compilation.
- Low-confidence or unknown assignments stay visible through summary counts and review output.

## Confidence notes

- Higher confidence means stronger lexical or regex evidence.
- `ROLE.OTHER.UNKNOWN` remains valid when no reliable evidence exists.
- Use overrides for intentional domain corrections rather than weakening classifier thresholds globally.
