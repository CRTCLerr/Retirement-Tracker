"""
gui/theme.py
============
Dark-blue colour scheme, font definitions, and style helpers for the
Retirement Tracker Tkinter UI.

All widgets should pull colours and fonts from the constants here so the
look can be updated in one place.
"""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

# ---------------------------------------------------------------------------
# Colour palette
# ---------------------------------------------------------------------------

# Backgrounds
BG_DARK   = "#0d1117"   # deepest background (main window)
BG_PANEL  = "#161b22"   # card / panel background
BG_ENTRY  = "#21262d"   # input field background
BG_HOVER  = "#1f2937"   # button / row hover

# Sidebar
SIDEBAR_BG       = "#0a0f14"
SIDEBAR_ITEM_BG  = "#0a0f14"
SIDEBAR_SEL_BG   = "#1d4ed8"   # selected nav item
SIDEBAR_FG       = "#94a3b8"
SIDEBAR_SEL_FG   = "#ffffff"

# Text
FG_PRIMARY   = "#e2e8f0"   # primary text
FG_SECONDARY = "#94a3b8"   # muted / label text
FG_ACCENT    = "#3b82f6"   # bright blue accent
FG_SUCCESS   = "#22c55e"   # green
FG_DANGER    = "#ef4444"   # red
FG_WARNING   = "#f59e0b"   # amber
FG_GOLD      = "#fbbf24"   # dividend gold

# Borders / separators
BORDER      = "#30363d"
BORDER_DARK = "#21262d"

# Chart colours
CHART_BG    = "#0d1117"
CHART_GRID  = "#21262d"
CHART_LINE1 = "#3b82f6"   # median
CHART_LINE2 = "#22c55e"   # p90
CHART_LINE3 = "#ef4444"   # p10
CHART_FILL  = "#1d3a6e"   # MC band fill

# Buttons
BTN_PRIMARY_BG   = "#1d4ed8"
BTN_PRIMARY_FG   = "#ffffff"
BTN_SECONDARY_BG = "#21262d"
BTN_SECONDARY_FG = "#e2e8f0"
BTN_DANGER_BG    = "#7f1d1d"
BTN_DANGER_FG    = "#fca5a5"

# Treeview alternating rows
TREE_ODD  = "#161b22"
TREE_EVEN = "#1a2233"
TREE_SEL  = "#1e3a5f"

# ---------------------------------------------------------------------------
# Font names (loaded lazily after Tk root exists)
# ---------------------------------------------------------------------------

FONT_FAMILY = "Segoe UI"   # falls back to TkDefaultFont on non-Windows

FONT_H1        = (FONT_FAMILY, 22, "bold")
FONT_H2        = (FONT_FAMILY, 16, "bold")
FONT_H3        = (FONT_FAMILY, 13, "bold")
FONT_BODY      = (FONT_FAMILY, 11)
FONT_BODY_BOLD = (FONT_FAMILY, 11, "bold")
FONT_SMALL     = (FONT_FAMILY, 9)
FONT_MONO      = ("Consolas", 10)

# ---------------------------------------------------------------------------
# ttk Style setup
# ---------------------------------------------------------------------------

