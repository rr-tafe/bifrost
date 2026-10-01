# Bifrost

Bifrost is a desktop app for managing SQL Server object permissions. It shows GRANT and DENY permissions as a matrix of users against objects, lets you change them, and records every change in an audit log.

- [The new interface (in progress)](#the-new-interface-in-progress)
- [Running on macOS (development)](#running-on-macos-development)
- [Running on Windows](#running-on-windows)
- [Troubleshooting](#troubleshooting)

## The new interface (in progress)

Bifrost is moving from Tkinter to a PySide6 (Qt) interface built for databases with hundreds of principals and thousands of objects. The plan and status are in [specs/002-pyside6-ui-redesign/plan.md](specs/002-pyside6-ui-redesign/plan.md).

- `python main.py` starts the new interface. The Matrix tab is a split view: pick a principal (or, in **By object** mode, an object) on the left, and its permissions show on the right as a grid of objects (or principals) against the 8 permissions.
  - Click selects a cell and never changes it. Double-click or Space changes one cell (none → GRANT → DENY → none). With cells selected, **G** grants, **D** denies, **R** or Delete revokes and **U** reverts to the committed state.
  - Click a column header to select that permission for every row, or a name to select the row. Right-click for presets, group actions ("Grant SELECT on all 86 objects in sales") and **Make like…**.
  - Changing 5 or more cells asks first. Everything is staged until you commit, and Ctrl+Z undoes.
  - **Ctrl+K** jumps to a principal, object or tag. **Ctrl+Shift+1** / **Ctrl+Shift+2** switch modes. **F6** moves between the list, the grid filter, the grid and the pending changes.
  - **Help → Database summary** shows what was loaded.
- `python main.py --legacy-tk` starts the previous Tkinter interface. It stays until step 6 in case something is missing from the new one.
- The app logs to `logs/bifrost.log` next to `config.json` (`~/Library/Application Support/Bifrost/` on a Mac, `%APPDATA%\Bifrost\` on Windows). Set `BIFROST_DEBUG=1` for more detail.

## Running on macOS (development)

On a Mac, Bifrost connects to a local SQL Server 2022 Developer Edition container, which is free for development and testing. macOS can't use Windows Authentication, so the app logs in with a dev-only SQL login. The login details are read from `dev/.env` and never written to the config file.

### After a reboot

Run these from the project folder:

```bash
cd ~/Documents/Projects/bifrost

# 1. Start the container runtime (the Linux VM that hosts Docker)
colima start

# 2. Start SQL Server and make sure the BifrostDev database is seeded
./dev/setup.sh

# 3. Load the dev login into this terminal session, then launch the app
set -a; source dev/.env; set +a
.venv/bin/python main.py
```

Step 3 only applies to the terminal you run it in. If you open a new terminal, run the `source` line again before starting the app.

### Settings to use

The first time you start the app, Settings opens. Enter:

| Field    | Value        |
|----------|--------------|
| Server   | `localhost`  |
| Port     | `1433`       |
| Database | `BifrostDev` |
| Schema   | `dbo`        |

Click **Test connection**, then **Save and connect**. The settings are saved to `~/Library/Application Support/Bifrost/config.json`, and later launches connect automatically.

The Settings window still says "Windows Authentication". On a Mac that's expected: while the dev login variables are set, they take over.

### Test data

`dev/seed.sql` creates the `BifrostDev` database with:

- **Users:** `test_alice`, `test_bob`, `test_carol`, `report_svc`, `etl_svc`
- **Objects:** tables in the `dbo` and `sales` schemas, a view, a stored procedure and a function
- **Starting permissions:** a few GRANTs and one DENY

You can re-run `./dev/setup.sh` at any time. It keeps your existing data and passwords.

To test at work-database scale, run `./dev/setup.sh --large`. It also loads `dev/seed_large.sql`, which adds 500 principals (`lg_user_0001` to `lg_user_0500`), 5,000 objects across schemas `lg01` to `lg20`, and about 49,000 explicit permissions. It takes about 15 seconds the first time and is safe to re-run. To go back to the small dataset, wipe the database (below) and run `./dev/setup.sh` without `--large`.

### Stopping, resetting and running tests

```bash
# Stop SQL Server and the VM (frees about 4 GB of RAM)
docker compose -f dev/docker-compose.yml --env-file dev/.env stop
colima stop

# Wipe the database and start fresh
docker compose -f dev/docker-compose.yml --env-file dev/.env down -v
./dev/setup.sh

# Run the tests
.venv/bin/python -m pytest

# Run only the fast tests (what the pre-commit hook runs)
.venv/bin/python -m pytest -m "not slow and not integration"

# Run the performance tests and print timings
# (1,000 principals x 20,000 objects x 200,000 permissions, synthetic)
.venv/bin/python -m pytest -m slow tests/perf -s --no-cov
```

### First-time setup on a new Mac

These steps are already done on this machine. On another Mac:

```bash
brew install colima docker docker-compose python@3.11
brew tap microsoft/mssql-release https://github.com/Microsoft/homebrew-mssql-release
brew trust --formula microsoft/mssql-release/msodbcsql18
brew trust --formula microsoft/mssql-release/mssql-tools18
HOMEBREW_ACCEPT_EULA=Y brew install msodbcsql18 mssql-tools18

# Let Docker find the compose plugin
mkdir -p ~/.docker
echo '{ "cliPluginsExtraDirs": ["/opt/homebrew/lib/docker/cli-plugins"] }' > ~/.docker/config.json

# SQL Server images are x86-only; run them through Rosetta on Apple Silicon
colima start --vm-type vz --vz-rosetta --cpu 4 --memory 4

python3 -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
./dev/setup.sh
```

The `echo` line overwrites any existing `~/.docker/config.json`. If you already have one, add the `cliPluginsExtraDirs` entry to it by hand.

After the first `colima start`, a plain `colima start` remembers these settings.

## Running on Windows

On Windows, Bifrost connects to your real SQL Server using your Windows login. No password is entered or stored.

### Requirements

- Windows 10 or 11
- [Python 3.11 or later](https://www.python.org/downloads/windows/) (3.14 is what we test with)
- [Microsoft ODBC Driver 18 for SQL Server](https://learn.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server)
- On the target database, your Windows account must be a member of `db_owner` (or `sysadmin` on the server)

### First-time setup

In PowerShell, from the project folder:

```powershell
py -3 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

### Running the app (including after a reboot)

```powershell
cd path\to\bifrost
.venv\Scripts\python main.py
```

The first time you start the app, enter your server name, port (usually `1433`), database and schema in Settings. Click **Test connection**, then **Save and connect**. The settings are saved to `%APPDATA%\Bifrost\config.json`, and later launches connect automatically.

Don't set `BIFROST_DEV_SQL_USER` or `BIFROST_DEV_SQL_PASSWORD` on Windows. They switch the app from Windows Authentication to the dev SQL login.

### Optional: local test database on Windows

To try changes without touching a real server, you can run the same SQL Server container on Windows:

1. Install [Docker Desktop](https://www.docker.com/products/docker-desktop/) and [Git for Windows](https://git-scm.com/download/win), which includes Git Bash.
2. In Git Bash, run `./dev/setup.sh` from the project folder.
3. In Git Bash, load the dev login and start the app:
   ```bash
   set -a; source dev/.env; set +a
   .venv/Scripts/python main.py
   ```
4. In Settings, use the same values as on macOS (`localhost`, `1433`, `BifrostDev`, `dbo`).

## Troubleshooting

**"OpenSSL library could not be loaded" (macOS)**
The ODBC driver supports OpenSSL up to version 3, and a Homebrew upgrade can switch `/opt/homebrew/opt/openssl` back to OpenSSL 4. Point it at version 3 again:
```bash
ln -sfn ../Cellar/openssl@3/$(ls /opt/homebrew/Cellar/openssl@3 | tail -1) /opt/homebrew/opt/openssl
```

**"SSPI Provider: No credentials were supplied" on macOS**
The dev login wasn't loaded in this terminal. Run `set -a; source dev/.env; set +a` before starting the app.

**"Cannot connect to the Docker daemon"**
Colima isn't running. Run `colima start`.

**`./dev/setup.sh` waits a long time, or the container shows as unhealthy**
SQL Server needs about 2 GB of RAM to start. Check with `colima list` that the VM has at least 4 GiB of memory.

**"No SQL Server ODBC driver found"**
Install Microsoft ODBC Driver 18: `msodbcsql18` on macOS (see first-time setup above), or the Windows installer linked above.
