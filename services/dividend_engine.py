"""
services/dividend_engine.py
===========================
Dividend calculation, DRIP reinvestment, and dividend calendar logic.

Public API
----------
process_dividends(session, asset)
    Calculate the dividend payment for an asset using the most recent
    real yfinance payment amount, and optionally apply DRIP.

build_dividend_calendar(session, months_ahead)
    Return a list of projected upcoming dividend events based on real
    historical payment dates extrapolated forward.

get_dividend_income_summary(session, year)
    Aggregate dividend income by month for a given calendar year.
"""

from __future__ import annotations

import logging
from calendar import monthrange
from datetime import date, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from db.models import Asset, DividendFrequency, Transaction, TransactionType
from services.market import get_current_price, get_real_dividend_schedule

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Payments-per-year lookup (used only as fallback when history unavailable)
# ---------------------------------------------------------------------------

_PAYMENTS_PER_YEAR: dict[str, int] = {
    DividendFrequency.WEEKLY:      52,
    DividendFrequency.MONTHLY:     12,
    DividendFrequency.QUARTERLY:    4,
    DividendFrequency.SEMIANNUAL:   2,
    DividendFrequency.ANNUAL:       1,
}


def _div_per_payment(asset: Asset) -> float:
    """Return the USD dividend per share for a single payment using stored annual DPS."""
    payments = _PAYMENTS_PER_YEAR.get(asset.dividend_frequency, 4)
    if payments == 0:
        return 0.0
    return asset.dividend_per_share / payments


# ---------------------------------------------------------------------------
# Real schedule projection
# ---------------------------------------------------------------------------

def _project_next_dates(last_date: date, interval_days: float, from_date: date, months_ahead: int) -> list[date]:
    """
    Project future payment dates by repeating the historical interval
    forward from the last known payment date until months_ahead from from_date.
    """
    cutoff = _add_months_fallback(from_date, months_ahead)

    current = last_date
    interval = max(1, round(interval_days))
    while current <= from_date:
        current += timedelta(days=interval)

    dates: list[date] = []
    while current <= cutoff:
        dates.append(current)
        current += timedelta(days=interval)
    return dates


def _add_months_fallback(d: date, months: int) -> date:
    """Add *months* months to *d*, clamping to last valid day of month."""
    month = d.month + months
    year  = d.year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    day   = min(d.day, monthrange(year, month)[1])
    return date(year, month, day)


def _min_days_between_payments(freq: DividendFrequency) -> int:
    """
    Return the minimum number of days that must elapse before we will
    process another dividend for this frequency.

    We use 80% of the expected interval so a payment a few days early
    still gets processed, but a double-click the same week does not.
    """
    intervals = {
        DividendFrequency.WEEKLY:     6,   # 7 × 0.80 ≈ 6
        DividendFrequency.MONTHLY:   24,   # 30 × 0.80 ≈ 24
        DividendFrequency.QUARTERLY: 73,   # 91 × 0.80 ≈ 73
        DividendFrequency.SEMIANNUAL:146,
        DividendFrequency.ANNUAL:    292,
    }
    return intervals.get(freq, 24)


# ---------------------------------------------------------------------------
# Core dividend processing
# ---------------------------------------------------------------------------

