"""Graphical User Interface (GUI) for aup3-to-reaper.

Features:
- Primary GUI: Modern, responsive PySide6 (Qt) interface with dark theme and drag-and-drop.
- Fallback GUI: Standard library Tkinter interface if PySide6 is not installed.
- Asynchronous worker thread (non-blocking UI during audio extraction).
- Real-time conversion logs, project summary preview, and quick-access buttons.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Optional

from .converter import ConversionResult, convert_aup3_to_reaper

logger = logging.getLogger(__name__)


def open_path_in_file_manager(path: Path) -> None:
    """Open a file or directory in the system's native file explorer."""
    target = Path(path).resolve()
    if sys.platform == "win32":
        if target.is_file():
            subprocess.run(["explorer", f"/select,{str(target)}"], check=False)
        else:
            subprocess.run(["explorer", str(target)], check=False)
    elif sys.platform == "darwin":
        subprocess.run(["open", str(target)], check=False)
    else:
        subprocess.run(["xdg-open", str(target)], check=False)


# ============================================================================
# PySide6 Modern GUI Implementation
# ============================================================================

def launch_qt_gui() -> int:
    """Launch modern PySide6 Qt GUI."""
    from PySide6.QtCore import QObject, QThread, Qt, Signal
    from PySide6.QtGui import QDragEnterEvent, QDropEvent, QFont, QIcon
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QFileDialog,
        QFrame,
        QGridLayout,
        QGroupBox,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMessageBox,
        QProgressBar,
        QPushButton,
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )

    try:
        import qdarktheme
        has_darktheme = True
    except ImportError:
        has_darktheme = False

    class ConversionWorker(QThread):
        """Worker thread for running conversion without freezing the UI."""
        progress_signal = Signal(str)
        finished_signal = Signal(object)
        error_signal = Signal(str)

        def __init__(
            self,
            aup3_path: Path,
            output_dir: Optional[Path],
            extract_fx: bool,
            dry_run: bool,
        ) -> None:
            super().__init__()
            self.aup3_path = aup3_path
            self.output_dir = output_dir
            self.extract_fx = extract_fx
            self.dry_run = dry_run

        def run(self) -> None:
            try:
                result = convert_aup3_to_reaper(
                    aup3_path=self.aup3_path,
                    output_dir=self.output_dir,
                    extract_fx_script=self.extract_fx,
                    dry_run=self.dry_run,
                    progress_callback=self.progress_signal.emit,
                )
                self.finished_signal.emit(result)
            except Exception as exc:
                self.error_signal.emit(str(exc))

    class AUP3ToReaperWindow(QWidget):
        def __init__(self) -> None:
            super().__init__()
            self.setWindowTitle("aup3-to-reaper — Audacity to REAPER Converter")
            self.setMinimumSize(720, 580)
            self.setAcceptDrops(True)

            self.worker: Optional[ConversionWorker] = None
            self.last_result: Optional[ConversionResult] = None

            self._init_ui()

        def _init_ui(self) -> None:
            main_layout = QVBoxLayout(self)
            main_layout.setSpacing(14)
            main_layout.setContentsMargins(20, 20, 20, 20)

            # Header Banner
            header_layout = QVBoxLayout()
            title_label = QLabel("AUP3 to REAPER Converter")
            title_font = QFont()
            title_font.setPointSize(16)
            title_font.setBold(True)
            title_label.setFont(title_font)
            subtitle_label = QLabel("Convert Audacity 3+ projects, audio clips, markers, and FX chains into REAPER projects.")
            subtitle_label.setStyleSheet("color: #888888;")
            header_layout.addWidget(title_label)
            header_layout.addWidget(subtitle_label)
            main_layout.addLayout(header_layout)

            # File Selection Box
            file_group = QGroupBox("Project Paths")
            file_layout = QGridLayout(file_group)
            file_layout.setSpacing(10)

            # Input AUP3
            file_layout.addWidget(QLabel("Audacity Project (.aup3):"), 0, 0)
            self.input_edit = QLineEdit()
            self.input_edit.setPlaceholderText("Select or drag & drop a .aup3 project file here...")
            self.input_edit.textChanged.connect(self._on_input_changed)
            file_layout.addWidget(self.input_edit, 0, 1)

            self.browse_input_btn = QPushButton("Browse...")
            self.browse_input_btn.setFixedWidth(90)
            self.browse_input_btn.clicked.connect(self._browse_input)
            file_layout.addWidget(self.browse_input_btn, 0, 2)

            # Output Directory
            file_layout.addWidget(QLabel("Output REAPER Folder:"), 1, 0)
            self.output_edit = QLineEdit()
            self.output_edit.setPlaceholderText("Defaults to <project_name>_reaper in the same directory")
            file_layout.addWidget(self.output_edit, 1, 1)

            self.browse_output_btn = QPushButton("Browse...")
            self.browse_output_btn.setFixedWidth(90)
            self.browse_output_btn.clicked.connect(self._browse_output)
            file_layout.addWidget(self.browse_output_btn, 1, 2)

            main_layout.addWidget(file_group)

            # Options
            options_layout = QHBoxLayout()
            self.fx_checkbox = QCheckBox("Generate ReaScript FX Loader (session_load_fx.lua)")
            self.fx_checkbox.setChecked(True)
            self.fx_checkbox.setToolTip("Creates a REAPER Lua script to restore ReaComp, ReaEQ, and VST/VST3 settings.")
            options_layout.addWidget(self.fx_checkbox)

            self.dry_run_checkbox = QCheckBox("Dry Run (Inspect only, do not write files)")
            self.dry_run_checkbox.setToolTip("Parses the project database and previews summary without extracting audio.")
            options_layout.addWidget(self.dry_run_checkbox)
            options_layout.addStretch()
            main_layout.addLayout(options_layout)

            # Progress Bar
            self.progress_bar = QProgressBar()
            self.progress_bar.setRange(0, 0)  # Indeterminate initially
            self.progress_bar.setVisible(False)
            main_layout.addWidget(self.progress_bar)

            # Action Buttons
            btn_layout = QHBoxLayout()
            self.convert_btn = QPushButton("Convert to REAPER Project")
            self.convert_btn.setFixedHeight(38)
            convert_font = QFont()
            convert_font.setPointSize(10)
            convert_font.setBold(True)
            self.convert_btn.setFont(convert_font)
            self.convert_btn.setStyleSheet("background-color: #0d6efd; color: white; border-radius: 4px;")
            self.convert_btn.clicked.connect(self._start_conversion)
            btn_layout.addWidget(self.convert_btn)

            self.open_folder_btn = QPushButton("Open Output Folder")
            self.open_folder_btn.setFixedHeight(38)
            self.open_folder_btn.setEnabled(False)
            self.open_folder_btn.clicked.connect(self._open_output_folder)
            btn_layout.addWidget(self.open_folder_btn)

            self.open_report_btn = QPushButton("View Migration Report")
            self.open_report_btn.setFixedHeight(38)
            self.open_report_btn.setEnabled(False)
            self.open_report_btn.clicked.connect(self._open_report)
            btn_layout.addWidget(self.open_report_btn)

            main_layout.addLayout(btn_layout)

            # Log / Status Console
            log_group = QGroupBox("Activity Log")
            log_layout = QVBoxLayout(log_group)
            self.log_edit = QTextEdit()
            self.log_edit.setReadOnly(True)
            log_font = QFont("Consolas, Courier New, monospace")
            log_font.setPointSize(9)
            self.log_edit.setFont(log_font)
            log_layout.addWidget(self.log_edit)
            main_layout.addWidget(log_group)

            self._log("Ready. Select or drag-and-drop an Audacity project (.aup3) to begin.")

        def _log(self, text: str) -> None:
            self.log_edit.append(text)
            self.log_edit.ensureCursorVisible()

        def _on_input_changed(self, text: str) -> None:
            stripped = text.strip().strip('"')
            if stripped and stripped.lower().endswith(".aup3"):
                p = Path(stripped)
                if not self.output_edit.text():
                    suggested = p.parent / f"{p.stem}_reaper"
                    self.output_edit.setText(str(suggested))

        def _browse_input(self) -> None:
            file_path, _ = QFileDialog.getOpenFileName(
                self,
                "Select Audacity Project",
                "",
                "Audacity Projects (*.aup3);;All Files (*.*)",
            )
            if file_path:
                self.input_edit.setText(file_path)

        def _browse_output(self) -> None:
            dir_path = QFileDialog.getExistingDirectory(
                self,
                "Select Output Directory for REAPER Project",
            )
            if dir_path:
                self.output_edit.setText(dir_path)

        def dragEnterEvent(self, event: QDragEnterEvent) -> None:
            if event.mimeData().hasUrls():
                for url in event.mimeData().urls():
                    if url.toLocalFile().lower().endswith(".aup3"):
                        event.acceptProposedAction()
                        return
            event.ignore()

        def dropEvent(self, event: QDropEvent) -> None:
            for url in event.mimeData().urls():
                file_path = url.toLocalFile()
                if file_path.lower().endswith(".aup3"):
                    self.input_edit.setText(file_path)
                    event.acceptProposedAction()
                    break

        def _start_conversion(self) -> None:
            input_str = self.input_edit.text().strip().strip('"')
            if not input_str:
                QMessageBox.warning(self, "Missing Input", "Please select an Audacity project file (.aup3).")
                return

            input_path = Path(input_str)
            if not input_path.exists():
                QMessageBox.critical(self, "File Not Found", f"The selected file does not exist:\n{input_path}")
                return

            output_str = self.output_edit.text().strip().strip('"')
            output_dir = Path(output_str) if output_str else None

            extract_fx = self.fx_checkbox.isChecked()
            dry_run = self.dry_run_checkbox.isChecked()

            # Prepare UI
            self.convert_btn.setEnabled(False)
            self.open_folder_btn.setEnabled(False)
            self.open_report_btn.setEnabled(False)
            self.progress_bar.setVisible(True)
            self._log("-" * 60)
            self._log(f"Starting conversion: {input_path.name}")

            # Launch Background Worker Thread
            self.worker = ConversionWorker(
                aup3_path=input_path,
                output_dir=output_dir,
                extract_fx=extract_fx,
                dry_run=dry_run,
            )
            self.worker.progress_signal.connect(self._log)
            self.worker.finished_signal.connect(self._on_conversion_finished)
            self.worker.error_signal.connect(self._on_conversion_error)
            self.worker.start()

        def _on_conversion_finished(self, result: ConversionResult) -> None:
            self.last_result = result
            self.convert_btn.setEnabled(True)
            self.progress_bar.setVisible(False)

            if result.is_dry_run:
                self._log("-" * 60)
                self._log("[DRY RUN COMPLETE] Plan inspected successfully.")
                self._log(f"  Tracks: {result.total_tracks}, Clips: {result.total_clips}, Duration: {result.total_duration_seconds:.2f}s")
                QMessageBox.information(
                    self,
                    "Dry Run Finished",
                    f"Dry run complete for '{result.project_name}'.\n\n"
                    f"Tracks: {result.total_tracks}\n"
                    f"Audio Clips: {result.total_clips}\n"
                    f"Total Duration: {result.total_duration_seconds:.2f} seconds\n\n"
                    "No files were written to disk.",
                )
                return

            self.open_folder_btn.setEnabled(True)
            if result.report_file and result.report_file.exists():
                self.open_report_btn.setEnabled(True)

            self._log("-" * 60)
            self._log("[SUCCESS] REAPER project created successfully!")
            self._log(f"  RPP File: {result.rpp_file}")
            self._log(f"  Extracted Media: {result.media_dir} ({result.total_extracted_files} WAVs)")
            self._log(f"  Report: {result.report_file}")
            if result.fx_script_file:
                self._log(f"  FX Loader: {result.fx_script_file}")

            QMessageBox.information(
                self,
                "Conversion Complete",
                f"Successfully converted '{result.project_name}' to REAPER!\n\n"
                f"Saved to: {result.output_dir}\n"
                f"Audio clips extracted: {result.total_extracted_files}\n\n"
                "You can now open the output folder or view the migration report.",
            )

        def _on_conversion_error(self, err_msg: str) -> None:
            self.convert_btn.setEnabled(True)
            self.progress_bar.setVisible(False)
            self._log(f"[ERROR] {err_msg}")
            QMessageBox.critical(self, "Conversion Error", f"An error occurred during conversion:\n\n{err_msg}")

        def _open_output_folder(self) -> None:
            if self.last_result and self.last_result.output_dir:
                open_path_in_file_manager(self.last_result.output_dir)

        def _open_report(self) -> None:
            if self.last_result and self.last_result.report_file and self.last_result.report_file.exists():
                open_path_in_file_manager(self.last_result.report_file)

    app = QApplication.instance() or QApplication(sys.argv)
    if has_darktheme:
        try:
            if hasattr(qdarktheme, "setup_theme"):
                qdarktheme.setup_theme("dark")
            elif hasattr(qdarktheme, "load_stylesheet"):
                app.setStyleSheet(qdarktheme.load_stylesheet("dark"))
        except Exception as exc:
            logger.debug("Failed to apply qdarktheme: %s", exc)
    else:
        # Fallback dark stylesheet if qdarktheme is not available
        app.setStyleSheet("""
            QWidget {
                background-color: #1e1e1e;
                color: #d4d4d4;
                font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, Roboto, sans-serif;
            }
            QGroupBox {
                border: 1px solid #3c3c3c;
                border-radius: 6px;
                margin-top: 10px;
                padding-top: 10px;
                font-weight: bold;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
            }
            QLineEdit, QTextEdit {
                background-color: #252526;
                border: 1px solid #3c3c3c;
                border-radius: 4px;
                padding: 5px;
                color: #ffffff;
            }
            QLineEdit:focus, QTextEdit:focus {
                border: 1px solid #007acc;
            }
            QPushButton {
                background-color: #333333;
                border: 1px solid #444444;
                border-radius: 4px;
                padding: 6px 12px;
                color: #ffffff;
            }
            QPushButton:hover {
                background-color: #3e3e42;
            }
            QPushButton:pressed {
                background-color: #007acc;
            }
            QPushButton:disabled {
                background-color: #2d2d2d;
                color: #666666;
                border-color: #333333;
            }
            QProgressBar {
                border: 1px solid #3c3c3c;
                border-radius: 4px;
                text-align: center;
                background-color: #252526;
            }
            QProgressBar::chunk {
                background-color: #007acc;
            }
        """)

    window = AUP3ToReaperWindow()
    window.show()
    return app.exec()


