"""Reproducible synthetic portfolio comparison against local main; no network or real DB."""

import importlib.machinery
import importlib.util
import sqlite3
import statistics
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from contextlib import contextmanager
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "StonkResearch.pyw"
LOTS = 96
UNIQUE_TICKERS = 12
PROVIDER_DELAY_SECONDS = 0.015
TRIALS = 7


def load(name, source):
    loader = importlib.machinery.SourceFileLoader(name, str(source))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def fake_research(ticker):
    return {
        "ticker": ticker, "quote": {"price": 120.0},
        "indicators": {"atr14": 3, "sma20": 115, "trend_score_raw": 1},
        "scores": {"risk": 20, "entry": 70, "momentum": 55},
        "news_risk": {"score": 0, "reasons": []},
        "price_model": {"risk_exit": 104, "take_profit_zone": [135, 150], "overextension_risk": 10},
        "earnings": {}, "exit_risk": {"score": 20},
    }


def benchmark(module, db_path):
    times, calls = [], []
    # The original implementation leaves SQLite connections open on Windows.
    # Give both versions identical explicit fixture cleanup for a repeatable benchmark.
    @contextmanager
    def isolated_connection():
        con = sqlite3.connect(db_path, timeout=5)
        con.row_factory = sqlite3.Row
        try:
            with con:
                yield con
        finally:
            con.close()

    with patch.object(module, "DB_PATH", db_path), patch.object(module, "connect", isolated_connection):
        module.init_db()
        with module.connect() as con:
            con.executemany(
                "INSERT INTO positions(ticker,shares,avg_price,thesis,thesis_json,created_at) "
                "VALUES(?,?,?,?,?,?)",
                [(f"SYM{i % UNIQUE_TICKERS:02d}", 1, 100, "", "[]", module.now_iso()) for i in range(LOTS)],
            )
            con.commit()

        for _ in range(TRIALS):
            lock = threading.Lock()
            counter = [0]

            def provider(ticker, use_ai):
                with lock:
                    counter[0] += 1
                time.sleep(PROVIDER_DELAY_SECONDS)
                return fake_research(ticker)

            with patch.object(module, "research_package", side_effect=provider):
                start = time.perf_counter()
                result = module.portfolio_risk()
                elapsed = (time.perf_counter() - start) * 1000
            assert len(result["positions"]) == LOTS, f"Incomplete results: {module.__name__}"
            assert result["total_value"] == LOTS * 120, f"Incorrect valuation: {module.__name__}"
            times.append(elapsed)
            calls.append(counter[0])
    return statistics.median(times), set(calls)


def main():
    ref = subprocess.check_output(["git", "rev-parse", "main"], cwd=ROOT, text=True).strip()
    original = subprocess.check_output(["git", "show", "main:StonkResearch.pyw"], cwd=ROOT)
    with tempfile.TemporaryDirectory(prefix="smartstock-bench-") as location:
        temp = Path(location)
        original_path = temp / "baseline.pyw"
        original_path.write_bytes(original)
        baseline = load("bench_baseline", original_path)
        updated = load("bench_updated", SOURCE)
        old_ms, old_calls = benchmark(baseline, temp / "old.db")
        new_ms, new_calls = benchmark(updated, temp / "new.db")
    assert old_calls == {LOTS}, f"Expected baseline per-lot requests, got {old_calls}"
    assert new_calls == {UNIQUE_TICKERS}, f"Expected updated per-ticker requests, got {new_calls}"
    print(f"Baseline main {ref[:8]}: {old_ms:.1f} ms median; {LOTS} research calls/run")
    print(f"Updated working tree: {new_ms:.1f} ms median; {UNIQUE_TICKERS} research calls/run")
    print(f"Measured speedup: {old_ms / new_ms:.2f}x; research call reduction: {100 * (1-UNIQUE_TICKERS/LOTS):.1f}%")
    print(f"Fixture: {LOTS} one-share lots, {UNIQUE_TICKERS} symbols, {TRIALS} trials, "
          f"{PROVIDER_DELAY_SECONDS * 1000:.0f} ms mocked provider latency, separate temporary databases")
    print("Scope: synthetic isolated provider latency only; not real network, startup, or Windows UI performance.")


if __name__ == "__main__":
    main()
