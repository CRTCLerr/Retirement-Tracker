"""
pyinstaller.py
==============
Build helper for creating a one-file Windows executable.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

import PyInstaller.__main__


def _build(onefile: bool = True, clean: bool = True) -> Path:
    """Run PyInstaller and return the produced executable path."""
    args = [
        "main.py",
        "--name=RetirementTracker",
        "--noconfirm",
        "--windowed",
        "--hidden-import=tkinter",
        "--hidden-import=PIL._tkinter_finder",
        "--collect-submodules=matplotlib",
        "--collect-data=matplotlib",
    ]
    if onefile:
        args.append("--onefile")
    if clean:
        args.append("--clean")

    PyInstaller.__main__.run(args)
    return Path("dist") / "RetirementTracker.exe"


def _copy_to_desktop(exe_path: Path) -> Path:
    """Copy the built executable to the current user's desktop."""
    desktop = Path.home() / "Desktop"
    desktop.mkdir(parents=True, exist_ok=True)
    target = desktop / exe_path.name
    shutil.copy2(exe_path, target)
    return target


def main() -> None:
    """Build one-file executable and optionally copy it to Desktop."""
    parser = argparse.ArgumentParser(description="Build Retirement Tracker executable")
    parser.add_argument("--no-desktop-copy", action="store_true", help="Do not copy exe to Desktop")
    parser.add_argument("--no-clean", action="store_true", help="Skip PyInstaller --clean")
    parser.add_argument("--onedir", action="store_true", help="Build one-dir bundle instead of one-file")
    args = parser.parse_args()

    exe_path = _build(onefile=not args.onedir, clean=not args.no_clean)
    print(f"Build complete: {exe_path.resolve()}")

    if not args.no_desktop_copy and exe_path.exists():
        target = _copy_to_desktop(exe_path)
        print(f"Copied to Desktop: {target}")


if __name__ == "__main__":
    main()
