# Retirement Tracker

Retirement tracking and projection desktop app built with Python + Tkinter.

## Local one-file build (Windows)

```powershell
pip install -r requirements.txt
python pyinstaller.py
```

This creates:
- `dist/RetirementTracker.exe`
- a copy on your Desktop (`~/Desktop/RetirementTracker.exe`)

## Release workflow

GitHub Actions builds a Windows `.exe` and attaches it to Releases on version tags.

Create a version tag:

```powershell
git tag v1.0.0
git push origin v1.0.0
```

The workflow file is at:
- `.github/workflows/release-windows-exe.yml`
