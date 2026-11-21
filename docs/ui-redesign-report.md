# SmartStockAZY — Stock Terminal UI Redesign

**Review status:** Feature branch `codex/stock-terminal-ui`, awaiting pull request review. No release or merge performed as part of the implementation.

## Navigation changes

| Previous section | New location | Notes |
| --- | --- | --- |
| Market | Market → Overview | Indexes, market regime, sector performance, risk context |
| Stonk Hunter | Discover | Scanning, opportunity ranking, search, filters, sorting |
| Deep Research | Research | Company overview, interactive charts, evidence and scores |
| News Intelligence | Market → News; Research → News & Events | Market headlines and ticker-specific events remain accessible |
| Portfolio | Portfolio → Holdings | Lot CRUD, grouped holdings, thesis, exposure, P/L |
| Risk Monitor | Portfolio → Risk Monitor | Exit and thesis risk analysis |
| Alerts | Portfolio → Alerts | WATCH-or-higher queue and severity |
| Settings | Sidebar Settings gear | Scanner, SEC, optional Ollama, data policy, GitHub updates |

Research also organizes **Financials & SEC**, **Technicals**, and **History** in tabs. The top bar exposes ticker search in every workspace. Market and Portfolio show their section tabs below the top bar, avoiding duplicated sidebar routes.

## Visual and interaction changes

- Replaced the earlier crowded navigation with four icon-labeled workspaces and a compact Settings entry; icon-only navigation activates in narrow windows.
- Adopted graphite surfaces, restrained blue emphasis, consistent inputs/buttons, legible type, compact tables, and distinct positive/negative/warning states.
- Structured Market around market snapshot, sectors, regime, and headline context, with News separated into its own tab.
- Redesigned Discover with sortable table columns, search, quick presets, collapsible advanced filters, and expandable per-ticker context. Cached scan results, filter selections, and the return path from Research are retained.
- Structured Research into distinct tabs with a larger chart, interactive range/overlay controls, evidence and risk panels, and research history.
- Combined holdings, risk, and alerts under Portfolio. The add/edit form collapses until needed; lot management and position analysis remain available.
- Preserved the in-app update notification, verified download stage, and explicit restart/install action under Settings.
- Corrected a header clipping issue when the update notification is visible around 1024 px. Fixed Discover's fifth summary metric wrapping awkwardly by using adaptive grid columns.
- Added a descriptive document title, accessible labels for the main navigation/search, and reduced-motion support.

## Consolidation and preserved behavior

**Removed from top-level navigation:** separate News Intelligence, Risk Monitor, Alerts, and full-size Settings routes; their live content is available in the locations above. Simplified repeated introductory/decorative content on Market and collapsed rarely needed filters/forms. No stock scoring feature, backend endpoint, or saved-data field was intentionally removed.

**Preserved:** the lightweight Python `.pyw` startup, HTML/CSS/JavaScript UI, SQLite compatibility, zero mandatory paid services, optional Ollama, free market/news/SEC providers, scanner scoring, company versus entry quality, chart ranges/overlays, research history, portfolio lots and cost basis, thesis health, exit/risk and profit-protection logic, alerts, settings persistence, and opt-in GitHub updater. The redesign did not modify `stonk.db` or change trade execution behavior.

## Files changed

| Path | Purpose |
| --- | --- |
| `app.js` | Workspaces, tabs, headers, context navigation, table/search interactions, return state |
| `app.css` | Design tokens, layouts, tables, controls, responsive header and chart presentation |
| `index.html` | Application page title |
| `tests/test_browser_ui.js` | Browser fixture workflow and viewport overflow checks |
| `README.md` | User-facing navigation migration guide |
| `docs/ui-redesign-report.md` | Redesign details and verification boundaries |
| `docs/ui-screenshots/*.png` | Headless Edge fixture images, not live market data |

## Verification (2026-11-21)

- Python: `python -m unittest discover -s tests -q` — **36 passed**, with one non-fatal `ResourceWarning` during temporary HTTPError cleanup.
- JavaScript: `node --test tests/test_ui.js tests/test_update_ui.js` — **15 passed**.
- Browser fixture: `node --test tests/test_browser_ui.js` with `SMARTSTOCK_PLAYWRIGHT_CORE` pointing to an external `playwright-core` installation — **1 passed** in real headless Microsoft Edge. Fixture endpoints validate Market, Discover filters/sort, Research chart/range/overlay/SEC/history, Holdings CRUD, Risk Monitor, Alerts, settings persistence, update-check/download UI flow, and an offline market error.
- Browser resize checks: **1280, 1024, 840, 720, and 480 px**, across **Market, Discover, Research, Portfolio, Settings**; no document-level horizontal overflow detected and global ticker search remained usable.
- `node --check app.js` and `git diff --check` — passed.
- Screenshots: [Market](ui-screenshots/market.png), [Discover](ui-screenshots/discover.png), [Research](ui-screenshots/research.png). **Screenshots contain simulated fixture quotes and headlines**. They are not claims about market prices or provider availability.

The browser test uses an in-memory fixture server and never accesses the user's real portfolio database. Its simulated updater endpoint validates UI states and button wiring only; it does not install or run downloaded code.

## Remaining validation / release risks

1. **Windows desktop launch:** manually double-click `StonkResearch.pyw` in a representative Windows environment, confirm no console window, navigation and window resizing, and save a settings change.
2. **Live sources:** validate real market feeds, delayed/stale indicators, SEC user agent, news results, error messages, and optional Ollama when configured. Free providers can be throttled or unavailable.
3. **Real data:** back up a test copy of SQLite and confirm historic research and portfolio lots load as expected. Do not use or modify the user's actual `stonk.db` for QA.
4. **Updater application:** from a sacrificial portable install, use authenticated private GitHub access, verify download/signature comparison and explicit restart/install/rollback; fixture checks cannot prove this path.
5. **Visual acceptance:** review contrast, long company names, chart legibility, and keyboard operation manually at common desktop sizes. Browser fixture coverage is not a full accessibility audit.

The branch should remain a **draft PR** until those manual release checks are completed.
