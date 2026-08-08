"""
gui/main_window.py
==================
Main application window with sidebar navigation and frame switcher.

The window is divided into two columns:
- Left  : fixed-width sidebar with navigation buttons.
- Right : content area where one frame is shown at a time.

Each nav section maps to a :class:`~tkinter.ttk.Frame` subclass defined in
``gui/frames/``.
"""

from __future__ import annotations

import tkinter as tk
import tkinter.messagebox as mb
from tkinter import ttk

from config import APP_TITLE, APP_VERSION, WINDOW_MIN_HEIGHT, WINDOW_MIN_WIDTH
from gui import theme as th
from gui.theme import apply_theme

# Frame imports (imported lazily inside show_frame to speed up startup)
_FRAME_CLASSES: dict[str, str] = {
    "Dashboard":   "gui.frames.dashboard.DashboardFrame",
    "Accounts":    "gui.frames.accounts.AccountsFrame",
    "Transactions":"gui.frames.transactions.TransactionsFrame",
    "Dividends":   "gui.frames.dividends.DividendsFrame",
    "Projection":  "gui.frames.projection.ProjectionFrame",
}

_NAV_ICONS: dict[str, str] = {
    "Dashboard":    "📊",
    "Accounts":     "🏦",
    "Transactions": "📋",
    "Dividends":    "💰",
    "Projection":   "📈",
}


def _import_frame_class(dotted: str):
    """Dynamically import and return a frame class by dotted path."""
    parts = dotted.rsplit(".", 1)
    module = __import__(parts[0], fromlist=[parts[1]])
    return getattr(module, parts[1])