# ============================================================================
# Tkinter Fallback GUI Implementation (Zero External Dependencies)
# ============================================================================

def launch_tk_gui() -> int:
    """Launch standard library Tkinter GUI fallback."""
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    root = tk.Tk()
    root.title("aup3-to-reaper — Audacity to REAPER Converter")
    root.geometry("680x520")
    root.minsize(580, 420)

    # Variables
    input_var = tk.StringVar()
    output_var = tk.StringVar()
    fx_var = tk.BooleanVar(value=True)
    dry_var = tk.BooleanVar(value=False)
    last_res = [None]

    def on_input_changed(*_):
        p_str = input_var.get().strip().strip('"')
        if p_str.lower().endswith(".aup3") and not output_var.get():
            p = Path(p_str)
            output_var.set(str(p.parent / f"{p.stem}_reaper"))

    input_var.trace_add("write", on_input_changed)

    def browse_input():
        f = filedialog.askopenfilename(filetypes=[("Audacity Projects", "*.aup3"), ("All Files", "*.*")])
        if f:
            input_var.set(f)

    def browse_output():
        d = filedialog.askdirectory()
        if d:
            output_var.set(d)

    # UI Layout
    pad = {"padx": 10, "pady": 5}

    title_frame = ttk.Frame(root)
    title_frame.pack(fill="x", **pad)
    ttk.Label(title_frame, text="AUP3 to REAPER Converter", font=("Helvetica", 14, "bold")).pack(anchor="w")
    ttk.Label(title_frame, text="Convert modern Audacity (.aup3) projects into native REAPER projects.").pack(anchor="w")

    path_frame = ttk.LabelFrame(root, text="Project Paths")
    path_frame.pack(fill="x", **pad)

    ttk.Label(path_frame, text="Audacity Project (.aup3):").grid(row=0, column=0, sticky="w", **pad)
    ttk.Entry(path_frame, textvariable=input_var, width=50).grid(row=0, column=1, sticky="ew", **pad)
    ttk.Button(path_frame, text="Browse...", command=browse_input).grid(row=0, column=2, **pad)

    ttk.Label(path_frame, text="Output REAPER Folder:").grid(row=1, column=0, sticky="w", **pad)
    ttk.Entry(path_frame, textvariable=output_var, width=50).grid(row=1, column=1, sticky="ew", **pad)
    ttk.Button(path_frame, text="Browse...", command=browse_output).grid(row=1, column=2, **pad)
    path_frame.columnconfigure(1, weight=1)

    opt_frame = ttk.Frame(root)
    opt_frame.pack(fill="x", **pad)
    ttk.Checkbutton(opt_frame, text="Generate ReaScript FX Loader (.lua)", variable=fx_var).pack(side="left", padx=5)
    ttk.Checkbutton(opt_frame, text="Dry Run (Inspect only)", variable=dry_var).pack(side="left", padx=5)

    btn_frame = ttk.Frame(root)
    btn_frame.pack(fill="x", **pad)
    convert_btn = ttk.Button(btn_frame, text="Convert to REAPER Project")
    convert_btn.pack(side="left", padx=5, fill="x", expand=True)

    open_dir_btn = ttk.Button(btn_frame, text="Open Output Folder", state="disabled")
    open_dir_btn.pack(side="left", padx=5)

    log_frame = ttk.LabelFrame(root, text="Activity Log")
    log_frame.pack(fill="both", expand=True, **pad)
    log_text = tk.Text(log_frame, wrap="word", height=10, font=("Consolas", 9))
    log_text.pack(fill="both", expand=True, padx=5, pady=5)

    def log_msg(msg: str):
        root.after(0, lambda: (log_text.insert("end", msg + "\n"), log_text.see("end")))

    def open_folder():
        if last_res[0] and last_res[0].output_dir:
            open_path_in_file_manager(last_res[0].output_dir)

    open_dir_btn.config(command=open_folder)

    def run_conversion():
        in_p = Path(input_var.get().strip().strip('"'))
        if not in_p.exists():
            messagebox.showerror("Error", f"Input file not found: {in_p}")
            convert_btn.config(state="normal")
            return

        out_d = Path(output_var.get().strip().strip('"')) if output_var.get().strip() else None

        def worker():
            try:
                res = convert_aup3_to_reaper(
                    aup3_path=in_p,
                    output_dir=out_d,
                    extract_fx_script=fx_var.get(),
                    dry_run=dry_var.get(),
                    progress_callback=log_msg,
                )
                last_res[0] = res
                root.after(0, lambda: on_finish(res))
            except Exception as e:
                root.after(0, lambda: on_error(str(e)))

        def on_finish(res: ConversionResult):
            convert_btn.config(state="normal")
            if not res.is_dry_run:
                open_dir_btn.config(state="normal")
                messagebox.showinfo("Success", f"Converted successfully to:\n{res.output_dir}")
            else:
                messagebox.showinfo("Dry Run Complete", f"Inspected {res.total_tracks} tracks and {res.total_clips} clips.")

        def on_error(err: str):
            convert_btn.config(state="normal")
            messagebox.showerror("Conversion Failed", err)

        convert_btn.config(state="disabled")
        log_msg("-" * 50)
        log_msg(f"Starting conversion: {in_p.name}")
        threading.Thread(target=worker, daemon=True).start()

    convert_btn.config(command=run_conversion)
    log_msg("Ready. Select an Audacity project (.aup3) and click Convert.")
    root.mainloop()
    return 0


# ============================================================================
# Main Entry Point
# ============================================================================

def launch_gui() -> int:
    """Launch the best available GUI (PySide6 with Tkinter fallback)."""
    try:
        import PySide6
        return launch_qt_gui()
    except ImportError:
        logger.info("PySide6 not found. Launching standard Tkinter GUI.")
        return launch_tk_gui()


if __name__ == "__main__":
    sys.exit(launch_gui())
