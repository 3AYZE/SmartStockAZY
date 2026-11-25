"""Deterministic regression tests. No network or personal database access."""

import http.client
import importlib.machinery
import importlib.util
import json
import math
import sqlite3
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from http.server import ThreadingHTTPServer


SOURCE = Path(__file__).resolve().parents[1] / "StonkResearch.pyw"
loader = importlib.machinery.SourceFileLoader("smartstock_test", str(SOURCE))
spec = importlib.util.spec_from_loader(loader.name, loader)
app = importlib.util.module_from_spec(spec)
loader.exec_module(app)


def fake_research(ticker, price=120.0):
    return {
        "ticker": ticker, "quote": {"price": price},
        "indicators": {"atr14": 3, "sma20": 115, "trend_score_raw": 1},
        "scores": {"risk": 20, "entry": 60, "momentum": 55},
        "news_risk": {"score": 0, "reasons": []},
        "price_model": {"risk_exit": 104, "take_profit_zone": [135, 150], "overextension_risk": 10},
        "earnings": {}, "exit_risk": {"score": 999},
    }


class DbFixture:
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = patch.object(app, "DB_PATH", Path(self.temp.name) / "test.db")
        self.db.start()
        with app.CACHE_LOCK:
            app.CACHE.clear()
        app.init_db()

    def tearDown(self):
        self.db.stop()
        self.temp.cleanup()

    def insert(self, ticker, shares, avg_price, tags="[]"):
        with app.connect() as con:
            con.execute("INSERT INTO positions(ticker,shares,avg_price,thesis,thesis_json,created_at) VALUES(?,?,?,?,?,?)",
                        (ticker, shares, avg_price, "", tags, app.now_iso()))
            con.commit()

    def test_empty_portfolio(self):
        risk = app.portfolio_risk()
        self.assertTrue(risk["valuation_complete"])
        self.assertEqual(risk["total_pnl"], 0)
        self.assertEqual(risk["grouped"], [])

    def test_duplicate_tickers_use_one_research_and_weighted_cost(self):
        self.insert("AAPL", 2, 100)
        self.insert("AAPL", 3, 110)
        self.insert("MSFT", 1, 200)
        calls = []
        source = fake_research("AAPL")

        def load(ticker, use_ai):
            calls.append(ticker)
            return source if ticker == "AAPL" else fake_research("MSFT", 250)

        with patch.object(app, "research_package", side_effect=load):
            risk = app.portfolio_risk()
        self.assertCountEqual(calls, ["AAPL", "MSFT"])
        self.assertAlmostEqual(risk["total_cost"], 730)
        self.assertAlmostEqual(risk["total_value"], 850)
        self.assertAlmostEqual(risk["total_pnl"], 120)
        group = next(x for x in risk["grouped"] if x["ticker"] == "AAPL")
        self.assertAlmostEqual(group["avg_cost"], 106)
        self.assertAlmostEqual(group["value"], 600)
        self.assertEqual(source["exit_risk"]["score"], 999)  # cached research must be untouched

    def test_missing_quote_does_not_create_false_losses(self):
        self.insert("AAPL", 2, 100)
        self.insert("AAPL", 3, 110)
        self.insert("MSFT", 1, 200)

        def load(ticker, unused):
            if ticker == "MSFT":
                raise RuntimeError("provider timeout")
            return fake_research(ticker)

        with patch.object(app, "research_package", side_effect=load):
            risk = app.portfolio_risk()
        self.assertFalse(risk["valuation_complete"])
        self.assertEqual(risk["unpriced_lots"], 1)
        self.assertIsNone(risk["total_value"])
        self.assertIsNone(risk["total_pnl"])
        self.assertIsNone(risk["total_pnl_percent"])
        self.assertEqual(risk["priced_market_value"], 600)
        self.assertEqual(risk["priced_cost"], 530)
        self.assertEqual(risk["sector_exposure"], [])
        self.assertEqual(risk["warnings"], [])
        self.assertIsNone(next(x for x in risk["grouped"] if x["ticker"] == "MSFT")["value"])
        self.assertTrue(any("provider timeout" in x.get("error", "") for x in risk["positions"]))

    def test_nonfinite_or_missing_price_is_unpriced(self):
        self.insert("AAPL", 2, 100)
        for value in (None, float("nan"), float("inf"), 0):
            with self.subTest(price=value), patch.object(app, "research_package", return_value=fake_research("AAPL", value)):
                self.assertEqual(app.portfolio_risk()["unpriced_lots"], 1)

    def test_stale_quote_disables_valuation_and_generates_alert(self):
        self.insert("AAPL", 2, 100)
        old = fake_research("AAPL", 150)
        old["quote"]["stale"] = True
        with patch.object(app, "research_package", return_value=old):
            risk = app.portfolio_risk()
            alerts = app.alerts_payload()
        self.assertFalse(risk["valuation_complete"])
        self.assertEqual(risk["unpriced_lots"], 1)
        self.assertIsNone(risk["total_value"])
        self.assertNotIn("position_strategy", risk["positions"][0])
        self.assertIn("stale", risk["positions"][0]["error"])
        self.assertEqual(alerts["alerts"][0]["severity"], "ERROR")

    def test_settings_and_research_cache(self):
        app.set_setting("ollama_enabled", "true")
        self.assertEqual(app.get_setting("ollama_enabled"), "true")
        cached = {"ticker": "AAPL", "research_history": ["original"]}
        app.cache_put(("research_core_v05", "AAPL"), cached)
        with patch.object(app, "research_history", return_value=[]):
            result = app.research_package("AAPL")
        self.assertEqual(cached["research_history"], ["original"])
        self.assertEqual(result["research_history"], [])

    def test_legacy_schema_migration_keeps_existing_row(self):
        with app.connect() as con:
            con.execute("DROP TABLE positions")
            con.execute("CREATE TABLE positions(id INTEGER PRIMARY KEY, ticker TEXT, shares REAL, avg_price REAL, thesis TEXT, created_at TEXT)")
            con.execute("INSERT INTO positions VALUES(1, 'AAPL', 2, 101, 'Keep', '2025-01-01')")
            con.commit()
        app.init_db()
        row = app.list_positions()[0]
        self.assertEqual(row["thesis"], "Keep")
        self.assertEqual(row["thesis_json"], "[]")
        self.assertIn("updated_at", row)