def apply_theme(root: tk.Tk) -> None:
    """
    Apply the dark-blue theme to *root* and configure all ttk styles.

    Call once immediately after creating the Tk root window.
    """
    root.configure(bg=BG_DARK)

    style = ttk.Style(root)

    # Use the built-in "clam" theme as a base — it exposes the most options
    style.theme_use("clam")

    # ------------------------------------------------------------------
    # Global defaults
    # ------------------------------------------------------------------
    style.configure(
        ".",
        background=BG_DARK,
        foreground=FG_PRIMARY,
        troughcolor=BG_ENTRY,
        bordercolor=BORDER,
        darkcolor=BG_PANEL,
        lightcolor=BG_PANEL,
        focuscolor=FG_ACCENT,
        font=FONT_BODY,
    )

    # ------------------------------------------------------------------
    # TFrame / TLabelframe
    # ------------------------------------------------------------------
    style.configure("TFrame", background=BG_DARK)
    style.configure("Panel.TFrame", background=BG_PANEL)
    style.configure("Sidebar.TFrame", background=SIDEBAR_BG)

    style.configure(
        "TLabelframe",
        background=BG_PANEL,
        foreground=FG_SECONDARY,
        bordercolor=BORDER,
        relief="flat",
    )
    style.configure("TLabelframe.Label", background=BG_PANEL, foreground=FG_ACCENT, font=FONT_H3)

    # ------------------------------------------------------------------
    # TLabel
    # ------------------------------------------------------------------
    style.configure("TLabel", background=BG_DARK, foreground=FG_PRIMARY, font=FONT_BODY)
    style.configure("Panel.TLabel", background=BG_PANEL, foreground=FG_PRIMARY)
    style.configure("Muted.TLabel", background=BG_PANEL, foreground=FG_SECONDARY, font=FONT_SMALL)
    style.configure("Accent.TLabel", background=BG_PANEL, foreground=FG_ACCENT, font=FONT_H3)
    style.configure("H1.TLabel", background=BG_DARK, foreground=FG_PRIMARY, font=FONT_H1)
    style.configure("H2.TLabel", background=BG_PANEL, foreground=FG_PRIMARY, font=FONT_H2)
    style.configure("Success.TLabel", background=BG_PANEL, foreground=FG_SUCCESS, font=FONT_BODY_BOLD)
    style.configure("Danger.TLabel", background=BG_PANEL, foreground=FG_DANGER, font=FONT_BODY_BOLD)
    style.configure("Gold.TLabel", background=BG_PANEL, foreground=FG_GOLD, font=FONT_BODY_BOLD)
    style.configure("Sidebar.TLabel", background=SIDEBAR_BG, foreground=SIDEBAR_FG, font=FONT_BODY)

    # ------------------------------------------------------------------
    # TButton
    # ------------------------------------------------------------------
    style.configure(
        "TButton",
        background=BTN_SECONDARY_BG,
        foreground=BTN_SECONDARY_FG,
        borderwidth=0,
        focusthickness=0,
        relief="flat",
        padding=(12, 6),
        font=FONT_BODY,
    )
    style.map(
        "TButton",
        background=[("active", BG_HOVER), ("pressed", BG_HOVER)],
        foreground=[("active", FG_PRIMARY)],
    )

    style.configure(
        "Primary.TButton",
        background=BTN_PRIMARY_BG,
        foreground=BTN_PRIMARY_FG,
        font=FONT_BODY_BOLD,
        padding=(14, 7),
    )
    style.map(
        "Primary.TButton",
        background=[("active", "#2563eb"), ("pressed", "#1e40af")],
    )

    style.configure(
        "Danger.TButton",
        background=BTN_DANGER_BG,
        foreground=BTN_DANGER_FG,
        padding=(12, 6),
    )
    style.map(
        "Danger.TButton",
        background=[("active", "#991b1b")],
    )

    # ------------------------------------------------------------------
    # TEntry / TSpinbox / TCombobox
    # ------------------------------------------------------------------
    style.configure(
        "TEntry",
        fieldbackground=BG_ENTRY,
        foreground=FG_PRIMARY,
        insertcolor=FG_PRIMARY,
        bordercolor=BORDER,
        relief="flat",
        padding=5,
    )
    style.map("TEntry", bordercolor=[("focus", FG_ACCENT)])

    style.configure(
        "TSpinbox",
        fieldbackground=BG_ENTRY,
        foreground=FG_PRIMARY,
        arrowcolor=FG_SECONDARY,
        bordercolor=BORDER,
        relief="flat",
    )

    style.configure(
        "TCombobox",
        fieldbackground=BG_ENTRY,
        background=BG_ENTRY,
        foreground=FG_PRIMARY,
        arrowcolor=FG_SECONDARY,
        bordercolor=BORDER,
        selectbackground=BG_ENTRY,
        selectforeground=FG_PRIMARY,
    )
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", BG_ENTRY)],
        foreground=[("readonly", FG_PRIMARY)],
    )

    # ------------------------------------------------------------------
    # TScrollbar
    # ------------------------------------------------------------------
    style.configure(
        "TScrollbar",
        background=BG_PANEL,
        troughcolor=BG_DARK,
        arrowcolor=FG_SECONDARY,
        bordercolor=BORDER,
        relief="flat",
        width=10,
    )

    # ------------------------------------------------------------------
    # Treeview
    # ------------------------------------------------------------------
    style.configure(
        "Treeview",
        background=TREE_ODD,
        fieldbackground=TREE_ODD,
        foreground=FG_PRIMARY,
        rowheight=28,
        bordercolor=BORDER,
        relief="flat",
        font=FONT_BODY,
    )
    style.configure(
        "Treeview.Heading",
        background=BG_PANEL,
        foreground=FG_SECONDARY,
        relief="flat",
        font=FONT_BODY_BOLD,
        borderwidth=0,
    )
    style.map(
        "Treeview",
        background=[("selected", TREE_SEL)],
        foreground=[("selected", FG_PRIMARY)],
    )
    style.map(
        "Treeview.Heading",
        background=[("active", BG_HOVER)],
    )

    # ------------------------------------------------------------------
    # Notebook (tabs)
    # ------------------------------------------------------------------
    style.configure(
        "TNotebook",
        background=BG_DARK,
        bordercolor=BORDER,
        tabmargins=(0, 0, 0, 0),
    )
    style.configure(
        "TNotebook.Tab",
        background=BG_PANEL,
        foreground=FG_SECONDARY,
        padding=(16, 8),
        font=FONT_BODY,
    )
    style.map(
        "TNotebook.Tab",
        background=[("selected", BG_DARK), ("active", BG_HOVER)],
        foreground=[("selected", FG_ACCENT), ("active", FG_PRIMARY)],
    )

    # ------------------------------------------------------------------
    # Separator
    # ------------------------------------------------------------------
    style.configure("TSeparator", background=BORDER)

    # ------------------------------------------------------------------
    # Progressbar
    # ------------------------------------------------------------------
    style.configure(
        "TProgressbar",
        troughcolor=BG_ENTRY,
        background=FG_ACCENT,
        bordercolor=BORDER,
        thickness=8,
    )


