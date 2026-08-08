"""
services/market.py
==================
Market data service — wraps yfinance to fetch prices, dividend history,
and historical annual returns for the projection engine.

All network calls are isolated here so the rest of the app stays testable
without hitting the internet.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Optional

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Price helpers
# ---------------------------------------------------------------------------

def get_current_price(ticker: str) -> Optional[float]:
    """
    Return the most recent closing price for *ticker*.

    Strategy (in order of reliability):
    1. ``fast_info.last_price``   — real-time-ish, works for most equities/ETFs.
    2. Last close from 5-day history — reliable fallback.
    3. ``info["currentPrice"]``   — often stale for ETFs, last resort.

    Returns ``None`` if the ticker is invalid or the network is unavailable.
    """
    try:
        t = yf.Ticker(ticker)

        # 1. fast_info is the most up-to-date and avoids the heavy info dict
        try:
            price = t.fast_info.last_price
            if price and price > 0:
                return float(price)
        except Exception:
            pass

        # 2. Recent history close (most reliable for ETFs)
        hist = t.history(period="5d", auto_adjust=True)
        if not hist.empty:
            return float(hist["Close"].iloc[-1])

        # 3. info dict fallback
        info = t.info
        price = info.get("currentPrice") or info.get("regularMarketPrice")
        return float(price) if price else None

    except Exception as exc:
        logger.warning("Could not fetch price for %s: %s", ticker, exc)
        return None


def get_ticker_info(ticker: str) -> dict:
    """
    Return a dictionary of useful metadata for *ticker*.

    Keys returned (best-effort, may be ``None``):
    - ``name``              — company / fund name
    - ``current_price``     — latest price (USD), via fast_info → history → info
    - ``dividend_yield``    — trailing annual yield (decimal, e.g. 0.015)
    - ``dividend_rate``     — annual dividend per share (USD), computed from history
    - ``dividend_frequency``— ``"Weekly"`` / ``"Monthly"`` / ``"Quarterly"`` / etc.
    - ``sector``            — sector string
    - ``asset_class``       — coarse class: ``"stocks"`` / ``"bonds"`` / ``"reits"``

    Notes on dividend yield accuracy
    ---------------------------------
    yfinance's ``info["dividendYield"]`` is notoriously unreliable — it can be
    ``None``, already a decimal, or occasionally a whole-number percentage depending
    on the ticker and yfinance version.  We therefore:

    1. Pull the last 12 months of actual dividend payments.
    2. Sum them to get the trailing annual dividend per share.
    3. Divide by the current price to get the true trailing yield.

    This is the same methodology most brokerages use for "TTM yield".
    """
    result: dict = {
        "name": ticker,
        "current_price": None,
        "dividend_yield": 0.0,
        "dividend_rate": 0.0,
        "dividend_frequency": "Quarterly",
        "sector": "",
        "asset_class": "stocks",
    }
    try:
        t = yf.Ticker(ticker)
        info = t.info

        result["name"] = info.get("longName") or info.get("shortName") or ticker
        result["sector"] = info.get("sector", "")

        # --- Price: prefer fast_info → history → info dict ---------------
        price = get_current_price(ticker)
        result["current_price"] = price

        # --- Infer asset class -------------------------------------------
        category = (info.get("category") or "").lower()
        if "bond" in category or "fixed" in category:
            result["asset_class"] = "bonds"
        elif "real estate" in (info.get("sector") or "").lower() or "reit" in category:
            result["asset_class"] = "reits"
        else:
            result["asset_class"] = "stocks"

        # --- Dividend data from actual payment history -------------------
        freq_str, annual_dps = _compute_dividend_metrics(t)
        result["dividend_frequency"] = freq_str
        result["dividend_rate"] = annual_dps

        # Yield = TTM dividends / current price
        if price and price > 0 and annual_dps > 0:
            result["dividend_yield"] = annual_dps / price
        else:
            # Last-resort: use yfinance's reported yield but sanity-check it
            raw_yield = info.get("dividendYield") or 0.0
            result["dividend_yield"] = _sanitize_yield(raw_yield, price)

    except Exception as exc:
        logger.warning("Could not fetch info for %s: %s", ticker, exc)

    return result


def _sanitize_yield(raw_yield: float, price: Optional[float]) -> float:
    """
    yfinance sometimes returns dividendYield as a whole-number percentage
    (e.g. 1.5 meaning 1.5%) and sometimes as a decimal (0.015).
    Heuristic: if the value is > 0.5, it is almost certainly a percentage —
    divide by 100.  Cap at 30% to filter obvious garbage data.
    """
    if raw_yield is None or raw_yield <= 0:
        return 0.0
    if raw_yield > 0.5:
        raw_yield = raw_yield / 100.0
    # Cap at 30% annual yield — anything above is almost certainly bad data
    return min(raw_yield, 0.30)


def _compute_dividend_metrics(ticker_obj: yf.Ticker) -> tuple[str, float]:
    """
    Compute the dividend frequency string and trailing-12-month annual DPS
    from actual payment history.

    Returns
    -------
    (frequency_str, annual_dps)
        frequency_str — ``"Weekly"`` / ``"Monthly"`` / ``"Quarterly"`` /
                        ``"Semi-Annual"`` / ``"Annual"``
        annual_dps    — sum of per-share payments in the trailing 12 months
    """
    try:
        divs = ticker_obj.dividends
        if divs is None or divs.empty:
            return "Quarterly", 0.0

        # Normalise index timezone
        if divs.index.tz is None:
            divs.index = divs.index.tz_localize("UTC")

        one_year_ago = pd.Timestamp.now(tz="UTC") - pd.DateOffset(years=1)
        recent = divs[divs.index >= one_year_ago]

        count = len(recent)
        annual_dps = float(recent.sum()) if count > 0 else 0.0

        # Determine frequency from payment count over the last 12 months
        if count >= 40:
            freq = "Weekly"
        elif count >= 10:
            freq = "Monthly"
        elif count >= 3:
            freq = "Quarterly"
        elif count == 2:
            freq = "Semi-Annual"
        elif count == 1:
            freq = "Annual"
        else:
            freq = "Quarterly"

        return freq, annual_dps

    except Exception:
        return "Quarterly", 0.0


# ---------------------------------------------------------------------------
# Dividend history
# ---------------------------------------------------------------------------

def get_dividend_history(
    ticker: str,
    start: Optional[date] = None,
    end: Optional[date] = None,
) -> pd.DataFrame:
    """
    Fetch the dividend payment history for *ticker*.

    Parameters
    ----------
    ticker : str
        Ticker symbol.
    start, end : date, optional
        Date range filter. Defaults to all available history.

    Returns
    -------
    pd.DataFrame
        Columns: ``date`` (datetime.date), ``dividend_per_share`` (float).
    """
    try:
        t = yf.Ticker(ticker)
        divs = t.dividends
        if divs is None or divs.empty:
            return pd.DataFrame(columns=["date", "dividend_per_share"])

        # Normalise index to UTC-aware then convert to date
        if divs.index.tz is None:
            divs.index = divs.index.tz_localize("UTC")

        if start:
            divs = divs[divs.index.date >= start]
        if end:
            divs = divs[divs.index.date <= end]

        df = pd.DataFrame({"date": divs.index.date, "dividend_per_share": divs.values})
        df = df.reset_index(drop=True)
        return df
    except Exception as exc:
        logger.warning("Could not fetch dividends for %s: %s", ticker, exc)
        return pd.DataFrame(columns=["date", "dividend_per_share"])


def get_real_dividend_schedule(ticker: str) -> dict:
    """
    Build a real dividend schedule for *ticker* from yfinance payment history.

    Uses the last several payments to determine:
    - The exact day-of-week (weekly) or day-of-month (monthly/quarterly)
      that the fund pays on.
    - The average per-share amount per payment.
    - The interval between payments in days.

    Returns
    -------
    dict with keys:
        ``last_payments``   — list of (date, amount) for the most recent payments
        ``avg_amount``      — average per-share payment amount
        ``interval_days``   — median days between payments
        ``frequency``       — inferred frequency string
    """
    empty = {"last_payments": [], "avg_amount": 0.0, "interval_days": 91, "frequency": "Quarterly"}
    try:
        t = yf.Ticker(ticker)
        divs = t.dividends
        if divs is None or divs.empty:
            return empty

        if divs.index.tz is None:
            divs.index = divs.index.tz_localize("UTC")

        # Use last 12 months of data
        one_year_ago = pd.Timestamp.now(tz="UTC") - pd.DateOffset(years=1)
        recent = divs[divs.index >= one_year_ago]
        if recent.empty:
            recent = divs.tail(8)  # fall back to last 8 payments

        dates = [d.date() for d in recent.index]
        amounts = [float(v) for v in recent.values]
        payments = list(zip(dates, amounts))

        avg_amount = sum(amounts) / len(amounts) if amounts else 0.0

        # Compute median interval between consecutive payments
        if len(dates) >= 2:
            intervals = [(dates[i+1] - dates[i]).days for i in range(len(dates)-1)]
            import statistics
            interval_days = statistics.median(intervals)
        else:
            interval_days = 91

        # Classify frequency
        if interval_days <= 10:
            frequency = "Weekly"
        elif interval_days <= 35:
            frequency = "Monthly"
        elif interval_days <= 100:
            frequency = "Quarterly"
        elif interval_days <= 200:
            frequency = "Semi-Annual"
        else:
            frequency = "Annual"

        return {
            "last_payments": payments,
            "avg_amount": avg_amount,
            "interval_days": interval_days,
            "frequency": frequency,
        }

    except Exception as exc:
        logger.warning("Could not build dividend schedule for %s: %s", ticker, exc)
        return empty


# ---------------------------------------------------------------------------
# Historical annual returns (for the projection engine)
# ---------------------------------------------------------------------------

def get_historical_annual_returns(
    ticker: str = "SPY",
    years: int = 30,
) -> list[float]:
    """
    Download annual total returns for *ticker* over the past *years* years.

    Used by the Monte Carlo engine to build empirical return distributions.

    Parameters
    ----------
    ticker : str
        ETF / index proxy (e.g. ``"SPY"``, ``"AGG"``, ``"VNQ"``).
    years : int
        Number of calendar years to look back.

    Returns
    -------
    list[float]
        Annual total return as a decimal for each year (e.g. ``0.12`` = 12 %).
        Empty list if data is unavailable.
    """
    try:
        end_dt = datetime.today()
        start_dt = end_dt.replace(year=end_dt.year - years)
        hist = yf.download(ticker, start=start_dt, end=end_dt, progress=False, auto_adjust=True)
        if hist.empty:
            return []
        # Resample to year-end prices
        annual = hist["Close"].resample("YE").last()
        returns = annual.pct_change().dropna().tolist()
        return [float(r) for r in returns]
    except Exception as exc:
        logger.warning("Could not fetch historical returns for %s: %s", ticker, exc)
        return []


def get_multi_ticker_prices(tickers: list[str]) -> dict[str, Optional[float]]:
    """
    Fetch current prices for multiple tickers in a single yfinance batch call.

    Uses ``history(period="2d")`` which is more reliable than ``info["currentPrice"]``
    for ETFs and funds.  Falls back to per-ticker ``fast_info`` on failure.

    Parameters
    ----------
    tickers : list[str]

    Returns
    -------
    dict[str, float | None]
        Mapping of ticker → price (``None`` if unavailable).
    """
    if not tickers:
        return {}
    try:
        data = yf.download(
            tickers,
            period="2d",
            progress=False,
            auto_adjust=True,
            group_by="ticker",
        )
        result: dict[str, Optional[float]] = {}
        for t in tickers:
            try:
                if len(tickers) == 1:
                    close_series = data["Close"]
                else:
                    close_series = data[t]["Close"]
                # dropna to skip any NaN rows, take the last valid close
                last = close_series.dropna()
                result[t] = float(last.iloc[-1]) if not last.empty else None
            except Exception:
                result[t] = None

        # Fill any None values with per-ticker fast_info fallback
        missing = [t for t, v in result.items() if v is None]
        for t in missing:
            result[t] = get_current_price(t)

        return result
    except Exception as exc:
        logger.warning("Batch price fetch failed: %s", exc)
        return {t: get_current_price(t) for t in tickers}


# ---------------------------------------------------------------------------
# Price change metrics (daily + 30-day)
# ---------------------------------------------------------------------------

def get_price_changes(tickers: list[str]) -> dict[str, dict]:
    """
    Fetch daily and 30-day price change metrics for a batch of tickers.

    Pulls 35 calendar days of history (enough for 30 trading days) in one
    yfinance batch call.

    Parameters
    ----------
    tickers : list[str]

    Returns
    -------
    dict[str, dict]
        Mapping of ticker → dict with keys:
        - ``price``           current close
        - ``prev_close``      previous session close (for day change)
        - ``day_change``      USD change vs prev close
        - ``day_change_pct``  % change vs prev close
        - ``price_30d_ago``   close ~30 calendar days ago
        - ``change_30d_pct``  % change over last 30 days
    """
    _empty = {
        "price": None,
        "prev_close": None,
        "day_change": None,
        "day_change_pct": None,
        "price_30d_ago": None,
        "change_30d_pct": None,
    }

    if not tickers:
        return {}

    try:
        data = yf.download(
            tickers,
            period="35d",
            progress=False,
            auto_adjust=True,
            group_by="ticker",
        )

        result: dict[str, dict] = {}
        for t in tickers:
            try:
                if len(tickers) == 1:
                    close = data["Close"].dropna()
                else:
                    close = data[t]["Close"].dropna()

                if close.empty or len(close) < 2:
                    result[t] = dict(_empty)
                    continue

                current    = float(close.iloc[-1])
                prev       = float(close.iloc[-2])
                day_chg    = current - prev
                day_pct    = (day_chg / prev * 100) if prev else 0.0

                # 30-calendar-day lookback — find the oldest available row
                price_30d  = float(close.iloc[0])
                chg_30d    = ((current - price_30d) / price_30d * 100) if price_30d else 0.0

                result[t] = {
                    "price":          current,
                    "prev_close":     prev,
                    "day_change":     day_chg,
                    "day_change_pct": day_pct,
                    "price_30d_ago":  price_30d,
                    "change_30d_pct": chg_30d,
                }
            except Exception:
                result[t] = dict(_empty)

        return result

    except Exception as exc:
        logger.warning("Price change fetch failed: %s", exc)
        return {t: dict(_empty) for t in tickers}

