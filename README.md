# SmartStockAZY v0.6 — Windows Standalone EXE & GitHub Auto-Updates

The preferred Windows download is **SmartStockAZY.exe** under [GitHub Releases](https://github.com/3AYZE/SmartStockAZY/releases/latest). Builds are created automatically from tested changes to the repository's main branch by a Windows GitHub Actions runner.

- Single-window-style desktop app launched by a standalone SmartStockAZY.exe.
- **No Python installation, console window, or paid services required** to run the EXE.
- The interface is bundled into the executable.
- Settings → Application Updates checks GitHub's latest *published* EXE, not raw source commits.
- New releases are detected automatically at startup and periodically; choose **Download & Verify**, then **Restart to Install**. No silent installation.
- Updates validate the exact asset's SHA-256 checksum published by GitHub before replacing the EXE. The old EXE is backed up; a temporary copy of the updater waits for the app to shut down, replaces the old EXE, and starts the new backend without launching a duplicate browser window.
- Runtime user data is stored under **%LOCALAPPDATA%\SmartStockAZY\stonk.db**. The EXE is replaceable without overwriting that database. On first run, if there is no existing AppData database but an older portable stonk.db sits **next to the EXE**, it is copied using SQLite's online backup API; the original stays untouched.
- Backups and update results are stored under **%LOCALAPPDATA%\SmartStockAZY\**.
- The standalone EXE uses the existing browser's app mode (Microsoft Edge preferred or Chrome) as its window. Its own executable remains the local engine. This is not an Electron bundle.
- This is an unsigned community application: Windows SmartScreen may display a warning. Do not disable security software; review the source and download only from the repository's official Release assets.

## Private GitHub release access

The repository is private, so downloads and update checks require a GitHub account with access. For the in-app updater, install the **free GitHub CLI** and run **gh auth login** once. The updater reads the CLI token in memory, does not embed or save credentials, and uses only the official GitHub API and Release asset URLs.

If the repository becomes public, GitHub CLI is not required.

**Important:** Update notifications appear only for a *successful published Windows EXE release*, not every source-code commit while GitHub Actions is still building it.

## Standalone Windows EXE build pipeline

Workflow: [Build & Release Windows EXE](.github/workflows/release-windows.yml).

Each qualifying main-branch application update or a manual workflow dispatch:

1. Runs Python and JavaScript regression tests.
2. Packages a single SmartStockAZY.exe using the free PyInstaller build tool (not a runtime dependency).
3. Smoke-tests the actual generated EXE, embedded UI files and updater API on Windows.
4. Uploads the EXE and a .sha256 verification file as GitHub Actions artifacts.
5. Publishes a new GitHub Release (v0.6.[run-number]), but **only if all earlier steps pass**.

Historical strategy backtesting and live-provider functionality are separate from the installer build. The release workflow tests packaged startup and deterministic regressions, not trading-prediction accuracy.

## Portable Python version

StonkResearch.pyw remains usable for Python 3.11+ development without PyInstaller. In that mode, the existing source updater continues to update allowlisted source files. The portable database remains next to the script.

The Windows EXE uses its independent **release asset** updater; it never attempts to install .pyw files over a running EXE.

---

# SmartStockAZY v0.6 — Windows EXE and Auto-Updates

A lightweight, $0-first local stock research terminal for Windows. The core engine is deterministic; Ollama remains optional.

## Stock terminal interface (review branch)

The updated interface groups the application's existing tools into four workspaces with **Settings** at the bottom of the sidebar:

| Current workspace | Previous menu entries | Where to find the tools |
| --- | --- | --- |
| **Market** | Market, News Intelligence | Overview and News tabs for indexes, regime, sectors, and market headlines |
| **Discover** | Stonk Hunter | Opportunity scan, sortable results, quick and advanced filters, per-ticker research |
| **Research** | Deep Research | Overview, Financials & SEC, Technicals, News & Events, History |
| **Portfolio** | Portfolio, Risk Monitor, Alerts | Holdings, Risk Monitor, Alerts tabs, plus lot editing and thesis tracking |
| **Settings** (gear) | Settings | Free data policy, scanner options, optional Ollama, SEC access, GitHub updates |

Use the **ticker search in the top bar** to open research from any workspace. On narrower windows the sidebar switches to icons; hover over an icon for its name. Tables can scroll horizontally without moving the entire page. The Update Available indicator leads to the existing opt-in update controls in Settings.

This UI redesign is on a review branch and is **not yet a released build**. See [UI redesign report](docs/ui-redesign-report.md) for changes, fixture screenshots, automated checks, and remaining manual Windows validation.

## v0.5 highlights

### Stricter decision reliability

- Separates **Company Quality** from **Current Entry Quality**.
- Adds **gap/chase risk** so a stock that jumps sharply is not rewarded just because price is rising.
- Adds a stronger **falling-knife detector** using trend, recent momentum, lower lows, distance from the recent low, and stabilization.
- Adds **Stabilization Score** so oversold stocks must actually stabilize before entry quality improves.
- Adds a **downside-first** entry model: downside to support is evaluated before upside to resistance.
- Adds **Upside / Downside** and stricter reward/risk gates.
- BUY ZONE now requires quality, entry, downside control, risk, confidence, timing, and event-risk checks together.
- Adds best-effort **earnings-date risk**. If the free calendar source is unavailable, the app says UNKNOWN instead of guessing.

### Better Deep Research

- Shows Gap Risk, Falling-Knife Risk, Stabilization, Earnings Risk, and Downside-First R/R.
- Shows **Why NOT Buy Now** and the exact conditions that would improve or invalidate the decision.
- Adds per-source **Data Freshness**.
- Explicitly separates **Primary Facts**, **Calculated Signals**, and optional **AI Interpretation**.
- Research History now includes a **What Changed** summary between snapshots.
- Chart event overlay marks large historical price gaps and high-impact news dates when available.

### Stonk Hunter polish

- Sortable columns.
- Ticker/company search.
- Minimum Opportunity and maximum Risk filters.
- Sector filter using the built-in benchmark map.
- Shows average volume, Gap Risk, Falling-Knife Risk, status, and a short reason.
- Oversold filter now excludes severe falling knives.
- Top finalists prefetch SEC/news data in the background to reduce Deep Research wait time.

### Portfolio polish

- Positions are treated as editable **lots**.
- Edit shares, average cost, ticker, thesis, and tracked thesis reasons without deleting/re-adding.
- Multiple lots of the same ticker are grouped into a combined holding summary.
- Adds weighted average cost per ticker.
- Adds sector exposure and sector-concentration warnings.
- Position-specific profit protection now includes the trailing method and can tighten when a profitable position becomes extended/gap-sensitive.
- Thesis Health and Exit Risk remain lot-aware.

## Requirements

- Windows 10/11
- Python 3.11+
- Microsoft Edge or Google Chrome recommended
- Ollama optional

## Start

Double-click:

`StonkResearch.pyw`

## Important

This is a research tool, not a broker or financial adviser. Free market/news/calendar sources can be delayed, incomplete, rate-limited, or unavailable. Entry, trailing-exit, take-profit, and risk levels are model-generated research references, not guarantees. Automatic buying/selling is never enabled.

## Audit hardening on review branch (2026-11-21)

The codex/stock-research-audit-v050 review branch improves reliability while preserving the v0.5.0 interfaces and the existing zero-dependency Windows application. It is **not a published release**.

- Current prices use the time of the source observation. Stale or missing prices display as unavailable for current valuations, entry/exit signals, and portfolio P/L.
- Portfolio positions with the same ticker share one research request, while keeping their own cost basis. Grouped holdings use weighted average cost; an incomplete valuation is clearly marked.
- SEC annual metrics use full-year periods; free cash flow is computed only when operating cash flow and capital expenditures refer to matching fiscal ends.
- News and market feeds tolerate partial outages. News outlet counts are no longer presented as proof of independent confirmation; a bullish headline alone cannot confirm a catalyst thesis.
- Stonk Hunter applies more conservative falling-knife, gap-chase and risk/reward gates. These are unbacktested heuristics.
- Page, news, research and chart responses are checked before updating the interface to prevent late results from replacing a newer selection.

### Verification on this branch

From the project directory, use:

    python -m unittest discover -s tests -v
    node --test tests/test_ui.js
    node --check app.js
    python tests/benchmark_portfolio.py

Node.js is needed for JavaScript tests only, **not to run the application**. Python tests use mocked network providers and temporary SQLite files; they do not open your personal stonk.db. The synthetic benchmark compares the current working copy to main using simulated provider delays. See docs/audit-report.md for the dated results, outstanding risks, and manual Windows checks.

### Back up your portfolio data before updating

Close the app fully first. Back up stonk.db **along with any existing stonk.db-wal and stonk.db-shm files** (or use SQLite's online backup mechanism while open). The DB uses write-ahead logging, and copying just the main file while the app is open could omit recent changes. The migration retains existing rows and only adds missing legacy columns to positions. If migration fails, it now reports an error rather than silently proceeding.

### Accuracy and launch limitations

This app uses free, best-effort market and news sources. Source timestamps and UNKNOWN/UNAVAILABLE labels reduce misleading output but do not ensure exchange-grade price freshness or investment accuracy. Signals have not been calibrated by historical backtests. Windows UI, all controls, and live source-provider resilience still require manual verification before release.


## v0.5.1 — Opt-in GitHub auto-updater

The Windows app checks the GitHub **main** branch at launch and periodically (at most every 6 hours, unless you manually press Check for Updates). It compares the actual application-file Git hashes against the selected main-branch commit, so documentation-only commits do not trigger a new program update and a forgotten version-number bump does not hide one.

**Settings → Application Updates** contains:

1. **CHECK FOR UPDATES** — manually refresh from GitHub.
2. **DOWNLOAD & VERIFY** — download only the selected immutable main-branch commit and validate each managed file against GitHub's commit tree.
3. **RESTART TO INSTALL** — explicitly approve installation. The existing window reconnects after the backend restarts.

There is also an **UPDATE AVAILABLE** notification in the top bar. The app **never silently installs code or auto-updates while you work**.

### Private GitHub repository

This repository is currently private. Unauthenticated updater checks cannot access private GitHub files. To enable update checking on a computer with access to this repository:

- Install the free GitHub CLI (https://cli.github.com/).
- Run the command **gh auth login** once in a terminal using a GitHub account with permission to view this repository.
- Start SmartStockAZY and select **Settings → Check for Updates**.

The app reuses an existing CLI login in memory; **no GitHub token is embedded in its source or saved in the SQLite settings database**. If the repository becomes public later, the updater can use GitHub without the CLI.

### Updating existing installations

**One-time bootstrap:** versions older than v0.5.1 do not have an updater. Replace the *program files* from the GitHub main-branch download once (while the app is fully closed), **without deleting your existing stonk.db**. Thereafter, the application can detect future changes to main.

### Safety and recovery

- The update only replaces: StonkResearch.pyw, app.js, app.css, index.html, update_support.py, README.md.
- stonk.db, its SQLite journal files, settings, research history, downloaded data, and custom files are not intentionally overwritten.
- Before replacement, a backup of existing program files and an online SQLite backup of the portfolio database is stored in %LOCALAPPDATA%\SmartStockAZY\backups\ on Windows.
- A failed replacement triggers rollback of already replaced application files; the last update result is shown in Settings.
- Code is obtained only from the hardcoded 3AYZE/SmartStockAZY repository, main branch, over HTTPS and pinned to a specific commit. Source contents are verified against Git blob hashes before installing. This validates the downloaded code against the chosen GitHub commit; it does **not** audit the safety of changes the repository owner merges.
- Installing into a protected folder (for example C:\Program Files) may fail without write access. Use a writable location for portable installation.
- On GitHub authentication, provider, or network errors, the current app continues to work; status is shown clearly instead of installing unverified files.
- Automated tests run on Windows and Linux in GitHub Actions. Manual Windows double-click, update/relaunch and private-account tests are still required before treating the updater as production-verified.

**No Python packages, paid updater service, automatic trading, or mandatory AI are required.**
