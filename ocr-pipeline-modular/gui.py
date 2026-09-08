#!/usr/bin/env python3
"""GUI for the modular OCR pipeline.

One window, one tab per step. Steps 1, 2, and the automatic (Claude API)
mode of step 3, and step 4 run the existing CLI scripts via QProcess and
stream their log output live. Step 3 also offers a manual review dialog
that reads/writes the same OCR JSON format without needing an API key.
"""

import importlib.util
import io
import os
import sys
from pathlib import Path
from typing import List, Optional

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QTextEdit, QFileDialog, QGroupBox,
    QTabWidget, QFormLayout, QDialog, QDialogButtonBox, QCheckBox,
    QScrollArea, QDoubleSpinBox, QSpinBox, QComboBox, QMessageBox,
)
from PySide6.QtCore import Qt, QProcess, QProcessEnvironment, Signal, QObject
from PySide6.QtGui import QFont, QColor, QTextCursor, QPixmap, QPainter, QPen

from utils import OCRDataHandler, TextBlock, APP_DIR, BUNDLE_DIR, IS_FROZEN

# User-entered relative paths resolve against the folder the app runs from,
# which is the pipeline directory in a checkout and the .exe's folder when
# frozen -- never the temp bundle, which vanishes on exit.
SCRIPT_DIR = APP_DIR
PYTHON_EXE = sys.executable

# The four steps this GUI can run. Also the allowlist for runner mode below,
# so a stray --run-step argument can't be pointed at anything else.
STEP_SCRIPTS = (
    "01_image_prep.py",
    "02_ocr_extract.py",
    "03_text_correct.py",
    "04_pdf_assemble.py",
)

# Internal flag that puts this program in runner mode instead of showing the
# GUI. Only a frozen build uses it -- see ProcessRunner.run and run_step.
RUN_STEP_FLAG = "--run-step"


def resolve_path(value: str) -> Path:
    """Resolve a user-entered path relative to the pipeline directory."""
    p = Path(value)
    return p if p.is_absolute() else (SCRIPT_DIR / p)


# ---------------------------------------------------------------------------
# Shared widgets
# ---------------------------------------------------------------------------

class LogConsole(QTextEdit):
    """Read-only, auto-scrolling console for subprocess output."""

    def __init__(self):
        super().__init__()
        self.setReadOnly(True)
        self.setFont(QFont("Menlo", 11))
        self.setLineWrapMode(QTextEdit.NoWrap)
        self.setMinimumHeight(220)

    def write_line(self, text: str) -> None:
        if not text:
            return
        color = QColor("white")
        if " ERROR " in text or text.startswith("ERROR"):
            color = QColor("#ff6b6b")
        elif " WARNING " in text or text.startswith("WARNING"):
            color = QColor("#ffb84d")
        elif " INFO " in text or text.startswith("INFO"):
            color = QColor("#8fd6ff")
        self.setTextColor(color)
        self.append(text.rstrip("\n"))
        self.moveCursor(QTextCursor.End)
        self.ensureCursorVisible()


class DirPicker(QWidget):
    """Line edit + Browse button for choosing a directory."""

    def __init__(self, default: str = "", for_output: bool = False):
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.edit = QLineEdit(default)
        self.for_output = for_output
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        layout.addWidget(self.edit)
        layout.addWidget(browse)

    def _browse(self):
        start = str(resolve_path(self.edit.text() or "."))
        chosen = QFileDialog.getExistingDirectory(self, "Select directory", start)
        if chosen:
            self.edit.setText(chosen)

    def path(self) -> Path:
        return resolve_path(self.edit.text().strip())


