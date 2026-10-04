"""User-facing, read-only community display support workflow.

This module deliberately depends only on the Phase 4.1 Safe Scan surface.  It
does not import discovery, lifecycle, output-session, or protocol transports.
"""
from __future__ import annotations

import logging
from pathlib import Path
import threading

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, QSize, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QPushButton, QStackedWidget, QTextBrowser,
    QVBoxLayout,
)

from .devices.catalog import catalog_models
from .diagnostics import (
    MatchState, ScanResult, default_safe_scanner, export_support_package,
    inspect_support_package,
)

log = logging.getLogger(__name__)


WELCOME = "WELCOME"
SCANNING = "SCANNING"
DEVICE_SELECTION = "DEVICE_SELECTION"
DEVICE_DETAILS = "DEVICE_DETAILS"
EXPORTING = "EXPORTING"
SUCCESS = "SUCCESS"
PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
ERROR = "ERROR"

_MATCH_LABELS = {
    MatchState.EXACT_IDENTITY_MATCH: "Known hardware identity",
    MatchState.POSSIBLE_FAMILY_MATCH: "Possible known display family",
    MatchState.AMBIGUOUS: "More information required",
    MatchState.UNKNOWN: "New / unknown display",
}


class SafeScanBridge(QObject):
    completed = Signal(object)
    failed = Signal(str)

    def run(self, scanner):
        try:
            self.completed.emit(tuple(scanner.scan()))
        except Exception:
            log.exception("Safe Scan failed")
            self.failed.emit("ONI could not complete the Safe Scan. No commands were sent to the display.")


def _catalog_names(result: ScanResult) -> tuple[str, ...]:
    by_key = {model.key: model.model for model in catalog_models()}
    return tuple(by_key.get(key, key) for key in result.match.candidates)


def _friendly_name(result: ScanResult) -> str:
    fp = result.fingerprint
    names = _catalog_names(result)
    if fp.description.strip(): return fp.description.strip()
    if len(names) == 1: return names[0]
    if fp.manufacturer.strip(): return f"{fp.manufacturer.strip()} USB Display"
    return "USB Display"


def _connection_label(result: ScanResult) -> str:
    values = [value.replace("mass-storage/scsi", "Storage / SCSI").replace("winusb", "WinUSB").replace("hid", "HID").replace("serial", "Serial").replace("generic-usb", "USB") for value in result.fingerprint.transport_types if value != "unknown"]
    return " / ".join(dict.fromkeys(values)) or "USB"


def _support_label(result: ScanResult) -> str:
    return " / ".join(result.match.support_statuses) if result.match.support_statuses else "Not currently classified"


def _is_partial(result: ScanResult) -> bool:
    return bool(result.warnings or any(interface.access_error for interface in result.fingerprint.interfaces))