# ---------------------------------------------------------------------------
# Utility widget factory functions
# ---------------------------------------------------------------------------

def card_frame(parent: tk.Widget, **kwargs) -> ttk.Frame:
    """Return a styled panel/card frame."""
    defaults = {"style": "Panel.TFrame", "padding": 16}
    defaults.update(kwargs)
    return ttk.Frame(parent, **defaults)


def section_label(parent: tk.Widget, text: str, **kwargs) -> ttk.Label:
    """Return a bold section-heading label."""
    return ttk.Label(parent, text=text, style="H2.TLabel", **kwargs)


def muted_label(parent: tk.Widget, text: str, **kwargs) -> ttk.Label:
    """Return a small muted helper label."""
    return ttk.Label(parent, text=text, style="Muted.TLabel", **kwargs)


def metric_label(parent: tk.Widget, text: str, **kwargs) -> ttk.Label:
    """Return a large metric-value label (accent blue, H2 size)."""
    return ttk.Label(parent, text=text, style="Accent.TLabel", **kwargs)


def primary_button(parent: tk.Widget, text: str, command=None, **kwargs) -> ttk.Button:
    """Return a primary (blue) action button."""
    return ttk.Button(parent, text=text, command=command, style="Primary.TButton", **kwargs)


def danger_button(parent: tk.Widget, text: str, command=None, **kwargs) -> ttk.Button:
    """Return a danger (red) action button."""
    return ttk.Button(parent, text=text, command=command, style="Danger.TButton", **kwargs)