class ProcessRunner(QObject):
    """Wraps QProcess to run one of the pipeline scripts and stream output."""

    line_output = Signal(str)
    process_finished = Signal(int)

    def __init__(self):
        super().__init__()
        self.process: Optional[QProcess] = None

    def is_running(self) -> bool:
        return self.process is not None and self.process.state() != QProcess.NotRunning

    def run(self, script: str, args: List[str]) -> None:
        if self.is_running():
            return

        # A frozen build has no interpreter to shell out to -- sys.executable
        # IS the app, so running it against a .py path would just relaunch the
        # GUI. Re-invoke ourselves in runner mode instead (see run_step). The
        # step still gets its own process, so the live log, the exit code, and
        # a crash not taking the window down all behave as before.
        step_args = [RUN_STEP_FLAG, script] if IS_FROZEN else [str(BUNDLE_DIR / script)]

        self.process = QProcess()
        self.process.setProgram(PYTHON_EXE)
        self.process.setArguments(step_args + args)
        self.process.setWorkingDirectory(str(APP_DIR))
        self.process.setProcessChannelMode(QProcess.MergedChannels)

        # _on_output decodes the child's stream as UTF-8, so make the child
        # actually emit UTF-8: on Windows it would otherwise use cp1252 and any
        # accent or curly quote in a log line would arrive as mojibake.
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONIOENCODING", "utf-8")
        self.process.setProcessEnvironment(env)

        self.process.readyReadStandardOutput.connect(self._on_output)
        self.process.finished.connect(self._on_finished)
        self.line_output.emit(f"$ {Path(PYTHON_EXE).name} {script} {' '.join(args)}")
        self.process.start()

    def _on_output(self):
        data = bytes(self.process.readAllStandardOutput()).decode("utf-8", errors="replace")
        for line in data.splitlines():
            self.line_output.emit(line)

    def _on_finished(self, exit_code: int, _status):
        self.line_output.emit(f"(exited with code {exit_code})")
        self.process_finished.emit(exit_code)


class RunnableStepTab(QWidget):
    """Base class for a tab that runs one CLI script and shows its log."""

    def __init__(self):
        super().__init__()
        self.runner = ProcessRunner()
        self.runner.line_output.connect(self._on_line)
        self.runner.process_finished.connect(self._on_finished)
        self.run_button: Optional[QPushButton] = None
        self.run_buttons: List[QPushButton] = []
        self.log = LogConsole()

    def _on_line(self, text: str) -> None:
        self.log.write_line(text)

    def _on_finished(self, _exit_code: int) -> None:
        for button in self._all_run_buttons():
            button.setEnabled(True)

    def _all_run_buttons(self) -> List[QPushButton]:
        return ([self.run_button] if self.run_button else []) + self.run_buttons

    def start_run(self, script: str, args: List[str]) -> None:
        if self.runner.is_running():
            QMessageBox.information(self, "Already running", "This step is already running.")
            return
        self.log.clear()
        for button in self._all_run_buttons():
            button.setEnabled(False)
        self.runner.run(script, args)


# ---------------------------------------------------------------------------
# Step 1: Image Prep
# ---------------------------------------------------------------------------

class ImagePrepTab(RunnableStepTab):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)

        form_box = QGroupBox("Step 1: Image Preparation (TIFF → JPG)")
        form = QFormLayout(form_box)

        self.input_dir = DirPicker("../gcv-ocr-to-pdf/stress-test")
        self.output_dir = DirPicker("prep_output")
        self.max_width = QSpinBox()
        self.max_width.setRange(100, 10000)
        self.max_width.setValue(1000)
        self.quality = QSpinBox()
        self.quality.setRange(1, 95)
        self.quality.setValue(85)
        self.recursive = QCheckBox("Recursive (scan subfolders, mirror structure into output)")

        form.addRow("Input directory:", self.input_dir)
        form.addRow("Output directory:", self.output_dir)
        form.addRow("Max width (px):", self.max_width)
        form.addRow("JPEG quality:", self.quality)
        form.addRow(self.recursive)

        self.run_button = QPushButton("Run Image Prep")
        self.run_button.clicked.connect(self._run)
        form.addRow(self.run_button)

        layout.addWidget(form_box)
        layout.addWidget(QLabel("Log:"))
        layout.addWidget(self.log)

    def _run(self):
        args = [
            "--input-dir", str(self.input_dir.path()),
            "--output-dir", str(self.output_dir.path()),
            "--max-width", str(self.max_width.value()),
            "--quality", str(self.quality.value()),
        ]
        if self.recursive.isChecked():
            args.append("--recursive")
        self.start_run("01_image_prep.py", args)


