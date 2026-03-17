# Troubleshooting and common failures

When MMO fails, start with the first clear message. Do not guess past it.

If you are using the desktop app, run `Doctor` first.

If you are using the CLI, run:

```sh
mmo env doctor --format text
```

## MMO says to choose a stems folder or workspace first

What happened:

- MMO does not know where your source audio lives, or where it should write its
  artifacts.

Why it happened:

- one of the required path fields is empty

What to do next:

- `stems folder` should point at your exported audio tracks
- `workspace` should point at the folder where you want MMO to write reports,
  scenes, renders, and receipts

## Analyze fails before it gets going

What happened:

- MMO could not read the stems cleanly enough to analyze them

Common reasons:

- the stems folder path is wrong
- the folder has no supported audio files
- `ffmpeg` or `ffprobe` are missing

What to do next:

- confirm the stems folder really contains audio files
- run `Doctor` or `mmo env doctor --format text`
- install `ffmpeg` and `ffprobe`, or set `MMO_FFMPEG_PATH` and
  `MMO_FFPROBE_PATH`

## Scene Lock save fails

What happened:

- MMO refused to save one of the scene lock edits

Why it happened:

- a role override is malformed
- a row is duplicated
- the edit would create an invalid scene

What to do next:

- load the rows with `Inspect Scene Locks`
- undo the last change
- save again after simplifying the override

Think of scene locks like taping notes onto a stage plot: if one note makes the
plot contradictory, MMO stops instead of pretending it still makes sense.

## Scene lint reports a failure

What happened:

- the placement draft references something MMO cannot trust yet

Common reasons:

- missing stem references
- missing files
- invalid lock combinations

What to do next:

- open `scene_lint.json`
- fix the first error
- rebuild the scene

If you use `--scene-strict`, MMO will stop at this point on purpose instead of
continuing into render.

## Render says it was blocked

What happened:

- MMO stopped before writing audio

Why it happened:

- a safety gate blocked the current target or recommendation set

What to do next:

- open `safe_render_receipt.json`
- read the blocked gate IDs and notes
- rerun with `--dry-run` if you want to inspect the plan without writing audio
- approve higher-risk changes only if you intentionally want them

This is MMO acting like a careful assistant hitting pause before a risky bounce.

## Render finished but wrote no audio

What happened:

- MMO completed the paperwork, but no renderer produced an output file

What to do next:

- open `safe_render_receipt.json`
- open `render_qa.json`
- confirm that at least one renderer in this build can write the chosen target

Use `--allow-empty-outputs` only when you intentionally want a receipt-only
pass.

## Compare cannot load one of the inputs

What happened:

- MMO could not resolve one side of the A/B pair

Why it happened:

- the path is wrong
- you pointed at the wrong folder
- the folder does not contain `report.json`

What to do next:

- point Compare at a finished workspace folder, or at the `report.json` file
  inside that workspace
- make sure both sides exist on disk before running Compare

## The desktop app opens, but no stage will run

What happened:

- the desktop shell opened, but the packaged audio helper did not launch

Why it happened:

- the sidecar backend is missing, blocked, or broken in that install

What to do next:

- run `Doctor`
- if `Doctor` also fails, reinstall the packaged release
- if you are a contributor, rebuild the sidecar from
  `gui/desktop-tauri/README.md`

## PDF export fails

What happened:

- MMO could not build a PDF report

Why it happened:

- ReportLab is missing

What to do next:

```sh
pip install .[pdf]
```

## Watch-folder misses a set

What happened:

- MMO started reading a folder before all files finished copying

What to do next:

- increase `--settle-seconds`

That gives MMO a longer "wait for the copy to finish" pause before it starts
processing.
