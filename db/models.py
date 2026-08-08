"""
db/models.py
============
SQLAlchemy ORM models for the Retirement Tracker.

Tables
------
Account            — brokerage, 401k, Roth IRA, HSA, cash accounts
Asset              — individual holdings (stocks, ETFs, bonds, REITs …)
Transaction        — every financial event (buy, sell, dividend, DRIP, contribution …)
ScheduledContrib   — recurring contribution rules
ProjectionRun      — saved Monte Carlo / projection outputs
"""

from __future__ import annotations

import enum
from datetime import datetime, date

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, relationship


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------

class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""
    pass


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class AccountType(str, enum.Enum):
    BROKERAGE = "Brokerage"
    ROTH_IRA = "Roth IRA"
    TRADITIONAL_IRA = "Traditional IRA"
    K401 = "401(k)"
    HSA = "HSA"
    CASH = "Cash"
    REAL_ESTATE = "Real Estate"


class TransactionType(str, enum.Enum):
    CONTRIBUTION = "Contribution"
    WITHDRAWAL = "Withdrawal"
    BUY = "Buy"
    SELL = "Sell"
    DIVIDEND = "Dividend"
    DRIP = "DRIP"
    SPECIAL = "Special Allocation"
    REBALANCE = "Rebalance"


class Frequency(str, enum.Enum):
    WEEKLY = "Weekly"
    BIWEEKLY = "Biweekly"
    MONTHLY = "Monthly"
    QUARTERLY = "Quarterly"
    ANNUALLY = "Annually"


class DividendFrequency(str, enum.Enum):
    WEEKLY = "Weekly"
    MONTHLY = "Monthly"
    QUARTERLY = "Quarterly"
    SEMIANNUAL = "Semi-Annual"
    ANNUAL = "Annual"


# ---------------------------------------------------------------------------
# Account
# ---------------------------------------------------------------------------

class Account(Base):
    """
    Represents a financial account container (brokerage, 401k, Roth IRA …).

    An account owns multiple :class:`Asset` holdings and is the target of
    :class:`Transaction` records.
    """

    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(120), nullable=False)
    account_type = Column(Enum(AccountType), nullable=False)
    institution = Column(String(120), default="")
    notes = Column(Text, default="")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # relationships
    assets = relationship(
        "Asset", back_populates="account", cascade="all, delete-orphan"
    )
    transactions = relationship(
        "Transaction", back_populates="account", cascade="all, delete-orphan"
    )
    scheduled_contribs = relationship(
        "ScheduledContrib", back_populates="account", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Account id={self.id} name={self.name!r} type={self.account_type}>"


# ---------------------------------------------------------------------------
# Asset / Holding
# ---------------------------------------------------------------------------

class Asset(Base):
    """
    A single holding (ticker position) inside an :class:`Account`.

    Stores static metadata (ticker, DRIP flag, dividend info) and the
    current share count / cost basis, which are updated as transactions occur.
    """

    __tablename__ = "assets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False)

    ticker = Column(String(20), nullable=False)
    name = Column(String(200), default="")          # full company/fund name
    asset_class = Column(String(40), default="stocks")  # stocks | bonds | reits | cash

    shares = Column(Float, default=0.0)
    cost_basis = Column(Float, default=0.0)         # total cost basis in USD

    # dividend metadata (populated / refreshed from yfinance)
    dividend_yield = Column(Float, default=0.0)     # annual yield as decimal
    dividend_per_share = Column(Float, default=0.0) # last known annual DPS
    dividend_frequency = Column(Enum(DividendFrequency), nullable=True)
    drip_enabled = Column(Boolean, default=False)
    last_dividend_date = Column(Date, nullable=True)  # date of last processed dividend

    # cached market price (updated on demand)
    last_price = Column(Float, default=0.0)
    price_updated_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    # relationships
    account = relationship("Account", back_populates="assets")
    transactions = relationship(
        "Transaction", back_populates="asset", cascade="all, delete-orphan"
    )

    @property
    def market_value(self) -> float:
        """Current market value of this position."""
        return self.shares * self.last_price

    @property
    def unrealized_gain(self) -> float:
        """Unrealised gain/loss vs cost basis."""
        return self.market_value - self.cost_basis

    def __repr__(self) -> str:
        return (
            f"<Asset id={self.id} ticker={self.ticker!r} "
            f"shares={self.shares:.4f} account_id={self.account_id}>"
        )


# ---------------------------------------------------------------------------
# Transaction
# ---------------------------------------------------------------------------

class Transaction(Base):
    """
    Records every financial event that touches an account or asset.

    ``amount`` always represents the USD value involved.
    ``shares`` is only relevant for equity-related transaction types.
    ``tag`` is a freeform label for special allocations (e.g. "tax refund").
    """

    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False)
    asset_id = Column(Integer, ForeignKey("assets.id"), nullable=True)

    transaction_type = Column(Enum(TransactionType), nullable=False)
    transaction_date = Column(Date, nullable=False, default=date.today)

    amount = Column(Float, default=0.0)     # USD value
    shares = Column(Float, default=0.0)     # shares bought/sold/dripped
    price_per_share = Column(Float, default=0.0)

    tag = Column(String(80), default="")    # e.g. "bonus", "tax refund"
    notes = Column(Text, default="")

    created_at = Column(DateTime, default=datetime.utcnow)

    # relationships
    account = relationship("Account", back_populates="transactions")
    asset = relationship("Asset", back_populates="transactions")

    def __repr__(self) -> str:
        return (
            f"<Transaction id={self.id} type={self.transaction_type} "
            f"date={self.transaction_date} amount={self.amount:.2f}>"
        )


