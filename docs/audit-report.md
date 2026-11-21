# SmartStockAZY v0.5.0 — Audit and review report

Date: 2026-11-21
Baseline: main at 6680345 (v0.5.0)
Review branch: codex/stock-research-audit-v050
Pull request: https://github.com/3AYZE/SmartStockAZY/pull/2
Release status: review only; not merged, deployed, or published

## 1. Findings and priority

| Severity | Finding | Root cause and risk | Review branch action |
| --- | --- | --- | --- |
| P0 | Incorrect/false portfolio P/L when a quote is missing or stale | Missing valuation was previously treated as a current amount or contributed to incomplete totals. | Unpriced values, P/L, weights, and exits explicitly unavailable; totals marked incomplete. |
| P0 | Multiple lots can misstate combined cost/holding basis | Per-lot valuation and grouping did not consistently preserve weighted cost. | Accumulate lot costs, compute weighted basis, group holdings, and avoid partial portfolio totals. |
| P1 | Legacy database migration failures were concealed | Broad exception suppression could hide a failed ALTER TABLE. | Surface migration error; retain additive schema migration. |
| P1 | SQLite connection lifecycle incomplete | Connection context transaction did not guarantee connection close on Windows. | Explicit context manager closes every connection. |
| P1 | Market data looked fresher than it was | Fetch time was used where observation time was required. | Preserve provider bar timestamp, mark stale market observations, and separate retrieval timestamps. |
| P1 | Unreliable financial fundamentals | Annual SEC facts could contain quarterly duration; unmatched capex could distort FCF. | Require full-year facts and matching fiscal year end; return unavailable when insufficient. |
| P1 | News was presented as independently confirmed without primary evidence | Republishing and multiple news outlets were conflated with verification. | Group duplicate stories, identify outlet count, reserve confirmation for SEC primary evidence. |
| P1 | Headline keyword false positives | Substring matches on ambiguous or negated words elevated risk. | Add negation-aware, bounded term matching for major risk terms. |
| P1 | News outages could block market content | Fast feed fallback and dashboard error handling assumed news providers worked. | Prefer primary feed and tolerate provider errors; display missing evidence. |
| P1 | Strong Hunter candidates could be chasing gains or falling sharply | Opportunity score insufficiently capped on gap, falling-knife, and stabilization risk. | Cap ranking for high risk; gate STRONG SETUP on risk/reward and stabilization. |
| P1 | Older async responses could overwrite the selected UI | Page, news, research, and chart requests lacked complete response ordering guards. | Ignore responses for superseded page/selection generations. |
| P2 | Partial data wasn't obvious in summaries | Missing market/news/valuation coverage lacked clear UI warnings. | Surface stale, missing, and incomplete labels. |

Priority is an engineering risk classification based on code review and deterministic reproductions. No live investment-prediction performance is claimed.

## 2. System map and inspected scope

- Backend: StonkResearch.pyw (Python 3.11+ standard library); localhost HTTP server, research/scoring engine, provider adapters, cache and SQLite.
- Frontend: index.html loads app.js and app.css. JavaScript renders Market, Stonk Hunter, Deep Research, News Intelligence, Portfolio, Risk Monitor, Alerts, and Settings; browser app mode is launched by the .pyw file.
- Providers: Yahoo chart/search data, SEC company facts and filings, GDELT news fallback; optional localhost Ollama adds interpretation.
- Persistence: local stonk.db with settings, positions, research_history, response_cache. Schema uses WAL and additive positions thesis_json/updated_at migration.
- API: health/settings/ping, dashboard, chart, stock, research/history, news search, Hunter, positions CRUD, risk, alerts, and optional AI.
- Existing issue tracker was considered in the preceding inspection. The review branch adds no new paid source, dependency, broker integration, or automatic trades.

## 3. Features fixed

- Portfolio missing/invalid/stale quote handling, aggregate cost and P/L math, duplicate ticker research reuse, partial valuation warnings, and unpriced risk alerts.
- DB connection closure, migration error visibility, and invalid/nonfinite/negative share or price validation.
- Provider observation timestamps and stale-data checks in research, Hunter, broad market, and relative-strength contexts.
- Annual SEC duration and fiscal-period matching for revenue, earnings and free cash flow.
- News source failure tolerance, duplicate publication treatment, negation ambiguity, and catalyst thesis verification status.
- Superseded asynchronous UI response guards, chart control generation, and stale coverage messaging.

## 4. Features improved

- Stonk Hunter scores cap falling knives, sharp gaps and weak stabilization; STRONG SETUP requires reasonable risk/reward and lower chase risk.
- Fast news retrieval uses Yahoo first and GDELT only with fewer than three primary items; partial feeds can render.
- Current price vs fetched-at timestamp is distinguished; Risk Monitor and Portfolio distinguish fully priced portfolios from incomplete valuations.
- Research cache returns per-request history summaries without mutating the shared cached research object.
- Deep Research and navigation reject responses that arrive for a previously selected view.

## 5. Added

- Deterministic backend and UI tests, including mocked API/SQLite/provider outages and async response ordering.
- Reproducible synthetic portfolio benchmark against the original main revision.
- Local database ignore rules and this review/audit document.
- Clear unpriced-lot and unavailable-news indicators in the UI.