class DbTest(DbFixture, unittest.TestCase):
    pass


class ApiTest(DbFixture, unittest.TestCase):
    # The fixture provides shared setup; these cases run only in DbTest.
    test_empty_portfolio = None
    test_duplicate_tickers_use_one_research_and_weighted_cost = None
    test_missing_quote_does_not_create_false_losses = None
    test_nonfinite_or_missing_price_is_unpriced = None
    test_settings_and_research_cache = None
    test_legacy_schema_migration_keeps_existing_row = None
    def setUp(self):
        super().setUp()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        super().tearDown()

    def request(self, method, url, payload=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=5)
        try:
            raw = json.dumps(payload).encode() if payload is not None else None
            connection.request(method, url, body=raw, headers={"Content-Type": "application/json"})
            response = connection.getresponse()
            return response.status, json.loads(response.read().decode())
        finally:
            connection.close()

    def test_crud_and_invalid_numeric_inputs(self):
        original = {"ticker": "AAPL", "shares": 2, "avg_price": 100, "thesis_tags": ["uptrend"]}
        for invalid in (float("nan"), float("inf"), -1, 0, None, "not a number"):
            with self.subTest(invalid=invalid):
                status, result = self.request("POST", "/api/positions", {**original, "shares": invalid})
                self.assertEqual(status, 400)
                self.assertIn("error", result)
        self.assertEqual(app.list_positions(), [])
        app.cache_put(("research_core_v05", "AAPL"), {"test": 1})
        status, created = self.request("POST", "/api/positions", original)
        self.assertEqual(status, 201)
        self.assertNotIn(("research_core_v05", "AAPL"), app.CACHE)
        self.assertEqual(created["ticker"], "AAPL")
        self.assertEqual(created["thesis_json"], '["uptrend"]')
        pid = created["id"]
        status, updated = self.request("PUT", f"/api/positions/{pid}", {**original, "ticker": "MSFT", "shares": 5})
        self.assertEqual(status, 200)
        self.assertEqual(updated["ticker"], "MSFT")
        self.assertEqual(updated["shares"], 5)
        status, positions = self.request("GET", "/api/positions")
        self.assertEqual(status, 200)
        self.assertEqual(len(positions["positions"]), 1)
        status, removed = self.request("DELETE", f"/api/positions/{pid}")
        self.assertEqual((status, removed), (200, {"ok": True}))
        self.assertEqual(app.list_positions(), [])

    def test_risk_api_reports_missing_quotes(self):
        self.insert("AAPL", 1, 100)
        with patch.object(app, "research_package", side_effect=RuntimeError("offline")):
            status, result = self.request("GET", "/api/risk")
        self.assertEqual(status, 200)
        self.assertFalse(result["valuation_complete"])
        self.assertIsNone(result["total_pnl"])


