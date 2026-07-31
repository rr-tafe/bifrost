"""
User interface layer for Bifrost.

This package provides the Tkinter-based desktop UI:
    - app.py: Root Tk window, tab strip, view lifecycle, startup flow
    - matrix_view.py: Unified matrix view (Single User, All Users, Object modes)
    - settings_view.py: Connection configuration form
    - audit_view.py: Audit log viewer with date/user/object filters
    - widgets/: Reusable UI components (cell renderer, tag editor, status bar, etc.)

Architecture:
    - Canvas-based virtual scrolling for the permission matrix (200 users × 500 objects)
    - Keyboard-first interaction (all features accessible without mouse)
    - WCAG 2.2 Level AA compliance (non-color indicators, focus indicators, screen reader support)

The UI layer depends on services/ for business logic and models/ for data structures.
"""