## 6. Removed or restricted

- Removed misleading independently confirmed label for multi-outlet news that lacks primary-source evidence.
- Removed fabricated/current-looking P/L and exit data for missing or stale quotes.
- Restricted STRONG SETUP classification during severe gap, falling-knife, stabilization, or poor risk/reward conditions.
- No useful page or working feature intentionally removed.

## 7. Measured performance

Command: python tests/benchmark_portfolio.py

The measured run on 2026-11-21 used 96 one-share lots, 12 unique tickers, 7 trials per version, 15 ms simulated provider latency/call, and separate temporary SQLite fixtures. Baseline main 6680345: 252.0 ms median and 96 research calls per run. Review branch: 35.9 ms median and 12 calls per run. This represents 7.03x speedup in the isolated scenario and 87.5% fewer mocked provider calls. Both versions used the same fixture connection cleanup to allow Windows temporary-file removal. This is not a benchmark of real provider/network latency, full Deep Research, app startup, or browser rendering.

## 8. Testing and failures

- Python: python -m unittest discover -s tests -v — 20 passed.
- Node: node --test tests/test_ui.js — 9 passed.
- Python AST parse of StonkResearch.pyw — passed.
- node --check app.js and git diff --check — passed.
- Synthetic benchmark assertions — passed.
- An initial benchmark execution previously failed temporary-directory cleanup because original-main SQLite connections remained open on Windows. Benchmark fixture cleanup was corrected for both compared versions and subsequent measurement passed.
- Regression tests run with temporary databases and mocked provider responses; user stonk.db was not opened or altered.
- NOT TESTED: live Yahoo/SEC/GDELT availability, free-provider rate limits, Windows browser app launch and close behavior, all visual viewport/control states, genuine multiplayer (not applicable), stock split/reinvestment edge cases at every provider, prediction calibration, strategy backtesting, real trading performance.
- Automated mock tests establish specific regression behavior, not comprehensive live UI or market-data accuracy.

## 9. Files changed

- StonkResearch.pyw — API, portfolio, provider, scoring, cache, and DB hardening.
- app.js — stale response guards and missing-data signals.
- README.md — review changes, launch, database backup and validation notes.
- .gitignore — stonk.db, WAL/SHM and Python bytecode exclusions.
- tests/test_regressions.py — Python deterministic unit/API/SQLite cases.
- tests/test_ui.js — JavaScript mocked-UI regression tests.
- tests/benchmark_portfolio.py — controlled baseline performance comparison.
- docs/audit-report.md — findings, verification, remaining risk.

No application styling rewrite or new runtime dependency was introduced.

## 10. Database compatibility and migration

Existing tables and columns are preserved. The current init path creates tables if absent and adds missing positions.thesis_json and positions.updated_at to legacy databases. The reviewed changes do not add a new schema revision or delete existing rows. Migration failures now raise a visible exception.

Before opening an existing populated database with any updated app, fully close the app, make a copy of stonk.db and any extant stonk.db-wal / stonk.db-shm files together, or make a SQLite online backup. The app uses write-ahead logging; copying only stonk.db while it is active can omit uncheckpointed changes. Never test on an irreplaceable personal database. Automated migrations were exercised only on temporary synthetic legacy data.

## 11. Remaining risks and limits

- Provider timestamps are source bars, not exchange-grade executable quotes. The five-day staleness threshold is conservative and coarse for intraday decisions.
- Yahoo/GDELT endpoints are unofficial/best effort and may fail, vary fields or be rate limited. SEC XBRL taxonomy coverage is not universal.
- SEC filing/news linkage is limited; multi-outlet agreement does not demonstrate independent fact verification. Some headline negation edge cases remain.
- Scoring/entry/exit weights remain heuristic and unbacktested. A lower risk score is not proof of a profitable entry.
- Some frontend operations remain tied to a single localhost browser client; cancellation is by response guard rather than stopping all in-flight HTTP calls.
- Full manual Windows 10/11 launch, Chrome/Edge view, all controls, layout, keyboard navigation, and real network performance need user verification before release.
- Automatic trades are not present. Optional Ollama is still entirely optional.

## 12. Next improvements, ordered

1. Perform Windows 10/11 manual app testing: launch, navigate every page, back from Deep Research, chart ranges and hover, filters, edit/delete positions on a disposable DB, settings persistence, minimize/close, and offline behavior.
2. Validate live Yahoo/SEC/GDELT timestamps, 429/timeouts, sample financial facts, reverse splits and adjusted history against primary filings and observed quotes.
3. Add source-level freshness/error metrics and bounded background request coalescing only after measured live latency bottlenecks are identified.
4. Backtest/forward-test signal calibration against held-out market periods before stating predictive usefulness.
5. Polish spacing and error states from actual screenshots and accessibility inspection; preserve existing options.

## 13. GitHub review destination

- Repository: https://github.com/3AYZE/SmartStockAZY
- Base: main (6680345 at audit start)
- Branch: codex/stock-research-audit-v050
- Draft PR: https://github.com/3AYZE/SmartStockAZY/pull/2
- Merge/deployment/release: prohibited without user approval.
