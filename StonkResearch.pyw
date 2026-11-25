from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import statistics
import subprocess
import sys
import threading
import time
import webbrowser
import update_support
# Older portable installations may not yet have the EXE-only updater module.
if getattr(sys, "frozen", False):
    import exe_updater
else:
    exe_updater = None
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse, unquote, parse_qs
from urllib.request import Request, urlopen

VERSION = "0.6.0-windows-exe"
HOST, PORT = "127.0.0.1", 8765
IS_FROZEN = bool(getattr(sys, "frozen", False))
ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
BUILD_INFO = exe_updater.installed_build(ROOT) if IS_FROZEN else {}
DB_PATH = (exe_updater.user_data_dir() / "stonk.db") if IS_FROZEN else (ROOT / "stonk.db")
UPDATE_MANAGER = (
    exe_updater.ExeUpdateManager(ROOT) if IS_FROZEN
    else update_support.UpdateManager(ROOT)
)
UPDATE_EXIT = threading.Event()
CACHE: dict = {}
CACHE_MAX_ENTRIES = 1200
CACHE_LOCK = threading.Lock()
DB_LOCK = threading.Lock()
LAST_HEARTBEAT = time.time()
HEARTBEAT_LOCK = threading.Lock()
SEC_TICKERS_LOCK = threading.Lock()

