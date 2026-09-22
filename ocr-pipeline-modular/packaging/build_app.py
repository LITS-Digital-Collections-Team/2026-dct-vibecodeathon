#!/usr/bin/env python3
"""Build the "OCR Pipeline" app as a self-contained frozen bundle.

gui.py normally runs each numbered pipeline script as `sys.executable
<script>.py` (see ProcessRunner.run() in gui.py). A frozen gui.py can't do
that -- its own sys.executable is the frozen binary itself, not a Python
interpreter, so it can't be reused to run an arbitrary .py file. Instead,
this freezes each numbered script as its own executable with PyInstaller,
then nests those alongside the frozen gui executable inside its app folder,
so the whole thing ships as one directory (a double-clickable .app on
macOS, or "OCR Pipeline.exe" + its folder on Windows) that a user can run
without installing Python, PySide6, or any pip package -- Tesseract and the
`claude` CLI remain external tools the app looks up on PATH, same as today.

gui.py's frozen_sibling_executable() finds these by convention: given the
running app's own directory (the folder containing its executable), each
script "NN_name.py" has a sibling executable at "<app-dir>/NN_name/NN_name"
(plus ".exe" on Windows).

Usage:
    python packaging/build_app.py [--dist-dir DIST]

Requires `pyinstaller` (see packaging/requirements-build.txt) and this
project's own requirements.txt installed in the current environment.
"""

import argparse
import platform
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
APP_NAME = "OCR Pipeline"
SCRIPT_STEMS = [
    "01_image_prep",
    "02_ocr_extract",
    "03_text_correct",
    "04_pdf_assemble",
    "05_pdf_merge",
]


def run_pyinstaller(entry_point: Path, name: str, work_root: Path, windowed: bool) -> None:
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--onedir",
        "--name", name,
        "--distpath", str(work_root / "dist"),
        "--workpath", str(work_root / "build"),
        "--specpath", str(work_root),
    ]
    if windowed:
        cmd.append("--windowed")
    cmd.append(str(entry_point))
    subprocess.run(cmd, cwd=PROJECT_DIR, check=True)


def gui_app_dir(gui_dist_root: Path) -> Path:
    """Directory containing the frozen gui executable -- where sys.executable
    resolves to at runtime, and where sibling script folders must live."""
    system = platform.system()
    if system == "Darwin":
        return gui_dist_root / f"{APP_NAME}.app" / "Contents" / "MacOS"
    return gui_dist_root / APP_NAME


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dist-dir", type=Path, default=PROJECT_DIR / "packaging" / "dist",
        help="Where to place the final packaged app (default: packaging/dist)"
    )
    args = parser.parse_args()

    work_root = PROJECT_DIR / "packaging" / "_build"
    if work_root.exists():
        shutil.rmtree(work_root)
    work_root.mkdir(parents=True)

    # Freeze each numbered script into its own onedir bundle first.
    script_dist_roots = {}
    for stem in SCRIPT_STEMS:
        script_work = work_root / stem
        print(f"--- Building {stem} ---", flush=True)
        run_pyinstaller(PROJECT_DIR / f"{stem}.py", stem, script_work, windowed=False)
        script_dist_roots[stem] = script_work / "dist" / stem

    # Freeze the GUI itself.
    gui_work = work_root / "gui"
    print("--- Building OCR Pipeline (GUI) ---", flush=True)
    run_pyinstaller(PROJECT_DIR / "gui.py", APP_NAME, gui_work, windowed=True)
    app_dir = gui_app_dir(gui_work / "dist")
    if not app_dir.exists():
        raise SystemExit(f"Expected frozen GUI output at {app_dir}, but it doesn't exist")

    # Nest each script's onedir bundle as a subfolder next to the GUI
    # executable, matching gui.py's frozen_sibling_executable() lookup.
    for stem, script_dist in script_dist_roots.items():
        target = app_dir / stem
        print(f"--- Nesting {stem} into {target} ---", flush=True)
        shutil.copytree(script_dist, target)

    args.dist_dir.mkdir(parents=True, exist_ok=True)
    if platform.system() == "Darwin":
        final_path = args.dist_dir / f"{APP_NAME}.app"
        if final_path.exists():
            shutil.rmtree(final_path)
        shutil.copytree(gui_work / "dist" / f"{APP_NAME}.app", final_path)
    else:
        final_path = args.dist_dir / APP_NAME
        if final_path.exists():
            shutil.rmtree(final_path)
        shutil.copytree(gui_work / "dist" / APP_NAME, final_path)

    shutil.rmtree(work_root)
    print(f"\nBuilt {final_path}")


if __name__ == "__main__":
    main()