# ---------------------------------------------------------------------------
# Step 2: OCR Extraction
# ---------------------------------------------------------------------------

class OcrExtractTab(RunnableStepTab):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)

        form_box = QGroupBox("Step 2: OCR Extraction (Tesseract → GCV cascade)")
        form = QFormLayout(form_box)

        self.input_dir = DirPicker("prep_output")
        self.output_dir = DirPicker("ocr_output")
        self.engine = QComboBox()
        self.engine.addItems(["auto", "tesseract", "gcv", "claude-vision"])
        self.engine.setToolTip(
            "claude-vision: full-page transcription via Claude's vision "
            "(OAuth, no API key) -- much better on hard material like "
            "cursive handwriting, but no per-word bounding boxes, and not "
            "part of the 'auto' cascade since it's slower/heavier."
        )
        self.confidence_threshold = QDoubleSpinBox()
        self.confidence_threshold.setRange(0.0, 1.0)
        self.confidence_threshold.setSingleStep(0.05)
        self.confidence_threshold.setValue(0.75)
        self.recursive = QCheckBox("Recursive (scan subfolders, mirror structure into output)")

        form.addRow("Input directory:", self.input_dir)
        form.addRow("Output directory:", self.output_dir)
        form.addRow("Engine:", self.engine)
        form.addRow("Confidence threshold:", self.confidence_threshold)
        form.addRow(self.recursive)

        self.run_button = QPushButton("Run OCR Extraction")
        self.run_button.clicked.connect(self._run)
        form.addRow(self.run_button)

        layout.addWidget(form_box)
        layout.addWidget(QLabel("Log:"))
        layout.addWidget(self.log)

    def _run(self):
        args = [
            "--input-dir", str(self.input_dir.path()),
            "--output-dir", str(self.output_dir.path()),
            "--engine", self.engine.currentText(),
            "--confidence-threshold", str(self.confidence_threshold.value()),
        ]
        if self.recursive.isChecked():
            args.append("--recursive")
        self.start_run("02_ocr_extract.py", args)


# ---------------------------------------------------------------------------
# Step 3: Text Correction (script-based auto mode + manual review dialog)
# ---------------------------------------------------------------------------