DEFAULT_UNIVERSE = [
    "AAPL","MSFT","NVDA","AMZN","GOOGL","META","TSLA","AVGO","AMD","NFLX",
    "JPM","BAC","GS","V","MA","WMT","COST","HD","MCD","LLY","UNH","JNJ",
    "ABBV","MRK","XOM","CVX","CAT","GE","RTX","PLTR","CRM","ORCL","ADBE",
    "INTC","QCOM","MU","PANW","CRWD","NOW","SHOP","RBLX","COIN","HOOD","SOFI",
    "TSM","ASML","LRCX","AMAT","CSCO","BA","UBER","DIS","NKE","SBUX","F","GM",
]
INDEXES = [("^GSPC", "S&P 500"), ("^IXIC", "NASDAQ"), ("^DJI", "Dow Jones"), ("^VIX", "VIX")]
SECTORS = [
    ("XLK","Technology"),("XLC","Communication"),("XLY","Consumer Disc."),("XLP","Consumer Staples"),
    ("XLF","Financials"),("XLV","Health Care"),("XLI","Industrials"),("XLE","Energy"),
    ("XLU","Utilities"),("XLB","Materials"),("XLRE","Real Estate"),
]
SECTOR_BENCHMARKS = {
    **{x:"XLK" for x in "AAPL MSFT NVDA AVGO AMD ORCL ADBE INTC QCOM MU PANW CRWD NOW PLTR ASML LRCX AMAT CSCO TSM".split()},
    **{x:"XLC" for x in "GOOGL META NFLX DIS".split()},
    **{x:"XLY" for x in "AMZN TSLA HD MCD NKE SBUX UBER RBLX GM F".split()},
    **{x:"XLF" for x in "JPM BAC GS V MA COIN HOOD SOFI".split()},
    **{x:"XLV" for x in "LLY UNH JNJ ABBV MRK".split()},
    **{x:"XLE" for x in "XOM CVX".split()},
    **{x:"XLI" for x in "CAT GE RTX BA".split()},
    **{x:"XLP" for x in "WMT COST".split()},
}
THESIS_TAGS = {
    "revenue_growth":"Revenue growth", "earnings_growth":"Earnings growth",
    "positive_fcf":"Positive free cash flow", "uptrend":"Healthy uptrend",
    "attractive_entry":"Attractive entry", "low_risk":"Controlled risk",
    "momentum":"Strong momentum", "catalyst":"Positive catalyst/news",
}
NEWS_EVENT_RULES = [
    ("BANKRUPTCY / LIQUIDITY", ("bankruptcy","chapter 11","going concern","default","liquidity warning")),
    ("ACCOUNTING / AUDIT", ("fraud","accounting","restatement","auditor","material weakness")),
    ("GUIDANCE", ("guidance","forecast","outlook")),
    ("EARNINGS", ("earnings","revenue","eps","quarter","results")),
    ("REGULATORY / SEC", ("sec ","regulator","investigation","probe","antitrust","ftc","doj")),
    ("FINANCING / DILUTION", ("offering","dilution","convertible","share sale","secondary")),
    ("MANAGEMENT", ("ceo","cfo","executive","resign","appointed")),
    ("LEGAL", ("lawsuit","litigation","court","settlement")),
    ("CYBERSECURITY", ("cyberattack","data breach","ransomware","hack")),
    ("FDA / CLINICAL", ("fda","clinical trial","phase 3","phase iii","drug approval")),
    ("M&A", ("acquisition","acquire","merger","takeover","buyout")),
    ("PRODUCT / CONTRACT", ("launch","product","contract","order","partnership")),
    ("ANALYST", ("upgrade","downgrade","price target","analyst")),
    ("MACRO", ("inflation","interest rate","fed ","tariff","recession","jobs report")),
]
RISK_TERMS = {
    "bankruptcy":34,"chapter 11":34,"default":28,"fraud":32,"accounting irregular":32,
    "sec investigation":28,"sec probe":27,"investigation":14,"restatement":25,"auditor resign":30,
    "guidance withdrawn":25,"cuts guidance":19,"guidance cut":19,"delisting":30,"dilution":18,
    "share offering":14,"cfo resign":20,"ceo resign":13,"recall":14,"cyberattack":14,
    "data breach":11,"lawsuit":8,"earnings miss":12,"misses estimates":10,"failed trial":25,
    "fda rejects":28,"liquidity warning":30,"going concern":30,"material weakness":22,
}
POS_TERMS = {
    "raises guidance":-12,"beats estimates":-8,"record revenue":-7,"approval":-6,"buyback":-5,
    "wins contract":-5,"raises forecast":-10,"earnings beat":-8,"new contract":-4,
}
TIER1 = {"reuters.com","apnews.com","bloomberg.com","wsj.com","ft.com","cnbc.com","marketwatch.com","barrons.com"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def history_stale(rows):
    try:
        observed = datetime.fromisoformat(rows[-1]["time"])
        if observed.tzinfo is None:
            return True
        age_seconds = (datetime.now(timezone.utc) - observed).total_seconds()
        return age_seconds > 5 * 86400 or age_seconds < -3600
    except (IndexError, KeyError, TypeError, ValueError):
        return True


def clamp(v, lo=0.0, hi=100.0):
    return max(lo, min(hi, v))


def clean_ticker(t):
    t = (t or "").strip().upper()
    if not t or len(t) > 16 or not re.fullmatch(r"[A-Z0-9.\-^=]+", t):
        raise ValueError("Invalid ticker")
    return t


def fnum(v):
    try:
        if v is None:
            return None
        x = float(v)
        return None if math.isnan(x) or math.isinf(x) else x
    except Exception:
        return None


def positive_number(value, label):
    number = fnum(value)
    if number is None or number <= 0:
        raise ValueError(f"{label} must be a finite positive number")
    return number

def normalize_chart_range(range_):
    value = str(range_ or "1y").strip().lower()
    mapping = {
        "1w": "5d", "5d": "5d", "1wk": "5d", "week": "5d",
        "1m": "1mo", "1mo": "1mo", "month": "1mo",
        "3m": "3mo", "3mo": "3mo",
        "6m": "6mo", "6mo": "6mo",
        "1y": "1y", "12m": "1y", "year": "1y",
        "2y": "2y", "24m": "2y",
        "5y": "5y",
        "10y": "10y", "max": "10y",
    }
    return mapping.get(value, "1y")


def chart_interval(range_):
    norm = normalize_chart_range(range_)
    return {"5d": "60m", "1mo": "1d", "3mo": "1d", "6mo": "1d", "1y": "1d", "2y": "1wk", "5y": "1mo", "10y": "1mo"}.get(norm, "1d")


def cache_get(key, ttl):
    with CACHE_LOCK:
        row = CACHE.get(key)
    return row[1] if row and time.time() - row[0] < ttl else None


def cache_put(key, value):
    with CACHE_LOCK:
        if len(CACHE) >= CACHE_MAX_ENTRIES and key not in CACHE:
            cutoff = time.time() - 3600
            for k, v in list(CACHE.items()):
                if v[0] < cutoff:
                    CACHE.pop(k, None)
            # Expired entries alone are insufficient during large, recent scans.
            while len(CACHE) >= CACHE_MAX_ENTRIES:
                oldest = min(CACHE, key=lambda k: CACHE[k][0])
                CACHE.pop(oldest)
        CACHE[key] = (time.time(), value)
    return value


def invalidate_research(*tickers):
    with CACHE_LOCK:
        for ticker in tickers:
            CACHE.pop(("research_core_v05", ticker), None)


def http_json(url, headers=None, timeout=12, method="GET", data=None, retries=1):
    h = {"User-Agent": "Mozilla/5.0 StonkResearch/0.5", "Accept": "application/json,text/plain,*/*"}
    if headers:
        h.update(headers)
    body = None if data is None else json.dumps(data).encode()
    if body is not None:
        h["Content-Type"] = "application/json"
    last = None
    for attempt in range(retries + 1):
        try:
            with urlopen(Request(url, headers=h, method=method, data=body), timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except (HTTPError, URLError, TimeoutError, ValueError) as exc:
            last = exc
            if attempt < retries:
                time.sleep(.25 * (attempt + 1))
    raise RuntimeError(f"Request failed: {last}")


@contextmanager
def connect():
    con = sqlite3.connect(DB_PATH, timeout=5)
    con.row_factory = sqlite3.Row
    try:
        with con:
            yield con
    finally:
        con.close()


def init_db():
    with DB_LOCK, connect() as con:
        con.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS positions(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            shares REAL NOT NULL,
            avg_price REAL NOT NULL,
            thesis TEXT NOT NULL DEFAULT '',
            thesis_json TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL,
            updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS research_history(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            created_at TEXT NOT NULL,
            status TEXT NOT NULL,
            price REAL, opportunity INTEGER, entry INTEGER, quality INTEGER, risk INTEGER, confidence INTEGER, timing_risk INTEGER,
            payload_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_research_history_ticker_id ON research_history(ticker,id DESC);
        CREATE TABLE IF NOT EXISTS response_cache(
            key TEXT PRIMARY KEY,
            value_json TEXT NOT NULL,
            saved_at REAL NOT NULL
        );
        """)
        try:
            cols = {row[1] for row in con.execute("PRAGMA table_info(positions)").fetchall()}
            if "thesis_json" not in cols:
                con.execute("ALTER TABLE positions ADD COLUMN thesis_json TEXT NOT NULL DEFAULT '[]'")
            if "updated_at" not in cols:
                con.execute("ALTER TABLE positions ADD COLUMN updated_at TEXT")
        except Exception as exc:
            raise RuntimeError("Positions schema migration failed") from exc
        defaults = {
            "ollama_enabled":"false",
            "ollama_url":"http://127.0.0.1:11434",
            "ollama_model":"auto",
            "sec_user_agent":"StonkResearch/0.5 contact@example.com",
            "hunter_max_symbols":"36",
            "hunter_universe":"",
        }
        for k, v in defaults.items():
            con.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (k, v))
        con.commit()


def get_setting(k, default=""):
    with connect() as con:
        r = con.execute("SELECT value FROM settings WHERE key=?", (k,)).fetchone()
    return r["value"] if r else default


def set_setting(k, v):
    with DB_LOCK, connect() as con:
        con.execute(
            "INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (k, str(v)),
        )
        con.commit()


def disk_cache_get(key, ttl):
    try:
        with connect() as con:
            row = con.execute("SELECT value_json,saved_at FROM response_cache WHERE key=?", (key,)).fetchone()
        if row and time.time() - float(row["saved_at"]) < ttl:
            return json.loads(row["value_json"])
    except Exception:
        return None
    return None


def disk_cache_put(key, value):
    try:
        raw = json.dumps(value, ensure_ascii=False, default=str)
        with DB_LOCK, connect() as con:
            con.execute(
                "INSERT INTO response_cache(key,value_json,saved_at) VALUES(?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,saved_at=excluded.saved_at",
                (key, raw, time.time()),
            )
            con.commit()
    except Exception:
        pass
    return value


def yahoo_chart(ticker, range_="1y"):
    ticker = clean_ticker(ticker)
    key = ("chart", ticker, range_)
    cached = cache_get(key, 300)
    if cached:
        return cached
    params = urlencode({"range": range_, "interval": "1d", "includePrePost": "false", "events": "div,splits"})
    err = None
    for domain in ("query1.finance.yahoo.com", "query2.finance.yahoo.com"):
        try:
            data = http_json(f"https://{domain}/v8/finance/chart/{quote(ticker)}?{params}", timeout=10, retries=1)
            result = ((data.get("chart") or {}).get("result") or [None])[0]
            if not result:
                raise ValueError(((data.get("chart") or {}).get("error") or {}).get("description") or "No chart data")
            ts = result.get("timestamp") or []
            q = ((result.get("indicators") or {}).get("quote") or [{}])[0]
            closes = q.get("close") or []
            opens = q.get("open") or []
            highs = q.get("high") or []
            lows = q.get("low") or []
            vols = q.get("volume") or []
            rows = []
            for i, stamp in enumerate(ts):
                close = fnum(closes[i] if i < len(closes) else None)
                if close is None:
                    continue
                rows.append({
                    "date": datetime.fromtimestamp(stamp, timezone.utc).date().isoformat(),
                    "time": datetime.fromtimestamp(stamp, timezone.utc).isoformat(),
                    "open": fnum(opens[i] if i < len(opens) else None),
                    "high": fnum(highs[i] if i < len(highs) else None),
                    "low": fnum(lows[i] if i < len(lows) else None),
                    "close": close,
                    "volume": fnum(vols[i] if i < len(vols) else None),
                })
            if len(rows) < 20:
                raise ValueError("Not enough market history")
            return cache_put(key, {"ticker": ticker, "rows": rows, "meta": result.get("meta") or {}})
        except Exception as exc:
            err = exc
    raise RuntimeError(f"Market data unavailable for {ticker}: {err}")


def yahoo_chart_display(ticker, range_="1y"):
    ticker = clean_ticker(ticker)
    norm = normalize_chart_range(range_)
    interval = chart_interval(norm)
    key = ("chart_display", ticker, norm, interval)
    cached = cache_get(key, 300)
    if cached:
        return cached
    params = urlencode({"range": norm, "interval": interval, "includePrePost": "false", "events": "div,splits"})
    err = None
    for domain in ("query1.finance.yahoo.com", "query2.finance.yahoo.com"):
        try:
            data = http_json(f"https://{domain}/v8/finance/chart/{quote(ticker)}?{params}", timeout=10, retries=1)
            result = ((data.get("chart") or {}).get("result") or [None])[0]
            if not result:
                raise ValueError(((data.get("chart") or {}).get("error") or {}).get("description") or "No chart data")
            ts = result.get("timestamp") or []
            q = ((result.get("indicators") or {}).get("quote") or [{}])[0]
            closes = q.get("close") or []
            opens = q.get("open") or []
            highs = q.get("high") or []
            lows = q.get("low") or []
            vols = q.get("volume") or []
            rows = []
            for i, stamp in enumerate(ts):
                close = fnum(closes[i] if i < len(closes) else None)
                if close is None:
                    continue
                dt = datetime.fromtimestamp(stamp, timezone.utc)
                rows.append({
                    "date": dt.date().isoformat(),
                    "time": dt.isoformat(),
                    "open": fnum(opens[i] if i < len(opens) else None),
                    "high": fnum(highs[i] if i < len(highs) else None),
                    "low": fnum(lows[i] if i < len(lows) else None),
                    "close": close,
                    "volume": fnum(vols[i] if i < len(vols) else None),
                })
            if len(rows) < 2:
                raise ValueError("Not enough chart points")
            out = {"ticker": ticker, "range": norm, "interval": interval, "history": rows,
                   "updated_at": rows[-1]["time"], "retrieved_at": now_iso()}
            return cache_put(key, out)
        except Exception as exc:
            err = exc
    raise RuntimeError(f"Chart data unavailable for {ticker}: {err}")


def sec_headers():
    return {"User-Agent": get_setting("sec_user_agent", "StonkResearch/0.5 contact@example.com"), "Accept": "application/json"}


def sec_tickers():
    c = cache_get(("sec_tickers",), 86400)
    if c:
        return c
    persistent = disk_cache_get("sec_tickers", 7 * 86400)
    if persistent:
        return cache_put(("sec_tickers",), persistent)
    with SEC_TICKERS_LOCK:
        c = cache_get(("sec_tickers",), 86400)
        if c:
            return c
        persistent = disk_cache_get("sec_tickers", 7 * 86400)
        if persistent:
            return cache_put(("sec_tickers",), persistent)
        data = http_json("https://www.sec.gov/files/company_tickers.json", headers=sec_headers(), timeout=8, retries=0)
        out = {}
        for x in data.values():
            t = str(x.get("ticker") or "").upper()
            if t:
                out[t] = {"cik": str(x.get("cik_str") or "").zfill(10), "name": x.get("title") or t}
        disk_cache_put("sec_tickers", out)
        return cache_put(("sec_tickers",), out)


def sec_identity(ticker):
    try:
        return sec_tickers().get(clean_ticker(ticker))
    except Exception:
        return None


def sec_filings(ticker, limit=12):
    ticker = clean_ticker(ticker)
    key = ("sec_filings", ticker)
    c = cache_get(key, 1200)
    if c is not None:
        return c
    persistent = disk_cache_get(f"sec_filings:{ticker}", 1800)
    if persistent is not None:
        return cache_put(key, persistent)
    ident = sec_identity(ticker)
    if not ident:
        return []
    d = http_json(f"https://data.sec.gov/submissions/CIK{ident['cik']}.json", headers=sec_headers(), timeout=9, retries=0)
    r = ((d.get("filings") or {}).get("recent") or {})
    forms = r.get("form") or []
    acc = r.get("accessionNumber") or []
    dates = r.get("filingDate") or []
    docs = r.get("primaryDocument") or []
    desc = r.get("primaryDocDescription") or []
    out = []
    important = {"10-K","10-Q","8-K","8-K/A","10-K/A","10-Q/A","20-F","6-K"}
    for i, form in enumerate(forms):
        if form not in important:
            continue
        a = acc[i] if i < len(acc) else ""
        doc = docs[i] if i < len(docs) else ""
        url = None
        if a and doc:
            url = f"https://www.sec.gov/Archives/edgar/data/{int(ident['cik'])}/{a.replace('-','')}/{quote(doc)}"
        out.append({
            "form": form,
            "date": dates[i] if i < len(dates) else None,
            "description": desc[i] if i < len(desc) else "",
            "url": url,
            "reliability": 100,
            "source": "sec",
            "importance": "HIGH" if form in {"8-K","10-Q","10-K"} else "MEDIUM",
        })
        if len(out) >= limit:
            break
    disk_cache_put(f"sec_filings:{ticker}", out)
    return cache_put(key, out)


def _fact_points(facts, tags, unit="USD"):
    gaap = (facts.get("facts") or {}).get("us-gaap") or {}
    points = []
    for tag in tags:
        units = (gaap.get(tag) or {}).get("units") or {}
        unit_rows = units.get(unit) or []
        for x in unit_rows:
            if x.get("form") not in {"10-K","10-Q","10-K/A","10-Q/A","8-K"}:
                continue
            v = fnum(x.get("val"))
            if v is not None:
                points.append({"v": v, "fy": x.get("fy"), "fp": x.get("fp"), "form": x.get("form"), "filed": x.get("filed"), "start": x.get("start"), "end": x.get("end")})
    points.sort(key=lambda x: (x.get("filed") or "", x.get("end") or ""), reverse=True)
    return points


def _annual_pair(facts, tags, unit="USD"):
    annual_by_end = {}
    for x in _fact_points(facts, tags, unit):
        if not x.get("form", "").startswith("10-K") or x.get("fp") not in {"FY", None}:
            continue
        try:
            duration = (datetime.fromisoformat(x["end"]) - datetime.fromisoformat(x["start"])).days
        except (TypeError, ValueError, KeyError):
            continue
        if not 330 <= duration <= 380:
            continue
        end = x["end"]
        if end not in annual_by_end or (x.get("filed") or "") > (annual_by_end[end].get("filed") or ""):
            annual_by_end[end] = x
    return [annual_by_end[k] for k in sorted(annual_by_end, reverse=True)[:2]]


def sec_fundamentals(ticker):
    ticker = clean_ticker(ticker)
    key = ("sec_fund", ticker)
    c = cache_get(key, 7200)
    if c:
        return c
    persistent = disk_cache_get(f"sec_fund:{ticker}", 6 * 3600)
    if persistent:
        return cache_put(key, persistent)
    ident = sec_identity(ticker)
    if not ident:
        return {"available": False, "name": ticker}
    data = http_json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{ident['cik']}.json", headers=sec_headers(), timeout=10, retries=0)
    rev = _annual_pair(data, ["RevenueFromContractWithCustomerExcludingAssessedTax","Revenues","SalesRevenueNet"])
    ni = _annual_pair(data, ["NetIncomeLoss","ProfitLoss"])
    ocf = _annual_pair(data, ["NetCashProvidedByUsedInOperatingActivities"])
    capex = _annual_pair(data, ["PaymentsToAcquirePropertyPlantAndEquipment"])
    assets = _fact_points(data, ["Assets"])
    liab = _fact_points(data, ["Liabilities"])
    cash = _fact_points(data, ["CashAndCashEquivalentsAtCarryingValue","CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"])
    eps = _annual_pair(data, ["EarningsPerShareDiluted","EarningsPerShareBasic"], "USD/shares")
    growth = (rev[0]["v"] / rev[1]["v"] - 1) * 100 if len(rev) >= 2 and rev[1]["v"] > 0 else None
    ig = (ni[0]["v"] / ni[1]["v"] - 1) * 100 if len(ni) >= 2 and ni[1]["v"] > 0 else None
    capex_by_end = {x["end"]: x["v"] for x in capex}
    fcf = ocf[0]["v"] - capex_by_end[ocf[0]["end"]] if ocf and ocf[0]["end"] in capex_by_end else None
    result = {
        "available": bool(rev or ni or ocf or assets or liab or cash),
        "name": ident["name"],
        "revenue": rev[0]["v"] if rev else None,
        "revenue_growth_pct": growth,
        "net_income": ni[0]["v"] if ni else None,
        "net_income_growth_pct": ig,
        "operating_cashflow": ocf[0]["v"] if ocf else None,
        "free_cashflow_est": fcf,
        "assets": assets[0]["v"] if assets else None,
        "liabilities": liab[0]["v"] if liab else None,
        "cash": cash[0]["v"] if cash else None,
        "eps_annual": eps[0]["v"] if eps else None,
        "latest_fiscal_end": rev[0].get("end") if rev else None,
        "source": "SEC companyfacts",
    }
    disk_cache_put(f"sec_fund:{ticker}", result)
    return cache_put(key, result)


def gdelt_news(query_text, max_records=20, timespan="7d"):
    query_text = (query_text or "").strip()
    if not query_text:
        return []
    key = ("gdelt_news", query_text.lower(), max_records, timespan)
    c = cache_get(key, 1200)
    if c is not None:
        return c
    persistent = disk_cache_get(f"gdelt:{query_text.lower()}:{max_records}:{timespan}", 1800)
    if persistent is not None:
        return cache_put(key, persistent)
    params = urlencode({"query": f'"{query_text}"', "mode": "artlist", "maxrecords": min(max_records, 30), "timespan": timespan, "sort": "datedesc", "format": "json"})
    try:
        data = http_json(f"https://api.gdeltproject.org/api/v2/doc/doc?{params}", timeout=7, retries=0)
    except Exception:
        return []
    out, seen = [], set()
    for a in data.get("articles") or []:
        title = (a.get("title") or "").strip()
        url = a.get("url")
        if not title or not url or title.lower() in seen:
            continue
        seen.add(title.lower())
        domain = (a.get("domain") or urlparse(url).netloc).lower().replace("www.", "")
        stamp = a.get("seendate")
        if isinstance(stamp, str) and re.fullmatch(r"\d{8}T\d{6}Z", stamp):
            stamp = datetime.strptime(stamp, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).isoformat()
        out.append({
            "title": title, "url": url, "publisher": domain, "domain": domain,
            "published": stamp, "source": "gdelt", "source_country": a.get("sourcecountry"),
        })
    disk_cache_put(f"gdelt:{query_text.lower()}:{max_records}:{timespan}", out)
    return cache_put(key, out)


def yahoo_news_search(query_text, max_records=20):
    query_text = (query_text or "").strip()
    if not query_text:
        return []
    key = ("yahoo_news", query_text.lower(), max_records)
    c = cache_get(key, 900)
    if c is not None:
        return c
    persistent = disk_cache_get(f"yahoo_news:{query_text.lower()}:{max_records}", 1200)
    if persistent is not None:
        return cache_put(key, persistent)
    params = urlencode({"q": query_text, "quotesCount": 0, "newsCount": min(max_records, 30), "enableFuzzyQuery": "false"})
    data = None
    for domain in ("query1.finance.yahoo.com", "query2.finance.yahoo.com"):
        try:
            data = http_json(f"https://{domain}/v1/finance/search?{params}", timeout=6, retries=0)
            break
        except Exception:
            continue
    if not data:
        return []
    out, seen = [], set()
    for a in data.get("news") or []:
        title = (a.get("title") or "").strip()
        url = a.get("link")
        if not title or not url or title.lower() in seen:
            continue
        seen.add(title.lower())
        stamp = a.get("providerPublishTime")
        published = datetime.fromtimestamp(stamp, timezone.utc).isoformat() if isinstance(stamp, (int, float)) else None
        domain = urlparse(url).netloc.lower().replace("www.", "")
        out.append({
            "title": title, "url": url, "publisher": a.get("publisher") or domain, "domain": domain,
            "published": published, "source": "yahoo-news", "related_tickers": a.get("relatedTickers") or [],
        })
    disk_cache_put(f"yahoo_news:{query_text.lower()}:{max_records}", out)
    return cache_put(key, out)


def fast_news(query_text, max_records=24, deep=False):
    primary_error = None
    try:
        primary = yahoo_news_search(query_text, min(max_records, 24))
    except Exception as exc:
        primary_error = exc
        primary = []
    merged = list(primary)
    # Avoid blocking an otherwise usable news feed on a slow fallback provider.
    if len(primary) < 3:
        try:
            extra = gdelt_news(query_text, 12 if deep else 10, "7d")
        except Exception as exc:
            if primary_error is not None:
                raise RuntimeError("All free news providers are unavailable") from exc
            extra = []
        seen = {str(x.get("title") or "").lower() for x in merged}
        for item in extra:
            key = str(item.get("title") or "").lower()
            if key and key not in seen:
                seen.add(key); merged.append(item)
                if len(merged) >= max_records:
                    break
    return merged[:max_records]


def reliability(item):
    d = (item.get("domain") or "").lower().replace("www.", "")
    publisher = (item.get("publisher") or "").lower().strip()
    if item.get("source") == "sec" or d == "sec.gov" or d.endswith(".sec.gov"):
        return 100
    if any(d == x or d.endswith("." + x) for x in TIER1):
        return 88
    if any(name in publisher for name in ("reuters","associated press","bloomberg","wall street journal","financial times","cnbc","marketwatch","barron's","barrons")):
        return 88
    if publisher:
        return 62
    return 52


def news_event_type(title):
    low = (title or "").lower()
    for label, terms in NEWS_EVENT_RULES:
        if any(term in low for term in terms):
            return label
    return "GENERAL"


def _event_tokens(title):
    stop = {"the","and","for","with","from","that","this","after","over","into","amid","says","stock","shares","company","inc","corp","corporation","on","in","of","to","a","an"}
    return {w for w in re.findall(r"[a-z0-9]+", (title or "").lower()) if len(w) > 2 and w not in stop}


def _same_event(a, b):
    ta, tb = _event_tokens(a), _event_tokens(b)
    if not ta or not tb:
        return False
    overlap = len(ta & tb) / max(1, len(ta | tb))
    return overlap >= .48 or (len(ta & tb) >= 4 and overlap >= .35)


def _risk_term_applies(title, term):
    if term == "default" and not re.search(
        r"\b(?:debt|bond|loan|payment|sovereign|credit) default\b|\bdefault(?:ed|s)? on\b|\bin default\b", title
    ):
        return False
    for match in re.finditer(r"(?<!\w)" + re.escape(term) + r"(?!\w)", title):
        preceding = title[max(0, match.start() - 85):match.start()]
        if re.search(
            r"\b(?:no|without|denies|denied|deny|rejects|dismisses|disproves|exonerated|cleared)"
            r"(?:[\W_]+\w+){0,3}[\W_]*$", preceding
        ):
            continue
        return True
    return False


def classify_news_item(item):
    title = (item.get("title") or "").lower()
    local, hits = 0, []
    for term, pts in RISK_TERMS.items():
        if _risk_term_applies(title, term):
            local += pts; hits.append(term)
    for term, pts in POS_TERMS.items():
        if term in title:
            local += pts; hits.append(term)
    rel = reliability(item)
    weighted = local * rel / 100
    if abs(weighted) >= 18: impact = "HIGH"
    elif abs(weighted) >= 8: impact = "MEDIUM"
    else: impact = "LOW"
    sentiment = "BEARISH" if weighted > 3 else "BULLISH" if weighted < -3 else "NEUTRAL"
    copy = dict(item)
    copy.update({"reliability": rel, "risk_points": round(weighted, 1), "matched": hits, "impact": impact,
                 "sentiment": sentiment, "event_type": news_event_type(item.get("title"))})
    return copy


def news_score(items):
    annotated = [classify_news_item(x) for x in items]
    clusters = []
    for item in annotated:
        placed = None
        for cluster in clusters:
            if _same_event(item.get("title"), cluster[0].get("title")):
                placed = cluster; break
        if placed is None:
            placed = []; clusters.append(placed)
        placed.append(item)

    events, risk_values, bull_values = [], [], []
    for idx, cluster in enumerate(clusters, 1):
        sources = {str(x.get("publisher") or x.get("domain") or "").lower() for x in cluster if x.get("publisher") or x.get("domain")}
        primary = any(x.get("source") == "sec" or (x.get("domain") or "").lower().endswith("sec.gov") for x in cluster)
        max_rel = max((x.get("reliability", 0) for x in cluster), default=0)
        if primary:
            confirmation, factor = "PRIMARY-SOURCE CONFIRMED", 1.0
        elif len(sources) >= 2:
            confirmation, factor = "MULTIPLE OUTLETS / UNVERIFIED", .74
        elif max_rel >= 85:
            confirmation, factor = "REPORTED / UNVERIFIED", .74
        else:
            confirmation, factor = "UNVERIFIED / LOW DIVERSITY", .55
        representative = max(cluster, key=lambda x: abs(x.get("risk_points", 0)))
        raw = representative.get("risk_points", 0)
        adjusted = raw * factor
        if adjusted > 0: risk_values.append(adjusted)
        elif adjusted < 0: bull_values.append(abs(adjusted))
        event = {
            "id": f"E{idx}", "type": representative.get("event_type", "GENERAL"), "title": representative.get("title"),
            "confirmation": confirmation, "outlet_count": len(sources), "reliability": max_rel,
            "impact": representative.get("impact"), "sentiment": representative.get("sentiment"),
            "risk_points": round(adjusted, 1), "articles": len(cluster),
        }
        events.append(event)
        for x in cluster:
            x.update({"event_id": event["id"], "confirmation": confirmation, "outlet_count": len(sources)})

    risk_values.sort(reverse=True); bull_values.sort(reverse=True)
    decay = (1.0, .58, .34, .20, .12)
    risk_total = sum(v * decay[i] for i, v in enumerate(risk_values[:len(decay)]))
    bull_offset = sum(v * decay[i] for i, v in enumerate(bull_values[:len(decay)]))
    total = clamp(risk_total - bull_offset * .5)
    reasons = sorted([x for x in annotated if abs(x["risk_points"]) >= 4], key=lambda x: abs(x["risk_points"]), reverse=True)[:10]
    events.sort(key=lambda x: abs(x["risk_points"]), reverse=True)
    return {"score": round(total), "reasons": reasons, "events": events[:12], "items": annotated,
            "available": bool(annotated), "event_count": len(events),
            "confirmed_event_count": len([e for e in events if e["confirmation"] == "PRIMARY-SOURCE CONFIRMED"])}


def yahoo_earnings_calendar(ticker):
    ticker = clean_ticker(ticker)
    key = ("earnings_calendar", ticker)
    cached = cache_get(key, 21600)
    if cached:
        return cached
    result = {"available": False, "next_earnings": None, "days_to_earnings": None, "risk": "UNKNOWN", "source": "Yahoo Finance calendar (best effort)"}
    try:
        url = f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{quote(ticker)}?modules=calendarEvents"
        data = http_json(url, timeout=7, retries=0)
        payload = (((data.get("quoteSummary") or {}).get("result") or [{}])[0].get("calendarEvents") or {}).get("earnings") or {}
        dates = payload.get("earningsDate") or []
        raw = None
        for d in dates:
            if isinstance(d, dict) and d.get("raw"):
                raw = int(d["raw"]); break
        if raw:
            dt = datetime.fromtimestamp(raw, timezone.utc)
            days = (dt.date() - datetime.now(timezone.utc).date()).days
            risk = "IMMINENT" if 0 <= days <= 2 else "NEAR" if 0 <= days <= 7 else "NORMAL"
            result.update({"available": True, "next_earnings": dt.isoformat(), "days_to_earnings": days, "risk": risk})
    except Exception as exc:
        result["error"] = str(exc)
    return cache_put(key, result)


def sector_info(ticker):
    bench = SECTOR_BENCHMARKS.get(clean_ticker(ticker), "^GSPC")
    names = dict(SECTORS)
    return {"benchmark": bench, "sector": names.get(bench, "Broad Market" if bench == "^GSPC" else bench)}


def research_change_summary(history):
    if not history or len(history) < 2:
        return {"available": False, "items": [], "summary": "No prior comparable research snapshot yet."}
    cur, prev = history[0], history[1]
    items=[]
    for key,label in (("price","Price"),("opportunity","Opportunity"),("entry","Entry"),("quality","Quality"),("risk","Risk"),("timing_risk","Timing risk")):
        a,b=cur.get(key),prev.get(key)
        if a is None or b is None: continue
        delta=round(float(a)-float(b),2)
        if abs(delta) >= (0.5 if key=="price" else 2):
            items.append({"metric":label,"from":b,"to":a,"delta":delta})
    return {"available": True, "status_from": prev.get("status"), "status_to": cur.get("status"), "items": items[:8],
            "summary": f"Status changed from {prev.get('status')} to {cur.get('status')}." if prev.get('status') != cur.get('status') else "Status is unchanged; score/price movement is shown below."}

def indicators(rows):
    c = [x["close"] for x in rows if x.get("close") is not None]
    if len(c) < 20:
        raise ValueError("Not enough price history")
    sma = lambda n: sum(c[-n:]) / n if len(c) >= n else None
    sma20, sma50, sma200 = sma(20), sma(50), sma(200)
    gains, losses = [], []
    for a, b in zip(c[-15:-1], c[-14:]):
        d = b-a; gains.append(max(d,0)); losses.append(max(-d,0))
    ag=sum(gains)/len(gains) if gains else 0; al=sum(losses)/len(losses) if losses else 0
    rsi=50 if ag==0 and al==0 else 100 if al==0 else 100-(100/(1+ag/al))
    trs=[]; rr=rows[-15:]
    for i in range(1,len(rr)):
        hi=fnum(rr[i].get("high")) or rr[i]["close"]; lo=fnum(rr[i].get("low")) or rr[i]["close"]; pc=rr[i-1]["close"]
        trs.append(max(hi-lo,abs(hi-pc),abs(lo-pc)))
    atr=sum(trs)/len(trs) if trs else c[-1]*.03
    rets=[c[i]/c[i-1]-1 for i in range(max(1,len(c)-20),len(c)) if c[i-1]]
    vol=statistics.pstdev(rets)*math.sqrt(252)*100 if len(rets)>1 else None
    price_std20=statistics.pstdev(c[-20:]) if len(c)>=20 else None
    vols=[fnum(x.get("volume")) for x in rows[-21:-1] if fnum(x.get("volume")) is not None]
    curvol=fnum(rows[-1].get("volume")); avgvol=sum(vols)/len(vols) if vols else None; rv=curvol/avgvol if curvol and avgvol else None
    def mom(days): return (c[-1]/c[-days-1]-1)*100 if len(c)>days and c[-days-1] else None
    recent=rows[-20:]; lows=[fnum(x.get("low")) for x in recent if fnum(x.get("low")) is not None]; highs=[fnum(x.get("high")) for x in recent if fnum(x.get("high")) is not None]
    year_rows=rows[-252:]; allhigh=[fnum(x.get("high")) for x in year_rows if fnum(x.get("high")) is not None]; alllow=[fnum(x.get("low")) for x in year_rows if fnum(x.get("low")) is not None]
    support=min(lows) if lows else min(c[-20:]); resistance=max(highs) if highs else max(c[-20:]); high52=max(allhigh) if allhigh else max(c); low52=min(alllow) if alllow else min(c)
    trend=0
    if sma20: trend += 1 if c[-1]>sma20 else -1
    if sma20 and sma50: trend += 1 if sma20>sma50 else -1
    if sma50 and sma200: trend += 1 if sma50>sma200 else -1
    up_streak=0
    for i in range(len(c)-1,0,-1):
        if c[i]>c[i-1]: up_streak+=1
        else: break
    p=c[-1]; position20=((p-support)/(resistance-support)*100) if resistance>support else 50; position52=((p-low52)/(high52-low52)*100) if high52>low52 else 50
    # Gap and falling-knife diagnostics.
    gaps=[]
    for i in range(max(1,len(rows)-20),len(rows)):
        op=fnum(rows[i].get("open")); prev=fnum(rows[i-1].get("close"))
        if op is not None and prev: gaps.append((op/prev-1)*100)
    current_gap=gaps[-1] if gaps else None; max_gap=max((abs(x) for x in gaps[-5:]),default=0)
    lower_lows=0
    recent_lows=[fnum(x.get("low")) or x.get("close") for x in rows[-11:]]
    for a,b in zip(recent_lows[:-1],recent_lows[1:]):
        if a is not None and b is not None and b<a: lower_lows+=1
    last20=c[-20:]; low20=min(last20); days_since_low=(len(last20)-1)-last20.index(low20); rebound=((p/low20)-1)*100 if low20 else 0
    knife=0
    if trend<=-2: knife+=30
    if (mom(5) or 0)<-5: knife+=20
    if (mom(21) or 0)<-12: knife+=20
    knife+=min(20,lower_lows*4)
    if days_since_low<=2 and rebound<3: knife+=10
    knife=round(clamp(knife))
    stabilization=round(clamp((days_since_low*5)+max(0,rebound*4)+(12 if trend>=0 else 0)-max(0,lower_lows-3)*4))
    gap_risk=round(clamp(max(0,(abs(current_gap or 0)-2.5)*10)+max(0,(max_gap-4)*10)))
    return {
        "price":p,"sma20":sma20,"sma50":sma50,"sma200":sma200,"rsi14":rsi,"atr14":atr,"volatility20":vol,"relative_volume":rv,
        "momentum_1w":mom(5),"momentum_1m":mom(21),"momentum_3m":mom(63),"momentum_6m":mom(126),"support20":support,"resistance20":resistance,"high52":high52,"low52":low52,
        "drawdown52":(p/high52-1)*100 if high52 else None,"trend_score_raw":trend,"current_volume":curvol,"avg_volume20":avgvol,"up_streak":up_streak,
        "price_vs_sma20_pct":((p/sma20-1)*100 if sma20 else None),"price_vs_sma50_pct":((p/sma50-1)*100 if sma50 else None),"price_vs_sma200_pct":((p/sma200-1)*100 if sma200 else None),
        "atr_from_sma20":((p-sma20)/atr if sma20 and atr else None),"position_20d_pct":position20,"position_52w_pct":position52,
        "room_to_resistance_pct":((resistance/p-1)*100 if p else None),"distance_from_support_pct":((p/support-1)*100 if support else None),"price_z20":((p-sma20)/price_std20 if sma20 and price_std20 else None),
        "current_gap_pct":current_gap,"max_abs_gap_5d_pct":max_gap,"gap_risk":gap_risk,"lower_lows_10d":lower_lows,"days_since_20d_low":days_since_low,"rebound_from_20d_low_pct":rebound,
        "falling_knife_risk":knife,"stabilization_score":stabilization,
    }


def price_model(ind):
    p=ind["price"]; atr=ind.get("atr14") or p*.03; support=ind.get("support20") or p-2*atr; resistance=ind.get("resistance20") or p+2*atr
    sma20=ind.get("sma20") or p; sma50=ind.get("sma50") or sma20; sma200=ind.get("sma200") or sma50
    below=[x for x in (sma20,sma50,support) if x and x<=p*1.01]; nearest_support=max(below) if below else support; deeper_support=min(nearest_support,max(support,min(sma50,sma20)))
    risk=max(.01,min(support-1.10*atr,nearest_support-1.45*atr,p-1.5*atr))
    strong_mid=max(.01,deeper_support); strong_lo=max(.01,strong_mid-.45*atr); strong_hi=min(p,strong_mid+.35*atr)
    preferred_mid=max(strong_hi,nearest_support); buy_lo=max(.01,preferred_mid-.30*atr); buy_hi=min(p,preferred_mid+.45*atr); buy_hi=max(buy_lo,buy_hi)
    trend_reference=sma20*.55+sma50*.30+sma200*.15; fair_lo=max(.01,trend_reference-.65*atr); fair_hi=trend_reference+.65*atr
    first_resistance=resistance if resistance>p else p+1.25*atr; take_lo=max(first_resistance,p+1.15*atr); take_hi=take_lo+1.35*atr
    risk_dollars=max(.01,p-risk); first_reward=max(0,first_resistance-p); rr=first_reward/risk_dollars
    downside_support=max(0,(p-nearest_support)/p*100) if p else 0; upside=max(0,(first_resistance-p)/p*100) if p else 0; asym=(upside/downside_support) if downside_support>.15 else 9.99
    over=0.0; d20=ind.get("price_vs_sma20_pct"); d50=ind.get("price_vs_sma50_pct"); rsi=ind.get("rsi14"); pos20=ind.get("position_20d_pct")
    if d20 is not None: over+=clamp((d20-3)*2.2,0,28)
    if d50 is not None: over+=clamp((d50-8)*1.25,0,25)
    if rsi is not None: over+=clamp((rsi-65)*1.5,0,24)
    if pos20 is not None and pos20>88: over+=clamp((pos20-88)*.7,0,9)
    if (ind.get("momentum_1w") or 0)>8: over+=7
    if (ind.get("up_streak") or 0)>=4: over+=5
    over+=ind.get("gap_risk",0)*.18; over=round(clamp(over))
    pullback=35.0
    if ind.get("trend_score_raw",0)>=1: pullback+=10
    if abs((p-sma20)/atr)<=1.0 if atr else False: pullback+=16
    if rsi is not None and 40<=rsi<=60: pullback+=14
    if ind.get("distance_from_support_pct") is not None and ind["distance_from_support_pct"]<=7: pullback+=12
    if ind.get("falling_knife_risk",0)>=50: pullback-=24
    pullback=round(clamp(pullback))
    timing="CHASE RISK" if over>=65 else "FALLING KNIFE" if ind.get("falling_knife_risk",0)>=65 else "WAIT FOR PULLBACK" if over>=45 else "FAVORABLE" if pullback>=65 and rr>=1.2 else "NEUTRAL"
    return {"current":round(p,2),"strong_buy_zone":[round(strong_lo,2),round(strong_hi,2)],"buy_zone":[round(buy_lo,2),round(buy_hi,2)],"reference_value_zone":[round(fair_lo,2),round(fair_hi,2)],
        "take_profit_zone":[round(take_lo,2),round(take_hi,2)],"risk_exit":round(risk,2),"bear_reference":round(max(.01,support-atr),2),"base_reference":round(trend_reference,2),"bull_reference":round(take_hi+atr,2),
        "risk_reward":round(rr,2),"potential_upside_pct":round(upside,1),"risk_to_exit_pct":round((risk/p-1)*100,1),"downside_to_support_pct":round(downside_support,1),"upside_downside_ratio":round(asym,2),
        "overextension_risk":over,"pullback_quality":pullback,"timing_status":timing,"nearest_support":round(nearest_support,2),"first_resistance":round(first_resistance,2),"gap_risk":ind.get("gap_risk",0),"falling_knife_risk":ind.get("falling_knife_risk",0),
        "method":"Downside-first entry model using support/resistance, ATR, moving averages, gap risk, falling-knife risk and overextension",
        "warning":"Research ranges only. The model evaluates downside before upside; momentum alone never creates a BUY signal."}


def scores(ind, fund=None, nscore=0):
    pm = price_model(ind)
    momentum = 50.0
    m1, m3 = ind.get("momentum_1m"), ind.get("momentum_3m")
    if m1 is not None:
        momentum += clamp(m1 * .75, -16, 13)
        if m1 > 22: momentum -= min(8, (m1 - 22) * .35)
    if m3 is not None:
        momentum += clamp(m3 * .28, -13, 12)
    momentum += ind.get("trend_score_raw", 0) * 5
    rsi = ind.get("rsi14")
    if rsi is not None:
        if 48 <= rsi <= 66: momentum += 5
        elif rsi >= 76: momentum -= 8
    rv = ind.get("relative_volume")
    if rv is not None: momentum += clamp((rv - 1) * 5, -4, 7)

    quality, evidence = 50.0, 45
    if fund and fund.get("available"):
        rg, ig, fcf = fund.get("revenue_growth_pct"), fund.get("net_income_growth_pct"), fund.get("free_cashflow_est")
        assets, liab = fund.get("assets"), fund.get("liabilities")
        if rg is not None: quality += clamp(rg * .35, -15, 15); evidence += 12
        if ig is not None: quality += clamp(ig * .15, -10, 10); evidence += 8
        if fcf is not None: quality += 7 if fcf > 0 else -10; evidence += 8
        if assets and liab: quality += 5 if assets > liab else -8; evidence += 7

    risk = 18.0
    vol, dd = ind.get("volatility20"), ind.get("drawdown52")
    if vol is not None: risk += clamp((vol - 20) * .65, 0, 35)
    if dd is not None: risk += clamp(abs(min(dd, 0)) * .30, 0, 15)
    if ind.get("trend_score_raw", 0) < 0: risk += abs(ind["trend_score_raw"]) * 7
    risk += nscore * .50
    risk += pm["overextension_risk"] * .15
    risk += ind.get("gap_risk",0) * .12
    risk += ind.get("falling_knife_risk",0) * .18

    entry = 52.0
    rr = pm.get("risk_reward") or 0
    if rr >= 2.0: entry += 20
    elif rr >= 1.5: entry += 12
    elif rr >= 1.0: entry += 4
    elif rr < .6: entry -= 22
    else: entry -= 12
    entry += (pm["pullback_quality"] - 50) * .28
    entry -= pm["overextension_risk"] * .42
    if rsi is not None and 40 <= rsi <= 60 and ind.get("trend_score_raw", 0) >= 1: entry += 8
    if ind.get("trend_score_raw", 0) <= -2: entry -= 14
    entry -= ind.get("falling_knife_risk",0) * .28
    entry -= ind.get("gap_risk",0) * .22
    if pm.get("upside_downside_ratio",0) < 1.0: entry -= 12
    if (ind.get("distance_from_support_pct") or 0) > 14: entry -= 8
    if (ind.get("price_vs_sma50_pct") or 0) > 20: entry -= 10

    safety = 100 - clamp(risk)
    raw_opp = quality * .32 + momentum * .20 + entry * .32 + safety * .16
    if entry < 45: raw_opp = min(raw_opp, 60)
    if pm["overextension_risk"] >= 65: raw_opp = min(raw_opp, 58)
    if risk >= 70: raw_opp = min(raw_opp, 52)
    return {
        "opportunity": round(clamp(raw_opp)), "entry": round(clamp(entry)), "risk": round(clamp(risk)),
        "quality": round(clamp(quality)), "momentum": round(clamp(momentum)), "confidence": round(clamp(evidence)),
        "timing_risk": pm["overextension_risk"], "pullback_quality": pm["pullback_quality"],
    }


def exit_risk(s, nscore, ind, thesis_damage=0):
    technical = 0
    if ind.get("trend_score_raw", 0) < 0:
        technical += abs(ind["trend_score_raw"]) * 13
    dd = ind.get("drawdown52")
    if dd is not None and dd < -20:
        technical += min(35, abs(dd + 20) * .8)
    value = round(clamp(nscore * .4 + s.get("risk", 0) * .25 + technical * .2 + thesis_damage * .15))
    label = "CRITICAL" if value >= 85 else "EXIT REVIEW" if value >= 70 else "REDUCE RISK" if value >= 50 else "WATCH" if value >= 30 else "NORMAL"
    return {
        "score": value, "label": label,
        "components": {"news": nscore, "market_risk": s.get("risk"), "technical_damage": round(clamp(technical)), "thesis_damage": thesis_damage},
    }


def score_explanations(ind, fund, s, ns):
    def add(bucket, text, effect="positive"): bucket.append({"text": text, "effect": effect})
    opportunity, momentum, quality, entry, risk, confidence = [], [], [], [], [], []
    pm = price_model(ind)
    if ind.get("trend_score_raw", 0) >= 2:
        add(momentum, "Trend is positive across multiple moving-average checks.")
    elif ind.get("trend_score_raw", 0) < 0:
        add(momentum, "Trend structure is below key moving-average checks.", "negative")
    if (ind.get("momentum_3m") or 0) > 8: add(momentum, f"3-month momentum is {ind['momentum_3m']:.1f}%.")
    if (ind.get("momentum_1m") or 0) > 22: add(momentum, "Recent momentum is unusually fast, so the model reduces chase credit.", "negative")
    if (ind.get("relative_volume") or 0) >= 1.5: add(momentum, f"Relative volume is elevated at {ind['relative_volume']:.2f}×.")
    add(entry, f"Timing/overextension risk is {pm['overextension_risk']}/100.", "negative" if pm['overextension_risk'] >= 45 else "neutral")
    add(entry, f"Pullback quality is {pm['pullback_quality']}/100.", "positive" if pm['pullback_quality'] >= 65 else "neutral")
    add(entry, f"Reward to first resistance vs. risk exit is {pm['risk_reward']:.2f}:1.", "positive" if pm['risk_reward'] >= 1.5 else "negative")
    if ind.get("price_vs_sma20_pct") is not None:
        add(entry, f"Price is {ind['price_vs_sma20_pct']:.1f}% from the 20-day average.", "negative" if ind['price_vs_sma20_pct'] > 8 else "neutral")
    if ind.get("rsi14") is not None and ind["rsi14"] >= 72: add(entry, f"RSI {ind['rsi14']:.1f} increases pullback/chase risk.", "negative")
    if ind.get("trend_score_raw", 0) <= -2: add(entry, "Weak trend triggers falling-knife protection; oversold alone is not treated as a buy.", "negative")
    if ind.get("falling_knife_risk",0) >= 40: add(entry, f"Falling-knife risk is {ind['falling_knife_risk']}/100; stabilization must improve before entry credit rises.", "negative")
    if ind.get("gap_risk",0) >= 30: add(entry, f"Recent opening-gap risk is {ind['gap_risk']}/100; the model penalizes chasing post-gap price.", "negative")
    if pm.get("upside_downside_ratio",0) < 1.0: add(entry, f"Upside/downside to first resistance vs support is only {pm['upside_downside_ratio']:.2f}:1.", "negative")
    if fund and fund.get("available"):
        rg = fund.get("revenue_growth_pct"); ig = fund.get("net_income_growth_pct")
        if rg is not None: add(quality, f"Latest comparable annual SEC revenue growth is {rg:.1f}%.", "positive" if rg > 0 else "negative")
        if ig is not None: add(quality, f"Latest comparable annual net-income growth is {ig:.1f}%.", "positive" if ig > 0 else "negative")
        if fund.get("free_cashflow_est") is not None: add(quality, "Estimated SEC-based free cash flow is positive." if fund["free_cashflow_est"] > 0 else "Estimated SEC-based free cash flow is negative.", "positive" if fund["free_cashflow_est"] > 0 else "negative")
        add(confidence, "Primary-source SEC financial facts are available.")
    else: add(confidence, "SEC financial facts were unavailable, reducing evidence depth.", "negative")
    if ns.get("score", 0) >= 30: add(risk, f"Recent headline risk is elevated at {ns['score']}/100.", "negative")
    if (ind.get("volatility20") or 0) > 45: add(risk, f"20-day annualized volatility is high at {ind['volatility20']:.1f}%.", "negative")
    if pm["overextension_risk"] >= 55: add(risk, "Price is extended relative to recent trend/support, increasing reversal risk.", "negative")
    if s["entry"] >= 70 and s["risk"] < 55: add(opportunity, "Entry quality and downside control support the setup.")
    if s["momentum"] >= 70 and s["entry"] < 55: add(opportunity, "Strong momentum is being discounted because entry quality is weak.", "negative")
    if s["timing_risk"] >= 60: add(opportunity, "Opportunity is capped because the price is overextended; the model prefers a pullback.", "negative")
    if not risk: add(risk, "No major deterministic risk trigger is currently dominant.", "neutral")
    if not momentum: add(momentum, "Momentum inputs are mixed or near neutral.", "neutral")
    if not quality: add(quality, "Fundamental evidence is limited; quality remains conservative.", "neutral")
    add(confidence, f"Current evidence coverage produces {s['confidence']}/100 confidence.", "neutral")
    return {"opportunity": opportunity, "momentum": momentum, "quality": quality, "entry": entry, "risk": risk, "confidence": confidence}


def market_regime():
    key = ("market_regime",)
    cached = cache_get(key, 300)
    if cached: return cached
    try:
        sp_rows = yahoo_chart("^GSPC", "1y")["rows"]
        vx_rows = yahoo_chart("^VIX", "6mo")["rows"]
        if history_stale(sp_rows) or history_stale(vx_rows):
            raise ValueError("Market benchmark history is stale")
        sp = indicators(sp_rows)
        vx = indicators(vx_rows)
        vix = vx.get("price") or 20
        trend = sp.get("trend_score_raw", 0)
        m1 = sp.get("momentum_1m") or 0
        if trend <= -2 or vix >= 30:
            label, entry_adj, risk_adj = "RISK-OFF", -12, 12
        elif vix >= 25:
            label, entry_adj, risk_adj = "HIGH VOLATILITY", -8, 9
        elif trend >= 2 and vix < 20 and m1 > 0:
            label, entry_adj, risk_adj = "RISK-ON", 5, -4
        elif trend <= 0 or m1 < -3:
            label, entry_adj, risk_adj = "CAUTIOUS", -5, 5
        else:
            label, entry_adj, risk_adj = "NEUTRAL", 0, 0
        return cache_put(key, {"label":label,"entry_adjust":entry_adj,"risk_adjust":risk_adj,"sp500_trend":trend,
                               "sp500_momentum_1m":round(m1,1),"vix":round(vix,2),"updated_at":now_iso()})
    except Exception as exc:
        return cache_put(key, {"label":"UNKNOWN","entry_adjust":0,"risk_adjust":0,"error":str(exc),"updated_at":now_iso()})


def relative_strength(ticker, ind):
    benchmark = SECTOR_BENCHMARKS.get(clean_ticker(ticker), "^GSPC")
    label_name = dict(SECTORS).get(benchmark, "S&P 500") if benchmark != "^GSPC" else "S&P 500"
    try:
        benchmark_rows = yahoo_chart(benchmark, "1y")["rows"]
        if history_stale(benchmark_rows):
            raise ValueError("Relative-strength benchmark history is stale")
        b = indicators(benchmark_rows)
        d1 = (ind.get("momentum_1m") or 0) - (b.get("momentum_1m") or 0)
        d3 = (ind.get("momentum_3m") or 0) - (b.get("momentum_3m") or 0)
        score = round(clamp(50 + d1 * 2.2 + d3 * .7))
        label = "STRONG" if score >= 68 else "ABOVE AVERAGE" if score >= 57 else "WEAK" if score < 40 else "NEUTRAL"
        return {"benchmark":benchmark,"benchmark_name":label_name,"score":score,"label":label,
                "stock_1m":ind.get("momentum_1m"),"benchmark_1m":b.get("momentum_1m"),"spread_1m":round(d1,1),
                "stock_3m":ind.get("momentum_3m"),"benchmark_3m":b.get("momentum_3m"),"spread_3m":round(d3,1)}
    except Exception as exc:
        return {"benchmark":benchmark,"benchmark_name":label_name,"score":50,"label":"UNKNOWN","error":str(exc)}


def score_with_context(ind, fund, ns, regime, relative, earnings=None):
    s=scores(ind,fund,ns.get("score",0)); entry=s["entry"]+(regime or {}).get("entry_adjust",0); risk=s["risk"]+(regime or {}).get("risk_adjust",0)
    days=(earnings or {}).get("days_to_earnings")
    if days is not None and 0<=days<=2: entry-=14; risk+=14
    elif days is not None and 0<=days<=7: entry-=8; risk+=8
    rel_score=(relative or {}).get("score",50); momentum=s["momentum"]+clamp((rel_score-50)*.18,-7,7); quality,confidence=s["quality"],s["confidence"]
    if (earnings or {}).get("available"): confidence+=4
    entry,risk,momentum=round(clamp(entry)),round(clamp(risk)),round(clamp(momentum)); safety=100-risk
    opp=quality*.31+momentum*.16+entry*.37+safety*.16; pm=price_model(ind)
    if entry<50: opp=min(opp,56)
    if pm["overextension_risk"]>=60: opp=min(opp,54)
    if ind.get("falling_knife_risk",0)>=55: opp=min(opp,50)
    if risk>=65: opp=min(opp,50)
    return {**s,"opportunity":round(clamp(opp)),"entry":entry,"risk":risk,"momentum":momentum,"confidence":round(clamp(confidence)),"market_adjustment":(regime or {}).get("entry_adjust",0),"relative_strength":rel_score}


def decision_layer(ind, fund, ns, s, ex, regime, relative, earnings=None):
    pm = price_model(ind)
    company = s.get("quality", 50)
    entry = s.get("entry", 50)
    company_label = "STRONG" if company >= 75 else "GOOD" if company >= 62 else "MIXED" if company >= 45 else "WEAK"
    entry_label = "ATTRACTIVE" if entry >= 72 and s.get("risk",100) < 55 and pm["overextension_risk"] < 45 else "WAIT / PULLBACK" if entry >= 45 else "POOR / AVOID CHASE"
    why_not = []
    if pm["overextension_risk"] >= 45: why_not.append(f"Timing risk is {pm['overextension_risk']}/100; price is extended relative to recent structure.")
    if pm["risk_reward"] < 1.25: why_not.append(f"Reward/risk to first resistance is only {pm['risk_reward']:.2f}:1.")
    if (ind.get("rsi14") or 0) >= 72: why_not.append(f"RSI is {ind['rsi14']:.1f}, increasing pullback risk.")
    if (ind.get("distance_from_support_pct") or 0) > 12: why_not.append(f"Price is {ind['distance_from_support_pct']:.1f}% above nearest 20-day support.")
    if s.get("risk",0) >= 60: why_not.append(f"Overall risk score is elevated at {s['risk']}/100.")
    if ns.get("score",0) >= 30: why_not.append(f"Recent event/news risk is {ns['score']}/100.")
    if (regime or {}).get("label") in ("RISK-OFF","HIGH VOLATILITY"): why_not.append(f"Market regime is {regime['label']}, so the entry threshold is stricter.")
    if ind.get("gap_risk",0)>=30: why_not.append(f"Recent gap risk is {ind['gap_risk']}/100; post-gap chasing is penalized.")
    if ind.get("falling_knife_risk",0)>=40: why_not.append(f"Falling-knife risk is {ind['falling_knife_risk']}/100; price needs stabilization before entry improves.")
    days=(earnings or {}).get("days_to_earnings")
    if days is not None and 0<=days<=7: why_not.append(f"Earnings are about {days} day(s) away, increasing event-gap risk.")
    if not why_not: why_not.append("No dominant deterministic reason to avoid the entry, but price outcomes remain uncertain.")
    buy_hi = pm.get("buy_zone", [None,None])[1]
    upgrade = []
    if buy_hi and ind["price"] > buy_hi: upgrade.append(f"Price moves into or below the preferred entry area near {buy_hi:.2f} without breaking support.")
    if (ind.get("rsi14") or 0) > 68: upgrade.append("RSI cools below roughly 68 while the trend remains intact.")
    if pm["risk_reward"] < 1.5: upgrade.append("Reward/risk to first resistance improves to at least about 1.5:1.")
    if ns.get("score",0) >= 30: upgrade.append("Negative event risk falls below 30/100 or is contradicted by stronger primary evidence.")
    if (regime or {}).get("label") in ("RISK-OFF","HIGH VOLATILITY","CAUTIOUS"): upgrade.append("Broad market regime improves toward NEUTRAL or RISK-ON.")
    if ind.get("falling_knife_risk",0)>=40: upgrade.append("Falling-knife risk drops below 35 as price stops making lower lows and stabilizes.")
    if ind.get("gap_risk",0)>=30: upgrade.append("Post-gap price consolidates and gap risk cools instead of extending higher immediately.")
    downgrade = [f"Price closes below the model risk-exit level near {pm['risk_exit']:.2f}.", "Verified material news pushes event/news risk above 50/100."]
    if fund and fund.get("available"):
        downgrade.append("Comparable SEC revenue or net-income growth turns materially negative.")
    downgrade.append("Trend structure breaks below key moving averages with expanding downside volume.")
    return {"company_quality":company,"company_label":company_label,"entry_quality":entry,"entry_label":entry_label,
            "why_not_buy":why_not[:6],"upgrade_conditions":upgrade[:6],"downgrade_conditions":downgrade[:6],
            "market_regime":regime,"relative_strength":relative,"earnings":earnings or {}}


def parse_thesis_tags(value):
    if isinstance(value, list): vals=value
    else:
        try: vals=json.loads(value or "[]")
        except Exception: vals=[]
    return [x for x in vals if x in THESIS_TAGS]


def evaluate_thesis(tags, pkg):
    tags = parse_thesis_tags(tags)
    if not tags:
        return {"tracked":False,"score":None,"damage":0,"valid":0,"invalid":0,"unknown":0,"items":[]}
    ind, fund, s, ns = pkg.get("indicators",{}), pkg.get("fundamentals",{}), pkg.get("scores",{}), pkg.get("news_risk",{})
    items=[]
    for tag in tags:
        valid=None; detail="Evidence unavailable"
        if tag=="revenue_growth":
            v=fund.get("revenue_growth_pct"); valid=(v is not None and v>0) if v is not None else None; detail=f"SEC revenue growth {v:.1f}%" if v is not None else detail
        elif tag=="earnings_growth":
            v=fund.get("net_income_growth_pct"); valid=(v is not None and v>0) if v is not None else None; detail=f"SEC net-income growth {v:.1f}%" if v is not None else detail
        elif tag=="positive_fcf":
            v=fund.get("free_cashflow_est"); valid=(v is not None and v>0) if v is not None else None; detail="Estimated FCF positive" if valid else "Estimated FCF not positive" if valid is False else detail
        elif tag=="uptrend": valid=ind.get("trend_score_raw",0)>=1; detail=f"Trend score {ind.get('trend_score_raw',0)}"
        elif tag=="attractive_entry": valid=s.get("entry",0)>=60; detail=f"Entry score {s.get('entry',0)}/100"
        elif tag=="low_risk": valid=s.get("risk",100)<50; detail=f"Risk score {s.get('risk',0)}/100"
        elif tag=="momentum": valid=s.get("momentum",0)>=60; detail=f"Momentum {s.get('momentum',0)}/100"
        elif tag=="catalyst":
            bullish=[e for e in ns.get("events",[]) if e.get("sentiment")=="BULLISH" and e.get("impact") in ("MEDIUM","HIGH")]
            confirmed=[e for e in bullish if e.get("confirmation")=="PRIMARY-SOURCE CONFIRMED"]
            valid=True if confirmed else None if bullish or ns.get("available") is False else False
            detail=(f"{len(confirmed)} primary-source confirmed bullish event(s)" if confirmed else
                    "Bullish reports found, but independent primary confirmation is unavailable" if bullish else
                    "News evidence unavailable" if ns.get("available") is False else
                    "No meaningful bullish event currently detected")
        items.append({"tag":tag,"label":THESIS_TAGS[tag],"valid":valid,"detail":detail})
    known=[x for x in items if x["valid"] is not None]; good=len([x for x in known if x["valid"]]); bad=len(known)-good
    score=round(good/len(known)*100) if known else None
    return {"tracked":True,"score":score,"damage":100-score if score is not None else 0,"valid":good,"invalid":bad,"unknown":len(items)-len(known),"items":items}


def position_strategy(position, pkg, thesis_health):
    price=pkg["quote"]["price"]; avg=float(position.get("avg_price") or 0); ind=pkg["indicators"]; pm=pkg["price_model"]; earnings=pkg.get("earnings") or {}
    gain=(price/avg-1)*100 if avg else 0; atr=ind.get("atr14") or price*.03; sma20=ind.get("sma20") or price
    base_model=pm.get("risk_exit") or 0; atr_trail=price-2*atr; sma_trail=sma20-.45*atr
    candidates=[base_model,atr_trail,sma_trail]
    if gain>=10: candidates.append(avg*1.01)
    if gain>=20: candidates.append(avg*1.08)
    if gain>=35: candidates.append(avg*1.16)
    trailing=max(x for x in candidates if x is not None); trailing=min(trailing,price-.25*atr)
    methods=[]
    if abs(trailing-atr_trail)<.01: methods.append("ATR trail")
    if abs(trailing-sma_trail)<.01: methods.append("SMA20 trail")
    if abs(trailing-base_model)<.01: methods.append("model risk exit")
    if trailing>avg and gain>=10: methods.append("profit floor")
    thesis_damage=(thesis_health or {}).get("damage",0); ex=pkg.get("exit_risk",{}).get("score",0); partial=0; reasons=[]
    days=earnings.get("days_to_earnings")
    if ex>=70 or thesis_damage>=70:
        action="EXIT REVIEW"; reasons.append("Exit risk or thesis damage is severe.")
    elif price <= (pm.get("risk_exit") or 0):
        action="RISK EXIT REVIEW"; reasons.append("Price is at/below the model risk-exit level.")
    elif gain>=25 and (ind.get("gap_risk",0)>=45 or pm.get("overextension_risk",0)>=60):
        action="TAKE PARTIAL PROFIT / TRAIL"; partial=25; reasons.append("A strong winner is becoming extended/gap-sensitive; protect part of the gain.")
    elif gain>=35 and price >= (pm.get("take_profit_zone") or [10**18])[0]*.98:
        action="TAKE PARTIAL PROFIT / TRAIL"; partial=33; reasons.append("Large unrealized gain is near the first take-profit zone.")
    elif gain>=20:
        action="HOLD + PROTECT PROFIT"; partial=25 if price >= (pm.get("take_profit_zone") or [10**18])[0]*.95 else 0; reasons.append("Position has a meaningful gain; trailing protection is more important than the original stop.")
    elif days is not None and 0<=days<=2 and gain>5:
        action="EARNINGS RISK REVIEW"; reasons.append(f"Earnings are about {days} day(s) away; consider whether to carry the event gap risk.")
    elif pkg.get("scores",{}).get("risk",0)>=60 or ind.get("falling_knife_risk",0)>=55:
        action="TIGHTEN RISK / REVIEW"; reasons.append("Current market/technical downside risk is elevated.")
    else:
        action="HOLD / MONITOR"; reasons.append("No position-specific exit trigger currently dominates.")
    protected=(trailing/avg-1)*100 if avg and trailing>avg else 0
    return {"action":action,"gain_percent":round(gain,1),"trailing_exit":round(max(.01,trailing),2),"trailing_method":" + ".join(methods) or "blended model",
            "partial_profit_percent":partial,"protected_gain_percent":round(protected,1),"earnings_risk":earnings,"reasons":reasons,"automatic_trading":False}

def research_history(ticker, limit=10):
    ticker=clean_ticker(ticker)
    with connect() as con:
        rows=con.execute("SELECT created_at,status,price,opportunity,entry,quality,risk,confidence,timing_risk,payload_json FROM research_history WHERE ticker=? ORDER BY id DESC LIMIT ?",(ticker,int(limit))).fetchall()
    out=[]
    for r in rows:
        d=dict(r)
        try: d.update(json.loads(d.pop("payload_json") or "{}"))
        except Exception: d.pop("payload_json",None)
        out.append(d)
    return out


def save_research_snapshot(pkg):
    core=pkg.get("core_research",{}); s=pkg.get("scores",{}); pm=pkg.get("price_model",{}); ticker=pkg["ticker"]
    last=research_history(ticker,1)
    current={"status":core.get("status","UNKNOWN"),"price":pkg.get("quote",{}).get("price"),"opportunity":s.get("opportunity"),"entry":s.get("entry"),"quality":s.get("quality"),"risk":s.get("risk"),"confidence":s.get("confidence"),"timing_risk":pm.get("overextension_risk")}
    should=True
    if last:
        prev=last[0]; age=0
        try: age=time.time()-datetime.fromisoformat(prev["created_at"]).timestamp()
        except Exception: pass
        changed=prev.get("status")!=current["status"] or any(abs((prev.get(k) or 0)-(current.get(k) or 0))>=5 for k in ("opportunity","entry","quality","risk","timing_risk"))
        should=changed or age>=900
    if not should: return
    payload={"market_regime":(pkg.get("market_regime") or {}).get("label"),"relative_strength":(pkg.get("relative_strength") or {}).get("score"),
             "gap_risk":(pkg.get("indicators") or {}).get("gap_risk"),"falling_knife_risk":(pkg.get("indicators") or {}).get("falling_knife_risk"),
             "earnings_risk":(pkg.get("earnings") or {}).get("risk")}
    try:
        with DB_LOCK, connect() as con:
            con.execute("INSERT INTO research_history(ticker,created_at,status,price,opportunity,entry,quality,risk,confidence,timing_risk,payload_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                        (ticker,now_iso(),current["status"],current["price"],current["opportunity"],current["entry"],current["quality"],current["risk"],current["confidence"],current["timing_risk"],json.dumps(payload)))
            con.execute("DELETE FROM research_history WHERE ticker=? AND id NOT IN (SELECT id FROM research_history WHERE ticker=? ORDER BY id DESC LIMIT 60)",(ticker,ticker)); con.commit()
    except Exception: pass

def basic_stock(ticker, range_="1y"):
    chart = yahoo_chart(ticker, range_)
    ind = indicators(chart["rows"])
    name = chart["meta"].get("longName") or chart["meta"].get("shortName") or chart["meta"].get("displayName") or clean_ticker(ticker)
    pm = price_model(ind)
    s = scores(ind)
    prev = chart["rows"][-2]["close"] if len(chart["rows"]) > 1 else ind["price"]
    change = (ind["price"] / prev - 1) * 100 if prev else None
    last = chart["rows"][-1]
    return {
        "ticker": clean_ticker(ticker),
        "quote": {
            "ticker": clean_ticker(ticker), "name": name, "price": ind["price"], "change_percent": change,
            "currency": chart["meta"].get("currency") or "USD", "exchange": chart["meta"].get("exchangeName"),
            "day_low": last.get("low"), "day_high": last.get("high"), "volume": last.get("volume"),
            "fifty_two_low": ind.get("low52"), "fifty_two_high": ind.get("high52"),
            "updated_at": last.get("time"), "retrieved_at": now_iso(),
            "stale": history_stale(chart["rows"]),
            "data_note": "Price as of the last observed chart bar; delayed or stale free market data, not a live quote.",
        },
        "indicators": ind, "price_model": pm, "scores": s, "exit_risk": exit_risk(s, 0, ind),
        "history": chart["rows"][-260:],
    }


def core_summary(ind, fund, ns, s, ex, regime=None, relative=None, earnings=None):
    bull,bear,contra=[],[],[]; pm=price_model(ind); days=(earnings or {}).get("days_to_earnings")
    if ind.get("trend_score_raw",0)>=2: bull.append("Price trend is constructive across multiple moving-average checks.")
    if (relative or {}).get("score",50)>=60: bull.append(f"Relative strength is {(relative or {}).get('label','strong')} versus {(relative or {}).get('benchmark_name','market benchmark')}.")
    if fund and fund.get("revenue_growth_pct") is not None and fund["revenue_growth_pct"]>5: bull.append("Latest SEC annual revenue comparison shows growth.")
    if fund and fund.get("free_cashflow_est") is not None and fund["free_cashflow_est"]>0: bull.append("Estimated free cash flow from SEC facts is positive.")
    if ind.get("trend_score_raw",0)<0: bear.append("Price trend is technically weak; oversold conditions alone do not override this.")
    if ind.get("falling_knife_risk",0)>=40: bear.append(f"Falling-knife risk is {ind['falling_knife_risk']}/100.")
    if ind.get("gap_risk",0)>=30: bear.append(f"Recent price-gap risk is {ind['gap_risk']}/100.")
    if (ind.get("volatility20") or 0)>45: bear.append("Recent annualized volatility is elevated.")
    if ns.get("score",0)>=30: bear.append("Recent event/news risk requires source review.")
    if pm["overextension_risk"]>=55: bear.append(f"Timing risk is {pm['overextension_risk']}/100; price may be vulnerable to a pullback even though momentum is positive.")
    if (regime or {}).get("label") in ("RISK-OFF","HIGH VOLATILITY"): bear.append(f"Broad-market regime is {regime['label']}, increasing downside sensitivity.")
    if days is not None and 0<=days<=7: bear.append(f"Earnings are approximately {days} day(s) away, creating event-gap risk.")
    if s["momentum"]>=70 and s["entry"]<55: contra.append("Momentum is strong while entry quality is weak; the model explicitly avoids chasing this setup.")
    if s["quality"]>=70 and s["entry"]<50: contra.append("Company quality is strong, but the current price is not a strong entry.")
    if ex["score"]>=70: status="EXIT REVIEW"
    elif s["risk"]>=65: status="HIGH RISK / AVOID"
    elif ind.get("falling_knife_risk",0)>=60: status="WAIT FOR STABILIZATION"
    elif s["opportunity"]>=68 and s["entry"]>=76 and s["quality"]>=60 and s["risk"]<45 and pm["overextension_risk"]<40 and pm.get("risk_reward",0)>=1.5 and s["confidence"]>=65 and not(days is not None and 0<=days<=2): status="BUY ZONE"
    elif s["entry"]>=70 and s["confidence"]<65: status="TECHNICAL SETUP / VERIFY"
    elif s["opportunity"]>=58 and (s["entry"]<65 or pm["overextension_risk"]>=40): status="WAIT FOR PULLBACK"
    elif s["entry"]<45: status="WAIT"
    else: status="HOLD / RESEARCH"
    return {"status":status,"summary":f"Company quality {s['quality']}/100; current entry {s['entry']}/100; downside-first R/R {pm['risk_reward']}:1; timing risk {pm['overextension_risk']}/100; total risk {s['risk']}/100. BUY requires quality, entry, downside control, evidence and event-risk checks together.",
        "bull_case":bull or ["No strong deterministic bull condition was confirmed."],"bear_case":bear or ["No major deterministic bear condition was confirmed."],"contradicting_evidence":contra or ["No major model contradiction detected."],"confidence":s["confidence"]}


def stored_thesis(ticker):
    with connect() as con:
        r = con.execute("SELECT thesis,thesis_json FROM positions WHERE ticker=? ORDER BY id DESC LIMIT 1", (clean_ticker(ticker),)).fetchone()
    if not r: return {"text":"","tags":[]}
    return {"text":r["thesis"] or "","tags":parse_thesis_tags(r["thesis_json"] if "thesis_json" in r.keys() else "[]")}


def research_package(ticker, use_ai=False):
    ticker = clean_ticker(ticker)
    key = ("research_core_v05", ticker)
    cached = cache_get(key, 300)
    if cached:
        history = research_history(ticker, 10)
        return {**cached, "research_history": history, "research_change": research_change_summary(history)}
    base = basic_stock(ticker)
    name = base["quote"]["name"] or ticker
    results = {}
    def grab(label, fn, fallback):
        try: results[label] = fn()
        except Exception as exc: results[label] = fallback(exc)
    with ThreadPoolExecutor(max_workers=6) as pool:
        futs = [
            pool.submit(grab, "fund", lambda: sec_fundamentals(ticker), lambda e: {"available": False, "error": str(e)}),
            pool.submit(grab, "filings", lambda: sec_filings(ticker), lambda e: [{"form": "SEC_UNAVAILABLE", "description": str(e), "reliability": 0}]),
            pool.submit(grab, "news", lambda: fast_news(name if name != ticker else ticker, 24, True), lambda e: []),
            pool.submit(grab, "regime", market_regime, lambda e: {"label":"UNKNOWN","entry_adjust":0,"risk_adjust":0,"error":str(e)}),
            pool.submit(grab, "relative", lambda: relative_strength(ticker, base["indicators"]), lambda e: {"score":50,"label":"UNKNOWN","error":str(e)}),
            pool.submit(grab, "earnings", lambda: yahoo_earnings_calendar(ticker), lambda e: {"available":False,"risk":"UNKNOWN","error":str(e)}),
        ]
        for f in futs: f.result()
    fund = results.get("fund") or {"available": False}; filings = results.get("filings") or []; raw_news = results.get("news") or []
    regime=results.get("regime") or {}; relative=results.get("relative") or {}; earnings=results.get("earnings") or {}
    ns = news_score(raw_news); news = ns.pop("items")
    s = score_with_context(base["indicators"], fund, ns, regime, relative, earnings)
    thesis = stored_thesis(ticker)
    # initial thesis health needs package-shaped inputs
    temp={**base,"fundamentals":fund,"news_risk":ns,"scores":s}
    th=evaluate_thesis(thesis.get("tags",[]),temp)
    ex = exit_risk(s, ns["score"], base["indicators"], th.get("damage",0))
    core=core_summary(base["indicators"], fund, ns, s, ex, regime, relative, earnings)
    decision=decision_layer(base["indicators"],fund,ns,s,ex,regime,relative,earnings)
    if base["quote"].get("stale"):
        core["status"] = "DATA STALE"
        core["summary"] = "Observed market price is stale. Entry and exit signals are historical and unavailable for current decisions."
        decision["entry_label"] = "UNAVAILABLE / STALE PRICE"
        decision["why_not_buy"].insert(0, "Latest price data is stale; wait for refreshed market observations.")
    base.update({
        "fundamentals": fund, "filings": filings, "news": news, "news_risk": ns, "scores": s, "exit_risk": ex,
        "price_model": price_model(base["indicators"]), "market_regime":regime,"relative_strength":relative,"earnings":earnings,
        "core_research":core,"decision_layer":decision,
        "score_explanations": score_explanations(base["indicators"], fund, s, ns), "stored_thesis": thesis.get("text",""),
        "stored_thesis_tags": thesis.get("tags",[]), "thesis_health":th,
        "source_summary": {"sec_available": bool(fund.get("available")), "primary_filings": len([x for x in filings if x.get("source") == "sec"]),
            "news_sources": len(set((x.get("publisher") or "") for x in news if x.get("publisher"))),
            "high_reliability_news": len([x for x in news if x.get("reliability", 0) >= 85]),
            "confirmed_news_events":ns.get("confirmed_event_count",0),"news_events":ns.get("event_count",0)},
        "ai_research": {"enabled": get_setting("ollama_enabled", "false") == "true",
            "status": "READY ON DEMAND" if get_setting("ollama_enabled", "false") == "true" else "CORE RESEARCH",
            "summary": "Ollama is optional and never blocks Core Research." if get_setting("ollama_enabled", "false") == "true" else "Ollama is disabled. Core Research remains fully active.",
            "confidence": s["confidence"]},
        "freshness": {"market": base["quote"].get("updated_at"), "research": now_iso(), "news": max((x.get("published") for x in news if x.get("published")), default=None), "sec_fiscal_end": fund.get("latest_fiscal_end"), "latest_filing": next((x.get("date") for x in filings if x.get("date")), None)},
        "performance": {"core_cached_seconds": 300, "news_provider": "Yahoo Finance search + GDELT fallback", "staged": True},
    })
    save_research_snapshot(base)
    base["research_history"] = research_history(ticker, 10)
    base["research_change"] = research_change_summary(base["research_history"])
    return cache_put(key, base)

def ai_research_package(ticker):
    pkg = research_package(ticker, False)
    if get_setting("ollama_enabled", "false") != "true":
        return {"enabled": False, "status": "OLLAMA DISABLED", "summary": "Enable Ollama in Settings to use AI interpretation.", "confidence": 0}
    return ollama_research(pkg)


def ollama_models():
    try:
        d = http_json(get_setting("ollama_url", "http://127.0.0.1:11434").rstrip("/") + "/api/tags", timeout=2)
        return [x.get("name") for x in d.get("models") or [] if x.get("name")]
    except Exception:
        return []


def ollama_research(pkg):
    models = ollama_models()
    if not models:
        return {"enabled": True, "status": "OLLAMA UNAVAILABLE", "summary": "Ollama is enabled, but no reachable local model was found.", "confidence": 0}
    configured = get_setting("ollama_model", "auto")
    model = models[0] if configured == "auto" or configured not in models else configured
    compact = {k: pkg.get(k) for k in ("ticker","quote","indicators","price_model","scores","exit_risk","fundamentals","news_risk","filings","stored_thesis")}
    compact["news"] = pkg.get("news", [])[:16]
    body = {
        "model": model, "stream": False, "format": "json",
        "messages": [
            {"role": "system", "content": "Evidence-bound equity research. Use only supplied evidence. Never invent figures, filings, headlines, prices, dates, or sources. Explicitly discuss uncertainty and evidence against the thesis. Return JSON."},
            {"role": "user", "content": "Analyze the evidence. Return status, summary, bull_case, bear_case, contradicting_evidence, critical_risks, thesis_assessment, confidence. Do not create new target prices. Evidence: " + json.dumps(compact, default=str)},
        ],
        "options": {"temperature": .15},
    }
    try:
        d = http_json(get_setting("ollama_url", "http://127.0.0.1:11434").rstrip("/") + "/api/chat", method="POST", data=body, timeout=90)
        out = json.loads(((d.get("message") or {}).get("content") or "{}").strip())
        out["enabled"], out["model"] = True, model
        return out
    except Exception as exc:
        return {"enabled": True, "status": "OLLAMA ERROR", "summary": str(exc), "confidence": 0}


def hunter_scan(symbols=None, limit=None):
    if symbols is None:
        custom = [x.strip().upper() for x in get_setting("hunter_universe", "").split(",") if x.strip()]
        symbols = custom or DEFAULT_UNIVERSE
    maxn = max(5, min(int(get_setting("hunter_max_symbols", "36") or 36), 100))
    if not isinstance(symbols, (list, tuple)) or any(not isinstance(x, str) for x in symbols):
        raise ValueError("Scanner symbols must be a list of ticker strings")
    normalized = [x.strip().upper() for x in symbols if x.strip()]
    symbols = list(dict.fromkeys(normalized))[:maxn]
    out, errors = [], []
    regime = market_regime()
    def one(t):
        t = clean_ticker(t)
        b = basic_stock(t, "6mo"); ind = b["indicators"]; pm = b["price_model"]; sc = dict(b["scores"])
        if b["quote"].get("stale"):
            raise ValueError("Market history is stale; scan candidate unavailable")
        sc["entry"] = round(clamp(sc["entry"] + regime.get("entry_adjust",0)))
        sc["risk"] = round(clamp(sc["risk"] + regime.get("risk_adjust",0)))
        safety=100-sc["risk"]
        sc["opportunity"]=round(clamp(sc["quality"]*.28+sc["momentum"]*.18+sc["entry"]*.38+safety*.16))
        knife = ind.get("falling_knife_risk",100)
        stabilization = ind.get("stabilization_score",0)
        gap = ind.get("gap_risk",100)
        if sc["entry"]<45 or pm.get("overextension_risk",0)>=65: sc["opportunity"]=min(sc["opportunity"],58)
        if knife>=55: sc["opportunity"]=min(sc["opportunity"],50)
        if knife>=35 or gap>=40 or (ind.get("trend_score_raw",0)<0 and stabilization<45):
            sc["opportunity"]=min(sc["opportunity"],55)
        strong = (sc["opportunity"] >= 72 and sc["entry"] >= 68 and sc["risk"] < 48
                  and pm.get("overextension_risk",100) < 45 and knife < 35 and gap < 30
                  and stabilization >= 45 and pm.get("risk_reward",0) >= 1.25)
        status = "STRONG SETUP" if strong else "HIGH RISK" if sc["risk"] >= 65 or knife>=55 else "WAIT FOR PULLBACK" if sc["opportunity"] >= 55 and (sc["entry"] < 60 or pm.get("overextension_risk",0) >= 45 or knife >= 35 or stabilization < 45) else "RESEARCH" if sc["opportunity"] >= 56 else "WATCH"
        return {"ticker":t,"name":b["quote"]["name"],"price":b["quote"]["price"],"change_percent":b["quote"]["change_percent"],
            "scores":sc,"status":status,"sector":sector_info(t),"indicators":{k:ind.get(k) for k in ("rsi14","relative_volume","momentum_1m","momentum_3m","volatility20","drawdown52","avg_volume20","gap_risk","falling_knife_risk")},
            "why":("Healthy entry + controlled risk" if status=="STRONG SETUP" else "Extended; wait for better price" if status=="WAIT FOR PULLBACK" else "Risk elevated" if status=="HIGH RISK" else "Needs deeper evidence"),
            "price_model":pm,"setup_rank":round(sc["opportunity"]*.52+sc["entry"]*.33+(100-sc["risk"])*.15,1)}
    with ThreadPoolExecutor(max_workers=8) as pool:
        futs = {pool.submit(one, t): t for t in symbols}
        for f in as_completed(futs):
            try: out.append(f.result())
            except Exception as exc: errors.append({"ticker": futs[f], "error": str(exc)[:140]})
    out.sort(key=lambda x: (x.get("setup_rank", 0), x["scores"]["confidence"]), reverse=True)
    finalists=out[:5]
    def warm(row):
        try:
            t=row["ticker"]; sec_fundamentals(t); sec_filings(t); fast_news(row.get("name") or t,12,True)
        except Exception: pass
    threading.Thread(target=lambda:[warm(x) for x in finalists],daemon=True).start()
    results = out if limit is None else out[:max(1,min(int(limit),maxn))]
    return {"results":results,"scanned":len(symbols),"successful":len(out),"errors":errors,
        "regime":regime,"note":"Fast quantitative first pass with market-regime adjustment. Run Deep Research on finalists before treating a candidate as actionable.","updated_at":now_iso()}


def quick_quote(symbol, name):
    b = basic_stock(symbol, "6mo")
    if b["quote"].get("stale"):
        raise ValueError("Market benchmark price is stale")
    return {"ticker": symbol, "name": name, "price": b["quote"]["price"], "change_percent": b["quote"]["change_percent"], "momentum_1m": b["indicators"].get("momentum_1m"), "observed_at": b["quote"].get("updated_at"), "retrieved_at": b["quote"].get("retrieved_at")}


def market_dashboard(force=False):
    key = ("dashboard",)
    if force:
        symbols = {s for s, _ in INDEXES + SECTORS}
        with CACHE_LOCK:
            for entry in list(CACHE):
                if entry in (key, ("market_regime",)) or (entry[0] == "chart" and entry[1] in symbols):
                    CACHE.pop(entry, None)
    c = cache_get(key, 180)
    if c:
        return c
    indexes, sectors, errors = [], [], []
    tasks = [("index", s, n) for s, n in INDEXES] + [("sector", s, n) for s, n in SECTORS]
    with ThreadPoolExecutor(max_workers=8) as pool:
        futs = {pool.submit(quick_quote, s, n): (kind, s, n) for kind, s, n in tasks}
        for f in as_completed(futs):
            kind, s, n = futs[f]
            try:
                row = f.result()
                (indexes if kind == "index" else sectors).append(row)
            except Exception as exc:
                errors.append({"ticker": s, "error": str(exc)[:120]})
    order_i = {s:i for i,(s,_) in enumerate(INDEXES)}
    indexes.sort(key=lambda x: order_i.get(x["ticker"], 99))
    sectors.sort(key=lambda x: x.get("change_percent") if x.get("change_percent") is not None else -999, reverse=True)
    try:
        broad_news = [classify_news_item(x) for x in fast_news("stock market", 16, False)]
    except Exception as exc:
        broad_news = []
        errors.append({"ticker": "NEWS", "error": str(exc)[:120]})
    result = {"indexes": indexes, "sectors": sectors, "news": broad_news[:12], "regime": market_regime(), "errors": errors, "updated_at": now_iso()}
    return cache_put(key, result)


def news_search(query_text):
    q = (query_text or "").strip()
    if not q:
        raise ValueError("Enter a ticker, company, or market topic")
    key = ("news_search", q.lower())
    cached = cache_get(key, 600)
    if cached:
        return cached
    raw = fast_news(q, 24, False)
    ns = news_score(raw); items = ns.pop("items")
    result = {"query": q, "resolved_query": q, "risk": ns, "items": items, "updated_at": now_iso(), "provider": "Fast Yahoo Finance news with GDELT fallback"}
    return cache_put(key, result)


def list_positions():
    with connect() as con:
        return [dict(x) for x in con.execute("SELECT * FROM positions ORDER BY id DESC").fetchall()]


def portfolio_risk():
    positions = list_positions()
    quotes, out, grouped, sector_values, warnings = {}, [], {}, {}, []
    tickers = list(dict.fromkeys(p["ticker"] for p in positions))
    if tickers:
        with ThreadPoolExecutor(max_workers=min(6, len(tickers))) as pool:
            futures = {pool.submit(research_package, ticker, False): ticker for ticker in tickers}
            for future in as_completed(futures):
                ticker = futures[future]
                try:
                    quotes[ticker] = (future.result(), None)
                except Exception as exc:
                    quotes[ticker] = (None, str(exc))

    priced_value = priced_cost = total_cost = 0.0
    unpriced_lots = 0
    for p in positions:
        ticker = p["ticker"]
        cost = p["shares"] * p["avg_price"]
        total_cost += cost
        group = grouped.setdefault(ticker, {"ticker": ticker, "shares": 0.0, "cost": 0.0, "value": 0.0, "lots": 0, "unpriced_lots": 0})
        group["shares"] += p["shares"]
        group["cost"] += cost
        group["lots"] += 1
        research, fetch_error = quotes[ticker]
        try:
            if fetch_error:
                raise ValueError(fetch_error)
            if research["quote"].get("stale"):
                raise ValueError("Market quote is stale; valuation and exit assessment unavailable")
            price = positive_number(research["quote"]["price"], "Market price")
            value = price * p["shares"]
            if not math.isfinite(value):
                raise ValueError("Market value exceeds numeric range")
            tags = parse_thesis_tags(p.get("thesis_json", "[]"))
            thesis = evaluate_thesis(tags, research)
            ex = exit_risk(research["scores"], research["news_risk"].get("score", 0), research["indicators"], thesis.get("damage", 0))
            strategy = position_strategy(p, {**research, "exit_risk": ex}, thesis)
            sector = sector_info(ticker)["sector"]
            sector_values[sector] = sector_values.get(sector, 0.0) + value
            priced_cost += cost
            priced_value += value
            group["value"] += value
            out.append({**p, "thesis_tags": tags, "price": price, "value": value,
                "pnl": value - cost, "pnl_percent": (price / p["avg_price"] - 1) * 100,
                "exit_risk": ex, "price_model": research["price_model"],
                "news_risk": research["news_risk"], "top_risk_news": research["news_risk"].get("reasons", [])[:4],
                "scores": research["scores"], "thesis_health": thesis, "position_strategy": strategy,
                "earnings": research.get("earnings") or {}, "sector": sector})
        except Exception as exc:
            unpriced_lots += 1
            group["unpriced_lots"] += 1
            out.append({**p, "error": str(exc), "price": None, "value": None, "pnl": None, "pnl_percent": None})

    complete = unpriced_lots == 0
    total = priced_value if complete else None
    grouped_rows = []
    for group in grouped.values():
        group["avg_cost"] = group["cost"] / group["shares"] if group["shares"] else None
        if group["unpriced_lots"]:
            group["value"] = group["pnl"] = group["pnl_percent"] = None
        else:
            group["pnl"] = group["value"] - group["cost"]
            group["pnl_percent"] = (group["value"] / group["cost"] - 1) * 100 if group["cost"] else None
        if complete and total and group["value"] / total * 100 >= 30:
            pct = group["value"] / total * 100
            warnings.append({"type": "POSITION CONCENTRATION", "ticker": group["ticker"], "percent": round(pct, 1), "severity": "HIGH" if pct >= 50 else "WATCH"})
        grouped_rows.append(group)
    if complete and total:
        for item in out:
            item["weight_percent"] = item["value"] / total * 100
        for sector, value in sector_values.items():
            pct = value / total * 100
            if pct >= 45:
                warnings.append({"type": "SECTOR CONCENTRATION", "ticker": sector, "percent": round(pct, 1), "severity": "HIGH" if pct >= 65 else "WATCH"})
    out.sort(key=lambda item: (item.get("exit_risk") or {}).get("score", -1), reverse=True)
    return {
        "positions": out, "grouped": sorted(grouped_rows, key=lambda g: g["value"] if g["value"] is not None else -1, reverse=True),
        "sector_exposure": [{"sector": k, "value": v, "percent": round(v / total * 100, 1)} for k, v in sorted(sector_values.items(), key=lambda x: x[1], reverse=True)] if complete and total else [],
        "total_value": total, "total_cost": total_cost, "total_pnl": total - total_cost if complete else None,
        "total_pnl_percent": (total / total_cost - 1) * 100 if complete and total_cost else (0 if complete else None),
        "priced_market_value": priced_value, "priced_cost": priced_cost, "unpriced_lots": unpriced_lots,
        "valuation_complete": complete, "warnings": warnings, "updated_at": now_iso(),
    }

def alerts_payload():
    risk = portfolio_risk()
    alerts = []
    for p in risk["positions"]:
        if p.get("error"):
            alerts.append({"severity":"ERROR","ticker":p["ticker"],"title":"Risk scan unavailable","body":p["error"]})
            continue
        score = p.get("exit_risk", {}).get("score", 0)
        if score >= 30:
            headline = (p.get("top_risk_news") or [{}])[0].get("title")
            action = (p.get("position_strategy") or {}).get("action")
            alerts.append({
                "severity": p["exit_risk"]["label"], "ticker": p["ticker"],
                "title": f"{action or p['exit_risk']['label']} · Exit risk {score}/100",
                "body": headline or ((p.get("position_strategy") or {}).get("reasons") or ["Technical/market risk increased; review the position evidence."])[0],
                "risk_score": score,
            })
    alerts.sort(key=lambda x: x.get("risk_score", 0), reverse=True)
    return {"alerts": alerts, "count": len(alerts), "updated_at": now_iso()}


def settings_payload():
    return {
        "ollama_enabled": get_setting("ollama_enabled", "false") == "true",
        "ollama_url": get_setting("ollama_url", "http://127.0.0.1:11434"),
        "ollama_model": get_setting("ollama_model", "auto"),
        "sec_user_agent": get_setting("sec_user_agent", "StonkResearch/0.5 contact@example.com"),
        "hunter_max_symbols": int(get_setting("hunter_max_symbols", "36") or 36),
        "hunter_universe": get_setting("hunter_universe", ""),
    }


def touch_heartbeat():
    global LAST_HEARTBEAT
    with HEARTBEAT_LOCK:
        LAST_HEARTBEAT = time.time()


def heartbeat_age():
    with HEARTBEAT_LOCK:
        return time.time() - LAST_HEARTBEAT


def send_json(h, obj, code=200):
    raw = json.dumps(obj, ensure_ascii=False, default=str).encode()
    h.send_response(code)
    h.send_header("Content-Type", "application/json; charset=utf-8")
    h.send_header("Content-Length", str(len(raw)))
    h.send_header("Cache-Control", "no-store")
    h.end_headers()
    h.wfile.write(raw)


def read_body(h):
    n = int(h.headers.get("Content-Length") or 0)
    return json.loads(h.rfile.read(n).decode("utf-8")) if n > 0 else {}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def _static(self, filename, content_type):
        path = ROOT / filename
        if not path.exists():
            return send_json(self, {"error": "Static file missing"}, 500)
        raw = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        try:
            parsed = urlparse(self.path)
            p = parsed.path
            if p in ("/", "/index.html"):
                return self._static("index.html", "text/html; charset=utf-8")
            if p == "/app.css":
                return self._static("app.css", "text/css; charset=utf-8")
            if p == "/app.js":
                return self._static("app.js", "application/javascript; charset=utf-8")
            if p == "/favicon.ico":
                self.send_response(204); self.end_headers(); return
            if p == "/api/updates/status":
                return send_json(self, UPDATE_MANAGER.status())
            if p == "/api/updates/check":
                force = (parse_qs(parsed.query).get("force") or ["0"])[0] == "1"
                UPDATE_MANAGER.check(force=force)
                return send_json(self, UPDATE_MANAGER.status())
            if p == "/api/health":
                return send_json(self, {"ok": True, "version": BUILD_INFO.get("tag", VERSION), "mode": "windows-exe" if IS_FROZEN else "zero-dependency", "pid": os.getpid(), "parent_pid": os.getppid(), "updated_at": now_iso()})
            if p == "/api/settings":
                return send_json(self, settings_payload())
            if p == "/api/ping":
                touch_heartbeat(); return send_json(self, {"ok": True})
            if p == "/api/dashboard":
                return send_json(self, market_dashboard(force=True) if (parse_qs(parsed.query).get("force") or ["0"])[0] == "1" else market_dashboard())
            if p.startswith("/api/chart/"):
                qs = parse_qs(parsed.query)
                rng = (qs.get("range") or ["1y"])[0]
                return send_json(self, yahoo_chart_display(unquote(p.rsplit("/", 1)[1]), rng))
            if p.startswith("/api/stock/"):
                return send_json(self, basic_stock(unquote(p.rsplit("/", 1)[1])))
            if p.startswith("/api/research-history/"):
                return send_json(self, {"ticker":unquote(p.rsplit("/",1)[1]).upper(),"history":research_history(unquote(p.rsplit("/",1)[1]),20)})
            if p.startswith("/api/news-search/"):
                return send_json(self, news_search(unquote(p.split("/api/news-search/", 1)[1])))
            if p == "/api/positions":
                return send_json(self, {"positions": list_positions()})
            if p == "/api/risk":
                return send_json(self, portfolio_risk())
            if p == "/api/alerts":
                return send_json(self, alerts_payload())
            if p == "/api/ollama/status":
                m = ollama_models()
                return send_json(self, {"enabled": get_setting("ollama_enabled", "false") == "true", "available": bool(m), "models": m, "required": False})
            return send_json(self, {"error": "Not found"}, 404)
        except Exception as exc:
            send_json(self, {"error": str(exc)}, 400)

    def do_POST(self):
        try:
            p = urlparse(self.path).path
            body = read_body(self)
            if p in ("/api/updates/download", "/api/updates/apply"):
                origin = self.headers.get("Origin")
                host = self.headers.get("Host", "")
                if origin not in (None, f"http://{HOST}:{PORT}") or host != f"{HOST}:{PORT}":
                    return send_json(self, {"error": "Update action blocked: invalid local request origin"}, 403)
                if p == "/api/updates/download":
                    return send_json(self, UPDATE_MANAGER.download())
                result = UPDATE_MANAGER.install()
                send_json(self, result)
                def exit_for_install():
                    time.sleep(.6)
                    UPDATE_EXIT.set()
                threading.Thread(target=exit_for_install, daemon=True).start()
                return
            if p == "/api/settings":
                url = str(body.get("ollama_url") or "http://127.0.0.1:11434").strip().rstrip("/")
                if not re.match(r"^https?://", url):
                    raise ValueError("Ollama URL must start with http:// or https://")
                ua = str(body.get("sec_user_agent") or "StonkResearch/0.5 contact@example.com").strip()[:200]
                set_setting("ollama_enabled", "true" if body.get("ollama_enabled") else "false")
                set_setting("ollama_url", url)
                set_setting("ollama_model", str(body.get("ollama_model") or "auto")[:160])
                set_setting("sec_user_agent", ua)
                set_setting("hunter_max_symbols", max(5, min(int(body.get("hunter_max_symbols") or 36), 100)))
                set_setting("hunter_universe", str(body.get("hunter_universe") or "")[:5000])
                return send_json(self, settings_payload())
            if p.startswith("/api/research/"):
                return send_json(self, research_package(unquote(p.rsplit("/", 1)[1]), False))
            if p.startswith("/api/ai-research/"):
                return send_json(self, ai_research_package(unquote(p.rsplit("/", 1)[1])))
            if p == "/api/hunter":
                return send_json(self, hunter_scan(body.get("symbols"), body.get("limit")))
            if p == "/api/positions":
                t = clean_ticker(body.get("ticker"))
                sh = positive_number(body.get("shares"), "Shares")
                ap = positive_number(body.get("avg_price"), "Average price")
                if not math.isfinite(sh * ap):
                    raise ValueError("Position cost exceeds numeric range")
                with DB_LOCK, connect() as con:
                    tags = parse_thesis_tags(body.get("thesis_tags") or [])
                    cur = con.execute("INSERT INTO positions(ticker,shares,avg_price,thesis,thesis_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?)", (t, sh, ap, str(body.get("thesis") or ""), json.dumps(tags), now_iso(), now_iso()))
                    con.commit()
                    row = con.execute("SELECT * FROM positions WHERE id=?", (cur.lastrowid,)).fetchone()
                invalidate_research(t)
                return send_json(self, dict(row), 201)
            return send_json(self, {"error": "Not found"}, 404)
        except Exception as exc:
            send_json(self, {"error": str(exc)}, 400)


    def do_PUT(self):
        try:
            p=urlparse(self.path).path; body=read_body(self)
            if p.startswith("/api/positions/"):
                pid=int(p.rsplit("/",1)[1]); t=clean_ticker(body.get("ticker"))
                sh=positive_number(body.get("shares"), "Shares"); ap=positive_number(body.get("avg_price"), "Average price")
                if not math.isfinite(sh * ap): raise ValueError("Position cost exceeds numeric range")
                tags=parse_thesis_tags(body.get("thesis_tags") or [])
                with DB_LOCK, connect() as con:
                    exists=con.execute("SELECT id,ticker FROM positions WHERE id=?",(pid,)).fetchone()
                    if not exists: raise ValueError("Position not found")
                    con.execute("UPDATE positions SET ticker=?,shares=?,avg_price=?,thesis=?,thesis_json=?,updated_at=? WHERE id=?",(t,sh,ap,str(body.get("thesis") or ""),json.dumps(tags),now_iso(),pid)); con.commit()
                    row=con.execute("SELECT * FROM positions WHERE id=?",(pid,)).fetchone()
                invalidate_research(exists["ticker"], t)
                return send_json(self,dict(row))
            return send_json(self,{"error":"Not found"},404)
        except Exception as exc:
            send_json(self,{"error":str(exc)},400)

    def do_DELETE(self):
        try:
            p = urlparse(self.path).path
            if p.startswith("/api/positions/"):
                pid = int(p.rsplit("/", 1)[1])
                with DB_LOCK, connect() as con:
                    old = con.execute("SELECT ticker FROM positions WHERE id=?", (pid,)).fetchone()
                    con.execute("DELETE FROM positions WHERE id=?", (pid,)); con.commit()
                if old:
                    invalidate_research(old["ticker"])
                return send_json(self, {"ok": True})
            return send_json(self, {"error": "Not found"}, 404)
        except Exception as exc:
            send_json(self, {"error": str(exc)}, 400)


def find_browser():
    paths = []
    for env, tail in (
        ("PROGRAMFILES(X86)", r"Microsoft\Edge\Application\msedge.exe"),
        ("PROGRAMFILES", r"Microsoft\Edge\Application\msedge.exe"),
        ("LOCALAPPDATA", r"Microsoft\Edge\Application\msedge.exe"),
        ("PROGRAMFILES", r"Google\Chrome\Application\chrome.exe"),
        ("PROGRAMFILES(X86)", r"Google\Chrome\Application\chrome.exe"),
        ("LOCALAPPDATA", r"Google\Chrome\Application\chrome.exe"),
    ):
        base = os.environ.get(env)
        if base:
            paths.append(Path(base) / tail)
    return next((str(p) for p in paths if p.exists()), None)


def background_warmup():
    # Do slow one-time metadata work after launch so the user is not waiting on it inside Deep Research.
    try: sec_tickers()
    except Exception: pass


def migrate_portable_database():
    """First-run EXE migration: preserve nearby portable SQLite data using an online backup."""
    if not IS_FROZEN or DB_PATH.exists():
        return
    portable = Path(sys.executable).resolve().parent / "stonk.db"
    if not portable.is_file():
        return
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    staging = DB_PATH.with_name("stonk.migration.tmp")
    try:
        from contextlib import closing
        with closing(sqlite3.connect(str(portable), timeout=10)) as source:
            with closing(sqlite3.connect(str(staging), timeout=10)) as destination:
                source.backup(destination)
        os.replace(staging, DB_PATH)
    finally:
        staging.unlink(missing_ok=True)


def main():
    if IS_FROZEN:
        migrate_portable_database()
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    init_db(); touch_heartbeat()
    threading.Thread(target=background_warmup, daemon=True).start()
    try:
        server = ThreadingHTTPServer((HOST, PORT), Handler)
    except OSError:
        # If another v0.3 instance exists, simply bring it forward instead of opening a console/error window.
        try:
            health = http_json(f"http://{HOST}:{PORT}/api/health", timeout=1)
            if health.get("ok"):
                browser = find_browser()
                url = f"http://{HOST}:{PORT}"
                if browser:
                    subprocess.Popen([browser, f"--app={url}", "--new-window"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else:
                    webbrowser.open(url)
                return
        except Exception:
            pass
        raise SystemExit("Port 8765 is already in use by another application.")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://{HOST}:{PORT}"
    browser = find_browser()
    launched = time.time()
    try:
        if "--no-browser" not in sys.argv:
            if browser:
                subprocess.Popen([browser, f"--app={url}", "--new-window", "--disable-features=Translate"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                webbrowser.open(url)
        while not UPDATE_EXIT.is_set():
            time.sleep(1)
            if time.time() - launched > 20 and heartbeat_age() > 15:
                break
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown(); server.server_close()


def show_fatal(message):
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, str(message), "Stonk Research", 0x10)
    except Exception:
        pass


if __name__ == "__main__":
    try:
        if not (IS_FROZEN and exe_updater.run_helper_command(sys.argv[1:])):
            main()
    except BaseException as exc:
        show_fatal(exc)
