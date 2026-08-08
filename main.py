"""
main.py
=======
Retirement Tracker — application entry point.

Bootstraps the database, starts the background scheduler,
then launches the Tkinter GUI.
"""

import logging
import sys
import tkinter.messagebox as mb

# ---------------------------------------------------------------------------
# Logging configuration
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def _check_dependencies() -> bool:
    """Verify that all required packages are installed."""
    missing = []
    for pkg in ("sqlalchemy", "yfinance", "pandas", "numpy", "matplotlib", "apscheduler"):
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)
    if missing:
        print(
            f"Missing required packages: {', '.join(missing)}\n"
            f"Run:  pip install -r requirements.txt",
            file=sys.stderr,
        )
        return False
    return True


def main() -> None:
    """Initialise all subsystems and start the GUI event loop."""

    if not _check_dependencies():
        sys.exit(1)

    # -- Database --------------------------------------------------------
    logger.info("Initialising database …")
    try:
        from db.database import init_db
        init_db()
        logger.info("Database ready.")
    except Exception as exc:
        mb.showerror("Database Error", f"Failed to initialise database:\n{exc}")
        sys.exit(1)

    # -- Scheduler -------------------------------------------------------
    logger.info("Starting contribution scheduler …")
    try:
        from services.scheduler import start_scheduler
        start_scheduler()
    except Exception as exc:
        logger.warning("Scheduler failed to start: %s", exc)
        # Non-fatal — the app still works without the scheduler

    # -- GUI -------------------------------------------------------------
    logger.info("Launching GUI …")
    try:
        from gui.main_window import MainWindow
        app = MainWindow()
        app.mainloop()
    except Exception as exc:
        logger.exception("Unhandled exception in GUI: %s", exc)
        try:
            mb.showerror("Fatal Error", f"The application crashed:\n\n{exc}")
        except Exception:
            pass
    finally:
        # Ensure scheduler is stopped even if the GUI crashes
        try:
            from services.scheduler import stop_scheduler
            stop_scheduler()
        except Exception:
            pass

    logger.info("Application exited.")


if __name__ == "__main__":
    main()