class ReviewDialog(QDialog):
    """Shown once per low-confidence block during manual review."""

    def __init__(self, pixmap: Optional[QPixmap], block: TextBlock,
                 filename: str, block_index: int, block_total: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Review block {block_index}/{block_total} — {filename}")
        self.setMinimumWidth(720)

        self.accepted_edit = False
        self.aborted = False
        self._edited_text = block.text

        layout = QVBoxLayout(self)

        info = QLabel(f"Confidence: {block.confidence:.2f}  (threshold triggered)")
        info.setStyleSheet("font-weight: bold;")
        layout.addWidget(info)

        if pixmap is not None and not pixmap.isNull():
            annotated = self._annotate(pixmap, block)
            image_label = QLabel()
            image_label.setPixmap(annotated)
            scroll = QScrollArea()
            scroll.setWidget(image_label)
            scroll.setMaximumHeight(360)
            layout.addWidget(scroll)

            crop = self._crop(pixmap, block)
            if crop is not None:
                crop_label = QLabel()
                crop_label.setPixmap(crop)
                crop_label.setAlignment(Qt.AlignCenter)
                layout.addWidget(QLabel("Close-up of block region:"))
                layout.addWidget(crop_label)
        else:
            layout.addWidget(QLabel("(source image not found — showing text only)"))

        layout.addWidget(QLabel("OCR text (editable):"))
        self.text_edit = QTextEdit()
        self.text_edit.setPlainText(block.text)
        self.text_edit.setFont(QFont("Menlo", 12))
        self.text_edit.setMaximumHeight(100)
        layout.addWidget(self.text_edit)

        buttons = QDialogButtonBox()
        accept_btn = buttons.addButton("Accept As-Is", QDialogButtonBox.AcceptRole)
        save_btn = buttons.addButton("Save Edited Text", QDialogButtonBox.ActionRole)
        abort_btn = buttons.addButton("Stop Reviewing", QDialogButtonBox.RejectRole)

        accept_btn.clicked.connect(self.accept)
        save_btn.clicked.connect(self._save_edit)
        abort_btn.clicked.connect(self._abort)

        layout.addWidget(buttons)

    def _save_edit(self):
        self._edited_text = self.text_edit.toPlainText().strip()
        self.accepted_edit = True
        self.accept()

    def _abort(self):
        self.aborted = True
        self.reject()

    def edited_text(self) -> str:
        return self._edited_text

    @staticmethod
    def _annotate(pixmap: QPixmap, block: TextBlock, max_width: int = 680) -> QPixmap:
        scaled = pixmap.scaledToWidth(max_width, Qt.SmoothTransformation) if pixmap.width() > max_width else QPixmap(pixmap)
        scale = scaled.width() / pixmap.width()
        annotated = QPixmap(scaled)
        painter = QPainter(annotated)
        painter.setPen(QPen(QColor("red"), 2))
        painter.drawRect(int(block.x * scale), int(block.y * scale),
                          max(int(block.width * scale), 2), max(int(block.height * scale), 2))
        painter.end()
        return annotated

    @staticmethod
    def _crop(pixmap: QPixmap, block: TextBlock, margin: int = 15, zoom: int = 2) -> Optional[QPixmap]:
        x = max(0, int(block.x) - margin)
        y = max(0, int(block.y) - margin)
        w = min(pixmap.width() - x, int(block.width) + margin * 2)
        h = min(pixmap.height() - y, int(block.height) + margin * 2)
        if w <= 0 or h <= 0:
            return None
        cropped = pixmap.copy(x, y, w, h)
        return cropped.scaled(cropped.width() * zoom, cropped.height() * zoom,
                               Qt.KeepAspectRatio, Qt.SmoothTransformation)


class CorrectionTab(RunnableStepTab):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)

        form_box = QGroupBox("Step 3: Text Correction")
        form = QFormLayout(form_box)

        self.image_dir = DirPicker("prep_output")
        self.input_dir = DirPicker("ocr_output")
        self.output_dir = DirPicker("corrected_output")
        self.threshold = QDoubleSpinBox()
        self.threshold.setRange(0.0, 1.0)
        self.threshold.setSingleStep(0.05)
        self.threshold.setValue(0.8)
        self.recursive = QCheckBox("Recursive (scan subfolders, mirror structure into output)")
        self.recursive.setToolTip(
            "Also applies to Manual Review below, which will scan subfolders "
            "for *_ocr.json files."
        )

        form.addRow("Image directory (for review):", self.image_dir)
        form.addRow("OCR JSON directory:", self.input_dir)
        form.addRow("Output directory:", self.output_dir)
        form.addRow("Confidence threshold:", self.threshold)
        form.addRow(self.recursive)

        button_row = QHBoxLayout()
        self.run_button = QPushButton("Run Auto Correction (Claude API Key)")
        self.run_button.clicked.connect(self._run_auto_api)
        self.cli_run_button = QPushButton("Run Auto Correction (Claude CLI / OAuth)")
        self.cli_run_button.setToolTip(
            "Uses the `claude` CLI's non-interactive mode instead of the Anthropic "
            "SDK — reuses your existing `claude /login` session, no ANTHROPIC_API_KEY "
            "needed."
        )
        self.cli_run_button.clicked.connect(self._run_auto_cli)
        self.run_buttons.append(self.cli_run_button)
        self.review_button = QPushButton("Start Manual Review")
        self.review_button.clicked.connect(self._run_manual_review)
        button_row.addWidget(self.run_button)
        button_row.addWidget(self.cli_run_button)
        button_row.addWidget(self.review_button)
        form.addRow(button_row)

        layout.addWidget(form_box)
        layout.addWidget(QLabel("Log:"))
        layout.addWidget(self.log)

    def _run_auto(self, backend: str):
        args = [
            "--input-dir", str(self.input_dir.path()),
            "--output-dir", str(self.output_dir.path()),
            "--threshold", str(self.threshold.value()),
            "--auto",
            "--backend", backend,
        ]
        if self.recursive.isChecked():
            args.append("--recursive")
        self.start_run("03_text_correct.py", args)

    def _run_auto_api(self):
        self._run_auto("api")

    def _run_auto_cli(self):
        self._run_auto("cli")

    def _resolve_image_path(self, stored_path: str, image_dir: Path) -> Optional[Path]:
        candidate = resolve_path(stored_path)
        if candidate.exists():
            return candidate
        fallback = image_dir / Path(stored_path).name
        return fallback if fallback.exists() else None

    def _run_manual_review(self):
        if self.runner.is_running():
            QMessageBox.information(self, "Already running", "A script is currently running.")
            return

        ocr_dir = self.input_dir.path()
        output_dir = self.output_dir.path()
        image_dir = self.image_dir.path()
        threshold = self.threshold.value()

        if not ocr_dir.exists():
            QMessageBox.warning(self, "Not found", f"OCR directory not found: {ocr_dir}")
            return

        glob_fn = ocr_dir.rglob if self.recursive.isChecked() else ocr_dir.glob
        json_files = sorted(glob_fn("*_ocr.json"))
        if not json_files:
            QMessageBox.warning(self, "No files", f"No *_ocr.json files found in {ocr_dir}")
            return

        output_dir.mkdir(parents=True, exist_ok=True)
        self.log.clear()
        self.log.write_line(f"Manual review: {len(json_files)} file(s), threshold={threshold}")

        total_corrected = 0
        aborted = False

        for json_path in json_files:
            if aborted:
                break

            ocr_output = OCRDataHandler.load_json(json_path)
            image_path = self._resolve_image_path(ocr_output.image_path, image_dir)
            pixmap = QPixmap(str(image_path)) if image_path else None

            flagged = [b for b in ocr_output.blocks if b.confidence < threshold]
            self.log.write_line(f"{json_path.name}: {len(flagged)} block(s) below threshold")

            corrected_blocks = []
            for i, block in enumerate(ocr_output.blocks, start=1):
                if block.confidence < threshold and not aborted:
                    dialog = ReviewDialog(pixmap, block, json_path.name, i, len(ocr_output.blocks), self)
                    dialog.exec()
                    if dialog.aborted:
                        aborted = True
                    elif dialog.accepted_edit:
                        block.text = dialog.edited_text()
                        block.source = "corrected"
                        total_corrected += 1
                corrected_blocks.append(block)

            ocr_output.blocks = corrected_blocks
            ocr_output.metadata["correction_threshold"] = threshold
            ocr_output.metadata["auto_corrected"] = False
            ocr_output.metadata["review_method"] = "manual_gui"

            relative_dir = json_path.parent.resolve().relative_to(ocr_dir.resolve())
            target_dir = output_dir / relative_dir if str(relative_dir) != "." else output_dir
            target_dir.mkdir(parents=True, exist_ok=True)
            out_path = target_dir / f"{json_path.stem}_corrected.json"
            OCRDataHandler.save_json(ocr_output, out_path)
            self.log.write_line(f"Saved: {out_path}")

        self.log.write_line(f"Manual review complete: {total_corrected} block(s) corrected"
                             + (" (stopped early)" if aborted else ""))


