"""
services/scheduler.py
=====================
Recurring contribution scheduler.

Uses APScheduler to fire a daily job that checks :class:`~db.models.ScheduledContrib`
rows and creates :class:`~db.models.Transaction` records when a contribution is due.

Usage
-----
    from services.scheduler import start_scheduler, stop_scheduler

    start_scheduler()   # call once at app startup
    ...
    stop_scheduler()    # call on app shutdown
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from config import SCHEDULER_TIMEZONE
from db.database import get_session
from db.models import Frequency, ScheduledContrib, Transaction, TransactionType

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


# ---------------------------------------------------------------------------
# Interval helpers
# ---------------------------------------------------------------------------

def _is_due(contrib: ScheduledContrib, today: date) -> bool:
    """
    Return True if *contrib* should fire today.

    Rules
    -----
    - ``WEEKLY``    — every 7 days from start_date.
    - ``BIWEEKLY``  — every 14 days from start_date.
    - ``MONTHLY``   — same day-of-month as start_date (or last day of month).
    - ``QUARTERLY`` — same day, every 3 months.
    - ``ANNUALLY``  — same day, every 12 months.
    """
    if not contrib.is_active:
        return False
    if today < contrib.start_date:
        return False
    if contrib.end_date and today > contrib.end_date:
        return False

    last = contrib.last_run_date or (contrib.start_date - timedelta(days=1))
    delta_days = (today - last).days
    freq = contrib.frequency

    if freq == Frequency.WEEKLY:
        return delta_days >= 7
    if freq == Frequency.BIWEEKLY:
        return delta_days >= 14
    if freq == Frequency.MONTHLY:
        return (
            today.day == contrib.start_date.day
            and (today.year, today.month) > (last.year, last.month)
        )
    if freq == Frequency.QUARTERLY:
        months_elapsed = (today.year - last.year) * 12 + today.month - last.month
        return months_elapsed >= 3 and today.day >= contrib.start_date.day
    if freq == Frequency.ANNUALLY:
        return (
            today.month == contrib.start_date.month
            and today.day == contrib.start_date.day
            and today.year > last.year
        )
    return False


# ---------------------------------------------------------------------------
# Daily job
# ---------------------------------------------------------------------------

def _process_due_contributions() -> None:
    """
    Scan all scheduled contributions and create transactions for those due today.

    This is the function APScheduler calls once per day.
    """
    today = date.today()
    created = 0

    with get_session() as session:
        contribs: list[ScheduledContrib] = (
            session.query(ScheduledContrib)
            .filter(ScheduledContrib.is_active == True)
            .all()
        )

        for contrib in contribs:
            if not _is_due(contrib, today):
                continue

            tx = Transaction(
                account_id=contrib.account_id,
                asset_id=contrib.asset_id,
                transaction_type=TransactionType.CONTRIBUTION,
                transaction_date=today,
                amount=contrib.amount,
                notes=f"Scheduled {contrib.frequency.value} contribution",
            )
            session.add(tx)
            contrib.last_run_date = today
            created += 1
            logger.info(
                "Scheduled contribution: $%.2f → account_id=%d",
                contrib.amount,
                contrib.account_id,
            )

    if created:
        logger.info("Scheduler processed %d contribution(s) for %s", created, today)


# ---------------------------------------------------------------------------
# Scheduler lifecycle
# ---------------------------------------------------------------------------

def start_scheduler() -> None:
    """
    Start the background APScheduler instance.

    Schedules :func:`_process_due_contributions` to run once per day at 08:00
    local time, and fires immediately on startup to catch up any missed dates.
    """
    global _scheduler

    if _scheduler and _scheduler.running:
        logger.debug("Scheduler already running — skipping start")
        return

    _scheduler = BackgroundScheduler(timezone=SCHEDULER_TIMEZONE)
    _scheduler.add_job(
        _process_due_contributions,
        trigger=CronTrigger(hour=8, minute=0, timezone=SCHEDULER_TIMEZONE),
        id="daily_contributions",
        replace_existing=True,
        misfire_grace_time=3600,  # 1-hour grace if app was offline
    )
    _scheduler.start()
    logger.info("Contribution scheduler started.")

    # Run immediately to catch any contributions missed since last launch
    _process_due_contributions()


def stop_scheduler() -> None:
    """Gracefully stop the scheduler. Safe to call even if not running."""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Contribution scheduler stopped.")
    _scheduler = None


def run_now() -> None:
    """Manually trigger the contribution check outside of the daily schedule."""
    _process_due_contributions()
