# Building a Windows exe

The GUI can be packaged into a standalone Windows build so users don't need
Python installed. PyInstaller **cannot cross-compile** — a Windows binary has
to be produced on Windows — so the supported route is the
`Build Windows exe` GitHub Actions workflow.

## What the user still has to install

The exe bundles Python and every Python dependency. It does **not** bundle the
two native programs the pipeline shells out to, because neither is a Python
package:

| Needed for | Program | Notes |
|---|---|---|
| `--engine tesseract`, `--engine auto` | **Tesseract OCR** | Must be on `PATH` |
| `--engine claude-vision`, Step 3 `--backend cli` | **`claude` CLI** | Found via `shutil.which("claude")`; needs `claude /login` once |
| `--engine gcv` | *(none)* | Bundled, but needs `GOOGLE_APPLICATION_CREDENTIALS` — see `GCV_SETUP.md` |

Step 3's `--backend api` needs `ANTHROPIC_API_KEY` instead.

## Getting a build

1. Actions tab → **Build Windows exe** → **Run workflow**, or push a tag
   matching `ocr-pipeline-v*`.
2. Download the **OCRPipeline-windows** artifact and unzip it.
3. Run `OCRPipeline.exe` from the unzipped folder.

Keep the folder together — this is a one-directory build, not a single file
(see *Why one-directory* below). Outputs and `logs/claude_usage.jsonl` are
written next to the exe, so unzip it somewhere writable, not `Program Files`.

## Building by hand

On a Windows machine with Python 3.12:

```
cd ocr-pipeline-modular
pip install -r requirements.txt pyinstaller
pyinstaller --noconfirm OCRPipeline.spec
```

The result is `dist\OCRPipeline\`. The same command works on macOS and Linux
and produces a native build for that OS, which is useful for checking the
packaging itself even when you need a Windows artifact.

## How the frozen build runs pipeline steps

Worth understanding before changing `gui.py`, because the obvious code is wrong
once frozen.

In a source checkout the GUI runs a step as `sys.executable
02_ocr_extract.py …` over `QProcess`. In a frozen build `sys.executable` **is
the app**, so that would just relaunch the GUI. Instead the GUI re-invokes
itself in *runner mode*:

```
OCRPipeline.exe --run-step 02_ocr_extract.py --input-dir … --output-dir …
```

`gui.py:main()` intercepts `--run-step` before any Qt object is created, and
`run_step()` loads that script from the bundle and calls its `main()`. Each step
still gets its own process, so live log streaming, exit codes, and a step crash
not taking the window down all behave as they do from source.

Two consequences to keep in mind:

- **The step scripts ship as bundled *data*, not modules.** Their filenames
  start with digits, so `import 02_ocr_extract` isn't valid Python. PyInstaller
  therefore never parses them and cannot discover their imports — every
  third-party module they use has to be listed in `HIDDEN_IMPORTS` in
  `OCRPipeline.spec`. A missing entry builds fine and fails at run time, which
  is why CI runs a real step instead of only checking that the build finished.
- **`--run-step` takes an allowlist.** Only the four known step filenames are
  accepted; anything else exits 2.

### Why one-directory

`--onefile` re-extracts the whole payload on every launch. Since the GUI
launches itself once per step run, that cost would be paid again for every
step. One-directory keeps startup cheap.

### `APP_DIR` vs `BUNDLE_DIR`

`utils.py` exposes both, and they are the same directory only in a checkout:

- `BUNDLE_DIR` — PyInstaller's `sys._MEIPASS`, the read-only payload, **deleted
  on exit**. The step scripts live here.
- `APP_DIR` — the folder the exe sits in. Writable, visible, persistent.
  Anything worth keeping goes here, including `logs/claude_usage.jsonl` and
  user-entered relative paths.

Writing anything durable under `BUNDLE_DIR` means losing it when the app exits.

### No console

The build sets `console=False`, so it's a GUI-subsystem binary with no console
window. It writes nothing to a terminal you launch it from — output goes to the
GUI's log pane. Assert on exit codes and files when scripting it, not on stdout.
`_ensure_std_streams()` in `gui.py` rebinds `sys.stdout`/`sys.stderr`, which a
windowed build can otherwise leave as `None`.
