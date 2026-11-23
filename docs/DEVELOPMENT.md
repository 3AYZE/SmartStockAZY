# Development guide

[← Project overview](../README.md) · [Reliability audit](audit-report.md) · [UI report](ui-redesign-report.md)

SmartStockAZY is a local Windows stock-research application. Its desktop launcher starts a Python HTTP server on **127.0.0.1:8765**, and the user interface is rendered in a browser's app-style window.

## Repository layout

| File or directory | Purpose |
| --- | --- |
| StonkResearch.pyw | Local HTTP backend, research models, provider adapters, portfolio and database operations |
| app.js / app.css / index.html | Main market, discovery, research, portfolio and settings interface |
| update_support.py | Portable Python source updater |
| exe_updater.py | Published GitHub Release updater for packaged Windows EXE builds |
| tools/create_windows_icon.py | Generates the Windows application icon during builds |
| tests/ | Deterministic Python, JavaScript and optional browser tests |
| .github/workflows/validate.yml | Windows/Linux regression checks |
| .github/workflows/release-windows.yml | Build, smoke-test and publish a Windows EXE |

The application does not require paid APIs or mandatory AI. Ollama is an optional local service.

## Run from source

**Requirements:** Python 3.11+, Windows 10/11 and Microsoft Edge or Chrome recommended.

From the repository folder, run:

    python StonkResearch.pyw

Or double-click the PY W launcher in Windows when Python associations are configured.

The source version creates a portable **stonk.db** in its repository folder. Do not commit it or run automated tests against personal databases.

## Test

From the repository root:

**Backend / database / updater regression tests:**

    python -m unittest discover -s tests -v

**JavaScript checks** (Node.js 22 recommended for tests; not required by the app):

    node --check app.js
    node --test tests/test_ui.js tests/test_update_ui.js

**Optional browser fixture:**

    node --test tests/test_browser_ui.js

The optional browser test requires a compatible Playwright module and Chromium/Edge. When the driver is unavailable, the browser fixture may skip; treat it as **UNVERIFIED**, not passed. Fixtures use simulated financial data.

**Synthetic benchmark:**

    python tests/benchmark_portfolio.py

This benchmark uses mocked provider latency. It does not measure live-network performance or validate investment predictions.

## Build the Windows EXE

The preferred packaging workflow is **[Build & Release Windows EXE](../.github/workflows/release-windows.yml)**.

The workflow runs on Windows, installs PyInstaller and Pillow as **build-only dependencies**, generates an icon, builds the single-file GUI executable, verifies its embedded assets and local HTTP startup, and publishes a release only when its required checks pass.

The packaged executable:

- Includes the HTML/CSS/JavaScript UI inside the frozen application.
- Uses a user database under **%LOCALAPPDATA%\SmartStockAZY**.
- Checks published GitHub EXE releases rather than modifying Python source files in place.
- Verifies downloaded EXE integrity and attempts backup/rollback when replacing an older version.

Do not manually distribute a modified EXE without building and testing it. The Windows release is currently unsigned.

## Data and safety

- Keep market facts distinct from calculated heuristics and optional AI interpretation.
- Never fabricate quotes, news confirmation, financial statements, or a score when the evidence is missing.
- Treat historical backtests and simulated benchmarks separately from live trading results.
- Keep automatic stock trading disabled.
- Do not hardcode secrets, GitHub access tokens or personal identifiers.
- Preserve existing SQLite columns and values during migrations; use disposable databases in tests.
- Keep the UI responsive and protect against obsolete asynchronous responses after navigation changes.

## Documentation for reviewers

The main README is intentionally a user-facing introduction. More detailed historical findings and test limitations remain in:

- [Reliability audit](audit-report.md)
- [UI redesign report](ui-redesign-report.md)
- [Version history](../CHANGELOG.md)

For bugs or proposed changes, [open an issue](https://github.com/3AYZE/SmartStockAZY/issues/new) with reproducible details. Avoid posting real portfolio data, credentials, or access tokens.