# ---------------------------------------------------------------------------
# ScheduledContrib  (recurring contributions)
# ---------------------------------------------------------------------------

class ScheduledContrib(Base):
    """
    Defines a recurring contribution rule for an account.

    The scheduler service reads these rows and creates :class:`Transaction`
    records automatically on each due date.
    """

    __tablename__ = "scheduled_contribs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False)
    asset_id = Column(Integer, ForeignKey("assets.id"), nullable=True)

    amount = Column(Float, nullable=False)
    frequency = Column(Enum(Frequency), nullable=False)
    start_date = Column(Date, nullable=False, default=date.today)
    end_date = Column(Date, nullable=True)          # None = indefinite
    is_active = Column(Boolean, default=True)

    last_run_date = Column(Date, nullable=True)
    notes = Column(Text, default="")

    created_at = Column(DateTime, default=datetime.utcnow)

    # relationships
    account = relationship("Account", back_populates="scheduled_contribs")
    asset   = relationship("Asset", foreign_keys=[asset_id])

    def __repr__(self) -> str:
        return (
            f"<ScheduledContrib id={self.id} account_id={self.account_id} "
            f"amount={self.amount:.2f} freq={self.frequency}>"
        )


# ---------------------------------------------------------------------------
# ProjectionRun  (saved simulation outputs)
# ---------------------------------------------------------------------------

class ProjectionRun(Base):
    """
    Stores the metadata and summary results of a projection / Monte Carlo run.

    Detailed year-by-year data is serialised as JSON in ``result_json``.
    """

    __tablename__ = "projection_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_date = Column(DateTime, default=datetime.utcnow)

    # inputs
    current_age = Column(Integer)
    retirement_age = Column(Integer)
    monthly_contribution = Column(Float)
    expected_return = Column(Float)     # decimal (e.g. 0.10)
    volatility = Column(Float)          # decimal
    inflation = Column(Float)           # decimal
    withdrawal_rate = Column(Float)     # decimal (e.g. 0.04)
    simulation_runs = Column(Integer)

    # summary outputs
    median_value = Column(Float)
    p10_value = Column(Float)           # pessimistic 10th percentile
    p90_value = Column(Float)           # optimistic 90th percentile
    success_probability = Column(Float) # probability of not running out of money

    # full JSON output for charting
    result_json = Column(Text, default="{}")

    label = Column(String(120), default="")

    def __repr__(self) -> str:
        return (
            f"<ProjectionRun id={self.id} date={self.run_date} "
            f"success={self.success_probability:.1%}>"
        )


# ---------------------------------------------------------------------------
# UserProfile  (single-row app settings + identity)
# ---------------------------------------------------------------------------

class UserProfile(Base):
    """
    Stores the user's personal details used for projection accuracy.

    Only one row is ever created (id=1).  Use ``get_or_create_profile()``
    in ``services/portfolio.py`` to access it.
    """

    __tablename__ = "user_profile"

    id         = Column(Integer, primary_key=True, default=1)
    name       = Column(String(100), default="")
    date_of_birth = Column(Date, nullable=True)   # used for exact-age projection
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @property
    def exact_age(self) -> float:
        """Fractional age in years based on today's date and DOB."""
        if not self.date_of_birth:
            return 0.0
        today = date.today()
        years = today.year - self.date_of_birth.year
        # Subtract 1 if birthday hasn't occurred yet this year
        if (today.month, today.day) < (self.date_of_birth.month, self.date_of_birth.day):
            years -= 1
        # Fractional part: days into current year / days in current year
        birthday_this_year = self.date_of_birth.replace(year=today.year)
        if birthday_this_year > today:
            birthday_this_year = self.date_of_birth.replace(year=today.year - 1)
        frac = (today - birthday_this_year).days / 365.25
        return years + frac

    @property
    def next_birthday(self) -> date | None:
        """Next upcoming birthday date."""
        if not self.date_of_birth:
            return None
        today = date.today()
        this_year = self.date_of_birth.replace(year=today.year)
        if this_year < today:
            return self.date_of_birth.replace(year=today.year + 1)
        return this_year

    def __repr__(self) -> str:
        return f"<UserProfile name={self.name!r} dob={self.date_of_birth}>"


# ---------------------------------------------------------------------------
# PortfolioSnapshot  (daily net-worth history for dashboard charts)
# ---------------------------------------------------------------------------

class PortfolioSnapshot(Base):
    """
    Records the total portfolio value once per day so the dashboard can
    display daily, monthly, and all-time performance charts.

    ``account_breakdown`` stores a JSON dict of {account_name: value}
    so per-account history can also be charted.
    """

    __tablename__ = "portfolio_snapshots"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    snapshot_date   = Column(Date, nullable=False, unique=True)
    total_value     = Column(Float, nullable=False)
    account_breakdown = Column(Text, default="{}")   # JSON: {account_name: float}
    recorded_at     = Column(DateTime, default=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<PortfolioSnapshot date={self.snapshot_date} value=${self.total_value:,.2f}>"
