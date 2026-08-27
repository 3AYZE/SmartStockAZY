# SmartStockAZY v0.5.0 — Reliability + Portfolio Polish

A lightweight, $0-first local stock research terminal for Windows. The core engine is deterministic; Ollama remains optional.

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
