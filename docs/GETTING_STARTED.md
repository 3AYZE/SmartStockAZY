# Windows setup and updates

[← Back to SmartStockAZY](../README.md) · [Latest Windows EXE](https://github.com/3AYZE/SmartStockAZY/releases/latest)

## 1. Download and launch

1. Open the [latest release](https://github.com/3AYZE/SmartStockAZY/releases/latest).
2. Under **Assets**, download **SmartStockAZY.exe**. You must be signed into a GitHub account that can access this repository while it remains private.
3. Place the file in a writable folder, such as a folder inside Documents or Downloads.
4. Double-click **SmartStockAZY.exe**. The local engine starts and opens the interface in a Microsoft Edge or Google Chrome app-style window.

The EXE is a **standalone, portable Windows 64-bit application**. It does not require you to install Python, Ollama, Node.js, or a paid API. A compatible browser is recommended for the interface.

> **Windows security:** This EXE is not code-signed. Windows may report an unknown publisher. Download only from the official GitHub Release, and verify the source before deciding whether to run an unsigned application. Do not disable Windows security protections.

## 2. First use

- **Market:** Review market indexes, sectors, and headlines.
- **Discover:** Run Stonk Hunter and filter stocks by risk and opportunity.
- **Research:** Search a ticker to view price charts, financial information, risks, and source evidence.
- **Portfolio:** Add holdings and review positions, risk, and alerts.
- **Settings:** Configure optional features and check for application updates.

Data comes from free, best-effort sources. A missing quote or filing does **not** mean the value is zero; the application may show it as unavailable.

## 3. Existing portfolio data

**Windows EXE storage:** Your live portfolio database is stored in:

    %LOCALAPPDATA%\SmartStockAZY\stonk.db

The application does not put the database inside the replaceable EXE.

**Moving from the older Python version:**

1. Completely close the older application.
2. Back up the old portable data before proceeding. If the source uses SQLite WAL mode, preserve the related WAL/SHM files alongside the main database while the app is closed, or create a SQLite online backup.
3. Put the new **SmartStockAZY.exe** in the same folder as the old **stonk.db**.
4. On first launch, when no AppData database already exists, the EXE uses SQLite's online backup mechanism to copy the nearby portable database into its user-data directory. The original file remains where it was.
5. Verify your holdings and research history before deleting or moving any old files.

**Important:** If you already have a database under the AppData path, automatic portable migration is skipped to avoid overwriting it. Back up and reconcile the two copies yourself; do not replace one with the other blindly.

## 4. Update the Windows EXE

The packaged app checks the **latest published GitHub Release** at startup and periodically. It does not install every commit to the main branch.

Go to **Settings → Application Updates**:

1. **Check for Updates** — check manually.
2. **Download & Verify** — retrieve the versioned EXE and validate its published SHA-256 digest.
3. **Restart to Install** — approve installation; the updater attempts to replace the old executable after it closes.

The previous EXE is backed up in the user-data directory. Your local SQLite database is separate from the application executable. **Updates are opt-in; they never silently replace the running app.**

### Private GitHub repository access

SmartStockAZY's repository is currently **private**. In-app release checks need an account with access.

1. Install the free [GitHub CLI](https://cli.github.com/).
2. Open PowerShell or Windows Terminal and run:

       gh auth login

3. Sign in to a GitHub account with permission to access the SmartStockAZY repository.
4. Open SmartStockAZY and select **Check for Updates** in Settings.

The updater reads your existing GitHub CLI authentication when needed. It does **not** embed a personal access token in its code or SQLite database.

If the repository becomes public in the future, GitHub CLI authentication is not required for public release downloads.

> **Verification boundary:** The EXE build, startup and bundled UI/API checks passed in GitHub Actions, but a complete private-repository download, replacement and restart cycle on an end-user Windows PC has not yet been independently validated. Keep a backup of the previous EXE until your first update succeeds.

## 5. If something goes wrong

| Problem | What to check |
| --- | --- |
| GitHub release is inaccessible | Confirm you are signed into a GitHub account with access to this private repository |
| Update check asks for GitHub CLI | Install GitHub CLI, run **gh auth login**, then retry |
| Application window does not appear | Confirm Edge or Chrome is installed and another copy of SmartStockAZY is not already running |
| Port 8765 already in use | Close duplicate SmartStockAZY processes and retry |
| Data or research is missing | Check that the active database is at the AppData path and that you migrated the correct portable database |
| News or market results are missing | A free provider may be unavailable, rate-limited, or returning incomplete data; retry later |
| Update failed | Keep the previous executable; inspect the update status and any backup under the AppData SmartStockAZY folder |

If you can reproduce a problem, [open an issue](https://github.com/3AYZE/SmartStockAZY/issues/new) with the app version, steps, expected behavior, actual behavior, and a screenshot if useful. **Do not include account tokens, private portfolio records, or other secrets.**

## 6. Using the Python source version

Developers can continue to run **StonkResearch.pyw** with **Python 3.11 or newer**. Unlike the standalone EXE, the source version keeps its SQLite database in the script folder and uses a source-file update mechanism.

See the [development guide](DEVELOPMENT.md) for source setup and tests.
