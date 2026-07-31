"""
Reusable UI widgets for Bifrost.

This package provides custom Tkinter widgets used across multiple views:
    - cell_renderer.py: Canvas cell with click-to-cycle, context menu, highlighting
    - tag_editor.py: Tag assignment dialog for users and objects
    - status_bar.py: Global status bar (staged changes, Commit/Cancel, connection info)
    - loading.py: Loading indicators and progress states
    - empty_state.py: Empty state screens for no results/data
    - confirmation_dialog.py: Modal confirmation dialogs
    - warning_dialog.py: Warning dialogs for validation failures
    - commit_failure_dialog.py: Partial commit failure reporting

Widgets are designed for reuse and follow WCAG 2.2 Level AA accessibility guidelines.
"""
