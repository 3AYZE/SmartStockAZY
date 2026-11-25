## Download

**Windows 10/11 (64-bit)** — Download **SmartStockAZY.exe** from **Assets** below.

- **SmartStockAZY.exe** — standalone Windows application; no Python installation needed.
- **SmartStockAZY.exe.sha256** — SHA-256 checksum to verify the downloaded executable.

> SmartStockAZY is publicly accessible. No GitHub account or GitHub CLI is required for public downloads.

## Reliability improvements

- Public release downloads require no GitHub login or CLI.
- Updates check the expected executable version and process startup before reporting success; failures attempt rollback.
- Discover displays every successfully scanned stock by default, with duplicate tickers normalized.
- Market refresh requests new benchmark quotes and displays observation times; flat-price RSI and missing risk labels are corrected.
- In-memory caching is bounded, and the Windows release pipeline exercises the actual packaged replacement helper with a disposable database.

## About SmartStockAZY

A free, local-first stock research terminal for exploring the market, screening stocks, reviewing company evidence and downside risk, and monitoring a portfolio.

| Workspace | Key features |
| --- | --- |
| **Market** | Market indexes, sector performance, news and risk context |
| **Discover** | Stonk Hunter screening, opportunity rankings and filters |
| **Research** | Charts, technicals, fundamentals, SEC filings and risk/entry analysis |
| **Portfolio** | Holdings, lots, profit/loss, risk monitoring and alerts |

Settings includes optional local Ollama interpretation and an opt-in updater.

## Install

1. Download **SmartStockAZY.exe** under **Assets** below.
2. Place the EXE in a writable folder.
3. Open it. Microsoft Edge or Google Chrome is recommended for the app-style window.

The EXE bundles the Python backend and user interface. No paid APIs, subscriptions, or mandatory AI are required.

**Existing portfolio?** Review the [migration and backup guide](https://github.com/3AYZE/SmartStockAZY/blob/main/docs/GETTING_STARTED.md) before first launch. The EXE stores its database separately under the Windows local application-data folder.

## Automatic updates

Newer **published GitHub Releases** can be detected within the app. Open **Settings → Application Updates**, then choose **Download & Verify** and **Restart to Install**.

Public in-app updates use the official tagged release asset. Updates are never installed silently. If an older v0.6.1/v0.6.2 updater cannot download the asset, close the application and replace the EXE manually; your AppData database is separate.

## Important information

- This is a **portable, unsigned** Windows EXE, not a Microsoft Store or signed installer.
- Prices, earnings dates, news and financial data can be delayed or unavailable.
- Research scores and suggested entry/exit levels are **not guaranteed predictions or financial advice**.
- The Windows build and local startup are checked automatically; live-provider and end-user update/restart behavior need additional manual verification.

**Guides:** [Overview](https://github.com/3AYZE/SmartStockAZY) · [Windows setup](https://github.com/3AYZE/SmartStockAZY/blob/main/docs/GETTING_STARTED.md) · [Changelog](https://github.com/3AYZE/SmartStockAZY/blob/main/CHANGELOG.md) · [Report a problem](https://github.com/3AYZE/SmartStockAZY/issues/new)