# ---------------------------------------------------------------------------
# Step 4: PDF Assembly
# ---------------------------------------------------------------------------

class PdfAssembleTab(RunnableStepTab):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)

        form_box = QGroupBox("Step 4: PDF Assembly")
        form = QFormLayout(form_box)

        self.image_dir = DirPicker("prep_output")
        self.ocr_dir = DirPicker("corrected_output")
        self.output_dir = DirPicker("pdf_output")
        self.debug = QCheckBox("Debug mode (visible bounding boxes)")
        self.merge_output = QLineEdit()
        self.recursive = QCheckBox("Recursive (scan subfolders, mirror structure into output)")
        self.merge_per_folder = QCheckBox("Merge each subfolder into one PDF per folder (requires Recursive)")

        form.addRow("Image directory:", self.image_dir)
        form.addRow("OCR/corrected JSON directory:", self.ocr_dir)
        form.addRow("Output directory:", self.output_dir)
        form.addRow(self.debug)
        form.addRow("Merge into single PDF (optional filename):", self.merge_output)
        form.addRow(self.recursive)
        form.addRow(self.merge_per_folder)

        self.run_button = QPushButton("Run PDF Assembly")
        self.run_button.clicked.connect(self._run)
        form.addRow(self.run_button)

        layout.addWidget(form_box)
        layout.addWidget(QLabel("Log:"))
        layout.addWidget(self.log)

    def _run(self):
        if self.merge_per_folder.isChecked() and not self.recursive.isChecked():
            QMessageBox.warning(
                self, "Recursive required",
                "\"Merge each subfolder into one PDF per folder\" requires Recursive to be checked."
            )
            return

        args = [
            "--image-dir", str(self.image_dir.path()),
            "--ocr-dir", str(self.ocr_dir.path()),
            "--output-dir", str(self.output_dir.path()),
        ]
        if self.debug.isChecked():
            args.append("--debug")
        if self.merge_output.text().strip():
            args += ["--merge-output", self.merge_output.text().strip()]
        if self.recursive.isChecked():
            args.append("--recursive")
        if self.merge_per_folder.isChecked():
            args.append("--merge-per-folder")
        self.start_run("04_pdf_assemble.py", args)


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("OCR Pipeline")
        self.resize(920, 760)

        tabs = QTabWidget()
        tabs.addTab(ImagePrepTab(), "1. Image Prep")
        tabs.addTab(OcrExtractTab(), "2. OCR Extract")
        tabs.addTab(CorrectionTab(), "3. Correction")
        tabs.addTab(PdfAssembleTab(), "4. PDF Assemble")
        self.setCentralWidget(tabs)


