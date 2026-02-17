# PR Checklist

Required for all PRs (including AI-authored PRs):

- [ ] Linked the exact `docs/STATUS.md` milestone checklist item(s) touched by this PR.
- [ ] Updated `docs/milestones.yaml` state if any milestone actually moved (with matching `docs/STATUS.md` updates).
- [ ] Updated `CHANGELOG.md` under `## [Unreleased]` for any user-facing behavior change.
- [ ] Ran `python tools/validate_contracts.py` and full tests; if anything was skipped/failed, listed exact exceptions in this PR.