class MainWindow(tk.Tk):
    """
    The top-level Tkinter window for the Retirement Tracker.

    Manages:
    - Window geometry & theming.
    - Sidebar navigation.
    - Frame lifetime (frames are created on first visit and cached).
    - Global status bar.
    """

    def __init__(self) -> None:
        super().__init__()

        apply_theme(self)

        self.title(f"{APP_TITLE}  v{APP_VERSION}")
        self.geometry(f"{WINDOW_MIN_WIDTH}x{WINDOW_MIN_HEIGHT}")
        self.minsize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)
        self.configure(bg=th.BG_DARK)

        self._active_page: str = ""
        self._frame_cache: dict[str, ttk.Frame] = {}
        self._nav_buttons: dict[str, tk.Label] = {}

        self._build_layout()
        self._build_sidebar()
        self._build_content_area()
        self._build_status_bar()

        # Show the dashboard on startup
        self.show_frame("Dashboard")

        # Record today's snapshot (no-op if already done today)
        self._record_startup_snapshot()

        # Check for user profile on first run
        self.after(500, self._check_profile)

        # Live clock in status bar
        self._tick_clock()

        # Handle window close
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------
    # Layout construction
    # ------------------------------------------------------------------

    def _build_layout(self) -> None:
        """Create the two-column root grid."""
        self.columnconfigure(0, weight=0)   # sidebar — fixed width
        self.columnconfigure(1, weight=1)   # content — expands
        self.rowconfigure(0, weight=1)
        self.rowconfigure(1, weight=0)      # status bar

    def _build_sidebar(self) -> None:
        """Build the fixed left sidebar with app branding and nav links."""
        sidebar = tk.Frame(self, bg=th.SIDEBAR_BG, width=220)
        sidebar.grid(row=0, column=0, sticky="nsw")
        sidebar.grid_propagate(False)

        # Branding
        brand_frame = tk.Frame(sidebar, bg=th.SIDEBAR_BG)
        brand_frame.pack(fill="x", pady=(24, 8))

        tk.Label(
            brand_frame,
            text="💼",
            font=("Segoe UI", 28),
            bg=th.SIDEBAR_BG,
            fg=th.FG_ACCENT,
        ).pack()

        tk.Label(
            brand_frame,
            text="Retirement",
            font=(*th.FONT_H3, ),
            bg=th.SIDEBAR_BG,
            fg=th.FG_PRIMARY,
        ).pack()
        tk.Label(
            brand_frame,
            text="Tracker",
            font=th.FONT_H3,
            bg=th.SIDEBAR_BG,
            fg=th.FG_ACCENT,
        ).pack()

        # Separator
        tk.Frame(sidebar, bg=th.BORDER, height=1).pack(fill="x", padx=16, pady=16)

        # Nav section label
        tk.Label(
            sidebar,
            text="  NAVIGATION",
            font=th.FONT_SMALL,
            bg=th.SIDEBAR_BG,
            fg=th.FG_SECONDARY,
            anchor="w",
        ).pack(fill="x", padx=8, pady=(0, 6))

        # Nav buttons
        for page_name in _FRAME_CLASSES:
            self._make_nav_item(sidebar, page_name)

        # Spacer pushes version label to bottom
        tk.Frame(sidebar, bg=th.SIDEBAR_BG).pack(fill="both", expand=True)

        tk.Label(
            sidebar,
            text=f"v{APP_VERSION}",
            font=th.FONT_SMALL,
            bg=th.SIDEBAR_BG,
            fg=th.FG_SECONDARY,
        ).pack(pady=(0, 16))

    def _make_nav_item(self, parent: tk.Frame, page_name: str) -> None:
        """Create one sidebar navigation button for *page_name*."""
        icon = _NAV_ICONS.get(page_name, "•")
        text = f"  {icon}  {page_name}"

        label = tk.Label(
            parent,
            text=text,
            font=th.FONT_BODY,
            bg=th.SIDEBAR_ITEM_BG,
            fg=th.SIDEBAR_FG,
            anchor="w",
            padx=12,
            pady=10,
            cursor="hand2",
        )
        label.pack(fill="x", padx=6, pady=2)

        label.bind("<Button-1>", lambda _e, p=page_name: self.show_frame(p))
        label.bind("<Enter>", lambda _e, lbl=label, p=page_name: self._on_nav_hover(lbl, p, True))
        label.bind("<Leave>", lambda _e, lbl=label, p=page_name: self._on_nav_hover(lbl, p, False))

        self._nav_buttons[page_name] = label

    def _on_nav_hover(self, label: tk.Label, page_name: str, hovering: bool) -> None:
        if page_name == self._active_page:
            return
        label.configure(bg=th.BG_HOVER if hovering else th.SIDEBAR_ITEM_BG)

    def _build_content_area(self) -> None:
        """Create the right-side content container."""
        self._content = tk.Frame(self, bg=th.BG_DARK)
        self._content.grid(row=0, column=1, sticky="nsew")
        self._content.columnconfigure(0, weight=1)
        self._content.rowconfigure(0, weight=1)

    def _build_status_bar(self) -> None:
        """Create a thin status bar along the bottom."""
        bar = tk.Frame(self, bg=th.BG_PANEL, height=28)
        bar.grid(row=1, column=0, columnspan=2, sticky="ew")

        self._status_var = tk.StringVar(value="Ready")
        tk.Label(
            bar,
            textvariable=self._status_var,
            font=th.FONT_SMALL,
            bg=th.BG_PANEL,
            fg=th.FG_SECONDARY,
            anchor="w",
        ).pack(side="left", padx=12)

        # Date + time on the right
        self._clock_var = tk.StringVar(value="")
        tk.Label(
            bar,
            textvariable=self._clock_var,
            font=th.FONT_SMALL,
            bg=th.BG_PANEL,
            fg=th.FG_ACCENT,
            anchor="e",
        ).pack(side="right", padx=12)

        # Profile name label (centre)
        self._profile_var = tk.StringVar(value="")
        tk.Label(
            bar,
            textvariable=self._profile_var,
            font=th.FONT_SMALL,
            bg=th.BG_PANEL,
            fg=th.FG_GOLD,
            anchor="center",
        ).pack(side="right", padx=24)

    # ------------------------------------------------------------------
    # Startup helpers
    # ------------------------------------------------------------------

    def _record_startup_snapshot(self) -> None:
        """Record a daily portfolio snapshot in a background thread."""
        import threading
        def _worker():
            try:
                from db.database import get_session
                from services.portfolio import record_snapshot
                with get_session() as session:
                    record_snapshot(session)
            except Exception as exc:
                import logging
                logging.getLogger(__name__).warning("Snapshot failed: %s", exc)
        threading.Thread(target=_worker, daemon=True).start()

    def _check_profile(self) -> None:
        """On first run (no DOB set), prompt the user to enter their profile."""
        try:
            from db.database import get_session
            from services.portfolio import get_or_create_profile
            with get_session() as session:
                profile = get_or_create_profile(session)
                has_dob  = profile.date_of_birth is not None
                has_name = bool(profile.name)
        except Exception:
            return

        if not has_dob or not has_name:
            _ProfileDialog(self, on_save=self._on_profile_saved)
        else:
            self._refresh_profile_bar(profile.name, profile.exact_age)

    def _on_profile_saved(self) -> None:
        """Called after the profile dialog saves."""
        try:
            from db.database import get_session
            from services.portfolio import get_or_create_profile
            with get_session() as session:
                profile = get_or_create_profile(session)
            self._refresh_profile_bar(profile.name, profile.exact_age)
        except Exception:
            pass

    def _refresh_profile_bar(self, name: str, age: float) -> None:
        next_bday = ""
        try:
            from db.database import get_session
            from services.portfolio import get_or_create_profile
            with get_session() as session:
                profile = get_or_create_profile(session)
            if profile.next_birthday:
                from datetime import date
                days = (profile.next_birthday - date.today()).days
                next_bday = f"  🎂 {days}d"
        except Exception:
            pass
        self._profile_var.set(f"👤 {name}  •  Age {age:.1f}{next_bday}")

    def _tick_clock(self) -> None:
        """Update the clock label every second."""
        from datetime import datetime
        now = datetime.now()
        self._clock_var.set(now.strftime("%a %b %d, %Y   %I:%M:%S %p"))
        self.after(1000, self._tick_clock)

    # ------------------------------------------------------------------
    # Frame switching
    # ------------------------------------------------------------------

    def show_frame(self, page_name: str) -> None:
        """
        Switch the visible content frame to *page_name*.

        Frames are instantiated lazily on first visit and then cached.
        """
        if page_name == self._active_page:
            return

        # Highlight the selected nav item
        for name, lbl in self._nav_buttons.items():
            if name == page_name:
                lbl.configure(bg=th.SIDEBAR_SEL_BG, fg=th.SIDEBAR_SEL_FG)
            else:
                lbl.configure(bg=th.SIDEBAR_ITEM_BG, fg=th.SIDEBAR_FG)

        self._active_page = page_name

        # Hide current frame
        for frame in self._frame_cache.values():
            frame.grid_remove()

        # Get or create the requested frame
        if page_name not in self._frame_cache:
            try:
                cls = _import_frame_class(_FRAME_CLASSES[page_name])
                frame = cls(self._content, app=self)
                frame.grid(row=0, column=0, sticky="nsew")
                self._frame_cache[page_name] = frame
            except Exception as exc:
                mb.showerror("Error", f"Could not load {page_name}:\n{exc}")
                return
        else:
            frame = self._frame_cache[page_name]
            frame.grid()
            # Refresh data on revisit if the frame supports it
            if hasattr(frame, "refresh"):
                frame.refresh()

        self.set_status(f"{page_name}")

    # ------------------------------------------------------------------
    # Status bar helpers
    # ------------------------------------------------------------------

    def set_status(self, message: str) -> None:
        """Update the bottom status bar text."""
        self._status_var.set(message)

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def _on_close(self) -> None:
        """Gracefully shut down the scheduler and close the window."""
        try:
            from services.scheduler import stop_scheduler
            stop_scheduler()
        except Exception:
            pass
        self.destroy()


