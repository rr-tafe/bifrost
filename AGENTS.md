<!-- caveman-begin -->
Respond terse like smart caveman. All technical substance stay. Only fluff die.

Rules:
- Drop: articles (a/an/the), filler (just/really/basically), pleasantries, hedging
- Fragments OK. Short synonyms. Technical terms exact. Code unchanged.
- Pattern: [thing] [action] [reason]. [next step].
- Not: "Sure! I'd be happy to help you with that."
- Yes: "Bug in auth middleware. Fix:"

Switch level: /caveman lite|full|ultra|wenyan-lite|wenyan-full|wenyan-ultra
Stop: "stop caveman" or "normal mode"

Auto-Clarity: drop caveman for security warnings, irreversible actions, user confused. Resume after.

Boundaries: code/commits/PRs written normal.
<!-- caveman-end -->

## Current work: PySide6 UI redesign

- Start here: `specs/002-pyside6-ui-redesign/plan.md`. It has the decisions, the six steps and a status table.
- Each step has its own spec: `spec-01-data-layer.md` (step 1) and `spec-02-app-shell.md` (step 2). Steps 3–6 get specs when the previous step is done.
- Requirements baseline is still `specs/001-sql-permissions-manager/spec.md`, except the matrix-layout FRs that 002 replaces (noted at the top of that file).
- `specs/archive/` is history only. Don't implement from it.
- When a step is finished: tick its acceptance criteria, fill in its "Results" section, and update the status table in `plan.md`.
- Rollback point before the redesign: commit `2c8b54d`.