class HelpAddDisplayDialog(QDialog):
    """Minimal Safe Scan wizard backed exclusively by immutable ScanResults."""
    def __init__(self, parent=None, *, scanner_factory=default_safe_scanner,
                 exporter=export_support_package, importer=inspect_support_package,
                 export_directory: Path | None = None):
        super().__init__(parent)
        self.setObjectName("helpAddDisplayDialog"); self.setWindowTitle("Help Add My Display")
        self.resize(780, 620); self.setMinimumSize(620, 520)
        self._scanner_factory=scanner_factory; self._exporter=exporter; self._importer=importer
        self._export_directory=Path(export_directory) if export_directory else None
        self._thread=None; self._bridge=None; self._scan_active=False; self._results=(); self._selected=None
        self._close_pending=False; self._last_package=None; self._state=WELCOME

        root=QVBoxLayout(self); root.setContentsMargins(22,20,22,20); root.setSpacing(12)
        header=QLabel("Help Add My Display"); header.setObjectName("pageTitle"); root.addWidget(header)
        self.subtitle=QLabel("Create a privacy-safe hardware report for a display that ONI does not support yet.")
        self.subtitle.setObjectName("pageSubtitle"); self.subtitle.setWordWrap(True); root.addWidget(self.subtitle)
        self.pages=QStackedWidget(); root.addWidget(self.pages,1)
        self._build_welcome(); self._build_scanning(); self._build_selection(); self._build_details()
        self._build_partial(); self._build_exporting(); self._build_success(); self._build_error()
        self._show_state(WELCOME)

    @property
    def workflow_state(self): return self._state

    @property
    def scan_thread_running(self): return self._scan_active

    def _page(self, state: str):
        page=QFrame(); page.setObjectName("card"); page.setProperty("workflowState",state)
        layout=QVBoxLayout(page); layout.setContentsMargins(22,20,22,20); layout.setSpacing(12)
        self.pages.addWidget(page); setattr(self,f"_{state.lower()}_page",page); return page,layout

    def _button_row(self, *buttons):
        row=QHBoxLayout(); row.addStretch()
        for button in buttons: row.addWidget(button)
        return row

    def _build_welcome(self):
        page,layout=self._page(WELCOME); layout.addStretch()
        title=QLabel("Help us add your display"); title.setObjectName("sectionTitle"); title.setAlignment(Qt.AlignCenter); layout.addWidget(title)
        copy=QLabel("ONI can scan your connected USB displays and create a support package that developers can use to add support for your display.")
        copy.setWordWrap(True); copy.setAlignment(Qt.AlignCenter); layout.addWidget(copy)
        safe=QLabel("Safe Scan does not send commands or images to your display."); safe.setObjectName("diagnosticSummary"); safe.setWordWrap(True); safe.setAlignment(Qt.AlignCenter); layout.addWidget(safe)
        self.scan_button=QPushButton("Scan for Displays"); self.scan_button.setObjectName("primaryButton"); self.scan_button.setAccessibleName("Scan for connected USB displays safely"); self.scan_button.clicked.connect(self.start_scan)
        layout.addLayout(self._button_row(self.scan_button)); layout.addStretch()

    def _build_scanning(self):
        page,layout=self._page(SCANNING); layout.addStretch()
        title=QLabel("Scanning connected devices…"); title.setObjectName("sectionTitle"); title.setAlignment(Qt.AlignCenter); layout.addWidget(title)
        self.scan_status=QLabel("Checking display interfaces…"); self.scan_status.setAlignment(Qt.AlignCenter); self.scan_status.setObjectName("muted"); layout.addWidget(self.scan_status)
        safety=QLabel("No commands or images are sent during Safe Scan."); safety.setAlignment(Qt.AlignCenter); safety.setObjectName("diagnosticSummary"); layout.addWidget(safety); layout.addStretch()

    def _build_selection(self):
        page,layout=self._page(DEVICE_SELECTION)
        title=QLabel("Select your display"); title.setObjectName("sectionTitle"); layout.addWidget(title)
        hint=QLabel("Each physical USB display is listed separately. Select one to create its report."); hint.setObjectName("muted"); hint.setWordWrap(True); layout.addWidget(hint)
        self.candidates=QListWidget(); self.candidates.setObjectName("diagnosticCandidateList"); self.candidates.setSelectionMode(QListWidget.SingleSelection); self.candidates.setSpacing(8); self.candidates.setAccessibleName("Detected display candidates"); layout.addWidget(self.candidates,1)
        self.candidates.currentItemChanged.connect(self._selection_changed); self.candidates.itemDoubleClicked.connect(lambda _item:self.show_selected_details()); self.candidates.itemActivated.connect(lambda _item:self.show_selected_details())
        self.scan_again=QPushButton("Scan Again"); self.scan_again.clicked.connect(self.start_scan)
        self.details_button=QPushButton("Continue"); self.details_button.setObjectName("primaryButton"); self.details_button.setEnabled(False); self.details_button.clicked.connect(self.show_selected_details)
        layout.addLayout(self._button_row(self.scan_again,self.details_button))

    def _build_details(self):
        page,layout=self._page(DEVICE_DETAILS)
        self.detail_title=QLabel(); self.detail_title.setObjectName("sectionTitle"); layout.addWidget(self.detail_title)
        self.detail_summary=QLabel(); self.detail_summary.setWordWrap(True); self.detail_summary.setObjectName("diagnosticSummary"); layout.addWidget(self.detail_summary)
        self.advanced_toggle=QPushButton("Show Advanced Details"); self.advanced_toggle.setCheckable(True); self.advanced_toggle.setAccessibleName("Show or hide advanced USB details"); self.advanced_toggle.toggled.connect(self._toggle_advanced); layout.addWidget(self.advanced_toggle)
        self.advanced=QTextBrowser(); self.advanced.setObjectName("diagnosticAdvancedDetails"); self.advanced.setVisible(False); self.advanced.setOpenExternalLinks(False); layout.addWidget(self.advanced,1)
        self.private_opt_in=QCheckBox("Include private raw identifiers (not recommended)"); self.private_opt_in.setAccessibleDescription("Adds a private report containing machine-specific USB identifiers"); layout.addWidget(self.private_opt_in)
        privacy=QLabel("The public support package hides machine-specific identifiers while keeping the USB information developers need. Private data is never included unless you select the option above.")
        privacy.setWordWrap(True); privacy.setObjectName("muted"); layout.addWidget(privacy)
        snapshot=QLabel("The package uses this completed Safe Scan snapshot. Disconnecting the display after scanning does not invent or change the captured result.")
        snapshot.setWordWrap(True); snapshot.setObjectName("muted"); layout.addWidget(snapshot)
        back=QPushButton("Back"); back.clicked.connect(lambda:self._show_state(DEVICE_SELECTION))
        self.export_button=QPushButton("Create Support Package"); self.export_button.setObjectName("primaryButton"); self.export_button.clicked.connect(self.begin_export)
        layout.addLayout(self._button_row(back,self.export_button))

    def _build_partial(self):
        page,layout=self._page(PARTIAL_SUCCESS); layout.addStretch()
        title=QLabel("Display found"); title.setObjectName("sectionTitle"); title.setAlignment(Qt.AlignCenter); layout.addWidget(title)
        self.partial_text=QLabel("Some optional USB details could not be read. You can still create a support package."); self.partial_text.setWordWrap(True); self.partial_text.setAlignment(Qt.AlignCenter); layout.addWidget(self.partial_text)
        view=QPushButton("View Displays"); view.setObjectName("primaryButton"); view.clicked.connect(lambda:self._show_state(DEVICE_SELECTION)); layout.addLayout(self._button_row(view)); layout.addStretch()

    def _build_exporting(self):
        page,layout=self._page(EXPORTING); layout.addStretch()
        title=QLabel("Creating support package…"); title.setObjectName("sectionTitle"); title.setAlignment(Qt.AlignCenter); layout.addWidget(title)
        info=QLabel("Preparing the public privacy-safe report and validating its checksums."); info.setAlignment(Qt.AlignCenter); info.setWordWrap(True); layout.addWidget(info); layout.addStretch()

    def _build_success(self):
        page,layout=self._page(SUCCESS); layout.addStretch()
        title=QLabel("Support Package Created"); title.setObjectName("sectionTitle"); title.setAlignment(Qt.AlignCenter); layout.addWidget(title)
        self.success_text=QLabel(); self.success_text.setWordWrap(True); self.success_text.setTextInteractionFlags(Qt.TextSelectableByMouse); self.success_text.setAlignment(Qt.AlignCenter); self.success_text.setObjectName("diagnosticSummary"); layout.addWidget(self.success_text)
        open_folder=QPushButton("Open Folder"); open_folder.clicked.connect(self.open_output_folder)
        copy_path=QPushButton("Copy File Path"); copy_path.clicked.connect(self.copy_output_path)
        done=QPushButton("Done"); done.setObjectName("primaryButton"); done.clicked.connect(self.accept)
        layout.addLayout(self._button_row(open_folder,copy_path,done)); layout.addStretch()

    def _build_error(self):
        page,layout=self._page(ERROR); layout.addStretch()
        title=QLabel("Safe Scan could not finish"); title.setObjectName("sectionTitle"); title.setAlignment(Qt.AlignCenter); layout.addWidget(title)
        self.error_text=QLabel(); self.error_text.setWordWrap(True); self.error_text.setAlignment(Qt.AlignCenter); self.error_text.setObjectName("diagnosticSummary"); layout.addWidget(self.error_text)
        retry=QPushButton("Scan Again"); retry.setObjectName("primaryButton"); retry.clicked.connect(self.start_scan); layout.addLayout(self._button_row(retry)); layout.addStretch()

    def _show_state(self,state):
        page=getattr(self,f"_{state.lower()}_page"); self.pages.setCurrentWidget(page); self._state=state

    @Slot()
    def start_scan(self):
        if self.scan_thread_running:return
        self._results=(); self._selected=None; self.candidates.clear(); self.details_button.setEnabled(False); self._show_state(SCANNING)
        try: scanner=self._scanner_factory()
        except Exception:
            log.exception("Safe Scanner construction failed"); self._scan_failed("ONI could not start the Safe Scan. No commands were sent to the display."); return
        self._bridge=SafeScanBridge(self); self._bridge.completed.connect(self._scan_completed,Qt.QueuedConnection); self._bridge.failed.connect(self._scan_failed,Qt.QueuedConnection); self._scan_active=True
        self._thread=threading.Thread(target=self._bridge.run,args=(scanner,),name="oni-safe-scan",daemon=True); self._thread.start()

    @Slot(object)
    def _scan_completed(self,results):
        if self._finish_scan_thread():return
        self._results=tuple(results)
        if not self._results:
            self.error_text.setText("No likely display was detected.\n\nCheck that the display is connected by USB and try again."); self._show_state(ERROR); return
        self._populate_candidates()
        self._show_state(PARTIAL_SUCCESS if any(_is_partial(item) for item in self._results) else DEVICE_SELECTION)

    @Slot(str)
    def _scan_failed(self,message):
        if self._finish_scan_thread():return
        self.error_text.setText(message); self._show_state(ERROR)

    def _finish_scan_thread(self):
        closing=self._close_pending
        self._scan_active=False; self._thread=None
        if self._bridge is not None:self._bridge.deleteLater();self._bridge=None
        if self._close_pending:self._close_pending=False; self.reject()
        return closing

    def _populate_candidates(self):
        self.candidates.clear()
        for result in self._results:
            status=_MATCH_LABELS[result.match.state]; extra=" · Some optional details unavailable" if _is_partial(result) else ""
            item=QListWidgetItem(f"{_friendly_name(result)}\n{status} · {_connection_label(result)} · ONI catalog: {_support_label(result)}{extra}")
            item.setData(Qt.UserRole,result); item.setSizeHint(QSize(0,64))
            item.setToolTip(f"{result.fingerprint.vid_pid.upper()} — {status}"); self.candidates.addItem(item)
        if self.candidates.count():self.candidates.setCurrentRow(0)

    def _selection_changed(self,current,_previous=None):
        self._selected=current.data(Qt.UserRole) if current else None; self.details_button.setEnabled(self._selected is not None)

    def show_selected_details(self):
        if self._selected is None:return
        result=self._selected; fp=result.fingerprint; names=_catalog_names(result)
        status=_MATCH_LABELS[result.match.state]; protocol="Additional protocol information may be needed" if result.match.protocol_verification=="REQUIRED" else "Existing ONI evidence is available"
        partial="\n\nSome optional USB details could not be read. This does not prevent report creation." if _is_partial(result) else ""
        self.detail_title.setText(_friendly_name(result)); self.detail_summary.setText(f"{status}\nONI support classification: {_support_label(result)}\nConnection: {_connection_label(result)}\n{protocol}{partial}")
        observed=[]
        for interface in fp.interfaces:
            line=f"- {interface.transport.upper()} interface"
            if interface.number is not None:line+=f" {interface.number}"
            if interface.access_error:line+=f": optional metadata unavailable ({interface.access_error})"
            elif interface.endpoints:line+=": "+", ".join(f"{ep.direction.upper()} 0x{ep.address:02X} {ep.transfer_type}" for ep in interface.endpoints)
            observed.append(line)
        provenance="\n".join(f"- {key}: {value}" for key,value in sorted(fp.provenance.items())) or "- No provenance fields"
        catalog="\n".join(f"- {name}" for name in names) or "- No catalog candidate"
        warnings="\n".join(f"- {warning}" for warning in result.warnings) or "- None"
        self.advanced.setPlainText(
            f"Observed Windows identity\nVID:PID: {fp.vid_pid.upper()}\nRevision: {fp.revision if fp.revision is not None else 'Unavailable'}\nService: {fp.service or 'Unavailable'}\nClass: {fp.class_name or 'Unavailable'}\nTransport: {_connection_label(result)}\n\n"
            f"Observed interfaces\n{chr(10).join(observed) or '- No optional descriptor metadata observed'}\n\n"
            f"Catalog references (not observed hardware facts)\n{catalog}\n\nEvidence provenance\n{provenance}\n\n"
            f"Protocol verification: {result.match.protocol_verification}\nWarnings\n{warnings}"
        ); self._show_state(DEVICE_DETAILS)

    def _toggle_advanced(self,enabled):
        self.advanced.setVisible(enabled); self.advanced_toggle.setText("Hide Advanced Details" if enabled else "Show Advanced Details")

    def begin_export(self):
        if self._selected is None:return
        directory=str(self._export_directory) if self._export_directory else QFileDialog.getExistingDirectory(self,"Choose Support Package Folder",str(Path.home()/"Downloads"))
        if not directory:return
        self._export_directory=Path(directory); self._show_state(EXPORTING); QTimer.singleShot(0,self._perform_export)

    def _perform_export(self):
        try:
            package=self._exporter((self._selected,),self._export_directory,include_private=self.private_opt_in.isChecked())
            inspected=self._importer(package)
            if inspected["reconstructed_fingerprint_ids"]!=[self._selected.fingerprint.deterministic_id()]:raise ValueError("fingerprint validation failed")
        except Exception:
            log.exception("Support package export failed"); self.error_text.setText("ONI could not create or validate the support package. Check the selected folder and available disk space, then try again."); self._show_state(ERROR); return
        self._last_package=Path(package); privacy="Public diagnostic report + explicitly requested private report" if self.private_opt_in.isChecked() else "Public diagnostic report"
        self.success_text.setText(f"Display: {_friendly_name(self._selected)}\n\nFile: {self._last_package.name}\n\nPrivacy: {privacy}\n\nSafety: No commands were sent to your display.")
        self._show_state(SUCCESS)

    def open_output_folder(self):
        if self._last_package:QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._last_package.parent)))

    def copy_output_path(self):
        if self._last_package:QApplication.clipboard().setText(str(self._last_package))

    def closeEvent(self,event):
        if self.scan_thread_running:
            self._close_pending=True; self.hide(); event.ignore(); return
        super().closeEvent(event)

