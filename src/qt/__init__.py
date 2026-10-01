"""
PySide6 user interface for Bifrost.

Layout:
    app.py          main(): QApplication, logging, crash handler, main window
    session.py      Session: application state and flows (no widgets)
    worker.py       DbWorker: runs all database work on one background thread
    theme.py        Colour tokens for light and dark mode
    actions.py      Every menu/toolbar command and its shortcut
    main_window.py  MainWindow
    widgets/        Status bar, pending tray, pills, search field
    views/          Matrix placeholder, audit log
    dialogs/        Settings, tags, commit preview/result, connection lost, messages

Rule: only session.py and worker.py talk to the database layer, and database
calls only ever run on the DbWorker thread.
"""