# ---------------------------------------------------------------------------
# Profile setup dialog
# ---------------------------------------------------------------------------

class _ProfileDialog(tk.Toplevel):
    """
    First-run dialog to collect the user's name and date of birth.
    DOB is used to compute exact age for projection accuracy.
    """

    def __init__(self, parent: tk.Tk, on_save) -> None:
        super().__init__(parent)
        self._on_save = on_save
        self.title("Welcome — Set Up Your Profile")
        self.resizable(False, False)
        self.configure(bg=th.BG_PANEL)
        self.grab_set()
        self._build()

    def _build(self) -> None:
        pad = {"padx": 20, "pady": 6}

        tk.Label(self, text="👤  Your Profile", font=th.FONT_H3,
                 bg=th.BG_PANEL, fg=th.FG_PRIMARY).grid(
            row=0, column=0, columnspan=2, sticky="w", padx=20, pady=(16, 4))
        tk.Label(self,
                 text="This is used to compute your exact age for projection accuracy.",
                 font=th.FONT_SMALL, bg=th.BG_PANEL, fg=th.FG_SECONDARY,
                 wraplength=340).grid(row=1, column=0, columnspan=2, sticky="w", padx=20, pady=(0, 12))

        tk.Label(self, text="Your Name", font=th.FONT_BODY,
                 bg=th.BG_PANEL, fg=th.FG_SECONDARY).grid(row=2, column=0, sticky="w", **pad)
        self._name_var = tk.StringVar()
        ttk.Entry(self, textvariable=self._name_var, width=28).grid(row=2, column=1, sticky="w", **pad)

        tk.Label(self, text="Date of Birth (YYYY-MM-DD)", font=th.FONT_BODY,
                 bg=th.BG_PANEL, fg=th.FG_SECONDARY).grid(row=3, column=0, sticky="w", **pad)
        self._dob_var = tk.StringVar()
        ttk.Entry(self, textvariable=self._dob_var, width=28).grid(row=3, column=1, sticky="w", **pad)

        self._err_var = tk.StringVar()
        tk.Label(self, textvariable=self._err_var, font=th.FONT_SMALL,
                 bg=th.BG_PANEL, fg=th.FG_DANGER).grid(
            row=4, column=0, columnspan=2, sticky="w", padx=20)

        btn_row = tk.Frame(self, bg=th.BG_PANEL)
        btn_row.grid(row=5, column=0, columnspan=2, pady=16)
        ttk.Button(btn_row, text="Save Profile", style="Primary.TButton",
                   command=self._save).pack(side="left", padx=6)
        ttk.Button(btn_row, text="Skip for Now", command=self.destroy).pack(side="left", padx=6)

    def _save(self) -> None:
        from datetime import datetime
        name = self._name_var.get().strip()
        dob_str = self._dob_var.get().strip()
        if not name:
            self._err_var.set("Please enter your name.")
            return
        try:
            dob = datetime.strptime(dob_str, "%Y-%m-%d").date()
        except ValueError:
            self._err_var.set("Date must be YYYY-MM-DD (e.g. 1995-03-14)")
            return
        try:
            from db.database import get_session
            from services.portfolio import save_profile
            with get_session() as session:
                save_profile(session, name, dob)
        except Exception as exc:
            self._err_var.set(f"Save failed: {exc}")
            return
        self._on_save()
        self.destroy()
