#!/usr/bin/env python3
"""
Bifrost - SQL Server Permissions Manager

Entry point for the desktop application. This module initializes the application,
loads the configuration, establishes the database connection, and launches the
main UI window.

Architecture:
    - Load configuration from %APPDATA%/Bifrost/config.json
    - If config missing or corrupt, show Settings view with explanatory message
    - If config valid, attempt SQL Server connection using Windows Authentication
    - On successful connection, load the permission matrix view
    - On connection failure, fall back to Settings view with error details

Usage:
    python main.py               # Qt app
    python main.py --legacy-tk   # previous Tkinter app (removed in step 6)

Requirements:
    - Python 3.11+
    - Windows 11
    - Microsoft ODBC Driver 18 for SQL Server
    - SQL Server 2019+ with db_owner or sysadmin privileges on target database
"""

import sys


def main() -> int:
    """Start the Qt app, or the previous Tk app with --legacy-tk (until step 6)."""
    if "--legacy-tk" in sys.argv[1:]:
        from src.ui.app import main as legacy_main

        return legacy_main()

    from src.qt.app import main as qt_main

    return qt_main([arg for arg in sys.argv if arg != "--legacy-tk"])


if __name__ == "__main__":
    sys.exit(main())
