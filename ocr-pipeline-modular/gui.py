#!/usr/bin/env python3
"""GUI for the modular OCR pipeline.

One window, one tab per step. Steps 1, 2, and the automatic (Claude API)
mode of step 3, and step 4 run the existing CLI scripts via QProcess and
stream their log output live. Step 3 also offers a manual review dialog
that reads/writes the same OCR JSON format without needing an API key.
"""

import sys
from pathlib import Path
from typing import List, Optional

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QTextEdit, QFileDialog, QGroupBox,
    QTabWidget, QFormLayout, QDialog, QDialogButtonBox, QCheckBox,
    QScrollArea, QDoubleSpinBox, QSpinBox, QComboBox, QMessageBox,
)
from PySide6.QtCore import Qt, QProcess, Signal, QObject
from PySide6.QtGui import QFont, QColor, QTextCursor, QPixmap, QPainter, QPen

from utils import OCRDataHandler, TextBlock

SCRIPT_DIR = Path(__file__).resolve().parent
PYTHON_EXE = sys.executable


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
        self.process = QProcess()
        self.process.setProgram(PYTHON_EXE)
        self.process.setArguments([str(SCRIPT_DIR / script)] + args)
        self.process.setWorkingDirectory(str(SCRIPT_DIR))
        self.process.setProcessChannelMode(QProcess.MergedChannels)
        self.process.readyReadStandardOutput.connect(self._on_output)
        self.process.finished.connect(self._on_finished)
        self.line_output.emit(f"$ {PYTHON_EXE} {script} {' '.join(args)}")
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

        form.addRow("Input directory:", self.input_dir)
        form.addRow("Output directory:", self.output_dir)
        form.addRow("Max width (px):", self.max_width)
        form.addRow("JPEG quality:", self.quality)

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

        form.addRow("Input directory:", self.input_dir)
        form.addRow("Output directory:", self.output_dir)
        form.addRow("Engine:", self.engine)
        form.addRow("Confidence threshold:", self.confidence_threshold)

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

        form.addRow("Image directory (for review):", self.image_dir)
        form.addRow("OCR JSON directory:", self.input_dir)
        form.addRow("Output directory:", self.output_dir)
        form.addRow("Confidence threshold:", self.threshold)

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

        json_files = sorted(ocr_dir.glob("*_ocr.json"))
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

            out_path = output_dir / f"{json_path.stem}_corrected.json"
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

        form.addRow("Image directory:", self.image_dir)
        form.addRow("OCR/corrected JSON directory:", self.ocr_dir)
        form.addRow("Output directory:", self.output_dir)
        form.addRow(self.debug)
        form.addRow("Merge into single PDF (optional filename):", self.merge_output)

        self.run_button = QPushButton("Run PDF Assembly")
        self.run_button.clicked.connect(self._run)
        form.addRow(self.run_button)

        layout.addWidget(form_box)
        layout.addWidget(QLabel("Log:"))
        layout.addWidget(self.log)

    def _run(self):
        args = [
            "--image-dir", str(self.image_dir.path()),
            "--ocr-dir", str(self.ocr_dir.path()),
            "--output-dir", str(self.output_dir.path()),
        ]
        if self.debug.isChecked():
            args.append("--debug")
        if self.merge_output.text().strip():
            args += ["--merge-output", self.merge_output.text().strip()]
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


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
