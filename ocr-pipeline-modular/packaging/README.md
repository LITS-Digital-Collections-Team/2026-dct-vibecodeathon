# Packaging the "OCR Pipeline" app

`build_app.py` freezes `gui.py` and each numbered pipeline script into a
single self-contained app (a `.app` on macOS, a folder with an `.exe` on
Windows) that runs without installing Python, PySide6, or any pip package.
Tesseract and the `claude` CLI are still external tools it looks up on
PATH -- neither is bundled.

## Why each script is frozen separately

`gui.py` normally runs each step by calling `sys.executable
<script>.py` (see `ProcessRunner.run()` in `gui.py`). A frozen `gui.py`'s
own `sys.executable` is its own frozen binary, not a Python interpreter, so
it can't be reused to run an arbitrary `.py` file. `build_app.py` instead
freezes `01_image_prep.py` through `05_pdf_merge.py` into their own
executables and nests them next to the frozen GUI executable, at
`<app-dir>/<script-stem>/<script-stem>[.exe]`. `gui.py`'s
`frozen_sibling_executable()` looks them up by that same convention at
runtime, when `sys.frozen` is set.

## Building locally

```bash
pip install -r requirements.txt -r packaging/requirements-build.txt
python packaging/build_app.py --dist-dir packaging/dist
```

Produces `packaging/dist/OCR Pipeline.app` (macOS) or `packaging/dist/OCR
Pipeline/` (Windows). Both are gitignored -- this is a build output, not a
tracked artifact.

## Releasing via GitHub Actions

`.github/workflows/ocr-pipeline-release.yml` builds both platforms and
publishes them as GitHub Release assets whenever a tag matching
`ocr-pipeline-v*` is pushed:

```bash
git tag ocr-pipeline-v1.0.0
git push origin ocr-pipeline-v1.0.0
```
