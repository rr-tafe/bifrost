# Remediation Plan: Matrix Performance + Spec Alignment

Date: 2026-08-04
Scope: Address highest-impact deviations identified in spec review and improve responsiveness.

## Phase 1 (Implement Now)

1. Matrix performance foundations
- Remove eager full-grid materialization in `PermissionMatrix.load()`.
- Keep assignments sparse (explicit GRANT/DENY only), synthesize `NONE` on demand.
- Ensure staging works for cells not pre-materialized.
- Keep refresh behavior preserving staged changes.

2. Commit/cancel workflow correctness
- Use `PermissionMatrix.commit()` as the single commit path from UI.
- Remove duplicate DB apply/audit writes from UI layer.
- Preserve partial-failure behavior and user feedback.

3. Export functionality
- Implement permission and audit CSV export via existing export service.
- Add Save As flow with suggested filename.

4. Undo/redo functionality
- Wire app shortcuts/menu handlers to matrix service undo/redo.
- Refresh matrix and status after undo/redo.

## Phase 2 (Next)

1. Unified Matrix View architecture alignment (FR-001)
- Add in-view mode controls: Single User, All Users (Compare), Object View.
- Add user/object selectors and orientation banner.

2. Compare mode scalability (FR-028, SC-007)
- User pagination (5/10/20/all), pinned users, page indicator.

3. Matrix semantics and accessibility (FR-003, FR-024, FR-025)
- Cross-query highlight.
- Non-color state symbols in cells.
- Keyboard and announcement improvements.

## Phase 3 (Next)

1. Advanced commit UX (FR-026)
- Commit preview dialog and success summary.

2. Connection-loss flow (FR-022)
- Detect and surface reconnect workflow while preserving staged changes.

## Implementation Notes

- Phase 1 is designed to be low-risk and high-impact for current sluggishness.
- Phase 2 and 3 require broader UI restructuring and should be delivered incrementally.

## Validation Gates

- Unit tests for matrix service pass.
- App can toggle, stage, commit/cancel, export, undo/redo without exceptions.
- Refresh preserves staged changes.
