# Specs

## Active

| Folder | What it covers |
|---|---|
| [002-pyside6-ui-redesign](002-pyside6-ui-redesign/plan.md) | **Current work.** Moving the UI to PySide6 with a split-view matrix. [plan.md](002-pyside6-ui-redesign/plan.md) has the six steps and their status; each step has its own spec. |
| [001-sql-permissions-manager](001-sql-permissions-manager/spec.md) | The original requirements: user stories, functional requirements (FRs), success criteria, data model, file and DB contracts, validation guide. Still the requirements baseline, except the matrix layout FRs that 002 replaces (noted at the top of `spec.md`). |

## Archive

[archive/](archive/) holds documents that no longer describe the plan, kept for history:

- `001-sql-permissions-manager/plan.md`: the Tkinter implementation plan.
- `001-sql-permissions-manager/ui-spec.md`: the Tkinter UI spec (three view modes, pagination).
- `001-sql-permissions-manager/tasks.md`: the original task list (its checkboxes were never kept up to date).
- `001-sql-permissions-manager/remediation-plan.md`: the 2026-08-04 performance and alignment plan, now replaced by 002.
- `001-sql-permissions-manager/checklists/`: spec-quality and release-gate checklists written against the Tkinter UI spec.