class DataTest(unittest.TestCase):
    def setUp(self):
        with app.CACHE_LOCK:
            app.CACHE.clear()

    def test_dashboard_keeps_quotes_if_news_provider_fails(self):
        def quote(ticker, name):
            return {"ticker": ticker, "name": name, "price": 100, "change_percent": 1}

        with patch.object(app, "quick_quote", side_effect=quote), \
             patch.object(app, "fast_news", side_effect=RuntimeError("news provider offline")), \
             patch.object(app, "market_regime", return_value={"label": "UNKNOWN"}):
            dashboard = app.market_dashboard()

        self.assertEqual(len(dashboard["indexes"]), len(app.INDEXES))
        self.assertEqual(dashboard["news"], [])
        self.assertTrue(any(e["ticker"] == "NEWS" for e in dashboard["errors"]))

    def test_annual_facts_reject_quarters_and_align_periods(self):
        def fact(start, end, val, filed, form="10-K"):
            return {"start": start, "end": end, "val": val, "filed": filed, "form": form, "fp": "FY"}
        data = {"facts": {"us-gaap": {
            "Revenues": {"units": {"USD": [
                fact("2023-01-01", "2023-12-31", 100, "2024-02-01"),
                fact("2024-01-01", "2024-12-31", 120, "2025-02-01"),
                fact("2024-10-01", "2024-12-31", 45, "2025-03-01"),
                fact("2024-01-01", "2024-12-31", 125, "2025-04-01"),
            ]}},
            "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": [fact("2024-01-01", "2024-12-31", 50, "2025-03-01")]}},
            "PaymentsToAcquirePropertyPlantAndEquipment": {"units": {"USD": [fact("2023-01-01", "2023-12-31", 8, "2024-02-01")]}},
        }}}
        result = app._annual_pair(data, ["Revenues"])
        self.assertEqual([r["v"] for r in result], [125, 100])
        self.assertEqual([r["end"] for r in result], ["2024-12-31", "2023-12-31"])

        with tempfile.TemporaryDirectory() as path, patch.object(app, "DB_PATH", Path(path) / "test.db"):
            app.init_db()
            with patch.object(app, "sec_identity", return_value={"name": "Example", "cik": "0000000001"}), patch.object(app, "http_json", return_value=data):
                financials = app.sec_fundamentals("AAPL")
        self.assertIsNone(financials["free_cashflow_est"])
        self.assertAlmostEqual(financials["revenue_growth_pct"], 25)

    def test_ambiguity_and_syndication_never_confirm_news(self):
        base = {"publisher": "Reuters", "domain": "reuters.com", "source": "yahoo-news"}
        self.assertEqual(app.classify_news_item({**base, "title": "Set by default in the app"})["risk_points"], 0)
        self.assertEqual(app.classify_news_item({**base, "title": "Company denies fraud"})["risk_points"], 0)
        self.assertGreater(app.classify_news_item({**base, "title": "Company reports fraud"})["risk_points"], 0)
        items = [
            {**base, "title": "Example company reports fraud in audit"},
            {**base, "domain": "other.com", "publisher": "Other", "title": "Example company reports fraud in audit"},
        ]
        clustered = app.news_score(items)
        self.assertEqual(clustered["event_count"], 1)
        self.assertEqual(clustered["confirmed_event_count"], 0)
        self.assertIn("UNVERIFIED", clustered["events"][0]["confirmation"])
        self.assertEqual(clustered["events"][0]["outlet_count"], 2)
        self.assertNotIn("independent_sources", clustered["events"][0])
        self.assertEqual(app.news_score([{**base, "source": "sec", "title": "Example fraud reported"}])["confirmed_event_count"], 1)

    def test_hunter_rejects_knife_gap_and_stale_candidates(self):
        template = {
            "quote": {"name": "Mock", "price": 100, "change_percent": 1, "stale": False},
            "scores": {"quality": 96, "momentum": 90, "entry": 88, "risk": 15, "confidence": 60},
            "indicators": {"falling_knife_risk": 10, "stabilization_score": 80,
                           "gap_risk": 10, "trend_score_raw": 2},
            "price_model": {"overextension_risk": 10, "risk_reward": 2.5},
        }
        cases = [
            ({}, "STRONG SETUP", None),
            ({"price_model": {"overextension_risk": 75}}, None, 58),
            ({"indicators": {"falling_knife_risk": 75}}, "HIGH RISK", 50),
            ({"indicators": {"gap_risk": 50}}, None, 55),
            ({"indicators": {"trend_score_raw": -2, "stabilization_score": 5}}, None, 55),
            ({"quote": {"stale": True}}, "UNAVAILABLE", None),
        ]
        for overrides, expected, max_opportunity in cases:
            with self.subTest(overrides=overrides):
                stock = {k: dict(v) for k, v in template.items()}
                for k, values in overrides.items():
                    stock[k].update(values)
                with patch.object(app, "basic_stock", return_value=stock), \
                     patch.object(app, "market_regime", return_value={"entry_adjust": 0, "risk_adjust": 0}), \
                     patch.object(app, "get_setting", return_value="36"), \
                     patch.object(app, "sec_fundamentals", return_value={}), \
                     patch.object(app, "sec_filings", return_value=[]), \
                     patch.object(app, "fast_news", return_value=[]):
                    data = app.hunter_scan(["TST"], 1)
                if expected == "UNAVAILABLE":
                    self.assertEqual(data["successful"], 0)
                    self.assertIn("stale", data["errors"][0]["error"])
                    continue
                row = data["results"][0]
                if expected is not None:
                    self.assertEqual(row["status"], expected)
                else:
                    self.assertNotEqual(row["status"], "STRONG SETUP")
                if max_opportunity is not None:
                    self.assertLessEqual(row["scores"]["opportunity"], max_opportunity)

    def test_display_chart_uses_last_observation_timestamp(self):
        stamps = [1690000000 + i * 86400 for i in range(5)]
        mock = {"chart": {"result": [{"timestamp": stamps,
            "indicators": {"quote": [{"close": [100, 101, 102, 103, 104]}]}}]}}
        with patch.object(app, "http_json", return_value=mock):
            chart = app.yahoo_chart_display("AAPL", "1mo")
        expected = datetime.fromtimestamp(stamps[-1], timezone.utc).isoformat()
        self.assertEqual(chart["updated_at"], expected)
        self.assertNotEqual(chart["retrieved_at"], expected)

    def test_fast_news_avoids_fallback_when_primary_has_three(self):
        with patch.object(app, "yahoo_news_search", return_value=[{"title": str(n)} for n in range(3)]), patch.object(app, "gdelt_news") as gdelt:
            result = app.fast_news("Example")
        self.assertEqual(len(result), 3)
        gdelt.assert_not_called()

    def test_news_provider_outages_preserve_available_source(self):
        with patch.object(app, "yahoo_news_search", side_effect=TimeoutError("Yahoo down")), \
             patch.object(app, "gdelt_news", return_value=[{"title": "Alternate feed"}]):
            self.assertEqual(app.fast_news("Example")[0]["title"], "Alternate feed")
        with patch.object(app, "yahoo_news_search", return_value=[{"title": "Primary headline"}]), \
             patch.object(app, "gdelt_news", side_effect=TimeoutError("GDELT down")):
            self.assertEqual(app.fast_news("Example")[0]["title"], "Primary headline")
        with patch.object(app, "yahoo_news_search", side_effect=TimeoutError("Yahoo down")), \
             patch.object(app, "gdelt_news", side_effect=TimeoutError("GDELT down")):
            with self.assertRaisesRegex(RuntimeError, "All free news providers"):
                app.fast_news("Example")

    def test_unverified_headline_does_not_validate_catalyst_thesis(self):
        item = {"type": "CATALYST", "sentiment": "BULLISH", "impact": "HIGH", "confirmation": "REPORTED / UNVERIFIED"}
        report = app.evaluate_thesis(["catalyst"], {"news_risk": {"available": True, "events": [item]}})
        self.assertIsNone(report["items"][0]["valid"])
        self.assertIn("unavailable", report["items"][0]["detail"])
        item["confirmation"] = "PRIMARY-SOURCE CONFIRMED"
        confirmed = app.evaluate_thesis(["catalyst"], {"news_risk": {"available": True, "events": [item]}})
        self.assertTrue(confirmed["items"][0]["valid"])
        missing = app.evaluate_thesis(["catalyst"], {"news_risk": {"available": False, "events": []}})
        self.assertIsNone(missing["items"][0]["valid"])

    def test_chart_time_is_source_observation_not_fetch_time(self):
        first = 1680000000
        times = [first + i * 86400 for i in range(260)]
        result = {"chart": {"result": [{"timestamp": times,
            "indicators": {"quote": [{"close": [100 + i * 0.1 for i in range(260)]}]},
            "meta": {"shortName": "Mock"}}]}}
        with patch.object(app, "http_json", return_value=result):
            stock = app.basic_stock("AAPL")
        expected = datetime.fromtimestamp(times[-1], timezone.utc).isoformat()
        self.assertEqual(stock["quote"]["updated_at"], expected)
        self.assertTrue(stock["quote"]["stale"])
        self.assertEqual(stock["history"][-1]["time"], expected)
        self.assertNotEqual(stock["quote"]["retrieved_at"], expected)

    def test_chart_ranges_and_invalid_inputs(self):
        self.assertEqual(app.normalize_chart_range("1w"), "5d")
        self.assertEqual(app.chart_interval("1w"), "60m")
        self.assertEqual(app.normalize_chart_range("10y"), "10y")
        for number in (None, 0, -1, float("nan"), float("inf"), "xyz"):
            with self.subTest(number=number), self.assertRaises(ValueError):
                app.positive_number(number, "Shares")