def _ensure_std_streams() -> None:
    """Give this process usable UTF-8 stdout/stderr.

    A --windowed frozen build starts with no console attached, so Python can
    leave sys.stdout/sys.stderr as None. QProcess hands the child real pipes,
    so the file descriptors are fine -- rebind the streams to them rather than
    let the first log call raise. Encoding is pinned to UTF-8 to match what the
    GUI decodes with.
    """
    for name, fd in (("stdout", 1), ("stderr", 2)):
        if getattr(sys, name, None) is not None:
            continue
        try:
            stream = io.TextIOWrapper(
                io.FileIO(fd, "w"), encoding="utf-8", errors="replace",
                line_buffering=True,
            )
        except OSError:
            stream = open(os.devnull, "w", encoding="utf-8")
        setattr(sys, name, stream)


def run_step(argv: List[str]) -> int:
    """Runner mode: run one pipeline step in this process, return its exit code.

    A frozen build ships the step scripts as bundled data rather than as
    importable modules -- their filenames start with digits, so `import
    02_ocr_extract` is not even valid syntax. Load the requested one from the
    bundle by path and call its main(), with sys.argv rewritten so its own
    argparse sees exactly the flags it expects.

    Args:
        argv: The step script name followed by that step's CLI arguments

    Returns:
        The step's exit code (2 for a bad runner-mode invocation)
    """
    if not argv:
        print(f"{RUN_STEP_FLAG} needs a step script name", file=sys.stderr)
        return 2

    script, step_args = argv[0], argv[1:]
    if script not in STEP_SCRIPTS:
        print(f"Not a pipeline step: {script}", file=sys.stderr)
        return 2

    script_path = BUNDLE_DIR / script
    if not script_path.is_file():
        print(f"Step script missing from the bundle: {script_path}", file=sys.stderr)
        return 2

    _ensure_std_streams()

    module_name = f"pipeline_step_{script[:2]}"
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module

    sys.argv = [script, *step_args]
    try:
        # __name__ is module_name, not "__main__", so the script's own
        # if-main block stays dormant and main() is called explicitly.
        spec.loader.exec_module(module)
        module.main()
    except SystemExit as e:
        return int(e.code) if isinstance(e.code, int) else (0 if e.code is None else 1)
    return 0


def main():
    # Runner mode has to be handled before any Qt object exists: this process
    # is standing in for a CLI invocation and must not open a window.
    if len(sys.argv) > 1 and sys.argv[1] == RUN_STEP_FLAG:
        sys.exit(run_step(sys.argv[2:]))

    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
