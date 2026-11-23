# Changelog

Notable product changes to SmartStockAZY. The repository's [Releases](https://github.com/3AYZE/SmartStockAZY/releases) page is the source of downloadable Windows EXE versions.

## v0.6.1 — Windows EXE release (November 23, 2026)

**First published standalone Windows EXE.**

- Bundles the local Python engine and modern stock-terminal interface in one Windows executable.
- Introduces GitHub Release-based update checks, verified EXE downloads, and approval before restart/install.
- Preserves local SQLite portfolio data separately from the replaceable executable, with a portable-data migration path.
- Adds a Windows GitHub Actions packaging pipeline, startup smoke test, EXE checksum, and a Windows application icon.
- Includes the redesigned **Market, Discover, Research and Portfolio** workspaces with Settings accessible from the sidebar.

[Download release v0.6.1](https://github.com/3AYZE/SmartStockAZY/releases/tag/v0.6.1)

## Previous source-development milestones

The following changes were merged into the repository before the first EXE release; they are not presented as separate downloadable EXE releases.

### v0.5.1 — Opt-in source updates and interface refresh

- Adds an optional GitHub updater for the Python source distribution.
- Provides manual update approval, staged source verification, local backups and rollback handling.
- Consolidates previously separate News, Risk Monitor and Alerts views into more focused navigation.

### v0.5.0 — Research and portfolio reliability

- Improves missing/stale market-price handling and distinction between source observation and retrieval time.
- Strengthens gap/chase and falling-knife safeguards in stock screening and entry analysis.
- Improves SEC annual-period matching and news source-confirmation labels.
- Fixes multi-lot portfolio cost basis and missing-quote profit/loss handling.
- Adds regression tests and a reproducible synthetic portfolio benchmark.

For implementation details and remaining verification boundaries, see [the reliability audit](docs/audit-report.md) and [UI redesign report](docs/ui-redesign-report.md).

---

**Note:** SmartStockAZY is a research application. Free data feeds may be delayed or unavailable, and model-generated buy zones or risk scores are not investment guarantees.