def process_dividends(
    session: Session,
    asset: Asset,
    payment_date: Optional[date] = None,
    force: bool = False,
) -> Optional[Transaction]:
    """
    Record a dividend payment for *asset* using the real most-recent yfinance
    per-share amount, and apply DRIP if enabled.

    Guard
    -----
    If ``asset.last_dividend_date`` is set and fewer than
    ``_min_days_between_payments(freq)`` days have passed since then,
    the call returns ``None`` and logs a skip — prevents double-processing
    if the button is clicked twice in the same payment window.
    Pass ``force=True`` to bypass the guard (for manual overrides).

    Steps
    -----
    1. Check guard — skip if already paid this period.
    2. Fetch real dividend schedule from yfinance; use latest payment amount.
       Falls back to stored ``dividend_per_share ÷ payments_per_year``.
    3. Log a DIVIDEND transaction.
    4. If ``asset.drip_enabled``: fetch current price, compute new shares,
       update the holding, log a DRIP transaction.
    5. Stamp ``asset.last_dividend_date = payment_date``.

    Parameters
    ----------
    session : Session
    asset : Asset
    payment_date : date, optional
        Override payment date (defaults to today).
    force : bool
        Skip the duplicate-payment guard.

    Returns
    -------
    Transaction or None
    """
    if payment_date is None:
        payment_date = date.today()

    # --- Duplicate-payment guard -----------------------------------------
    if not force and asset.last_dividend_date and asset.dividend_frequency:
        days_since = (payment_date - asset.last_dividend_date).days
        min_days   = _min_days_between_payments(asset.dividend_frequency)
        if days_since < min_days:
            logger.info(
                "Skipping %s dividend — only %d days since last payment "
                "(minimum %d for %s)",
                asset.ticker, days_since, min_days,
                asset.dividend_frequency.value,
            )
            return None

    # --- Real per-share amount from yfinance ----------------------------
    try:
        sched = get_real_dividend_schedule(asset.ticker)
        if sched["last_payments"]:
            # Most recent actual payment amount
            dps_this_payment = sched["last_payments"][-1][1]
        else:
            dps_this_payment = _div_per_payment(asset)
    except Exception:
        dps_this_payment = _div_per_payment(asset)

    dividend_amount = asset.shares * dps_this_payment

    if dividend_amount <= 0:
        logger.debug("No dividend for %s (amount=0)", asset.ticker)
        return None

    # --- Log dividend transaction ----------------------------------------
    div_tx = Transaction(
        account_id=asset.account_id,
        asset_id=asset.id,
        transaction_type=TransactionType.DIVIDEND,
        transaction_date=payment_date,
        amount=dividend_amount,
        shares=0.0,
        price_per_share=dps_this_payment,
        notes=f"Dividend — {asset.ticker}  ${dps_this_payment:.4f}/share",
    )
    session.add(div_tx)

    # --- DRIP reinvestment -----------------------------------------------
    if asset.drip_enabled:
        price = get_current_price(asset.ticker) or asset.last_price
        if price and price > 0:
            new_shares = dividend_amount / price
            asset.shares     += new_shares
            asset.cost_basis += dividend_amount

            drip_tx = Transaction(
                account_id=asset.account_id,
                asset_id=asset.id,
                transaction_type=TransactionType.DRIP,
                transaction_date=payment_date,
                amount=dividend_amount,
                shares=new_shares,
                price_per_share=price,
                notes=f"DRIP: {new_shares:.6f} shares of {asset.ticker} @ ${price:.2f}",
            )
            session.add(drip_tx)
            logger.info(
                "DRIP %s: $%.4f/share × %.4f shares = $%.2f → %.6f new shares @ $%.2f",
                asset.ticker, dps_this_payment, asset.shares - new_shares,
                dividend_amount, new_shares, price,
            )
        else:
            logger.warning("DRIP skipped for %s — could not determine price", asset.ticker)

    # --- Stamp last payment date so the guard works next time -----------
    asset.last_dividend_date = payment_date

    session.flush()
    return div_tx


# ---------------------------------------------------------------------------
# Dividend calendar — real dates projected forward
# ---------------------------------------------------------------------------

