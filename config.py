"""
config.py
=========
Central configuration for the Retirement Tracker app.
All tunable constants, file paths, and default assumptions live here.
"""

import os
import sys

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
if getattr(sys, "frozen", False):
    # When bundled (PyInstaller --onefile), store data beside the executable.
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "retirement.db")

os.makedirs(DATA_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
DATABASE_URL = f"sqlite:///{DB_PATH}"

# ---------------------------------------------------------------------------
# Market / projection assumptions
# ---------------------------------------------------------------------------
# Default annualised return assumptions (decimal)
DEFAULT_RETURNS = {
    "stocks": 0.10,    # S&P 500 long-run average
    "bonds": 0.04,
    "reits": 0.08,
    "cash": 0.02,
}

# Default annualised volatility (standard deviation, decimal)
DEFAULT_VOLATILITY = {
    "stocks": 0.17,
    "bonds": 0.07,
    "reits": 0.15,
    "cash": 0.005,
}

# Inflation assumption
DEFAULT_INFLATION = 0.03

# Monte Carlo simulation count
MONTE_CARLO_RUNS = 1_000

# Retirement withdrawal rate (4 % rule)
DEFAULT_WITHDRAWAL_RATE = 0.04

# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------
SCHEDULER_TIMEZONE = "America/Chicago"

# ---------------------------------------------------------------------------
# UI / theme
# ---------------------------------------------------------------------------
APP_TITLE = "Retirement Tracker"
APP_VERSION = "1.0.0"
WINDOW_MIN_WIDTH = 1_200
WINDOW_MIN_HEIGHT = 750
