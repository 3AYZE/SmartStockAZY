# Stonk Research Desktop v0.4.0 — Decision Quality + Chart Intelligence

A lightweight, $0-first local stock research terminal for Windows.

## v0.4 highlights

### Decision quality

- Separates **Company Quality** from **Current Entry Quality**.
- A strong/rising company can still be marked **WAIT / PULLBACK** or **POOR / AVOID CHASE**.
- Adds **Why NOT buy now**.
- Adds explicit conditions that would improve the decision.
- Adds explicit thesis-break / downgrade conditions.
- Broad-market regime can tighten or loosen entry requirements.
- Relative strength compares the stock with a sector ETF when mapped, otherwise the S&P 500.

### News intelligence

- Classifies headlines into event types such as earnings, guidance, regulatory, dilution, management, legal, cybersecurity, FDA/clinical, M&A, product/contract, analyst, and macro.
- Groups similar headlines into one event so syndicated copies do not count as independent confirmation.
- Shows confirmation as **Primary-source confirmed**, **Multiple sources**, **Single reliable source**, or **Unverified / low diversity**.
- Event confirmation affects risk weighting.

### Thesis health + position protection

When adding a portfolio position, you can select the reasons behind the purchase:

- Revenue growth
- Earnings growth
- Positive free cash flow
- Healthy uptrend
- Attractive entry
- Controlled risk
- Strong momentum
- Positive catalyst/news

The Risk Monitor then tracks which conditions remain valid and calculates a **Thesis Health** score.

Position monitoring now also considers your actual average cost and can show:

- Hold / monitor
- Hold + protect profit
- Tighten risk / review
- Take partial profit / trail
- Risk exit review
- Exit review
- Position-specific trailing-exit reference
- Protected gain above cost when applicable

The app never automatically trades.

### Chart intelligence

The Price History chart supports:

- Hover price + exact date/time
- 1W / 1M / 6M / 1Y / 2Y / 5Y ranges
- Volume bars
- Current SMA20 / SMA50 / SMA200 reference levels
- Support
- Resistance
- Preferred Entry Zone
- Risk Exit
- Take Profit

Chart range changes only fetch chart data and do not rerun Deep Research.

### Research history

Deep Research stores decision snapshots locally and shows how Opportunity, Entry, Risk, status, and price changed over time. Snapshots are deduplicated so identical research does not spam the history.

### Performance / safety

- Zero third-party Python dependencies.
- No Node.js / React / FastAPI / pandas / NumPy.
- Hidden local backend; no CMD window.
- Deep Research remains staged.
- SEC, news, market-regime, and benchmark evidence run in parallel.
- Stale Deep Research results are prevented from overwriting a newer ticker selection.
- Ollama remains optional and on-demand.

## Requirements

- Windows 10/11
- Python 3.11+
- Microsoft Edge or Google Chrome recommended
- Ollama optional

## Start

Double-click:

`StonkResearch.pyw`

## Important

This is a research tool, not a broker or financial adviser. Free market/news sources can be delayed, incomplete, rate-limited, or unavailable. Entry, trailing-exit, and take-profit levels are model-generated research references, not guarantees. Automatic buying/selling is never enabled.