class SystemPolishTests(unittest.TestCase):
    def test_flat_price_rsi_is_neutral(self):
        rows = [{"close": 100.0, "open": 100.0, "high": 100.0,
                 "low": 100.0, "volume": 1000.0} for _ in range(30)]
        self.assertEqual(app.indicators(rows)["rsi14"], 50)

    def test_memory_cache_has_a_hard_entry_limit(self):
        with patch.object(app, "CACHE", {}), patch.object(app, "CACHE_MAX_ENTRIES", 5):
            for i in range(12):
                app.cache_put(("example", i), i)
            self.assertEqual(len(app.CACHE), 5)
            self.assertEqual(app.cache_get(("example", 11), 60), 11)
            self.assertIsNone(app.cache_get(("example", 0), 60))
            app.cache_put(("example", 11), "updated")
            self.assertEqual(len(app.CACHE), 5)

    def test_scanner_returns_all_successful_rows_by_default(self):
        stock = {
            "quote": {"name": "Mock", "price": 100, "change_percent": 1, "stale": False},
            "scores": {"quality": 96, "momentum": 90, "entry": 88, "risk": 15, "confidence": 60},
            "indicators": {"falling_knife_risk": 10, "stabilization_score": 80,
                           "gap_risk": 10, "trend_score_raw": 2},
            "price_model": {"overextension_risk": 10, "risk_reward": 2.5},
        }
        symbols = ["T" + str(i) for i in range(40)] + [" t0 ", "t1", "INVALID!"]
        with patch.object(app, "get_setting", return_value="100"), \
             patch.object(app, "market_regime", return_value={"entry_adjust": 0, "risk_adjust": 0}), \
             patch.object(app, "basic_stock", return_value=stock), \
             patch.object(app.threading.Thread, "start"):
            result = app.hunter_scan(symbols)
            limited = app.hunter_scan(symbols, 10)
        self.assertEqual(result["scanned"], 41)
        self.assertEqual(result["successful"], 40)
        self.assertEqual(len(result["results"]), 40)
        self.assertEqual(len(result["errors"]), 1)
        self.assertEqual(len(limited["results"]), 10)
        self.assertEqual(len({x["ticker"] for x in result["results"]}), 40)

    def test_market_refresh_discards_only_relevant_cached_data(self):
        calls = []
        def fake_quote(symbol, name):
            calls.append(symbol)
            return {"ticker": symbol, "name": name, "price": 100, "change_percent": 0}

        with patch.object(app, "CACHE", {}), \
             patch.object(app, "quick_quote", side_effect=fake_quote), \
             patch.object(app, "market_regime", return_value={"label": "NEUTRAL"}), \
             patch.object(app, "fast_news", return_value=[]):
            app.cache_put(("chart", "^GSPC", "6mo"), "old benchmark")
            app.cache_put(("chart", "AAPL", "1y"), "unrelated stock")
            app.market_dashboard()
            count = len(calls)
            app.market_dashboard()
            self.assertEqual(len(calls), count)
            app.market_dashboard(force=True)
            self.assertEqual(len(calls), count * 2)
            self.assertIsNone(app.cache_get(("chart", "^GSPC", "6mo"), 60))
            self.assertEqual(app.cache_get(("chart", "AAPL", "1y"), 60), "unrelated stock")

    def test_quick_quote_exposes_provider_observation_time(self):
        quote = {"stale": False, "price": 100, "change_percent": 1,
                 "updated_at": "2026-11-23T14:00:00+00:00",
                 "retrieved_at": "2026-11-24T14:00:00+00:00"}
        with patch.object(app, "basic_stock", return_value={"quote": quote, "indicators": {}}):
            row = app.quick_quote("^GSPC", "S&P 500")
        self.assertEqual(row["observed_at"], quote["updated_at"])
        self.assertEqual(row["retrieved_at"], quote["retrieved_at"])


if __name__ == "__main__":
    unittest.main()
