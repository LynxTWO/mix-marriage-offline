# PR Checklist

## Plain Change Record

- What changed:
- Why it changed:
- What remains unclear:
- Risk changed:
- Approval needed:
- Docs updated:
- Tests or checks run:
- Repo evidence reviewed:

## Required checks

- [ ] Linked the exact `docs/STATUS.md` milestone checklist item(s) touched by
      this PR.
- [ ] Updated `docs/milestones.yaml` state if any milestone moved,
      with matching `docs/STATUS.md` updates.
- [ ] Updated `CHANGELOG.md` under `## [Unreleased]` for any user-facing
      behavior change.
- [ ] Ran `python tools/validate_contracts.py` and the needed tests or checks.
- [ ] Listed exact blockers or skips when validation did not run in the correct
      environment.
