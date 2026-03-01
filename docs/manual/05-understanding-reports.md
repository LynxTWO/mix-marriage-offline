# Understanding the report and recall sheet

If you do not understand the output, you cannot trust the output.
MMO reports are designed to be explainable, not mystical.

The report is JSON first.
That is on purpose.
A JSON report can be validated, diffed, and consumed by tools.

The recall sheet is the human bridge.
The CSV is designed to be pasted into a DAW checklist.
It is the “do this, in this order” version of the report.

How MMO describes issues.
Every issue is expected to have “what, why, where, confidence.”
“What” is the observable symptom.
“Why” is the mechanical cause MMO is pointing at.
“Where” is the file, channel group, or time region it applies to.
“Confidence” is how strongly MMO believes it.

How to triage like a pro.
Start with safety and delivery failures first (clipping, invalid format, missing channels).
Then fix translation risks (mono collapse, extreme correlation, harshness).
Then address balance and masking issues.
Do not treat every low-confidence hint as mandatory.

What “blocked” means.
Blocked means the action exceeded the current authority profile or violated a lock.
Blocked is a safety feature, not a failure.

Receipts are your audit log.
Render and apply flows produce receipts that record what changed, what did not, and why.

Pro notes.
Use `mmo compare` to compare two reports and see what changed across revisions.
Use `mmo report` when you want validation plus exports in one command.