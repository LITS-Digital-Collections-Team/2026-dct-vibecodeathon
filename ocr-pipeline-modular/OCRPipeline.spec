# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build for the modular OCR pipeline GUI.

Build with:  pyinstaller --noconfirm OCRPipeline.spec

Produces a one-directory build (dist/OCRPipeline/). That is deliberate rather
than --onefile: the GUI runs each pipeline step by re-invoking itself in runner
mode, and a --onefile build re-extracts its entire payload on every launch, so
every step run would pay that cost again.

Two things this build does NOT include, because they are separate native
programs rather than Python packages -- see BUILD.md:
  * Tesseract, used by --engine tesseract/auto
  * the `claude` CLI, used by --engine claude-vision and --backend cli
"""

from PyInstaller.utils.hooks import collect_submodules

# The four step scripts ride along as data files, not as imported modules:
# their filenames start with digits, so `import 02_ocr_extract` is not even
# valid Python. gui.py's runner mode loads them from the bundle by path.
STEP_SCRIPTS = [
    "01_image_prep.py",
    "02_ocr_extract.py",
    "03_text_correct.py",
    "04_pdf_assemble.py",
]

# PyInstaller never parses files shipped as data, so it cannot discover what
# the step scripts import. Every third-party module they pull in at runtime has
# to be declared here by hand, or the build succeeds and then dies with an
# ImportError the first time a step runs. Keep in sync with requirements.txt.
#   01: PIL          02: PIL, pytesseract, google.cloud.vision
#   03: anthropic    04: fitz (pymupdf)
HIDDEN_IMPORTS = [
    "PIL",
    "PIL.Image",
    "pytesseract",
    "fitz",
    "anthropic",
    "dotenv",
]

# google.cloud.vision resolves through a namespace package and lazily imports
# its generated protobuf modules, which PyInstaller's static analysis misses.
# It is the one optional dependency here, so a build environment without it
# should still produce a working exe -- just one where --engine gcv is absent.
try:
    _gcv = collect_submodules("google.cloud.vision")
except Exception as _e:  # not installed, or an import error while walking it
    _gcv = []
    print(f"[OCRPipeline.spec] WARNING: google-cloud-vision unavailable ({_e}); "
          f"the built app will not support --engine gcv")
if _gcv:
    HIDDEN_IMPORTS += _gcv
else:
    print("[OCRPipeline.spec] WARNING: no google.cloud.vision submodules collected; "
          "--engine gcv will not work in this build")

# Qt ships far more than this GUI touches. Dropping the big unused pieces keeps
# the build to a sane size; QtWidgets/QtCore/QtGui are pulled in as needed.
EXCLUDES = [
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.QtQuick", "PySide6.QtQuick3D", "PySide6.QtQml", "PySide6.Qt3DCore",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtCharts",
    "PySide6.QtDataVisualization", "PySide6.QtBluetooth", "PySide6.QtDesigner",
    "tkinter", "matplotlib", "pandas", "pytest",
]

a = Analysis(
    ["gui.py"],
    pathex=["."],
    binaries=[],
    datas=[(script, ".") for script in STEP_SCRIPTS],
    hiddenimports=HIDDEN_IMPORTS,
    hookspath=[],
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="OCRPipeline",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # No console window: this is a GUI app, and the steps it spawns write to a
    # pipe rather than a terminal. gui.py's _ensure_std_streams covers the fact
    # that a windowed build can start with sys.stdout unset.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="OCRPipeline",
)