def build_dividend_calendar(
    session: Session,
    months_ahead: int = 3,
) -> list[dict]:
    """
    Build a projected dividend payment calendar using real yfinance history.

    For each holding the function:
    1. Fetches the last several actual payment dates + amounts from yfinance.
    2. Uses the median inter-payment interval to project forward.
    3. Uses the average actual per-share amount for the estimate.

    Falls back to the stored ``dividend_per_share`` and frequency-based
    schedule if yfinance is unavailable.

    Parameters
    ----------
    session : Session
    months_ahead : int

    Returns
    -------
    list[dict]
        Sorted by date.  Keys: ``date``, ``ticker``, ``account_name``,
        ``shares``, ``div_per_share``, ``estimated_amount``, ``drip``,
        ``source`` (``"real"`` or ``"estimated"``).
    """
    from db.models import Account

    assets: list[Asset] = (
        session.query(Asset)
        .join(Account)
        .filter(Account.is_active == True, Asset.shares > 0)
        .all()
    )

    events: list[dict] = []
    today = date.today()

    for asset in assets:
        if not asset.dividend_frequency or asset.dividend_per_share <= 0:
            continue

        source = "estimated"
        payment_dates: list[date] = []
        dps = _div_per_payment(asset)  # fallback amount

        try:
            sched = get_real_dividend_schedule(asset.ticker)
            if sched["last_payments"] and len(sched["last_payments"]) >= 2:
                source = "real"
                last_date = sched["last_payments"][-1][0]
                dps = sched["avg_amount"]           # real average per-payment
                interval = sched["interval_days"]
                payment_dates = _project_next_dates(last_date, interval, today, months_ahead)
            else:
                # Only one payment in history — use it as anchor if available
                if sched["last_payments"]:
                    last_date = sched["last_payments"][-1][0]
                    dps = sched["last_payments"][-1][1]
                    interval = sched["interval_days"]
                    payment_dates = _project_next_dates(last_date, interval, today, months_ahead)
                    source = "real"
        except Exception as exc:
            logger.debug("Real schedule unavailable for %s: %s", asset.ticker, exc)

        # Fall back to stored-frequency schedule if real data unavailable
        if not payment_dates:
            payment_dates = _fallback_dates(asset, today, months_ahead)

        for pdate in payment_dates:
            events.append({
                "date":             pdate,
                "ticker":           asset.ticker,
                "account_name":     asset.account.name,
                "shares":           asset.shares,
                "div_per_share":    dps,
                "estimated_amount": asset.shares * dps,
                "drip":             asset.drip_enabled,
                "source":           source,
            })

    events.sort(key=lambda e: e["date"])
    return events


def _fallback_dates(asset: Asset, from_date: date, months_ahead: int) -> list[date]:
    """Generate payment dates from stored frequency when real history is missing."""
    freq = asset.dividend_frequency
    cutoff = _add_months_fallback(from_date, months_ahead)
    dates: list[date] = []

    if freq == DividendFrequency.WEEKLY:
        days_until_friday = (4 - from_date.weekday()) % 7
        current = from_date + timedelta(days=days_until_friday or 7)
        while current <= cutoff:
            dates.append(current)
            current += timedelta(weeks=1)
    else:
        ppy = _PAYMENTS_PER_YEAR.get(freq, 4)
        interval_months = max(1, 12 // ppy)
        payment_month = ((from_date.month - 1) // interval_months) * interval_months + 1
        anchor = date(from_date.year, payment_month, 15)
        if anchor <= from_date:
            anchor = _add_months_fallback(anchor, interval_months)
        current = anchor
        while current <= cutoff:
            dates.append(current)
            current = _add_months_fallback(current, interval_months)

    return dates


# ---------------------------------------------------------------------------
# _add_months helper (kept for backward compatibility)
# ---------------------------------------------------------------------------

def _add_months(d: date, months: int) -> date:
    """Add *months* months to *d*, clamping to the last valid day."""
    return _add_months_fallback(d, months)


# ---------------------------------------------------------------------------
# Income summary
# ---------------------------------------------------------------------------

def get_dividend_income_summary(session: Session, year: int) -> dict[int, float]:
    """
    Aggregate actual dividend income by month for *year*.

    Returns
    -------
    dict[int, float]
        Month (1–12) → total USD received.
    """
    from sqlalchemy import extract

    rows = (
        session.query(Transaction)
        .filter(
            Transaction.transaction_type == TransactionType.DIVIDEND,
            extract("year", Transaction.transaction_date) == year,
        )
        .all()
    )

    summary: dict[int, float] = {m: 0.0 for m in range(1, 13)}
    for tx in rows:
        summary[tx.transaction_date.month] += tx.amount
    return summary
