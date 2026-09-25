from __future__ import annotations
import json, os, sys, subprocess, threading, time, weakref
from copy import deepcopy
from collections import deque
from pathlib import Path
from PySide6.QtCore import Qt, Signal, QObject, QTimer, QUrl, QMimeData, QSize, QRect, QRectF, QEvent, QStandardPaths, QPoint
from PySide6.QtGui import QPixmap, QImage, QIcon, QDrag, QAction, QPainter, QPen, QColor, QLinearGradient, QRadialGradient, QPainterPath, QFont
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QLabel,
    QPushButton, QComboBox, QFileDialog, QFrame, QMessageBox, QDialog, QCheckBox, QFormLayout,
    QDialogButtonBox, QListWidget, QListWidgetItem, QAbstractItemView, QTabWidget, QScrollArea,
    QSystemTrayIcon, QMenu, QInputDialog, QStackedWidget, QSizePolicy, QLineEdit, QSpinBox, QDoubleSpinBox,
    QSlider, QToolButton, QBoxLayout, QSplitter, QButtonGroup, QGroupBox, QGridLayout)
from .media import cache_overlay, render_static, render_image, FitMode, MediaPipeline, QUALITY_PROFILES
from .playback import open_frame_source, FrameScheduler, SharedFrameScheduler
from .settings import SettingsStore, AppSettings, DisplayProfile
from .conflicts import thermalright_processes
from .runtime import DisplaySession, SessionState
from .output_rate import RATE_LABELS, resolve_output_rate
from .persistence import POLICIES, VIDEO_TRANSPORT_TARGETS, video_transport_target
from .logging_setup import configure_logging
from .device_connection import build_gui_sender
from .modes import MODES, resource_mode
from .startup import StartupManager, startup_command, open_logs
from .splash import OniSplash
from .hardware_monitor import MonitorElement, MonitorLayout, MonitorRenderer, templates
from .monitor_designer import HardwareMonitorDesigner, HomeQuickEditor, ThemeGalleryDialog
from .single_instance import SingleInstance
from .sensors import Aida64Provider, AfterburnerProvider, CachedSensorService, HwinfoProvider, NativeBasicProvider, RtssProvider, SemanticResolverCache, resolve_semantic_sensor
from .sync import DisplaySyncController
from .theme_package import export_theme, import_theme, merge_theme
from .sensor_theme_editor import SensorThemeEditorPage
from .sensor_theme_runtime import SENSOR_THEME_FPS, SensorThemeOutputRuntime
from .sensor_theme_store import SensorThemeStore
from .profile_package import Compatibility, export_profile, import_profile, safe_filename
from .profiles import MAX_USER_PROFILES, duplicate_profile, rename_profile, save_device_profile as save_profile_record, user_profile_count
from .output_mode import OutputMode, OutputOwnership
from .media_types import MediaKind, detect_media_kind, media_filter
from .device_discovery import DiscoveredDisplay, DisplayLifecycle, discover_supported_displays, simulated_reviewed_displays
from .devices.registry import DEVICES, device_definition
from .devices.catalog import catalog_models
from .oni_pages import (
    OniDiagnosticsPage, OniHardwareMonitorPage, OniHomePage, OniMediaLibraryPage,
    OniPerformancePage, OniProfilesPage, OniSensorThemesWorkspace, OniSettingsPage, scroll_page,
)

MEDIA = media_filter()
VIDEO_RATE_LABELS = ("Auto (Recommended)", "10", "15", "20", "24", "25", "30", "40", "50", "60")

def _unsafe_media_directory(path: Path) -> bool:
    try:
        resolved = path.resolve(strict=False)
        roots = [os.environ.get("SystemRoot"), os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")]
        return any(root and (resolved == Path(root).resolve(strict=False) or resolved.is_relative_to(Path(root).resolve(strict=False))) for root in roots)
    except (OSError, RuntimeError): return True

def media_dialog_start_directory(last_directory: str = "", managed_directory: Path | None = None) -> str:
    candidates = []
    if last_directory: candidates.append(Path(last_directory))
    for location in (QStandardPaths.DownloadLocation, QStandardPaths.PicturesLocation, QStandardPaths.MoviesLocation, QStandardPaths.HomeLocation):
        value = QStandardPaths.writableLocation(location)
        if value: candidates.append(Path(value))
    for candidate in candidates:
        try:
            if candidate.is_dir() and os.access(candidate, os.R_OK) and not _unsafe_media_directory(candidate): return str(candidate)
        except OSError: continue
    if managed_directory is not None:
        try:
            managed = Path(managed_directory); managed.mkdir(parents=True, exist_ok=True)
            if managed.is_dir() and not _unsafe_media_directory(managed): return str(managed)
        except OSError: pass
    return ""

def bundled_path(relative: str) -> Path:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return root / relative


class AtmosphericShell(QWidget):
    """Static, resolution-independent Oni atmosphere behind the application."""
    def paintEvent(self, event):
        painter = QPainter(self); painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect())
        foundation = QLinearGradient(rect.topLeft(), rect.bottomRight())
        foundation.setColorAt(0.0, QColor("#030712")); foundation.setColorAt(.48, QColor("#070a18")); foundation.setColorAt(1.0, QColor("#040611"))
        painter.fillRect(rect, foundation)
        for x, y, radius, inner, outer in (
            (.08, .34, .47, QColor(25, 113, 175, 43), QColor(3, 8, 19, 0)),
            (.55, .03, .42, QColor(100, 47, 190, 38), QColor(6, 7, 18, 0)),
            (.92, .62, .39, QColor(27, 112, 157, 28), QColor(4, 7, 16, 0)),
            (.48, .92, .32, QColor(74, 34, 145, 22), QColor(5, 6, 15, 0)),
        ):
            glow = QRadialGradient(rect.width()*x, rect.height()*y, max(rect.width(), rect.height())*radius)
            glow.setColorAt(0, inner); glow.setColorAt(1, outer); painter.fillRect(rect, glow)
        painter.setPen(QPen(QColor(74, 106, 191, 15), 1))
        for start, end in ((.08,.48),(.27,.70),(.51,.91),(.69,1.06)):
            path=QPainterPath(); path.moveTo(rect.width()*start,-20); path.cubicTo(rect.width()*(start+.10),rect.height()*.28,rect.width()*(end-.16),rect.height()*.64,rect.width()*end,rect.height()+20); painter.drawPath(path)
        painter.setPen(Qt.NoPen)
        for px, py, size in ((.13,.18,2.0),(.22,.76,1.5),(.39,.12,1.4),(.62,.31,1.8),(.73,.83,1.3),(.87,.17,1.5),(.94,.71,1.8)):
            painter.setBrush(QColor(111, 176, 255, 26)); painter.drawEllipse(QRectF(rect.width()*px,rect.height()*py,size,size))
        painter.end()


def faded_sidebar_art(source: QPixmap, width: int = 254, height: int = 158) -> QPixmap:
    """Blend the guardian into the sidebar without hard image edges."""
    if source.isNull(): return source
    scaled = source.scaled(width, height, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    image = QImage(width, height, QImage.Format_ARGB32_Premultiplied); image.fill(Qt.transparent)
    paint = QPainter(image); paint.setRenderHint(QPainter.SmoothPixmapTransform); paint.drawPixmap((width-scaled.width())//2, (height-scaled.height())//2, scaled); paint.end()
    for y in range(height):
        ny=y/max(1,height-1); top=min(1.0,max(0.0,(ny-.01)/.24)); bottom=min(1.0,max(.50,(1.0-ny)/.17))
        for x in range(width):
            nx=x/max(1,width-1); left=min(1.0,.35+nx/.18); right=min(1.0,max(0.0,(1.0-nx)/.34)); edge=top*bottom*left*right
            color=image.pixelColor(x,y); color.setAlpha(int(color.alpha()*edge)); image.setPixelColor(x,y,color)
    return QPixmap.fromImage(image)


class OniNavigationButton(QPushButton):
    """Artwork-backed navigation card; painting never intercepts input."""
    def __init__(self, title: str, subtitle: str, icon: str, asset_name: str, icon_asset: str = "", parent=None):
        super().__init__(parent); self._title=title; self._subtitle=subtitle; self._icon=icon
        self._art=QPixmap(str(bundled_path(f"assets/ui/{asset_name}"))); self.setCheckable(True)
        self._icon_art=QPixmap(str(bundled_path(f"assets/ui/{icon_asset}"))) if icon_asset else QPixmap()
        self.setObjectName("navArtworkButton"); self.setFixedHeight(74); self.setCursor(Qt.PointingHandCursor)
        self.setAccessibleName(f"{title}, {subtitle}"); self.setToolTip(f"{title} — {subtitle}")

    @property
    def artwork_loaded(self): return not self._art.isNull()

    def paintEvent(self, event):
        painter=QPainter(self); painter.setRenderHint(QPainter.Antialiasing); painter.setRenderHint(QPainter.SmoothPixmapTransform)
        bounds=QRectF(self.rect()).adjusted(1.5,1.5,-1.5,-1.5); radius=10.0
        base=QPainterPath(); base.addRoundedRect(bounds,radius,radius); painter.setClipPath(base)
        painter.fillPath(base,QColor("#0b101c"))
        compact=self.width()<100
        if not compact and not self._art.isNull():
            art_left=max(126,self.width()*.40); art_target=QRectF(art_left,0,self.width()-art_left,self.height())
            scaled=self._art.scaled(int(art_target.width()),int(art_target.height()),Qt.KeepAspectRatioByExpanding,Qt.SmoothTransformation)
            source=QRectF(max(0,(scaled.width()-art_target.width())/2),max(0,(scaled.height()-art_target.height())/2),art_target.width(),art_target.height())
            painter.setOpacity(.94 if self.isChecked() else .82); painter.drawPixmap(art_target,scaled,source); painter.setOpacity(1)
        shade=QLinearGradient(bounds.left(),0,bounds.right(),0)
        if self.isChecked():
            shade.setColorAt(0,QColor(62,67,236,246)); shade.setColorAt(.40,QColor(54,53,188,220)); shade.setColorAt(.68,QColor(18,26,72,82)); shade.setColorAt(1,QColor(5,10,24,20))
        elif self.underMouse():
            shade.setColorAt(0,QColor(18,25,49,248)); shade.setColorAt(.44,QColor(18,27,55,205)); shade.setColorAt(.73,QColor(8,13,29,58)); shade.setColorAt(1,QColor(4,7,17,18))
        else:
            shade.setColorAt(0,QColor(8,13,25,252)); shade.setColorAt(.44,QColor(11,17,32,216)); shade.setColorAt(.73,QColor(6,10,22,52)); shade.setColorAt(1,QColor(3,6,15,12))
        painter.fillRect(bounds,shade); painter.setClipping(False)
        if self.isChecked():
            painter.setPen(QPen(QColor(74,93,255,72),5)); painter.drawPath(base)
        painter.setPen(QPen(QColor("#8178ff") if self.isChecked() else QColor("#29334a"),1.25)); painter.drawPath(base)
        icon_box=QRectF((self.width()-42)/2 if compact else 12,16,42,42); icon_grad=QLinearGradient(icon_box.topLeft(),icon_box.bottomRight()); icon_grad.setColorAt(0,QColor("#55dfff")); icon_grad.setColorAt(.52,QColor("#397fe7")); icon_grad.setColorAt(1,QColor("#7449e8")); painter.setBrush(icon_grad); painter.setPen(QPen(QColor(161,232,255,115),1)); painter.drawRoundedRect(icon_box,8,8)
        if not self._icon_art.isNull():
            icon_pixmap=self._icon_art.scaled(28,28,Qt.KeepAspectRatio,Qt.SmoothTransformation)
            painter.drawPixmap(QRectF(icon_box.center().x()-14,icon_box.center().y()-14,28,28),icon_pixmap,QRectF(icon_pixmap.rect()))
        else:
            painter.setPen(QColor("#ffffff")); font=QFont("Segoe UI Symbol",16,QFont.DemiBold); painter.setFont(font); painter.drawText(icon_box,Qt.AlignCenter,self._icon)
        if not compact:
            text_width=max(110,self.width()-78); painter.setPen(QColor("#ffffff") if self.isChecked() else QColor("#f4f5fb")); painter.setFont(QFont("Segoe UI Variable",11,QFont.DemiBold)); painter.drawText(QRectF(66,12,text_width,27),Qt.AlignLeft|Qt.AlignVCenter,self._title)
            painter.setPen(QColor("#d3d6ed") if self.isChecked() else QColor("#aeb6c9")); painter.setFont(QFont("Segoe UI Variable",8)); painter.drawText(QRectF(66,38,text_width,21),Qt.AlignLeft|Qt.AlignVCenter,self._subtitle)
        painter.end()


class SupportedDisplaysDialog(QDialog):
    """Searchable authoritative support catalog; it never discovers devices."""
    def __init__(self,parent=None):
        super().__init__(parent);self.setWindowTitle("Supported Displays");self.resize(980,680);self.setObjectName("supportedDisplaysDialog")
        outer=QVBoxLayout(self);outer.setContentsMargins(20,18,20,18);outer.setSpacing(12)
        title=QLabel("Supported Displays");title.setObjectName("pageTitle");subtitle=QLabel("Browse hardware Oni knows about. This catalog does not represent connected devices.");subtitle.setObjectName("pageSubtitle");outer.addWidget(title);outer.addWidget(subtitle)
        self.search=QLineEdit();self.search.setPlaceholderText("Search manufacturer, model, VID:PID or protocol…");self.search.setClearButtonEnabled(True);outer.addWidget(self.search)
        body=QSplitter(Qt.Horizontal);self.brands=QListWidget();self.brands.setMinimumWidth(210);self.models=QListWidget();self.models.setSpacing(6);self.models.setWordWrap(True);self.details=QLabel();self.details.setWordWrap(True);self.details.setAlignment(Qt.AlignTop|Qt.AlignLeft);self.details.setObjectName("diagnosticSummary");self.details.setMinimumWidth(280)
        body.addWidget(self.brands);body.addWidget(self.models);body.addWidget(self.details);body.setStretchFactor(1,2);body.setStretchFactor(2,2);outer.addWidget(body,1)
        buttons=QDialogButtonBox(QDialogButtonBox.Close);buttons.rejected.connect(self.accept);outer.addWidget(buttons)
        self.search.textChanged.connect(self._rebuild);self.brands.currentTextChanged.connect(self._rebuild_models);self.models.currentItemChanged.connect(self._show_details);self._rebuild()

    def _matches(self,item,query):
        return not query or query in " ".join((item.manufacturer,item.family,item.model,*item.identifiers,item.connection_type,item.key)).casefold()

    def _rebuild(self):
        query=self.search.text().strip().casefold();current=self.brands.currentItem().text() if self.brands.currentItem() else "All manufacturers";manufacturers=sorted({item.manufacturer for item in catalog_models() if self._matches(item,query)})
        self.brands.blockSignals(True);self.brands.clear();self.brands.addItem("All manufacturers");self.brands.addItems(manufacturers);matches=self.brands.findItems(current,Qt.MatchExactly);self.brands.setCurrentItem(matches[0] if matches else self.brands.item(0));self.brands.blockSignals(False);self._rebuild_models()

    def _rebuild_models(self):
        query=self.search.text().strip().casefold();brand=self.brands.currentItem().text() if self.brands.currentItem() else "All manufacturers";self.models.clear()
        for model in catalog_models():
            if not self._matches(model,query) or (brand!="All manufacturers" and model.manufacturer!=brand):continue
            row=QListWidgetItem(f"{model.model}\n{model.manufacturer}  ·  {model.status}");row.setData(Qt.UserRole,model);row.setToolTip(model.notes);self.models.addItem(row)
        if self.models.count():self.models.setCurrentRow(0)
        else:self.details.setText("No supported display matches this search.")

    def _show_details(self,current,_previous=None):
        if current is None:return
        model=current.data(Qt.UserRole);resolutions=", ".join(f"{w} × {h}" for w,h in model.resolutions) or "Model dependent";ids=", ".join(model.identifiers) or "Model-specific identity"
        explanation=("Physically validated by the ONI project." if model.status=="Verified" else "Experimental Support\n\nEnd-to-end display output is implemented, but this physical model has not yet been validated by the ONI project." if model.status=="Experimental" else "Output support is currently incomplete for this device. ONI will not send display frames until a safe implementation is available.")
        family_note=f"\nDevice family\n{model.family}" if model.family_level or model.family!=model.model else ""
        self.details.setText(f"{model.status.upper()}\n\n{model.model}\n{model.manufacturer}{family_note}\n\nResolution / render sizes\n{resolutions}\n\nConnection / transport\n{model.connection_type}\n\nVID:PID / identifiers\n{ids}\n\n{explanation}\n\n{model.notes}")

def product_photo(device_id:str)->QLabel:
    asset_name="trofeo-vision-9-16-official.png" if device_id.endswith("5408") else "trofeo-vision-6-86-official.png"
    asset_path=bundled_path(f"assets/products/{asset_name}")
    if asset_path.exists():
        source=QPixmap(str(asset_path))
        if not source.isNull():
            canvas=QPixmap(142,68);canvas.fill(Qt.transparent);p=QPainter(canvas);p.setRenderHint(QPainter.SmoothPixmapTransform)
            scaled=source.scaled(136,62,Qt.KeepAspectRatio,Qt.SmoothTransformation);p.drawPixmap((142-scaled.width())//2,(68-scaled.height())//2,scaled);p.end()
            label=QLabel();label.setObjectName("productPhoto");label.setAlignment(Qt.AlignCenter);label.setFixedSize(142,68);label.setPixmap(canvas);label.setToolTip("Thermalright Trofeo Vision product reference");label.setProperty("assetPath",str(asset_path));return label
    wide=device_id.endswith("5408");canvas=QPixmap(142,68);canvas.fill(Qt.transparent);p=QPainter(canvas);p.setRenderHint(QPainter.Antialiasing)
    ratio=4.0 if wide else 1280/480;width=124 if wide else 106;height=width/ratio;x=(142-width)/2;y=(68-height)/2+2
    # Original project-owned perspective illustration: rear shadow, metallic
    # shell, glass face and reflected accent. No vendor photograph is bundled.
    p.setPen(Qt.NoPen);p.setBrush(QColor(0,0,0,105));p.drawRoundedRect(QRectF(x+7,y+8,width,height),7,7)
    shell=QColor("#445269");p.setBrush(shell);p.drawRoundedRect(QRectF(x-3,y-3,width+6,height+6),7,7)
    screen=QLinearGradient(x,y,x+width,y+height);screen.setColorAt(0,QColor("#160b31"));screen.setColorAt(.46,QColor("#3d164f"));screen.setColorAt(1,QColor("#07162e"));p.setBrush(screen);p.drawRoundedRect(QRectF(x,y,width,height),5,5)
    # Original Oni night-scene miniature: skyline, moon and a stylized crimson
    # eye. It reads like a lit product display rather than a placeholder line.
    p.setPen(Qt.NoPen);p.setBrush(QColor(255,74,111,210));p.drawEllipse(QRectF(x+width*.68,y+height*.12,height*.26,height*.26))
    p.setBrush(QColor("#07101e"))
    for i,f in enumerate((.05,.14,.24,.34,.46,.57,.66,.78,.88)):
        bh=height*(.22+((i*37)%46)/100);p.drawRect(QRectF(x+width*f,y+height-bh,width*.07,bh))
    eye=QPainterPath();eye.moveTo(x+width*.18,y+height*.54);eye.cubicTo(x+width*.35,y+height*.20,x+width*.62,y+height*.22,x+width*.78,y+height*.48);eye.cubicTo(x+width*.58,y+height*.76,x+width*.34,y+height*.78,x+width*.18,y+height*.54);p.setPen(QPen(QColor("#ff416f"),1.5));p.setBrush(QColor(15,7,24,190));p.drawPath(eye);p.setBrush(QColor("#8b64ff"));p.drawEllipse(QRectF(x+width*.46,y+height*.39,height*.15,height*.15))
    p.setPen(QPen(QColor(255,255,255,40),1));p.drawLine(int(x+6),int(y+5),int(x+width-7),int(y+5));p.end()
    label=QLabel();label.setObjectName("productPhoto");label.setAlignment(Qt.AlignCenter);label.setFixedSize(142,68);label.setPixmap(canvas);label.setToolTip("Original Oni illustration of this Thermalright LCD form factor");label.setProperty("assetPath","procedural:oni-device-thumbnail");return label

class PreviewBridge(QObject):
    frameReady = Signal()
    def __init__(self, parent=None):
        super().__init__(parent); self._lock = threading.Lock(); self._latest = None; self._scheduled = False; self.dropped = 0
    def submit(self,image):
        if isinstance(image,QImage) and (image.width()>720 or image.height()>240):
            image=image.scaled(720,240,Qt.KeepAspectRatio,Qt.FastTransformation)
        notify=False
        with self._lock:
            if self._latest is not None:self.dropped+=1
            self._latest=image
            if not self._scheduled:self._scheduled=True;notify=True
        if notify:self.frameReady.emit()
    def take(self):
        with self._lock: image, self._latest = self._latest, None; self._scheduled = False; return image
    def clear(self):
        with self._lock: self._latest = None; self._scheduled = False
    @property
    def pending(self):
        with self._lock: return int(self._latest is not None)

class DisplayScanBridge(QObject):
    resultsReady = Signal(object)
    failed = Signal(str)

class PreviewLabel(QLabel):
    zoomRequested = Signal(float); panRequested = Signal(int, int); nudgeRequested = Signal(int, int)
    def __init__(self, *args, preview_height=190, **kwargs):
        super().__init__(*args, **kwargs); self._drag = None; self.paint_count = 0; self.preview_height = int(preview_height)
        self.setFocusPolicy(Qt.StrongFocus)
    def paintEvent(self, event): self.paint_count += 1; super().paintEvent(event)
    def sizeHint(self): return QSize(500, self.preview_height)
    def minimumSizeHint(self): return QSize(0, self.preview_height)
    def wheelEvent(self, event): self.zoomRequested.emit(1.1 if event.angleDelta().y() > 0 else 1 / 1.1); event.accept()
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton: self.setFocus(Qt.MouseFocusReason); self._drag = event.position(); event.accept()
        else: super().mousePressEvent(event)
    def mouseMoveEvent(self, event):
        if self._drag is not None:
            delta = event.position() - self._drag; self._drag = event.position(); self.panRequested.emit(int(delta.x()), int(delta.y())); event.accept()
        else: super().mouseMoveEvent(event)
    def mouseReleaseEvent(self, event): self._drag = None; super().mouseReleaseEvent(event)
    def keyPressEvent(self, event):
        movement = {Qt.Key_Left: (-1, 0), Qt.Key_Right: (1, 0), Qt.Key_Up: (0, -1), Qt.Key_Down: (0, 1)}.get(event.key())
        if movement:
            step = 10 if event.modifiers() & Qt.ShiftModifier else 1
            self.nudgeRequested.emit(movement[0] * step, movement[1] * step); event.accept(); return
        super().keyPressEvent(event)

class MediaLibraryList(QListWidget):
    def startDrag(self, actions):
        item = self.currentItem()
        if not item: return
        path = item.data(Qt.UserRole); mime = QMimeData(); mime.setUrls([QUrl.fromLocalFile(path)])
        drag = QDrag(self); drag.setMimeData(mime); drag.exec(Qt.CopyAction)

class MediaLibraryDialog(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent); self.settings = settings; self.setWindowTitle("Media Library"); self.resize(720, 480)
        v = QVBoxLayout(self); self.list = MediaLibraryList(); self.list.setViewMode(QListWidget.IconMode); self.list.setIconSize(QImage(180, 90, QImage.Format_RGB32).size()); self.list.setDragEnabled(True); self.list.setSelectionMode(QAbstractItemView.SingleSelection); v.addWidget(self.list)
        row = QHBoxLayout(); add = QPushButton("Add Media"); remove = QPushButton("Remove Reference"); row.addWidget(add); row.addWidget(remove); row.addStretch(); v.addLayout(row)
        add.clicked.connect(self.add_media); remove.clicked.connect(self.remove_selected); self.refresh()
    def refresh(self):
        self.list.clear()
        for raw in self.settings.media_library:
            p = Path(raw)
            if not p.is_file() or detect_media_kind(p) is None: continue
            item = QListWidgetItem(p.name); item.setData(Qt.UserRole, str(p)); pix = QPixmap(str(p))
            if not pix.isNull(): item.setIcon(QIcon(pix.scaled(180, 90, Qt.KeepAspectRatio, Qt.SmoothTransformation)))
            item.setToolTip(str(p)); self.list.addItem(item)
    def add_media(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Add media references", "", MEDIA)
        for p in files:
            if detect_media_kind(p) is not None and p not in self.settings.media_library: self.settings.media_library.append(p)
        self.refresh()
    def remove_selected(self):
        item = self.list.currentItem()
        if item and item.data(Qt.UserRole) in self.settings.media_library: self.settings.media_library.remove(item.data(Qt.UserRole)); self.refresh()

class SettingsDialog(QDialog):
    def __init__(self, settings, cards, parent=None):
        super().__init__(parent); self.settings = settings; self.cards = cards; self.setWindowTitle("Settings and diagnostics"); self.resize(700, 560)
        tabs = QTabWidget(self); general = QWidget(); form = QFormLayout(general); self.checks = {}
        for key, label in (("start_with_windows", "Start with Windows"), ("start_minimized", "Start minimized"), ("minimize_to_tray", "Minimize to tray"), ("restore_previous_media", "Restore previous media"), ("auto_reconnect", "Auto reconnect"), ("remember_window_position", "Remember window position"), ("stale_frame_dropping", "Drop stale frames"), ("resume_playback", "Resume playback"), ("hardware_decode", "Optional D3D11 video decode")):
            box = QCheckBox(); box.setChecked(bool(getattr(settings, key))); self.checks[key] = box; form.addRow(label, box)
        self.close_behavior = QComboBox(); self.close_behavior.addItem("Minimize to tray", "minimize_to_tray"); self.close_behavior.addItem("Exit application", "exit_application"); self.close_behavior.setCurrentIndex(max(0, self.close_behavior.findData(settings.close_button_behavior))); form.addRow("Close button behavior", self.close_behavior)
        self.default_fps = QComboBox(); self.default_fps.addItems(list(RATE_LABELS)); self.default_fps.setCurrentText("Auto (Recommended)" if settings.default_fps in {"Auto", "Automatic"} else settings.default_fps); form.addRow("Default FPS", self.default_fps); tabs.addTab(general, "General & playback")
        self.default_mode = QComboBox(); self.default_mode.addItems([x.value for x in FitMode]); self.default_mode.setCurrentText(settings.default_display_mode); form.addRow("Default display mode", self.default_mode)
        self.performance_mode = QComboBox(); self.performance_mode.addItems(list(MODES)); self.performance_mode.setCurrentText(settings.performance_mode); form.addRow("Performance profile", self.performance_mode)
        self.sensor_interval = QComboBox(); self.sensor_interval.addItems(["250", "500", "1000", "2000"]); self.sensor_interval.setCurrentText(str(settings.sensor_interval_ms)); form.addRow("Sensor polling (ms)", self.sensor_interval)
        devices = QWidget(); devv = QVBoxLayout(devices)
        for card in cards:
            row = QHBoxLayout(); row.addWidget(QLabel(f"{card.title_text}: {card.connection.text()}")); row.addStretch(); retry = QPushButton("Reconnect"); retry.clicked.connect(lambda _, c=card: c.reconnect()); row.addWidget(retry); devv.addLayout(row)
        devv.addStretch(); tabs.addTab(devices, "Devices")
        diag = QWidget(); dv = QVBoxLayout(diag)
        for card in cards:
            policy = POLICIES[card.device_id]; text = (f"{card.title_text}  {card.device_id}\nResolution: {card.size_target[0]}×{card.size_target[1]}\n"
                f"Interface/endpoints: {card.mapping}\nPersistence: {policy.confidence}, requested {policy.requested_fps:g} FPS, observed {policy.observed_fps:.3f} FPS\n"
                f"Actual preview FPS: {card.actual_fps():.1f} · Dropped: {card.drop_count()}\nLast error: {card.session.metrics.last_error or 'None'}")
            label = QLabel(text); label.setObjectName("diagnostic"); label.setTextInteractionFlags(Qt.TextSelectableByMouse); dv.addWidget(label)
        export = QPushButton("Export Diagnostics"); export.clicked.connect(self.export_diagnostics); dv.addWidget(export); dv.addStretch(); tabs.addTab(diag, "Advanced diagnostics")
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel); buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject)
        v = QVBoxLayout(self); v.addWidget(tabs); v.addWidget(buttons)
    def accept(self):
        for k, w in self.checks.items(): setattr(self.settings, k, w.isChecked())
        self.settings.close_button_behavior = self.close_behavior.currentData(); self.settings.close_to_tray = self.settings.close_button_behavior == "minimize_to_tray"
        self.settings.default_fps = self.default_fps.currentText(); self.settings.default_display_mode = self.default_mode.currentText(); self.settings.performance_mode = self.performance_mode.currentText(); self.settings.sensor_interval_ms = int(self.sensor_interval.currentText()); super().accept()
    def export_diagnostics(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export diagnostics", "oni-thermal-lcd-diagnostics.json", "JSON (*.json)")
        if not path: return
        data = {"application": "Oni Thermal LCD Control", "usb_payloads_included": False, "displays": []}
        for c in self.cards:
            p = POLICIES[c.device_id]; definition = device_definition(c.device_id)
            data["displays"].append({"name": c.title_text, "manufacturer": definition.manufacturer, "model": definition.model, "vid_pid": c.device_id, "selected_adapter": definition.backend, "support_status": definition.support_status, "connection": c.connection.text(), "transport": definition.connection_type, "interface": definition.interface, "out_endpoint": definition.out_endpoint, "in_endpoint": definition.in_endpoint, "transmitted_resolution": list(c.size_target), "orientation": definition.orientation, "frame_format": "full-frame JPEG" if definition.full_frame_jpeg_required else "device-specific", "brightness_support": definition.brightness_support, "maximum_fps": definition.maximum_fps, "mapping": c.mapping, "requested_fps": c.fps.currentText(), "actual_fps": c.actual_fps(), "initialization_result": c.session.state.value, "usb_bytes_per_second": c.session.metrics.usb_bytes_per_second, "last_send_ms": c.session.metrics.last_send_ms, "ack_latency_ms": c.session.metrics.ack_latency_ms, "dropped_frames": c.drop_count(), "output_error": c.session.metrics.last_error, "persistence_confidence": p.confidence})
        Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")

class HardwareMonitorDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent); self.setWindowTitle("Hardware Monitor Designer"); self.resize(900, 520); v = QVBoxLayout(self); row = QHBoxLayout(); self.target = QComboBox(); self.target.addItem('9.16" LCD', "0416:5408"); self.target.addItem('6" LCD', "0416:5302"); self.template = QComboBox(); self.template.setPlaceholderText("No saved layouts"); row.addWidget(QLabel("Display")); row.addWidget(self.target); row.addWidget(QLabel("Template")); row.addWidget(self.template); row.addStretch(); v.addLayout(row)
        self.preview = QLabel(); self.preview.setMinimumHeight(250); self.preview.setAlignment(Qt.AlignCenter); self.preview.setObjectName("preview"); v.addWidget(self.preview); note = QLabel("Read-only providers · 1/2/4/10 Hz sensor refresh · layouts remain independent from media on the other LCD"); note.setObjectName("muted"); v.addWidget(note)
        sensor_row = QHBoxLayout(); self.sensor_search = QLineEdit(); self.sensor_search.setPlaceholderText("Search discovered sensors"); scan = QPushButton("Refresh Sensors"); sensor_row.addWidget(self.sensor_search); sensor_row.addWidget(scan); v.addLayout(sensor_row); self.sensor_list = QListWidget(); self.sensor_list.setMaximumHeight(110); v.addWidget(self.sensor_list); scan.clicked.connect(self._refresh_sensors); self.sensor_search.textChanged.connect(self._filter_sensors)
        buttons = QDialogButtonBox(QDialogButtonBox.Close); buttons.rejected.connect(self.reject); v.addWidget(buttons); self.target.currentIndexChanged.connect(self.refresh); self.template.currentTextChanged.connect(self.refresh); self.refresh()
    def refresh(self):
        target = self.target.currentData(); layout = templates(target).get(self.template.currentText())
        if layout is None:self.preview.setPixmap(QPixmap());self.preview.setText("No saved layouts");return
        sample = {"game.fps": 144, "game.frametime": 6.9, "gpu.usage": 82, "gpu.temperature": 63, "gpu.hotspot": 72, "cpu.temperature": 55, "cpu.usage": 34, "memory.usage": 42, "network.download": 240, "network.upload": 32}
        image = MonitorRenderer(layout).render(sample); q = QImage(image.tobytes("raw", "RGB"), image.width, image.height, image.width * 3, QImage.Format_RGB888).copy(); self.preview.setPixmap(QPixmap.fromImage(q).scaled(self.preview.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
    def _refresh_sensors(self):
        from .sensors import Aida64Provider, AfterburnerProvider, HwinfoProvider, NativeBasicProvider, RtssProvider, SensorManager
        snapshot = SensorManager((HwinfoProvider(), AfterburnerProvider(), RtssProvider(), Aida64Provider(), NativeBasicProvider())).poll(); self.sensor_list.clear()
        for value in snapshot.values:
            item = QListWidgetItem(f"{value.provider} · {value.category} · {value.name}: {value.value} {value.unit}"); item.setData(Qt.UserRole, value.definition.qualified_id); self.sensor_list.addItem(item)
        if not snapshot.values: self.sensor_list.addItem("No providers currently expose values. Media playback is unaffected.")
    def _filter_sensors(self, text):
        needle = text.casefold()
        for i in range(self.sensor_list.count()): self.sensor_list.item(i).setHidden(needle not in self.sensor_list.item(i).text().casefold())

class ProfileManagerDialog(QDialog):
    def __init__(self, settings, store, cards, parent=None):
        super().__init__(parent); self.settings = settings; self.store = store; self.cards = cards; self.setWindowTitle("Profile Library"); self.resize(650, 440)
        v = QVBoxLayout(self); v.addWidget(QLabel("<h2>Profile library</h2><span style='color:#8290a4'>Named profiles preserve independent settings for both displays. Portable .oniprofile packages include required media.</span>")); self.list = QListWidget(); v.addWidget(self.list)
        row = QHBoxLayout()
        for text, callback in (("New", self.create), ("Rename", self.rename), ("Duplicate", self.duplicate), ("Save", self.save_selected), ("Save As", self.save_as), ("Delete", self.delete)):
            button = QPushButton(text); button.clicked.connect(callback); row.addWidget(button)
        v.addLayout(row); theme = QHBoxLayout(); imp = QPushButton("Import .oniprofile"); exp = QPushButton("Export .oniprofile"); legacy = QPushButton("Legacy .onitheme…"); theme.addWidget(imp); theme.addWidget(exp); theme.addWidget(legacy); theme.addStretch(); v.addLayout(theme); imp.clicked.connect(self.import_package); exp.clicked.connect(self.export_package); legacy.clicked.connect(self.import_legacy)
        buttons = QDialogButtonBox(QDialogButtonBox.Close); buttons.rejected.connect(self.reject); v.addWidget(buttons); self.refresh()
    def refresh(self, select=None):
        self.list.clear(); self.list.addItems(sorted(self.settings.profiles)); matches = self.list.findItems(select or self.settings.active_profile, Qt.MatchExactly)
        if matches: self.list.setCurrentItem(matches[0])
    def selected(self): return self.list.currentItem().text() if self.list.currentItem() else None
    def _name(self, title, default=""):
        value, ok = QInputDialog.getText(self, title, "Profile name", text=default); value = " ".join(value.strip().split()); return value if ok and value else None
    def _save_current(self, name, overwrite=False):
        source_profile = self.settings.active_profile
        try:
            for card in self.cards: save_profile_record(self.settings, name, card.device_id, card.profile(), overwrite=overwrite or name in self.settings.profiles)
        except (ValueError, OverflowError, FileExistsError) as exc: QMessageBox.warning(self, "Profile not saved", str(exc)); return False
        if source_profile in self.settings.monitor_layouts: self.settings.monitor_layouts[name] = deepcopy(self.settings.monitor_layouts[source_profile])
        self.settings.active_profile = name; self.store.save(self.settings); self.refresh(name); return True
    def create(self):
        name = self._name("Create profile")
        if name: self._save_current(name)
    def save_selected(self):
        name = self.selected()
        if name: self._save_current(name, overwrite=True)
    def save_as(self):
        name = self._name("Save profile as", self.selected() or "Profile")
        if name:
            if name in self.settings.profiles and QMessageBox.question(self, "Replace profile", f"A profile named '{name}' already exists.\nReplace it?", QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel) != QMessageBox.Yes: return
            self._save_current(name, overwrite=name in self.settings.profiles)
    def rename(self):
        old = self.selected(); name = self._name("Rename profile", old or "")
        if old and name and name != old:
            try: rename_profile(self.settings, old, name)
            except (ValueError, FileExistsError) as exc: QMessageBox.warning(self, "Profile not renamed", str(exc)); return
            if old in self.settings.monitor_layouts: self.settings.monitor_layouts[name] = self.settings.monitor_layouts.pop(old)
            self.store.save(self.settings); self.refresh(name)
    def duplicate(self):
        old = self.selected(); name = self._name("Duplicate profile", f"{old} Copy" if old else "")
        if old and name:
            try: duplicate_profile(self.settings, old, name)
            except (ValueError, OverflowError, FileExistsError) as exc: QMessageBox.warning(self, "Profile not duplicated", str(exc)); return
            if old in self.settings.monitor_layouts: self.settings.monitor_layouts[name] = deepcopy(self.settings.monitor_layouts[old])
            self.store.save(self.settings); self.refresh(name)
    def delete(self):
        name = self.selected()
        if name and len(self.settings.profiles) > 1: self.settings.profiles.pop(name); self.settings.monitor_layouts.pop(name, None); self.settings.active_profile = next(iter(self.settings.profiles)); self.store.save(self.settings); self.refresh()
    def _target(self, title):
        labels = [card.title_text for card in self.cards]; label, ok = QInputDialog.getItem(self, title, "Target display", labels, 0, False); return next((card for card in self.cards if card.title_text == label), None) if ok else None
    def export_package(self):
        name = self.selected(); card = self._target("Export profile")
        if not name or card is None: return
        default = f"{safe_filename(name)}_{'9.16' if card.device_id.endswith('5408') else '6.86'}.oniprofile"; path, _ = QFileDialog.getSaveFileName(self, "Export portable profile", default, "Oni Profile (*.oniprofile)")
        if not path: return
        profile = self.settings.profiles.get(name, {}).get(card.device_id)
        if not profile: QMessageBox.warning(self, "Export unavailable", "The selected profile has no settings for this display."); return
        try: export_profile(Path(path), name, card.device_id, profile, monitor_layout=self.settings.monitor_layouts.get(name, {}).get(card.device_id), output_mode=self.settings.output_modes.get(card.device_id, "media"), sensor_template=self.settings.monitor_templates.get(card.device_id, ""), preview_scale=self.settings.preview_scales.get(card.device_id, 100))
        except Exception as exc: QMessageBox.critical(self, "Export failed", str(exc))
    def import_package(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import portable profile", "", "Oni Profile (*.oniprofile)"); card = self._target("Import profile") if path else None
        if not path or card is None: return
        try: result = import_profile(Path(path), self.store.path.parent / "profile-assets", card.device_id)
        except Exception as exc: QMessageBox.critical(self, "Import failed", str(exc)); return
        if result.compatibility != Compatibility.EXACT:
            source = result.source_device or "unknown device"; target = card.title_text
            detail = f"Compatibility: {result.compatibility.value}\n\nThis profile was created for {source}.\nYour selected display is {target}.\n\nCrop, zoom, positioning, sensor layout and media framing may need adjustment.\n\nImport anyway?"
            if QMessageBox.question(self, "Profile compatibility", detail, QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel) != QMessageBox.Yes: return
        name = result.name
        if name in self.settings.profiles and QMessageBox.question(self, "Replace profile", f"A profile named '{name}' already exists.\nReplace it?", QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel) != QMessageBox.Yes: return
        try: save_profile_record(self.settings, name, card.device_id, result.profile, overwrite=name in self.settings.profiles)
        except (ValueError, OverflowError, FileExistsError) as exc: QMessageBox.warning(self, "Import failed", str(exc)); return
        if result.monitor_layout is not None: self.settings.monitor_layouts.setdefault(name, {})[card.device_id] = result.monitor_layout
        self.settings.output_modes[card.device_id] = result.output_mode; self.settings.monitor_templates[card.device_id] = result.sensor_template; self.settings.preview_scales[card.device_id] = result.preview_scale; self.store.save(self.settings); self.refresh(name)
        if result.warnings: QMessageBox.warning(self, "Import notes", "\n".join(result.warnings))
    def import_legacy(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import legacy theme", "", "Oni Theme (*.onitheme)")
        if not path: return
        try: data, warnings = import_theme(Path(path), self.store.path.parent / "profile-assets" / "legacy"); merge_theme(self.settings, data); self.store.save(self.settings); self.refresh()
        except Exception as exc: QMessageBox.critical(self, "Import failed", str(exc)); return
        if warnings: QMessageBox.warning(self, "Compatibility warning", "\n".join(warnings))

class DisplayCard(QFrame):
    mediaChanged = Signal(str)
    profileSelected = Signal(str); profileSaveRequested = Signal(str); profileSaveAsRequested = Signal(str); profileManageRequested = Signal()
    def __init__(self, title, size, device_id, parent=None, hardware_sender=None, media_directory_provider=None, media_directory_selected=None):
        super().__init__(parent); self.title_text = title; self.device_id = device_id; self.size_target = size; self.path = None; self._media_paths = {kind: None for kind in MediaKind}; self.media_kind = MediaKind.PHOTO; self.selected_media_kind = MediaKind.PHOTO; self.scheduler = None; self.shared_hub = None; self.playing = False; self.desired_playback_state = "Stopped"; self.hardware_started = False; self.preview_enabled = True; self.window_visible = True; self.foreground_preview_fps = 20.0; self.preview_fps = 20.0; self._next_preview = 0.0; self._last_encoded_source_index = None; self._scheduler_key = None; self.scheduler_creations = 0; self.coordinator = None; self.timeline_epoch = None; self.output_mode_request = None; self.media_directory_provider = media_directory_provider; self.media_directory_selected = media_directory_selected; self.output_ownership = OutputOwnership(); self._output_lease = self.output_ownership.lease(); self._overlay_lock = threading.Lock(); self._sensor_overlay = None; self._transform_lock = threading.Lock(); self.transform_mode = FitMode.FIT; self.transform_rotation = 0; self.pan_x = 0; self.pan_y = 0; self.zoom = 1.0; self.transform_generation = 0; self.quality_profile = "Balanced"; self.brightness = 100; self._preview_presented = deque(maxlen=180); self.preview_intervals = deque(maxlen=180); self._static_next_compose = 0.0; self.setAcceptDrops(True); self.setObjectName("card"); self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._last_delivered_frame_ref = None; self._preview_media_path = None
        self.mapping = "interface 0 · BULK OUT 0x09 · BULK IN 0x81" if device_id.endswith("5408") else "HID MI_00 · INTERRUPT OUT 0x02 · INTERRUPT IN 0x83"
        self.qimage_count = 0; self.qpixmap_count = 0; self.preview_scale_count = 0; self.metrics_update_count = 0; self._last_primary_metrics = ""; self._last_detail_metrics = ""; self.bridge = PreviewBridge(self); self.bridge.frameReady.connect(self._consume_preview)
        self.pipeline = MediaPipeline(2); self._injected_sender = hardware_sender; self.hardware_sender = hardware_sender or build_gui_sender(device_id)
        self.session = DisplaySession(device_id, self.hardware_sender, policy=POLICIES[device_id])
        
        # --- BOYUT HESAPLAMALARI ---
        self.is_wide = device_id.endswith("5408")
        identity = ("Trofeo Vision 9.16 LCD", "9.16\" · 1920 × 480 (4:1)") if self.is_wide else ("Trofeo Vision LCD", "6.86\" · 1280 × 480 (8:3)")
        
        # Render ve Stacked (Alt Alta) mod boyutu: Devasa
        self.render_size = (960, 240) if self.is_wide else (768, 288)
        self.stacked_size = self.render_size
        # Side by Side (Yan Yana) mod boyutu: Tam Yarı Yarıya (Oranlar kusursuz korunur)
        self.sbs_size = (480, 120) if self.is_wide else (384, 144) 
        
        v = QVBoxLayout(self); self.card_layout = v; v.setContentsMargins(12, 10, 12, 10); v.setSpacing(8)
        
        self.header_widget = QWidget(); self.header_widget.setFixedHeight(54); head = QHBoxLayout(self.header_widget); head.setContentsMargins(0, 0, 0, 0); head.setSpacing(10)
        self.product_photo = product_photo(device_id); self.product_photo.setFixedSize(110, 52); self.product_photo.setScaledContents(True); head.addWidget(self.product_photo)
        
        dev_info = QVBoxLayout(); dev_info.setSpacing(1); dev_info.setContentsMargins(0, 0, 0, 0)
        vendor_lbl = QLabel("THERMALRIGHT"); vendor_lbl.setObjectName("vendorLabel")
        name_lbl = QLabel(identity[0]); name_lbl.setObjectName("deviceNameLabel")
        spec_lbl = QLabel(identity[1]); spec_lbl.setObjectName("deviceSpecLabel")
        dev_info.addWidget(vendor_lbl); dev_info.addWidget(name_lbl); dev_info.addWidget(spec_lbl)
        head.addLayout(dev_info); head.addStretch()

        self.dot = QLabel("●"); self.dot.setObjectName("connectedDot")
        self.connection = QLabel("Connected"); self.connection.setObjectName("connectionText")
        self.media_badge = QLabel("PHOTO · STATIC"); self.media_badge.setObjectName("mediaBadge")
        self.header_fps = QLabel("Output 24 FPS"); self.header_fps.setObjectName("secondaryStatus")
        self.header_fps.hide()
        
        head.addWidget(self.dot); head.addWidget(self.connection); head.addSpacing(6)
        head.addWidget(self.media_badge); head.addSpacing(6)
        head.addWidget(self.header_fps); head.addSpacing(8)
        
        head.addWidget(QLabel("Brightness")); self.header_brightness_slider = QSlider(Qt.Horizontal); self.header_brightness_slider.setRange(0, 100); self.header_brightness_slider.setValue(100); self.header_brightness_slider.setFixedWidth(110)
        self.header_brightness = QLabel("100%"); self.header_brightness.setObjectName("secondaryStatus"); self.header_brightness.setFixedWidth(36)
        head.addWidget(self.header_brightness_slider); head.addWidget(self.header_brightness); head.addSpacing(8)
        
        self.header_settings = QToolButton(); self.header_settings.setText("⚙"); self.header_settings.setFixedSize(28, 28); self.header_settings.clicked.connect(lambda: self.window().open_settings() if hasattr(self.window(), "open_settings") else None)
        self.header_overflow = QToolButton(); self.header_overflow.setText("⋮"); self.header_overflow.setFixedSize(28, 28)
        head.addWidget(self.header_settings); head.addWidget(self.header_overflow)
        v.addWidget(self.header_widget)

        self.workspace = QWidget(); self.workspace_layout = QHBoxLayout(self.workspace); self.workspace_layout.setContentsMargins(0, 0, 0, 0); self.workspace_layout.setSpacing(12)
        
        self.preview_column = QWidget(); self.preview_column_layout = QVBoxLayout(self.preview_column); self.preview_column_layout.setContentsMargins(0, 0, 0, 0); self.preview_column_layout.setSpacing(6)
        
        self.preview = PreviewLabel("Drop media here", preview_height=180 if self.is_wide else 190)
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setObjectName("preview")
        self.preview.zoomRequested.connect(self.adjust_zoom); self.preview.panRequested.connect(self.adjust_pan); self.preview.nudgeRequested.connect(self.adjust_pan_native)

        self.media_empty_state = QWidget(); empty_layout = QVBoxLayout(self.media_empty_state); empty_layout.setContentsMargins(16, 16, 16, 16); empty_layout.addStretch()
        self.media_empty_title = QLabel("Add Media"); self.media_empty_title.setObjectName("pageTitle"); self.media_empty_title.setAlignment(Qt.AlignCenter); empty_layout.addWidget(self.media_empty_title)
        self.media_empty_hint = QLabel("Choose a media type, browse for a file, or drag and drop it here."); self.media_empty_hint.setObjectName("muted"); self.media_empty_hint.setAlignment(Qt.AlignCenter); empty_layout.addWidget(self.media_empty_hint)
        empty_actions = QHBoxLayout(); empty_actions.addStretch(); self.media_empty_buttons = {}
        for label, kind in (("Photo", MediaKind.PHOTO), ("Video", MediaKind.VIDEO), ("GIF", MediaKind.GIF)):
            button = QPushButton(label); button.clicked.connect(lambda _checked=False, k=kind: self._choose_media_kind(k)); self.media_empty_buttons[kind] = button; empty_actions.addWidget(button)
        self.media_empty_browse = QPushButton("Browse"); self.media_empty_browse.setObjectName("primaryButton"); self.media_empty_browse.clicked.connect(self.choose); empty_actions.addWidget(self.media_empty_browse); empty_actions.addStretch(); empty_layout.addLayout(empty_actions); empty_layout.addStretch()
        
        self.preview_stack = QStackedWidget()
        self.preview_stack.addWidget(self.preview)
        self.preview_stack.addWidget(self.media_empty_state)
        
        # İlk açılışta Stacked boyutunu ata
        self.preview.setFixedSize(*self.stacked_size)
        self.preview_stack.setFixedSize(*self.stacked_size)
        
        self.preview_column_layout.addStretch()
        self.preview_column_layout.addWidget(self.preview_stack, 0, Qt.AlignCenter)
        self.preview_column_layout.addStretch()

        self.preview_footer = QFrame(); self.preview_footer.setObjectName("previewFooter"); footer = QHBoxLayout(self.preview_footer); footer.setContentsMargins(8, 4, 8, 4); footer.setSpacing(4)
        self.footer_thumbnail = product_photo(device_id); self.footer_thumbnail.setFixedSize(36, 24); self.footer_thumbnail.setScaledContents(True)
        self.footer_name = QLabel("No media selected"); self.footer_name.setObjectName("footerMediaName"); self.footer_name.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed); self.footer_name.setMinimumWidth(60)
        footer.addWidget(self.footer_thumbnail); footer.addWidget(self.footer_name)
        
        self.footer_change = QPushButton("Change"); self.footer_clear = QPushButton("Clear")
        self.footer_play = QPushButton("Play"); self.footer_pause = QPushButton("Pause"); self.footer_stop = QPushButton("Stop")
        
        self.footer_play.setObjectName("btnPlay"); self.footer_pause.setObjectName("btnPause"); self.footer_stop.setObjectName("btnStop"); self.footer_clear.setObjectName("btnClear")
        self.footer_change.clicked.connect(self.choose); self.footer_clear.clicked.connect(self.clear); self.footer_play.clicked.connect(self.play); self.footer_pause.clicked.connect(self.pause); self.footer_stop.clicked.connect(self.stop)
        
        for btn, width in ((self.footer_change, 92), (self.footer_clear, 48), (self.footer_play, 48), (self.footer_pause, 54), (self.footer_stop, 48)):
            btn.setFixedSize(width, 28); footer.addWidget(btn)
        
        footer.addSpacing(6)
        self.footer_mode_buttons = {}
        for name in ("Fit", "Fill", "Center"):
            btn = QPushButton(name); btn.setCheckable(True); btn.setFixedHeight(28); btn.setFixedWidth(50)
            btn.clicked.connect(lambda checked, n=name: self.set_transform_mode_str(n) if checked else None)
            self.footer_mode_buttons[name] = btn; footer.addWidget(btn)
        self.footer_mode_buttons["Fit"].setChecked(True)

        footer.addSpacing(6)
        self.pan_x_box = QSpinBox(); self.pan_y_box = QSpinBox(); self.zoom_box = QDoubleSpinBox(); self.rotation = QComboBox()
        for box in (self.pan_x_box, self.pan_y_box): box.setRange(-8192, 8192); box.setFixedWidth(74); box.setFixedHeight(28)
        self.zoom_box.setRange(1, 8); self.zoom_box.setDecimals(2); self.zoom_box.setSingleStep(0.05); self.zoom_box.setValue(1); self.zoom_box.setFixedWidth(74); self.zoom_box.setFixedHeight(28)
        self.rotation.addItems(["0°", "90°", "180°", "270°"]); self.rotation.setFixedWidth(74); self.rotation.setFixedHeight(28)

        self.footer_reset = QPushButton("Reset"); self.footer_reset.setFixedHeight(28); self.footer_reset.setFixedWidth(56); self.footer_reset.clicked.connect(self.reset_transform); footer.addWidget(self.footer_reset)
        
        self.preview_column_layout.addWidget(self.preview_footer, 0)
        self.workspace_layout.addWidget(self.preview_column, 3)

        self.unified_inspector = QFrame(); self.unified_inspector.setObjectName("unifiedInspector"); self.unified_inspector.setMinimumWidth(326); self.unified_inspector.setMaximumWidth(336)
        insp_v = QVBoxLayout(self.unified_inspector); insp_v.setContentsMargins(10, 8, 10, 8); insp_v.setSpacing(8)

        disp_group = QGroupBox("Display"); disp_grid = QGridLayout(disp_group); disp_grid.setContentsMargins(6, 6, 6, 6); disp_grid.setSpacing(6)
        disp_grid.addWidget(QLabel("Brightness"), 0, 0)
        self.brightness_slider = QSlider(Qt.Horizontal); self.brightness_slider.setRange(0, 100); self.brightness_slider.setValue(100)
        self.brightness_value = QLabel("100%"); self.brightness_value.setFixedWidth(32)
        disp_grid.addWidget(self.brightness_slider, 0, 1); disp_grid.addWidget(self.brightness_value, 0, 2)
        insp_v.addWidget(disp_group)

        media_group = QGroupBox("Media"); media_grid = QGridLayout(media_group); media_grid.setContentsMargins(6, 6, 6, 6); media_grid.setSpacing(6)
        self.media_type_buttons = {}
        type_row = QHBoxLayout(); type_row.setSpacing(4)
        for label, kind in (("Photo", MediaKind.PHOTO), ("Video", MediaKind.VIDEO), ("GIF", MediaKind.GIF)):
            btn = QPushButton(label); btn.setCheckable(True); btn.setFixedHeight(26)
            btn.clicked.connect(lambda checked, k=kind: self.select_media_kind(k) if checked else None)
            self.media_type_buttons[kind] = btn; type_row.addWidget(btn)
        self.media_type_buttons[MediaKind.PHOTO].setChecked(True)
        media_grid.addLayout(type_row, 0, 0, 1, 3)

        self.filename = QLabel("image(10).png"); self.filename.setObjectName("mediaFileName")
        self.choose_button = QPushButton("Add Media"); self.choose_button.setFixedWidth(92); self.choose_button.setFixedHeight(26); self.choose_button.clicked.connect(self.choose)
        media_grid.addWidget(self.filename, 1, 0, 1, 2); media_grid.addWidget(self.choose_button, 1, 2)
        insp_v.addWidget(media_group)

        self.playback_group = QGroupBox("Playback"); play_grid = QGridLayout(self.playback_group); play_grid.setContentsMargins(6, 6, 6, 6); play_grid.setSpacing(6)
        self.fps = QComboBox(); self.fps.addItems(VIDEO_RATE_LABELS)
        self.fps_label = QLabel("FPS"); play_grid.addWidget(self.fps_label, 0, 0); play_grid.addWidget(self.fps, 0, 1, 1, 2)
        self.playback_hint = QLabel("Panel supports up to ~30 FPS"); self.playback_hint.setObjectName("muted"); play_grid.addWidget(self.playback_hint, 1, 0, 1, 3)
        insp_v.addWidget(self.playback_group)

        trans_group = QGroupBox("Transform"); trans_grid = QGridLayout(trans_group); trans_grid.setContentsMargins(6, 6, 6, 6); trans_grid.setSpacing(4)
        self.mode_segments = {}
        mode_row = QHBoxLayout(); mode_row.setSpacing(4)
        for name in ("Fit", "Fill", "Center"):
            btn = QPushButton(name); btn.setCheckable(True); btn.setFixedHeight(26)
            btn.clicked.connect(lambda checked, n=name: self.set_transform_mode_str(n) if checked else None)
            self.mode_segments[name] = btn; mode_row.addWidget(btn)
        self.mode_segments["Fit"].setChecked(True)
        trans_grid.addLayout(mode_row, 0, 0, 1, 4)

        transform_values = QWidget(); transform_values_layout = QGridLayout(transform_values); transform_values_layout.setContentsMargins(0, 2, 0, 0); transform_values_layout.setHorizontalSpacing(4); transform_values_layout.setVerticalSpacing(3)
        transform_values_layout.addWidget(QLabel("X"), 0, 0); transform_values_layout.addWidget(self.pan_x_box, 0, 1)
        transform_values_layout.addWidget(QLabel("Y"), 0, 2); transform_values_layout.addWidget(self.pan_y_box, 0, 3)
        transform_values_layout.addWidget(QLabel("Zoom"), 1, 0); transform_values_layout.addWidget(self.zoom_box, 1, 1)
        transform_values_layout.addWidget(QLabel("Rotation"), 1, 2); transform_values_layout.addWidget(self.rotation, 1, 3)
        trans_grid.addWidget(transform_values, 1, 0, 1, 4)
        insp_v.addWidget(trans_group)

        out_group = QGroupBox("Output"); out_grid = QGridLayout(out_group); out_grid.setContentsMargins(6, 6, 6, 6); out_grid.setSpacing(4)
        self.output_selector = QComboBox(self); self.output_selector.hide()
        self.output_segments = {}
        out_row = QHBoxLayout(); out_row.setSpacing(4)
        for label, val in (("Media", OutputMode.MEDIA.value), ("Sensor Theme", OutputMode.HARDWARE_MONITOR.value), ("Sensor + Media", OutputMode.MEDIA_WITH_SENSOR_OVERLAY.value), ("OFF", OutputMode.STOPPED.value)):
            btn = QPushButton(label); btn.setCheckable(True); btn.setFixedHeight(28); btn.setStyleSheet("padding: 0 3px; font-size: 10px;"); btn.setMinimumWidth(btn.sizeHint().width())
            btn.clicked.connect(lambda checked, v=val: self.set_output_mode_val(v) if checked else None)
            self.output_segments[val] = btn; out_row.addWidget(btn)
        self.output_segments[OutputMode.MEDIA.value].setChecked(True)
        out_grid.addLayout(out_row, 0, 0, 1, 3)
        
        self.monitor_template = QComboBox(); self.monitor_template.addItems(sorted(templates(device_id))); self.monitor_template.hide()
        self.quick_edit = QPushButton("Edit"); self.quick_edit.setCheckable(True); self.quick_edit.hide()
        out_grid.addWidget(self.monitor_template, 1, 0, 1, 2); out_grid.addWidget(self.quick_edit, 1, 2)
        insp_v.addWidget(out_group)
        
        insp_v.addStretch()
        self.workspace_layout.addWidget(self.unified_inspector, 0)
        v.addWidget(self.workspace, 1)

        self.mode = QComboBox(self); self.mode.addItems([x.value for x in FitMode]); self.mode.setMaximumWidth(105); self.mode.hide()
        self.quality_box = QComboBox(self); self.quality_box.addItems(QUALITY_PROFILES); self.quality_box.hide()
        self.auto_preview = QCheckBox(self); self.auto_preview.setChecked(True); self.auto_preview.hide()
        self.preview_scale_slider = QSlider(Qt.Horizontal, self); self.preview_scale_slider.setValue(100); self.preview_scale_slider.hide()
        self.preview_scale_value = QLabel("Auto", self); self.preview_scale_value.hide()
        self.context_tabs = QTabWidget(self); self.context_tabs.hide()
        self.profile_box = QComboBox(self); self.profile_box.setEditable(True); self.profile_box.setInsertPolicy(QComboBox.NoInsert); self.profile_box.setMaximumWidth(170); self.profile_box.setMinimumWidth(120); self.profile_box.hide()
        self.advanced_toggle = QToolButton(self); self.advanced_toggle.hide()
        self.advanced = QWidget(self); self.advanced.hide()
        self.status = QLabel("READY", self); self.status.hide()
        self.output_metrics = QLabel("", self); self.output_metrics.hide()
        self.metrics = QLabel("", self); self.metrics.hide()
        self.connection_retry = QPushButton(self); self.connection_retry.hide()
        self.connection_reconnect = QPushButton(self); self.connection_reconnect.hide()

        self.header_brightness_slider.valueChanged.connect(self.brightness_slider.setValue)
        self.brightness_slider.valueChanged.connect(self.header_brightness_slider.setValue)
        self.brightness_slider.valueChanged.connect(self._brightness_changed)
        self.fps.currentTextChanged.connect(self._fps_changed)
        self.pan_x_box.valueChanged.connect(self._transform_changed)
        self.pan_y_box.valueChanged.connect(self._transform_changed)
        self.zoom_box.valueChanged.connect(self._transform_changed)
        self.rotation.currentIndexChanged.connect(self._transform_changed)

        # Full-runtime compatibility layer. These objects preserve the proven
        # profile/startup/sensor/tray contracts while the visible Gemini UI stays unchanged.
        self._preview_base_height = 180 if self.is_wide else 190
        self._preview_base_width = 720 if self.is_wide else 600
        self.preview_scale = 100
        self.preview_scale_slider.setRange(50, 200); self.preview_scale_slider.setValue(100); self.preview_scale_slider.valueChanged.connect(self.set_preview_scale)

        # Backend control aliases are intentionally separate from the visible footer
        # so legacy visibility rules cannot accidentally hide the new toolbar.
        self.play_button = QPushButton("Show", self); self.pause_button = QPushButton("Pause", self); self.stop_button = QPushButton("Stop", self); self.clear_button = QPushButton("Clear", self)
        for b in (self.play_button,self.pause_button,self.stop_button,self.clear_button): b.hide()
        self.play_button.clicked.connect(self.play); self.pause_button.clicked.connect(self.pause); self.stop_button.clicked.connect(self.stop); self.clear_button.clicked.connect(self.clear)
        self.reset_transform_button = QPushButton("Reset", self); self.reset_transform_button.hide(); self.reset_transform_button.clicked.connect(self.reset_transform)
        self.quality_label = QLabel("Quality", self); self.quality_label.hide()
        self.quality_box = QComboBox(self); self.quality_box.addItems(QUALITY_PROFILES); self.quality_box.setCurrentText("Balanced"); self.quality_box.hide(); self.quality_box.currentTextChanged.connect(self._quality_changed)
        self.theme_label = QLabel("Theme", self); self.theme_label.hide()
        self.inspector_thumbnail = QLabel(self); self.inspector_thumbnail.setFixedSize(38,25); self.inspector_thumbnail.hide()
        self.output_group = out_group; self.inspector_layout = insp_v; self.playback_layout = play_grid

        self.media_type_group = QButtonGroup(self); self.media_type_group.setExclusive(True)
        for _kind,_button in self.media_type_buttons.items(): self.media_type_group.addButton(_button)

        # Preserve the old context-tab API off-screen for integrations/tests.
        self.context_tabs.clear()
        self.media_tab = QWidget(self); self.media_tab_layout = QVBoxLayout(self.media_tab)
        self.transform_tab = QWidget(self); self.transform_tab_layout = QVBoxLayout(self.transform_tab)
        self.monitor_tab = QWidget(self); self.monitor_tab_layout = QVBoxLayout(self.monitor_tab)
        self.device_tab = QWidget(self); self.device_tab_layout = QVBoxLayout(self.device_tab)
        for _label,_tab in (("MEDIA",self.media_tab),("TRANSFORM",self.transform_tab),("MONITOR",self.monitor_tab),("DEVICE",self.device_tab)): self.context_tabs.addTab(_tab,_label)
        self.context_tabs.hide()

        self.profile_box.setEditable(True); self.profile_box.setInsertPolicy(QComboBox.NoInsert); self.profile_box.setMaximumWidth(170); self.profile_box.setMinimumWidth(120)
        self.profile_save_button = QPushButton("Save", self); self.profile_save_button.setFixedWidth(68); self.profile_save_button.hide()
        self.profile_save_as_button = QPushButton("Save As", self); self.profile_save_as_button.setFixedWidth(78); self.profile_save_as_button.hide()
        self.profile_manage_button = QToolButton(self); self.profile_manage_button.setText("⋯"); self.profile_manage_button.hide()
        self.profile_overflow_menu = QMenu(self.profile_manage_button)
        _save_as_action = self.profile_overflow_menu.addAction("Save As…"); _manage_action = self.profile_overflow_menu.addAction("Manage, Import or Export…")
        _save_as_action.triggered.connect(lambda:self.profileSaveAsRequested.emit(self.profile_box.currentText())); _manage_action.triggered.connect(self.profileManageRequested.emit)
        self.profile_manage_button.setMenu(self.profile_overflow_menu); self.profile_manage_button.setPopupMode(QToolButton.InstantPopup)
        self.profile_box.currentTextChanged.connect(self.profileSelected.emit); self.profile_save_button.clicked.connect(lambda:self.profileSaveRequested.emit(self.profile_box.currentText())); self.profile_save_as_button.clicked.connect(lambda:self.profileSaveAsRequested.emit(self.profile_box.currentText()))

        self.monitor_save_button = QPushButton("Save", self); self.monitor_save_as_button = QPushButton("Save As…", self); self.monitor_reset_button = QPushButton("Reset preset", self); self.monitor_edit_hint = QLabel("Turn on Edit Layout, then click an element in the preview.", self)
        for _w in (self.monitor_save_button,self.monitor_save_as_button,self.monitor_reset_button,self.monitor_edit_hint): _w.hide()
        self.home_quick_editor = None
        self.advanced_toggle.setCheckable(True)

        # Populate the hidden authoritative output selector used by profiles and
        # sensor/output ownership logic. Visible segmented buttons mirror it.
        self.output_selector.clear()
        for _label,_value in (("Media",OutputMode.MEDIA),("Sensor Theme",OutputMode.HARDWARE_MONITOR),("Sensor + Media",OutputMode.MEDIA_WITH_SENSOR_OVERLAY),("Off",OutputMode.STOPPED)):
            self.output_selector.addItem(_label,_value.value)
        self.output_selector.currentIndexChanged.connect(lambda:[btn.setChecked(key==self.output_selector.currentData()) for key,btn in self.output_segments.items()])
        self.mode.currentTextChanged.connect(lambda name:[btn.setChecked(key==name) for key,btn in self.mode_segments.items()])
        self.mode.currentTextChanged.connect(lambda name:[btn.setChecked(key==name) for key,btn in self.footer_mode_buttons.items()])

        self._transform_refresh_timer = QTimer(self); self._transform_refresh_timer.setSingleShot(True); self._transform_refresh_timer.setInterval(32); self._transform_refresh_timer.timeout.connect(self._apply_transform_refresh)
        self.timer = QTimer(self); self.timer.timeout.connect(self._update_metrics); self.timer.start(500)
        self._update_media_controls(); self.update_output_controls(); self._update_preview_geometry()

    # --- YENİ EKLENEN LAYOUT MODU DEĞİŞTİRİCİ ---
    def _fit_side_by_side_preview(self):
        """Use almost all free space in the left preview column in Side-by-Side."""
        if not getattr(self, "_side_by_side_active", False):
            return

        # After Qt has laid the two cards out, this is the real width remaining
        # beside the compact inspector.  Fill it instead of using a small
        # hard-coded preview size.
        available=self.preview_column.contentsRect();available_w=max(280,available.width()-8);available_h=max(105,available.height()-self.preview_footer.sizeHint().height()-18)
        ratio=self.size_target[0]/self.size_target[1]

        # Keep a small breathing margin but otherwise make the LCD preview as
        # large as the half-screen card allows.
        width=min(available_w,int(available_h*ratio));height=int(round(width/ratio))

        self.preview.setFixedSize(width, height)
        self.preview_stack.setFixedSize(width, height)

    def sizeHint(self):
        # Keep the card's layout hint stable after its first real layout query.
        # Setting/changing preview pixmaps must never make the whole card request
        # a different width/height; the preview itself already has a bounded
        # fixed geometry. This preserves responsive resizing while preventing
        # media frames from changing the parent layout's preferred size.
        hint = QFrame.sizeHint(self)
        cached = getattr(self, "_stable_card_size_hint", None)
        if cached is None:
            self._stable_card_size_hint = QSize(hint)
            return hint
        return QSize(cached)

    def set_layout_mode(self, side_by_side: bool):
        # Stacked mode is intentionally left exactly as before.
        self._side_by_side_active = bool(side_by_side)

        if side_by_side:
            # Give Qt one event-loop turn to finish splitting the window, then
            # size the preview from the *actual* remaining width.
            QTimer.singleShot(0, self._fit_side_by_side_preview)
            QTimer.singleShot(60, self._fit_side_by_side_preview)
        else:
            self.preview.setFixedSize(*self.stacked_size)
            self.preview_stack.setFixedSize(*self.stacked_size)

        # Keep the compact footer actions available in stacked mode. Transform
        # values live in the inspector in both layouts.
        for button in self.footer_mode_buttons.values():
            button.setVisible(not side_by_side)
        self.footer_reset.setVisible(not side_by_side)

        self.preview_column.setMinimumWidth(0)
        self.workspace.setMinimumWidth(0)
        self.setMinimumWidth(0)

        if self.path and not self.playing:
            self._apply_transform_refresh()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0,self._update_workspace_layout);QTimer.singleShot(0,self._update_preview_geometry)

    def set_transform_mode_str(self, name: str):
        self.mode.setCurrentText(name)
        for k, btn in self.mode_segments.items(): btn.setChecked(k == name)
        for k, btn in self.footer_mode_buttons.items(): btn.setChecked(k == name)
        self._transform_changed()

    def set_output_mode_val(self, val: str):
        idx = self.output_selector.findData(val)
        if idx >= 0: self.output_selector.setCurrentIndex(idx)
        for k, btn in self.output_segments.items(): btn.setChecked(k == val)
        self.update_output_controls()

    def update_output_controls(self):
        theme=self.output_selector.currentData() in {OutputMode.HARDWARE_MONITOR.value,OutputMode.MEDIA_WITH_SENSOR_OVERLAY.value}
        self.theme_label.setVisible(theme);self.monitor_template.setVisible(theme);self.quick_edit.setVisible(theme);self.output_group.setFixedHeight(78 if theme else 50)

    def choose(self):
        start=self.media_directory_provider() if self.media_directory_provider else media_dialog_start_directory()
        p,_=QFileDialog.getOpenFileName(self,f"Choose {self.selected_media_kind.value}",start,media_filter(self.selected_media_kind))
        if p:
            selected=Path(p)
            if self.load(selected) and self.media_directory_selected:self.media_directory_selected(selected.parent)

    def _choose_media_kind(self,kind):
        self.select_media_kind(kind);self.choose()

    def _stop_scheduler(self):
        if not self.scheduler:return True
        scheduler=self.scheduler
        if not scheduler.stop():self.status.setText("Playback worker did not stop; replacement blocked");return False
        if self.scheduler is scheduler:self.scheduler=None;self._scheduler_key=None
        return True

    def clear(self):
        self.stop();self._media_paths[self.selected_media_kind]=None;self.path=None;self.media_kind=self.selected_media_kind;self.pipeline.clear();self.bridge.clear();self.preview.clear();self.preview.setText(f"Drop a {self.selected_media_kind.value.lower()} here");self.filename.setText(f"No {self.selected_media_kind.value.lower()} selected");self.footer_name.setText(f"No {self.selected_media_kind.value.lower()} selected");self.status.setText("Ready · no media");self._update_media_controls()

    def load(self,p):
        p=Path(p)
        if not p.is_file():self.status.setText("Media file is missing.");return False
        kind=detect_media_kind(p)
        if kind is None:self.status.setText("Unsupported or unreadable media format.");return False
        changed=self.path!=p
        resume=changed and self.playing and self.output_ownership.lease().mode in {OutputMode.MEDIA,OutputMode.MEDIA_WITH_SENSOR_OVERLAY}
        if changed and not self._stop_scheduler():return False
        if changed:self.bridge.clear();self.session.clear_media();self._last_encoded_source_index=None;self._last_delivered_frame_ref=None
        # Selecting/restoring media is not Play. In particular, never open two
        # high-resolution video decoders merely because a profile was loaded.
        self.path=p;self._media_paths[kind]=p;self.media_kind=kind;self.selected_media_kind=kind;self.media_type_buttons[kind].setChecked(True)
        if kind is MediaKind.PHOTO:
            self.fps.blockSignals(True);self.fps.setCurrentText("Automatic");self.fps.blockSignals(False);self.session.set_refresh_interval(10.0)
        compact=p.name if len(p.name)<=19 else p.name[:16]+"…";self._update_media_controls();self.filename.setText(compact);self.filename.setToolTip(p.name);self.footer_name.setText(f"{p.name}\n{self.size_target[0]} × {self.size_target[1]}");self.playing=False;self.hardware_started=False;self.preview.clear();self._preview_media_path=None;self.preview_stack.setCurrentWidget(self.preview);self.refresh()
        if kind is not MediaKind.PHOTO and self.output_ownership.lease().mode in {OutputMode.MEDIA,OutputMode.MEDIA_WITH_SENSOR_OVERLAY}:self._render_first_media_preview()
        if resume:self.play(coordinated=True)
        self.mediaChanged.emit(str(p));return True

    def select_media_kind(self,kind):
        kind=MediaKind(kind)
        if kind==self.selected_media_kind:return
        self.selected_media_kind=kind;retained=self._media_paths.get(kind)
        if retained and Path(retained).is_file():self.load(Path(retained));return
        self._stop_scheduler();self.bridge.clear();self.session.stop();self.session.clear_media();self.path=None;self.media_kind=kind;self.playing=False;self.hardware_started=False;self.preview.clear();self.preview.setText(f"Drop a {kind.value.lower()} here");self.filename.setText(f"No {kind.value.lower()} selected");self.footer_name.setText(f"No {kind.value.lower()} selected");self._update_media_controls()

    def _update_media_controls(self):
        kind=self.media_kind if self.path else self.selected_media_kind;photo=kind is MediaKind.PHOTO
        self.media_badge.setText("PHOTO · STATIC" if photo else f"{kind.value.upper()} · {'PLAYING' if self.playing else 'READY'}")
        self.header_fps.setVisible(not photo)
        self.fps_label.setVisible(not photo);self.fps.setVisible(not photo);self.quality_label.hide();self.quality_box.hide();self.pause_button.hide();self.play_button.hide();self.stop_button.hide();self.clear_button.hide()
        self.footer_play.show();self.footer_pause.show();self.footer_stop.show()
        action="Change Media" if self.path else "Add Media";self.play_button.setText("Show" if photo else "Play");self.choose_button.setText(action);self.footer_change.setText(action);self.preview_stack.setCurrentWidget(self.preview if self.path else self.media_empty_state)
        self.playback_hint.setText("Static photo · retention active after Show" if photo else "Source timing + override" if kind is MediaKind.GIF else "Timeline playback")
        self.playback_group.setVisible(not photo)

    def _playback_key(self):
        if not self.path:return None
        stat=self.path.stat();return (str(self.path.resolve()),stat.st_mtime_ns,stat.st_size,self.fps.currentText())

    def _transform_changed(self):
        with self._transform_lock:self.transform_mode=FitMode(self.mode.currentText());self.transform_rotation=self.rotation.currentIndex()*90;self.pan_x=self.pan_x_box.value();self.pan_y=self.pan_y_box.value();self.zoom=self.zoom_box.value();self.quality_profile=self.quality_box.currentText();self.brightness=self.brightness_slider.value()
        self.transform_generation+=1
        # Active animation consumes the latest immutable transform state on its
        # next delivered frame. Calling the general refresh path here used to
        # mix UI edits with scheduler lifecycle decisions and could make rapid
        # edits appear to stall output. Static media gets one coalesced rebuild.
        if self.path and self.media_kind is MediaKind.PHOTO:self._transform_refresh_timer.start()
        elif self.path and not self.playing:self._set_status("Ready",f"{self.media_kind.value.title()} ready — transform saved for Play")

    def _apply_transform_refresh(self):
        if self.path and self.media_kind is MediaKind.PHOTO:self.refresh()

    def _brightness_changed(self,value):self.brightness_value.setText(f"{value}%");self.header_brightness.setText(f"{value}%");self._transform_changed()

    def _fps_changed(self,_=None):
        rate=resolve_output_rate(self.fps.currentText(),self.device_id,animated=bool(self.path and self.media_kind is not MediaKind.PHOTO),quality_profile=self.quality_box.currentText())
        self.session.set_refresh_interval(rate.interval_seconds)
        self.refresh()

    def output_rate(self,animated=None):
        if animated is None:animated=bool(self.path and self.media_kind is not MediaKind.PHOTO)
        if not animated:return resolve_output_rate("0.1",self.device_id,animated=False,quality_profile=self.quality_box.currentText())
        return resolve_output_rate(self.fps.currentText(),self.device_id,animated=animated,quality_profile=self.quality_box.currentText())

    def static_generation_due(self,now=None):
        """Rate-limit changed static generations without a periodic render loop."""
        now=time.monotonic() if now is None else now;rate=self.output_rate(animated=False)
        minimum=.25 if rate.interval_seconds is None else rate.interval_seconds
        if now+1e-9<self._static_next_compose:return False
        self._static_next_compose=now+minimum;return True

    def adjust_zoom(self,factor):self.zoom_box.setValue(max(1,min(8,self.zoom_box.value()*factor)))
    def set_preview_scale(self,value):
        # Retained only for loading older profiles. Home always auto-fits.
        self.preview_scale=max(50,min(200,int(value)));self._update_preview_geometry()

    def adjust_pan(self,dx,dy):
        sx=self.size_target[0]/max(1,self.preview.width());sy=self.size_target[1]/max(1,self.preview.height());self.pan_x_box.setValue(self.pan_x_box.value()+round(dx*sx));self.pan_y_box.setValue(self.pan_y_box.value()+round(dy*sy))

    def adjust_pan_native(self,dx,dy):self.pan_x_box.setValue(self.pan_x_box.value()+dx);self.pan_y_box.setValue(self.pan_y_box.value()+dy)
    def reset_transform(self):self.pan_x_box.setValue(0);self.pan_y_box.setValue(0);self.zoom_box.setValue(1)

    def refresh(self):
        if not self.path:return
        try:
            if self.media_kind is not MediaKind.PHOTO:
                if not self.playing:
                    if self.scheduler and self._scheduler_key!=self._playback_key():self._stop_scheduler()
                    self._set_status("Ready","Animated media ready — press Play")
                    return
                if self.shared_hub:
                    rate=resolve_output_rate(self.fps.currentText(),self.device_id,animated=True,quality_profile=self.quality_profile);self.session.set_refresh_interval(rate.interval_seconds);self.shared_hub.set_enabled(self.device_id,True);self._set_status("Playing","Shared source decoder · independent LCD output branch");return
                key=self._playback_key()
                if self.scheduler and self._scheduler_key==key and self.scheduler.is_active:self.scheduler.resume();return
                if not self._stop_scheduler():return
                rate=resolve_output_rate(self.fps.currentText(),self.device_id,animated=True,quality_profile=self.quality_profile);output_target=rate.fps or video_transport_target(self.device_id,self.quality_profile);self.session.set_refresh_interval(rate.interval_seconds)
                working_fps=max(output_target,self.preview_fps if self.preview_enabled else 0)
                cover=self.mode.currentText() in {FitMode.FILL.value,FitMode.CROP.value} or self.zoom_box.value()>1 or self.pan_x_box.value()!=0 or self.pan_y_box.value()!=0
                try:source=open_frame_source(self.path,decode_size=self.size_target,output_fps=working_fps,decode_cover=cover)
                except ValueError:source=None
                if source:
                    fps=None if rate.kind.value in {"automatic","maximum","event_driven"} else rate.fps
                    self.scheduler=FrameScheduler(source,self._deliver_frame,fps,start_epoch=self.timeline_epoch);self._scheduler_key=key;self.scheduler_creations+=1;self.scheduler.start();return
            if not self._stop_scheduler():return
            if not self.hardware_started:
                # A small software preview avoids allocating/encoding the full
                # LCD canvas until the user explicitly presses Play.
                prepared=render_static(self.path,(720,190),FitMode(self.mode.currentText()),self.rotation.currentIndex()*90,QUALITY_PROFILES[self.quality_box.currentText()],self.pan_x_box.value(),self.pan_y_box.value(),self.zoom_box.value(),self.brightness_slider.value())
                self._show_image(self._qimage(prepared.canvas,720,190));self._preview_media_path=self.path.resolve();prepared.canvas.close()
                self._set_status("Ready","Static media ready — press Play");return
            lease=self._output_lease
            with self._overlay_lock:overlay=self._sensor_overlay if lease.mode==OutputMode.MEDIA_WITH_SENSOR_OVERLAY else None
            if overlay is None:prepared,encoded=self.pipeline.prepare_static(self.path,self.device_id,FitMode(self.mode.currentText()),self.rotation.currentIndex()*90,QUALITY_PROFILES[self.quality_box.currentText()],self.pan_x_box.value(),self.pan_y_box.value(),self.zoom_box.value(),self.brightness_slider.value())
            else:
                from PIL import Image
                with Image.open(self.path) as source:prepared,encoded=self.pipeline.prepare_image(source,self.device_id,FitMode(self.mode.currentText()),self.rotation.currentIndex()*90,QUALITY_PROFILES[self.quality_box.currentText()],self.pan_x_box.value(),self.pan_y_box.value(),self.zoom_box.value(),self.brightness_slider.value(),overlay)
            self._show_image(self._qimage(prepared.canvas,720,190));self._preview_media_path=self.path.resolve()
            if self.hardware_started and self.hardware_sender.enabled:
                self.session.set_media(encoded,immediate=True);self.session.play();self._set_status("Playing","Static media playing on physical LCD")
            elif self.hardware_started:
                self.status.setText("Hardware control locked · preview only")
            else:self.status.setText("Static media ready · press Play")
        except Exception as e:self.status.setText(f"Preview error: {e}")

    def _render_first_media_preview(self):
        """Synchronously replace stale content with one bounded decoded frame."""
        if not self.path or self.media_kind is MediaKind.PHOTO:return False
        if self._preview_media_path==self.path.resolve():return True
        source=frame=prepared=image=None
        try:
            source=open_frame_source(self.path,decode_size=self.size_target,output_fps=1,decode_cover=False)
            frame=source.next_frame()
            if frame is None:return False
            if frame.image is not None:image=frame.image
            else:
                import cv2
                from PIL import Image
                image=Image.fromarray(cv2.cvtColor(frame.native_bgr,cv2.COLOR_BGR2RGB))
            with self._overlay_lock:overlay=self._sensor_overlay if self.output_ownership.lease().mode==OutputMode.MEDIA_WITH_SENSOR_OVERLAY else None
            prepared=render_image(image,self.size_target,FitMode(self.mode.currentText()),self.rotation.currentIndex()*90,QUALITY_PROFILES[self.quality_box.currentText()],pan_x=self.pan_x_box.value(),pan_y=self.pan_y_box.value(),zoom=self.zoom_box.value(),brightness=self.brightness_slider.value(),overlay=overlay)
            self._show_image(self._qimage(prepared.canvas,720,190));self._preview_media_path=self.path.resolve();return True
        except Exception as exc:
            self._set_status("Preview unavailable",str(exc));return False
        finally:
            if prepared is not None and prepared.canvas is not None:prepared.canvas.close()
            if frame is not None and frame.image is not None:frame.image.close()
            elif image is not None:image.close()
            if source is not None:source.close()

    def _qimage(self,im,max_width=720,max_height=240):
        owned=None;preview=im
        if im.width>max_width or im.height>max_height:
            owned=im.copy();owned.thumbnail((max_width,max_height));preview=owned
        data=preview.tobytes("raw","RGB");result=QImage(data,preview.width,preview.height,preview.width*3,QImage.Format_RGB888).copy();self.qimage_count+=1
        if owned is not None:owned.close()
        return result

    def _deliver_frame(self,frame):
        try:
            if not self.playing:return
            lease=getattr(self,"_output_lease",None)
            if self.output_mode_request and lease is not None and not self.output_ownership.accepts(lease,OutputMode.MEDIA,OutputMode.MEDIA_WITH_SENSOR_OVERLAY):return
            now=time.perf_counter();show_preview=self.preview_enabled and now>=self._next_preview
            if show_preview:
                interval=1/max(.1,self.preview_fps)
                if not self._next_preview:self._next_preview=now
                self._next_preview+=interval
                if self._next_preview<=now:self._next_preview+=max(1,int((now-self._next_preview)//interval)+1)*interval
            with self._transform_lock:mode=self.transform_mode;rotation=self.transform_rotation;pan_x=self.pan_x;pan_y=self.pan_y;zoom=self.zoom;quality=QUALITY_PROFILES[self.quality_profile];brightness=self.brightness
            with self._overlay_lock:overlay=self._sensor_overlay if lease is not None and lease.mode==OutputMode.MEDIA_WITH_SENSOR_OVERLAY else None
            if self.hardware_started and self.hardware_sender.enabled:
                # Keep source time moving, but do not JPEG-encode frames that
                # cannot reach transport. This is queue-state coalescing, not
                # a second clock: the DisplaySession absolute deadline is the
                # sole cadence owner.
                # The bounded latest transport slot is the authoritative stale-
                # frame guard. Source indices are not globally unique: GIF and
                # looping video sources reset them at every loop, and timeline
                # dropping may legitimately select the same index on successive
                # cycles. Comparing only the index froze those animations after
                # their first physical frame even though decoding continued.
                previous=self._last_delivered_frame_ref() if self._last_delivered_frame_ref else None
                if len(self.session.queue) or previous is frame:return
                prepared,encoded=(self.pipeline.prepare_bgr(frame.native_bgr,self.device_id,mode,rotation,quality,pan_x,pan_y,zoom,show_preview,brightness,overlay) if frame.native_bgr is not None else self.pipeline.prepare_image(frame.image,self.device_id,mode,rotation,quality,pan_x,pan_y,zoom,brightness,overlay))
                if show_preview and prepared.canvas is not None:self.bridge.submit(self._qimage(prepared.canvas,720,190))
                if prepared.canvas is not None:prepared.canvas.close()
                self._last_encoded_source_index=frame.index;self._last_delivered_frame_ref=weakref.ref(frame);self.session.set_media(encoded);self.session.play()
            elif show_preview:
                # Preview-only playback never needs an LCD-sized canvas, JPEG,
                # protocol frame, or full-resolution Qt queued payload.
                if frame.native_bgr is not None:
                    import cv2
                    h,w=frame.native_bgr.shape[:2];scale=min(720/w,190/h,1);small=cv2.resize(frame.native_bgr,(max(1,int(w*scale)),max(1,int(h*scale))),interpolation=cv2.INTER_AREA);rgb=cv2.cvtColor(small,cv2.COLOR_BGR2RGB);self.qimage_count+=1;self.bridge.submit(QImage(rgb.data,rgb.shape[1],rgb.shape[0],rgb.strides[0],QImage.Format_RGB888).copy())
                else:self.bridge.submit(self._qimage(frame.image,720,190))
        finally:
            if frame.image is not None:frame.image.close()

    def _consume_preview(self):
        image=self.bridge.take()
        if image is not None and self.preview_enabled:self._show_image(image);self._preview_media_path=self.path.resolve() if self.path else None

    def _show_image(self,q):
        if not self.preview_enabled:return
        self.preview_stack.setCurrentWidget(self.preview)
        self.preview_scale_count+=1;scaled=q.scaled(self.preview.size(),Qt.KeepAspectRatio,Qt.SmoothTransformation);self.qpixmap_count+=1;self.preview.setPixmap(QPixmap.fromImage(scaled));self.footer_thumbnail.setPixmap(QPixmap.fromImage(q.scaled(self.footer_thumbnail.size(),Qt.KeepAspectRatioByExpanding,Qt.SmoothTransformation)));self.inspector_thumbnail.setPixmap(QPixmap.fromImage(q.scaled(self.inspector_thumbnail.size(),Qt.KeepAspectRatioByExpanding,Qt.SmoothTransformation)));self.preview.setText("")
        presented=time.perf_counter()
        if self._preview_presented:self.preview_intervals.append((presented-self._preview_presented[-1])*1000)
        self._preview_presented.append(presented)

    def actual_preview_fps(self):
        if len(self._preview_presented)<2:return 0.0
        span=self._preview_presented[-1]-self._preview_presented[0]
        return (len(self._preview_presented)-1)/span if span>0 else 0.0

    def set_preview_enabled(self,enabled):
        self.preview_enabled=bool(enabled)
        if not enabled:
            self.preview.clear();self.preview.setText("Preview suspended to reduce resource use")
            if not self.hardware_started or not self.hardware_sender.enabled:self._stop_scheduler()
        elif self.path:self.refresh()

    def set_resource_mode(self,mode):
        self.foreground_preview_fps=15.0 if mode.name in {"Game Mode","Ultra Low Resource","Low Resource"} else 20.0
        self.preview_fps=self.foreground_preview_fps if self.window_visible else .1
        self.timer.setInterval(mode.diagnostics_interval_ms)

    def _update_metrics(self):
        self.metrics_update_count+=1
        shared_scheduler=self.shared_hub.scheduler if self.shared_hub else None;active_scheduler=self.scheduler or shared_scheduler;actual=self.actual_fps();preview_actual=self.actual_preview_fps();requested=self.fps.currentText();rate=self.output_rate();target=rate.fps if rate.fps is not None else "Event";limited=" · PERFORMANCE LIMITED" if rate.fps and rate.kind.value=="fixed" and actual and actual<rate.fps*.9 else "";stage=self.pipeline.last_metrics;backend=getattr(active_scheduler.source,"backend","Image/animation CPU") if active_scheduler else "Idle";decode=active_scheduler.metrics.decode_fps if active_scheduler else 0;source=float(getattr(active_scheduler.source,"source_fps",getattr(active_scheduler.source,"fps",0)) or 0) if active_scheduler else 0
        primary=(f"PHOTO · Static · Retention active · Physical commits {actual:.1f} FPS" if self.path and self.media_kind is MediaKind.PHOTO else f"{self.media_kind.value.upper()} · Content {target} FPS · Physical commits {actual:.1f} FPS{limited}");detail=f"Selected content {target} FPS · Physical cached-commit floor {1/self.session.keepalive_interval:.1f} FPS · Content sends {self.session.metrics.content_sends} · Cached commits {self.session.metrics.keepalive_sends} · Fresh transaction frames {self.session.metrics.transport_frames_rebuilt} · Source {source:.2f} · Decode {decode:.1f} · GUI Preview Presented {preview_actual:.1f} (cap {self.preview_fps:.1f}) · Actual LCD commits {actual:.1f} · Dropped {self.drop_count()}\nPrepare {stage.get('total_prepare_ms',0):.2f} ms · JPEG {stage.get('jpeg_encode_ms',0):.2f} ms · Transport {self.session.metrics.last_send_ms:.2f} ms · Complete interval {self.session.metrics.complete_interval_ms:.2f} ms · Scheduler latency {self.session.metrics.scheduler_latency_ms:.2f} ms · Hidden wait {self.session.metrics.hidden_wait_ms:.2f} ms · ACK {self.session.metrics.ack_latency_ms:.2f} ms · {backend} · Shared decoder {'YES' if self.shared_hub else 'NO'} · Software brightness {self.brightness}%"
        if primary!=self._last_primary_metrics:
            self.output_metrics.setText(primary);self.header_fps.setText(f"Output {actual:.1f} FPS" if self.media_kind is not MediaKind.PHOTO and actual else "");self._last_primary_metrics=primary
            if self.media_kind is not MediaKind.PHOTO:
                ceiling=float(video_transport_target(self.device_id,self.quality_box.currentText()));requested_fps=rate.fps or ceiling
                self.playback_hint.setText((f"{requested_fps:.0f} requested · current measured transport target ~{ceiling:.0f} FPS" if requested_fps>ceiling+.5 else f"Auto targets a useful ~{ceiling:.0f} FPS" if rate.kind.value=="automatic" else "Source timing · measured output shown above"))
        if detail!=self._last_detail_metrics:self.metrics.setText(detail);self._last_detail_metrics=detail
        if not self.hardware_sender.enabled:self.connection.setText("Hardware locked");self.dot.setStyleSheet("color:#e3a84b")
        elif self.session.state==SessionState.ERROR:self.connection.setText("Error");self.dot.setStyleSheet("color:#ff5d6c");self.status.setText("9.16 LCD connection timed out" if self.device_id.endswith("5408") and "timeout" in self.session.metrics.last_error.casefold() else "Display connection failed");self.connection_retry.setVisible(True);self.connection_reconnect.setVisible(True)
        elif self.hardware_started:self.connection.setText("Connected");self.dot.setStyleSheet("color:#20df7a")
        else:self.connection.setText("Connected");self.dot.setStyleSheet("color:#20df7a");self.connection_retry.setVisible(False);self.connection_reconnect.setVisible(False)

    def actual_fps(self):
        if self.hardware_started and self.hardware_sender.enabled:return self.session.metrics.actual_fps
        return 0.0

    def drop_count(self):return (self.scheduler.metrics.dropped if self.scheduler else self.shared_hub.dropped[self.device_id] if self.shared_hub else 0)+self.session.queue.dropped+self.bridge.dropped

    def play(self,coordinated=False):
        if self.coordinator and not coordinated and self.coordinator.coordinate("play",self):return
        if not self.path:self.status.setText("Choose media before Play");return
        if self.output_mode_request:
            current=self.output_ownership.lease().mode
            self.output_mode_request(self.device_id,OutputMode.MEDIA_WITH_SENSOR_OVERLAY if current==OutputMode.MEDIA_WITH_SENSOR_OVERLAY else OutputMode.MEDIA)
            if current not in {OutputMode.MEDIA,OutputMode.MEDIA_WITH_SENSOR_OVERLAY} and self.media_kind is not MediaKind.PHOTO and not self.shared_hub:self._render_first_media_preview()
        if self.playing and self.hardware_started:
            if self.scheduler:self.scheduler.resume()
            if self.hardware_sender.enabled:self.session.play()
            return
        self.playing=True;self.desired_playback_state="Playing";self.hardware_started=True;self._update_media_controls()
        if self.scheduler and self._scheduler_key==self._playback_key() and self.scheduler.is_active:
            self.scheduler.resume()
            if self.hardware_sender.enabled:self.session.play()
        else:self.refresh()
        if not self.hardware_sender.enabled:self.status.setText("Hardware control locked · preview only")

    def pause(self,coordinated=False):
        if self.coordinator and not coordinated and self.coordinator.coordinate("pause",self):return
        self.playing=False;self.desired_playback_state="Paused";self._update_media_controls()
        if self.scheduler:self.scheduler.pause()
        if self.shared_hub:self.shared_hub.set_enabled(self.device_id,False)
        # Decode/timeline presentation stops, while the last already encoded
        # physical frame becomes static content and follows the selected static
        # persistence policy. Stop remains the operation that closes output.
        self.bridge.clear()
        if self.hardware_started and self.hardware_sender.enabled:
            rate=self.output_rate(animated=False);self.session.set_refresh_interval(rate.interval_seconds);self.session.play()
        self._set_status("Paused","Timeline paused; cached final frame remains active")

    def stop(self,coordinated=False):
        if self.coordinator and not coordinated and self.coordinator.coordinate("stop",self):return
        self.playing=False;self.desired_playback_state="Stopped";self.hardware_started=False;self._update_media_controls();self._stop_scheduler();self.bridge.clear();self.session.stop();self._set_status("Stopped")
        if self.shared_hub:self.shared_hub.set_enabled(self.device_id,False)
        if self.output_mode_request:self.output_mode_request(self.device_id,OutputMode.STOPPED,False)

    def set_window_visible(self,visible):
        self.window_visible=bool(visible);self.preview_fps=self.foreground_preview_fps if visible else .1;self._next_preview=0.0
        if not visible:self._preview_presented.clear();self.preview_intervals.clear()
        if visible:self.set_preview_enabled(True)
        else:self.set_preview_enabled(False)
        if visible:
            if not self.timer.isActive():self.timer.start(500)
        else:self.timer.stop()

    def shutdown(self):
        self.timer.stop();self.stop(coordinated=True);self.session.clear_media();self.pipeline.clear();self.bridge.clear();self.preview.clear()
        with self._overlay_lock:
            if self._sensor_overlay is not None:self._sensor_overlay.image.close();self._sensor_overlay=None

    def reconnect(self):
        desired=self.desired_playback_state;output_mode=self.output_ownership.lease().mode;self.session.stop()
        self.hardware_sender=self._injected_sender or build_gui_sender(self.device_id)
        self.session=DisplaySession(self.device_id,self.hardware_sender,policy=POLICIES[self.device_id])
        self.desired_playback_state=desired
        if desired=="Playing" and self.path and self.hardware_sender.enabled and output_mode in {OutputMode.MEDIA,OutputMode.MEDIA_WITH_SENSOR_OVERLAY}:
            self.playing=False;self.hardware_started=False;self.play(coordinated=True)
        self.status.setText("Hardware session restored" if self.hardware_sender.enabled else "Waiting for display · saved output will resume automatically")

    def profile(self):return DisplayProfile(str(self.path or ""),self.mode.currentText(),self.rotation.currentIndex()*90,self.fps.currentText(),self.desired_playback_state=="Playing",self.pan_x_box.value(),self.pan_y_box.value(),self.zoom_box.value(),self.quality_box.currentText(),self.brightness_slider.value(),self.desired_playback_state,self.output_selector.currentData() or "media",self.monitor_template.currentText(),self.preview_scale,self.media_kind.value,{kind.value:str(path or "") for kind,path in self._media_paths.items()})

    def apply_profile(self,p):
        desired=p.desired_playback_state or ("Playing" if p.playing else "Stopped")
        self.mode.setCurrentText(p.fit_mode);self.rotation.setCurrentIndex((p.rotation%360)//90);saved_rate="Auto (Recommended)" if p.fps in {"Auto","Automatic","0.1","0.2","0.5","1","2","5","45","Maximum"} else p.fps;self.fps.setCurrentText(saved_rate if saved_rate in VIDEO_RATE_LABELS else "Auto (Recommended)");self.pan_x_box.setValue(p.pan_x);self.pan_y_box.setValue(p.pan_y);self.zoom_box.setValue(p.zoom);self.quality_box.setCurrentText(p.quality);self.brightness_slider.setValue(p.brightness)
        for name,value in getattr(p,"media_by_type",{}).items():
            if name in {x.value for x in MediaKind} and value:self._media_paths[MediaKind(name)]=Path(value)
        if p.media_type in {x.value for x in MediaKind}:self.selected_media_kind=MediaKind(p.media_type);self.media_type_buttons[self.selected_media_kind].setChecked(True);self._update_media_controls()
        if p.output_mode==OutputMode.MEDIA_WITH_SENSOR_OVERLAY.value and self.output_selector.findData(p.output_mode)<0:self.output_selector.addItem("Sensor + Media",p.output_mode)
        self.output_selector.setCurrentIndex(max(0,self.output_selector.findData(p.output_mode)));self.monitor_template.setCurrentText(p.sensor_template or self.monitor_template.currentText());self.preview_scale_slider.setValue(max(50,min(200,int(p.preview_scale))))
        if p.media:
            if Path(p.media).is_file():self.load(Path(p.media))
            else:self._set_status("Media missing",p.media)
        self.desired_playback_state=desired;self.playing=False

    def dragEnterEvent(self,e):
        urls=e.mimeData().urls() if e.mimeData().hasUrls() else []
        if urls and detect_media_kind(Path(urls[0].toLocalFile())) is not None:self._set_drop_highlight(True);e.acceptProposedAction()
        else:e.ignore()

    def dropEvent(self,e):
        self._set_drop_highlight(False);urls=e.mimeData().urls()
        if urls and self.load(Path(urls[0].toLocalFile())):e.acceptProposedAction()
        else:e.ignore()

    def _quality_changed(self,_=None):self._transform_changed();self._fps_changed()

    def _set_status(self,state,detail=""):self.status.setText(state.upper());self.status.setToolTip(detail or state)

    def sustainable_fps(self):
        """Honest measured ceiling; transport policy remains evidence-backed."""
        candidates=[]
        if self.scheduler:
            source_fps=float(getattr(self.scheduler.source,"fps",0) or 0)
            if source_fps:candidates.append(source_fps)
            if self.scheduler.metrics.decode_fps:candidates.append(self.scheduler.metrics.decode_fps)
        prepare=float(self.pipeline.last_metrics.get("total_prepare_ms",0) or 0)
        if prepare:candidates.append(1000/prepare)
        if self.hardware_sender.enabled:
            send=float(self.session.metrics.last_send_ms or 0)
            if send:candidates.append(1000/send)
            if self.session.refresh_interval:candidates.append(1/self.session.refresh_interval)
        return min(candidates) if candidates else 0.0

    def runtime_diagnostics(self):
        scheduler_pending=self.scheduler.pending_frames if self.scheduler else 0
        return {"scheduler_count":int(self.scheduler is not None),"playback_workers":self.scheduler.active_workers if self.scheduler else 0,"decoder_active":bool(self.scheduler and self.scheduler.is_active),"display_session_active":bool(self.session._thread and self.session._thread.is_alive()),"selected_content_rate":self.fps.currentText(),"physical_commit_floor_fps":round(1/self.session.keepalive_interval,3) if self.session.keepalive_interval else 0,"content_sends":self.session.metrics.content_sends,"cached_commit_sends":self.session.metrics.keepalive_sends,"fresh_transaction_frames":self.session.metrics.transport_frames_rebuilt,"held_frame_generation":self.session.metrics.held_frame_generation,"decoded_queue_size":scheduler_pending,"transport_queue_size":len(self.session.queue),"preview_pending":self.bridge.pending,"retained_full_resolution_frames":scheduler_pending,"cache_size":self.pipeline.cache_entries,"metrics_history_length":len(self.session._sent_times),"metric_timer_active":self.timer.isActive()}

    def dragLeaveEvent(self,e):self._set_drop_highlight(False);super().dragLeaveEvent(e)

    def _set_drop_highlight(self,active):
        border="3px solid #6fe7ff" if active else "none";background="#081523" if active else "transparent";self.preview.setProperty("dropActive",bool(active));self.preview.setStyleSheet(f"QLabel{{background:{background};border:{border};border-radius:{8 if self.device_id.endswith('5408') else 12}px;color:#7892a8;padding:2px}}")

    def fit_preview(self):
        self.auto_preview.setChecked(True);self._update_preview_geometry()

    def _update_workspace_layout(self):
        if not hasattr(self,"workspace_layout"):return
        # Side-by-side cards are individually narrow enough that retaining a
        # desktop-width rail would crush both the preview and controls.  At
        # this breakpoint each card becomes a compact vertical workspace.
        vertical=self.width()<=920;direction=QBoxLayout.TopToBottom if vertical else QBoxLayout.LeftToRight
        if self.workspace_layout.direction()!=direction:self.workspace_layout.setDirection(direction)
        self.unified_inspector.setMaximumWidth(16777215 if vertical else 336)
        for button in self.footer_mode_buttons.values():button.setVisible(not vertical)
        self.footer_reset.setVisible(not vertical)
        QTimer.singleShot(0,self._update_preview_geometry)

    def showEvent(self,event):
        super().showEvent(event);self.workspace.layout().activate();QTimer.singleShot(0,self._update_preview_geometry);QTimer.singleShot(50,self._update_preview_geometry)

    def _update_preview_geometry(self):
        if getattr(self,"_side_by_side_active",False):
            self._fit_side_by_side_preview();return
        ratio=self.size_target[0]/self.size_target[1]
        available=self.preview_column.contentsRect();available_w=max(280,available.width()-8);available_h=max(105,available.height()-self.preview_footer.sizeHint().height()-18)
        scale=getattr(self,"preview_scale",100)/100;width=min(available_w,int(available_h*ratio));width=max(280,int(width*scale));height=max(105,int(round(width/ratio)))
        if height>available_h:height=available_h;width=int(round(height*ratio))
        self.preview.setFixedSize(width,height);self.preview_stack.setFixedSize(width,height)
        if hasattr(self,"preview_scale_value"):self.preview_scale_value.setText(f"{getattr(self,'preview_scale',100)}%")


class MainWindow(QMainWindow):
    def __init__(self, discovery_provider=None):
        super().__init__(); self.setWindowTitle("Oni Thermal LCD Control"); self.resize(1440, 860); self.setMinimumSize(820, 560)
        base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "OniThermalLcd"; self.base = base; self.store = SettingsStore(base / "settings.json"); self.settings = self.store.load(); self.startup = StartupManager()
        
        root = AtmosphericShell(); root.setObjectName("appShell"); self.setCentralWidget(root); shell = QHBoxLayout(root); shell.setContentsMargins(0, 0, 0, 0); shell.setSpacing(0)
        
        self.sidebar = QFrame(); self.sidebar.setObjectName("sidebar"); self.sidebar.setFixedWidth(306)
        side = QVBoxLayout(self.sidebar); side.setContentsMargins(10, 14, 10, 12); side.setSpacing(7)
        
        brand_row = QHBoxLayout(); brand_row.setSpacing(7)
        brand_pixmap = QPixmap(str(bundled_path("assets/oni-thermal-lcd-icon.png")))
        self.sidebar_toggle = QToolButton(); self.sidebar_toggle.setObjectName("sidebarToggle"); self.sidebar_toggle.setText(""); self.sidebar_toggle.setToolTip("Collapse / expand menu"); self.sidebar_toggle.setFixedSize(38, 38)
        if not brand_pixmap.isNull():
            self.sidebar_toggle.setIcon(QIcon(brand_pixmap)); self.sidebar_toggle.setIconSize(QSize(32, 32))
        else:
            self.sidebar_toggle.setText("ONI")
        self.sidebar_toggle.clicked.connect(self.toggle_sidebar)

        # Compatibility attribute retained; actual logo now is the menu button.
        self.brand_icon = QLabel(self); self.brand_icon.hide()
        self.brand_lbl = QLabel("<span style='font-size:20pt;font-weight:850;letter-spacing:1px;color:#ffffff'>ONI</span><br><span style='font-size:8pt;font-weight:600;letter-spacing:.7px;color:#aeb6c9'>THERMALRIGHT LCD</span>")
        brand_row.addWidget(self.sidebar_toggle); brand_row.addWidget(self.brand_lbl); brand_row.addStretch()
        side.addLayout(brand_row); side.addSpacing(6)

        self.nav = {}
        nav_items = [
            ("Home", "", "Display Studio", "nav-display-studio.jpg", "icon-home.svg"), ("Media Library", "", "Images, Videos, GIFs", "nav-media-library.jpg", "icon-media-library.svg"),
            ("Sensor Themes", "", "Design & Customize", "nav-sensor-themes.jpg", "icon-sensor-themes.svg"), ("Profiles", "", "Layouts & Presets", "nav-profiles.jpg", "icon-profiles.svg"),
            ("Hardware Monitor", "", "CPU, GPU, Sensors", "nav-hardware-monitor.jpg", "icon-hardware-monitor.svg"), ("Performance", "", "FPS & Resources", "nav-performance.jpg", "icon-performance.svg"),
            ("Settings", "", "App & Device Options", "nav-settings.jpg", "icon-settings.svg"), ("Diagnostics", "", "Status & Troubleshooting", "nav-diagnostics.jpg", "icon-diagnostics.svg")
        ]
        self.pages = QStackedWidget(); self.pages.setObjectName("pageStack"); self.pages.setAutoFillBackground(True); self.pages.setAttribute(Qt.WA_TranslucentBackground, False); self.pages.setAttribute(Qt.WA_StyledBackground, True)
        for i, (name, icon, subtitle, asset_name, icon_asset) in enumerate(nav_items):
            btn = OniNavigationButton(name,subtitle,icon,asset_name,icon_asset)
            btn.setProperty("fullText", name); btn.setProperty("subtitle", subtitle); btn.setProperty("compactText", icon); btn.setProperty("navTone", str(i % 4)); btn.setToolTip(f"{name} — {subtitle}")
            btn.clicked.connect(lambda _, index=i: self.select_page(index)); self.nav[name] = btn; side.addWidget(btn)
        
        self.supported_displays_button=QPushButton("Supported Displays");self.supported_displays_button.setObjectName("supportedDisplaysButton");self.supported_displays_button.setToolTip("Browse Oni's hardware support catalog");self.supported_displays_button.clicked.connect(self.open_supported_displays);side.addWidget(self.supported_displays_button);side.addStretch()
        self.sidebar_brand = QFrame(); self.sidebar_brand.setObjectName("sidebarBrand"); brand_footer = QVBoxLayout(self.sidebar_brand); brand_footer.setContentsMargins(2, 0, 2, 7); brand_footer.setSpacing(0); self.sidebar_art=QLabel(); self.sidebar_art.setObjectName("sidebarArt"); self.sidebar_art.setAlignment(Qt.AlignCenter); art=QPixmap(str(bundled_path("assets/ui/oni-sidebar-guardian.jpg"))); art_focus=art.copy(0,int(art.height()*.06),art.width(),int(art.height()*.58)) if not art.isNull() else art; self.sidebar_art.setPixmap(faded_sidebar_art(art_focus,226,132)); self.sidebar_art.setFixedHeight(132); brand_name = QLabel("ONI"); brand_name.setObjectName("sidebarBrandName"); brand_slogan = QLabel("THERMALRIGHT LCD\nREADY"); brand_slogan.setObjectName("sidebarSlogan"); brand_slogan.setAlignment(Qt.AlignCenter); brand_footer.addWidget(self.sidebar_art); brand_footer.addWidget(brand_name, alignment=Qt.AlignCenter); brand_footer.addWidget(brand_slogan); side.addWidget(self.sidebar_brand)
        self.ultra_low_lbl = QLabel("● Ultra Low Resource"); self.ultra_low_lbl.setObjectName("ultraLowLabel")
        self.version_lbl = QLabel("v1.6.0"); self.version_lbl.setObjectName("versionLabel")
        side.addWidget(self.ultra_low_lbl); side.addWidget(self.version_lbl)
        shell.addWidget(self.sidebar)

        home = QWidget(); v = QVBoxLayout(home); v.setContentsMargins(16, 14, 16, 14); v.setSpacing(12)
        
        top = QHBoxLayout()
        title_v = QVBoxLayout(); title_v.setSpacing(2)
        title_lbl = QLabel("Display Studio"); title_lbl.setObjectName("pageTitle")
        subtitle_lbl = QLabel("Control · Customize · Create"); subtitle_lbl.setObjectName("pageSubtitle")
        title_v.addWidget(title_lbl); title_v.addWidget(subtitle_lbl)
        top.addLayout(title_v); top.addStretch()

        header_toolbar = QHBoxLayout(); header_toolbar.setSpacing(12)
        header_toolbar.addWidget(QLabel("Layout:"))
        
        self.layout_selector = QComboBox(self); self.layout_selector.addItem("Stacked", "stacked"); self.layout_selector.addItem("Side by Side", "side_by_side"); self.layout_selector.setMaximumWidth(126); self.layout_selector.hide()
        self.layout_buttons = {}
        for label, val in (("Stacked", "stacked"), ("Side by Side", "side_by_side")):
            btn = QPushButton(label); btn.setCheckable(True); btn.setFixedHeight(28)
            btn.clicked.connect(lambda checked, v=val: self.set_display_layout(v) if checked else None)
            self.layout_buttons[val] = btn; header_toolbar.addWidget(btn)
        self.layout_buttons["stacked"].setChecked(True)

        swap_btn = QPushButton("⇄"); swap_btn.setFixedSize(32, 28); swap_btn.clicked.connect(self.swap_display_order); header_toolbar.addWidget(swap_btn)
        header_toolbar.addSpacing(10)

        header_toolbar.addWidget(QLabel("Global Brightness"))
        self.global_brightness = QSlider(Qt.Horizontal); self.global_brightness.setRange(0, 100); self.global_brightness.setValue(100); self.global_brightness.setFixedWidth(120)
        self.global_brightness_val = QLabel("100%"); self.global_brightness_val.setFixedWidth(36)
        header_toolbar.addWidget(self.global_brightness); header_toolbar.addWidget(self.global_brightness_val)
        header_toolbar.addSpacing(10)

        self.sync_toggle = QCheckBox("Display Sync"); self.sync_toggle.setChecked(True); header_toolbar.addWidget(self.sync_toggle)
        self.unified_toggle = QCheckBox("Unified View"); header_toolbar.addWidget(self.unified_toggle)
        header_toolbar.addSpacing(8); self.display_count_label = QLabel("Displays: scanning…"); self.display_count_label.setObjectName("secondaryStatus"); header_toolbar.addWidget(self.display_count_label)
        self.manage_displays_button = QPushButton("Manage"); self.manage_displays_button.setFixedHeight(28); self.manage_displays_button.clicked.connect(self.open_display_manager); header_toolbar.addWidget(self.manage_displays_button)
        top.addLayout(header_toolbar)
        v.addLayout(top)

        chooser_provider = lambda: self._media_dialog_directory(); chooser_selected = lambda path: self._remember_media_directory(path)
        self._chooser_provider=chooser_provider;self._chooser_selected=chooser_selected;self.cards=[];self.card_by_id={};self.card_by_physical_id={}
        self.display_splitter = QSplitter(Qt.Vertical)
        self.display_splitter.setChildrenCollapsible(False)
        v.addWidget(self.display_splitter, 1)
        self.display_empty_state=QFrame();self.display_empty_state.setObjectName("card");empty=QVBoxLayout(self.display_empty_state);empty.addStretch();empty_title=QLabel("No LCD connected");empty_title.setObjectName("pageTitle");empty_title.setAlignment(Qt.AlignCenter);empty.addWidget(empty_title);empty_hint=QLabel("Connect a supported USB LCD or scan for displays.");empty_hint.setObjectName("muted");empty_hint.setAlignment(Qt.AlignCenter);empty.addWidget(empty_hint);empty_actions=QHBoxLayout();empty_actions.addStretch();scan=QPushButton("Scan for Displays");scan.setObjectName("primaryButton");scan.clicked.connect(self.scan_for_displays);add_display=QPushButton("Add / Connect Display");add_display.clicked.connect(self.open_display_manager);supported=QPushButton("Supported Displays");supported.clicked.connect(self.open_supported_displays);empty_actions.addWidget(scan);empty_actions.addWidget(add_display);empty_actions.addWidget(supported);empty_actions.addStretch();empty.addLayout(empty_actions);empty.addStretch();v.addWidget(self.display_empty_state,1)
        if discovery_provider is None and os.environ.get("QT_QPA_PLATFORM","").casefold()=="offscreen":discovery_provider=simulated_reviewed_displays
        self._discovery_provider=discovery_provider or discover_supported_displays
        self.display_lifecycle=DisplayLifecycle(self._add_discovered_display,self._remove_display_card)
        try:self.display_lifecycle.reconcile(self._discovery_provider())
        except Exception:self.display_lifecycle.reconcile(())
        self._refresh_display_surface()
        self.global_brightness.valueChanged.connect(self._set_global_brightness)

        bottom_bar = QHBoxLayout(); bottom_bar.setSpacing(10)
        gallery_btn = QPushButton("Sensor Theme Gallery"); designer_btn = QPushButton("Open Designer"); profiles_btn = QPushButton("Profiles")
        gallery_btn.clicked.connect(self.open_theme_gallery); designer_btn.clicked.connect(self.open_monitor_designer); profiles_btn.clicked.connect(self.open_profiles)
        
        bottom_bar.addWidget(gallery_btn); bottom_bar.addWidget(designer_btn); bottom_bar.addWidget(profiles_btn)
        bottom_bar.addStretch()

        apply_both = QPushButton("Apply to Both"); save_profile = QPushButton("Save Profile"); save_profile.setObjectName("primaryButton")
        apply_both.clicked.connect(self.apply_active_profile_to_both); save_profile.clicked.connect(lambda: self.save_all_profile(self.settings.active_profile))
        bottom_bar.addWidget(apply_both); bottom_bar.addWidget(save_profile)
        v.addLayout(bottom_bar)

        home_scroll = QScrollArea(); home_scroll.setWidgetResizable(True); home_scroll.setFrameShape(QFrame.NoFrame); home_scroll.setWidget(home)
        self.display_workspace_page = home_scroll
        self.home_page = OniHomePage(self); self.home_page.displayWorkspaceRequested.connect(self.open_display_workspace)
        self.media_page = OniMediaLibraryPage(self)
        self.sensor_theme_workspace = OniSensorThemesWorkspace(self, self._sensor_theme_store())
        self.sensor_theme_editor = self.sensor_theme_workspace.editor
        self.profiles_page = OniProfilesPage(self)
        self.hardware_monitor_page = OniHardwareMonitorPage(self)
        self.performance_page = OniPerformancePage(self)
        self.settings_page = OniSettingsPage(self)
        self.diagnostics_page = OniDiagnosticsPage(self)
        self.home_page_scroll = scroll_page(self.home_page); self.profiles_page_scroll = scroll_page(self.profiles_page); self.hardware_monitor_page_scroll = scroll_page(self.hardware_monitor_page); self.performance_page_scroll = scroll_page(self.performance_page); self.settings_page_scroll = scroll_page(self.settings_page); self.diagnostics_page_scroll = scroll_page(self.diagnostics_page)
        for page in (self.home_page_scroll, self.media_page, self.sensor_theme_workspace, self.profiles_page_scroll, self.hardware_monitor_page_scroll, self.performance_page_scroll, self.settings_page_scroll, self.diagnostics_page_scroll, self.display_workspace_page): self.pages.addWidget(page)
        shell.addWidget(self.pages, 1)

        self.sync_controller = DisplaySyncController(tuple(self.cards))
        for card in self.cards:card.coordinator=self.sync_controller

        self._sidebar_expanded = bool(getattr(self.settings, "sidebar_expanded", True))
        self.set_sidebar_expanded(self._sidebar_expanded, save=False)
        self.select_page(0, open_dialog=False)
        # ---- restore full proven runtime contracts under the current visible UI ----
        if self.settings.hardware_decode: os.environ["ONI_LCD_HW_DECODE"]="d3d11va"
        else: os.environ.pop("ONI_LCD_HW_DECODE",None)
        self.global_brightness_value=self.global_brightness_val; self.mode_badge=self.ultra_low_lbl; self.version_label=self.version_lbl
        self.brand=self.brand_lbl; self.global_toolbar=QFrame(self); self.global_toolbar.hide(); self.conflict_panel=QFrame(self); self.conflict_panel.hide(); self.conflict_label=QLabel("",self.conflict_panel)
        self.layout_selector.setMaximumWidth(126)
        self.home_actions=QFrame(self); self.home_actions.setFixedHeight(54); self.home_actions.hide()
        self.link_brightness=QCheckBox("Link brightness",self); self.link_brightness.setChecked(bool(getattr(self.settings,"link_brightness",False))); self.link_brightness.hide(); self.link_brightness.toggled.connect(lambda enabled:setattr(self.settings,"link_brightness",bool(enabled)))

        for card in self.cards:
            card.output_mode_request=self.set_output_mode
            card.output_selector.currentIndexChanged.connect(lambda _,c=card:self._output_selection_changed(c))
            card.monitor_template.currentTextChanged.connect(lambda _,c=card:self._monitor_template_changed(c))
            card.profile_box.clear();card.profile_box.addItems(sorted(self.settings.profiles));card.profile_box.setCurrentText(self.settings.active_profile)

        self.shared_hub=None
        self.sync_controller=DisplaySyncController(tuple(self.cards),prepare_shared=self._prepare_shared_decode,stop_shared=self._stop_shared_decode)
        for card in self.cards:card.coordinator=self.sync_controller
        self.sync_toggle.toggled.connect(self._sync_changed)
        for card in self.cards:
            card.brightness_slider.valueChanged.connect(lambda value,c=card:self._sync_brightness(c,value));card.mediaChanged.connect(lambda _value:self._stop_shared_decode())

        self.unified_panel=QFrame(); self.unified_panel.setObjectName("card"); _uv=QVBoxLayout(self.unified_panel); self.unified_preview=QLabel("Shared media preview"); self.unified_preview.setAlignment(Qt.AlignCenter); self.unified_preview.setMinimumHeight(180); self.unified_preview.setObjectName("preview"); self.unified_metrics=QLabel("9.16: 0.0 FPS · 6.86: 0.0 FPS"); _uv.addWidget(self.unified_preview); _uv.addWidget(self.unified_metrics); self.unified_panel.hide(); v.insertWidget(max(0,v.indexOf(self.display_splitter)+1),self.unified_panel,1)
        self.unified_toggle.setChecked(bool(getattr(self.settings,"unified_sync_view",False))); self.unified_toggle.toggled.connect(self.set_unified_view)
        self.unified_timer=QTimer(self);self.unified_timer.setInterval(500);self.unified_timer.timeout.connect(self.update_unified_view);self.unified_timer.start()

        # Restore persisted layout/order/profile state without changing the new skin.
        self.settings.display_order=[x for x in getattr(self.settings,"display_order",[]) if x in self.card_by_id]
        self.settings.display_order.extend(card.device_id for card in self.cards if card.device_id not in self.settings.display_order)
        self.set_display_layout(getattr(self.settings,"display_layout","stacked"))
        _profile=self.settings.profiles.get(self.settings.active_profile,{})
        for card in self.cards:
            if card.device_id in _profile:card.apply_profile(_profile[card.device_id])
            card.profileSelected.connect(lambda name,c=card:self.apply_device_profile(name,c.device_id,c));card.profileSaveRequested.connect(lambda name,c=card:self.save_device_profile(name,c.device_id,c));card.profileSaveAsRequested.connect(lambda name,c=card:self.save_device_profile(name,c.device_id,c,save_as=True));card.profileManageRequested.connect(self.open_profiles)

        self._force_exit=False;self._shutdown_done=False
        self.monitor_layouts_active={};self._monitor_value_keys={};self.semantic_resolver=SemanticResolverCache();self.monitor_render_skips=0;self.monitor_jpeg_encodes=0
        self.monitor_service=CachedSensorService((HwinfoProvider(),AfterburnerProvider(),RtssProvider(),Aida64Provider(),NativeBasicProvider()),minimum_interval=max(.5,self.settings.sensor_interval_ms/1000))
        self.monitor_timer=QTimer(self);self.monitor_timer.setInterval(max(500,self.settings.sensor_interval_ms));self.monitor_timer.timeout.connect(self.render_monitor_layouts);QTimer.singleShot(0,self.rescan_sensors)
        for card in self.cards:
            card.output_selector.blockSignals(True);card.output_selector.setCurrentIndex(max(0,card.output_selector.findData(self.settings.output_modes.get(card.device_id,OutputMode.STOPPED.value))));card.output_selector.blockSignals(False);card.update_output_controls()
            _saved=self.settings.monitor_templates.get(card.device_id)
            if _saved:card.monitor_template.setCurrentText(_saved)
            card.preview_scale_slider.setValue(int(self.settings.preview_scales.get(card.device_id,100)))
            card.advanced_toggle.setChecked(bool(self.settings.advanced_expanded.get(card.device_id,False)));card.advanced.setVisible(False)
            card.quick_edit.toggled.connect(lambda enabled,c=card:self.set_home_edit_mode(c,enabled));card.monitor_save_button.clicked.connect(lambda _,c=card:self._save_home_layout(c,False));card.monitor_save_as_button.clicked.connect(lambda _,c=card:self._save_home_layout(c,True));card.monitor_reset_button.clicked.connect(lambda _,c=card:self._reset_home_layout(c))

        self.reconnect_timer=QTimer(self);self.reconnect_timer.setInterval(5000);self.reconnect_timer.timeout.connect(self._resume_waiting_devices)
        if self.settings.auto_reconnect:self.reconnect_timer.start()
        if self.settings.remember_window_position and len(self.settings.window_geometry)==4:self._restore_safe_geometry(self.settings.window_geometry)
        else:QTimer.singleShot(0,self._set_default_window_geometry)
        self.sync_toggle.setChecked(bool(getattr(self.settings,"display_sync",False)))
        self.apply_resource_mode(getattr(self.settings, "performance_mode", "Ultra Low Resource"))
        self._setup_tray()
        QTimer.singleShot(0,self.restore_desired_outputs)

    def _media_dialog_directory(self): return media_dialog_start_directory(self.settings.last_media_directory, self.base / "media")
    def _definition_for_card(self, card): return device_definition(card.device_id)
    def _monitor_layout_names(self, device_id):
        return tuple(dict.fromkeys((*templates(device_id), *self.settings.monitor_layout_library.get(device_id, {}))))
    def _monitor_renderer_preview(self, layout):
        try:snapshot=self.monitor_service.poll();raw={value.definition.qualified_id:value.value for value in snapshot.values}
        except Exception:raw={}
        image=MonitorRenderer(layout).render(raw);image.thumbnail((960,300));return image
    def _open_logs(self): open_logs(self.base / "logs")
    def open_display_workspace(self): self.select_page(8, open_dialog=False)
    def _remember_media_directory(self, path):
        directory = Path(path)
        try:
            if not directory.is_dir() or _unsafe_media_directory(directory): return False
        except OSError:
            return False
        value = str(directory)
        if self.settings.last_media_directory == value: return True
        self.settings.last_media_directory = value
        self.store.save(self.settings)
        return True

    def _add_discovered_display(self, observation: DiscoveredDisplay):
        definition=device_definition(observation.device_id)
        card=DisplayCard(f"{definition.manufacturer.upper()} · {definition.model}",definition.encoded_size,observation.device_id,media_directory_provider=self._chooser_provider,media_directory_selected=self._chooser_selected)
        card.physical_id=observation.stable_id;self.cards.append(card);self.card_by_physical_id[observation.stable_id]=card;self.card_by_id.setdefault(observation.device_id,card);self.display_splitter.addWidget(card)
        return card

    def _remove_display_card(self,card):
        if hasattr(self,"monitor_layouts_active"):self.monitor_layouts_active.pop(card.device_id,None);self._stop_sensor_theme_output(card.device_id)
        card.output_mode_request=None;card.shutdown()
        if getattr(self,"_shutting_down",False):return
        self.cards=[item for item in self.cards if item is not card];self.card_by_physical_id.pop(getattr(card,"physical_id",""),None)
        if self.card_by_id.get(card.device_id) is card:
            self.card_by_id.pop(card.device_id,None);replacement=next((item for item in self.cards if item.device_id==card.device_id),None)
            if replacement is not None:self.card_by_id[card.device_id]=replacement
        card.hide();card.setParent(self);card.deleteLater();self._refresh_display_surface()

    def _refresh_display_surface(self):
        self.left=self.card_by_id.get("0416:5408");self.right=self.card_by_id.get("0416:5302")
        count=len(self.cards);self.display_count_label.setText(f"Displays: {count} connected");self.display_empty_state.setVisible(count==0);self.display_splitter.setVisible(count>0)
        for widget in (*self.layout_buttons.values(),self.sync_toggle,self.unified_toggle):widget.setEnabled(count>1)
        if count==1:self.cards[0].set_layout_mode(False)

    def _set_global_brightness(self,value):
        self.global_brightness_val.setText(f"{value}%")
        for card in self.cards:card.brightness_slider.setValue(value)

    def scan_for_displays(self):
        active=getattr(self,"_display_scan_thread",None)
        if active is not None and active.is_alive():return False
        self._display_scan_shutting_down=False;self._display_scan_buttons=[]
        for button in self.findChildren(QPushButton):
            if button.text() in {"Scan for Displays","Scan / Refresh"}:
                self._display_scan_buttons.append((weakref.ref(button),button.text()));button.setEnabled(False);button.setText("Scanning…")
        self.display_count_label.setText("Displays: scanning…")
        bridge=getattr(self,"_display_scan_bridge",None)
        if bridge is None:
            bridge=DisplayScanBridge(self);bridge.resultsReady.connect(self._display_scan_completed,Qt.QueuedConnection);bridge.failed.connect(self._display_scan_failed,Qt.QueuedConnection);self._display_scan_bridge=bridge
        def work():
            try:bridge.resultsReady.emit(tuple(self._discovery_provider()))
            except Exception as exc:bridge.failed.emit(f"{type(exc).__name__}: {exc}")
        thread=threading.Thread(target=work,name="Oni-Display-Scan",daemon=True);self._display_scan_thread=thread;thread.start();return True

    def _display_scan_completed(self,observations):
        if getattr(self,"_display_scan_shutting_down",False):return
        added,removed=self.display_lifecycle.reconcile(observations);self.sync_controller=DisplaySyncController(tuple(self.cards),prepare_shared=self._prepare_shared_decode,stop_shared=self._stop_shared_decode)
        for card in self.cards:card.coordinator=self.sync_controller
        self._refresh_display_surface();self._rebuild_display_splitter()
        if hasattr(self,"monitor_service"):
            for key in added:self._wire_runtime_card(self.card_by_physical_id[key])
        if hasattr(self,"home_page"):self.home_page.refresh()
        self._finish_display_scan()

    def _display_scan_failed(self,message):
        if getattr(self,"_display_scan_shutting_down",False):return
        import logging
        logging.getLogger("thermalright_lcd.gui").warning("Display scan failed: %s",message)
        self._refresh_display_surface();self._finish_display_scan();QMessageBox.warning(self,"Display scan failed","Windows device discovery did not complete. Existing displays were left unchanged.\n\n"+message)

    def _finish_display_scan(self):
        self._display_scan_thread=None
        for reference,text in getattr(self,"_display_scan_buttons",()):
            button=reference()
            if button is not None:button.setText(text);button.setEnabled(True)
        self._display_scan_buttons=[];self._refresh_display_surface()

    def _wire_runtime_card(self,card):
        card.output_mode_request=self.set_output_mode;card.output_selector.currentIndexChanged.connect(lambda _,c=card:self._output_selection_changed(c));card.monitor_template.currentTextChanged.connect(lambda _,c=card:self._monitor_template_changed(c));card.coordinator=self.sync_controller
        card.profile_box.clear();card.profile_box.addItems(sorted(self.settings.profiles));card.profile_box.setCurrentText(self.settings.active_profile);profile=self.settings.profiles.get(self.settings.active_profile,{}).get(card.device_id)
        if profile:card.apply_profile(profile)
        card.profileSelected.connect(lambda name,c=card:self.apply_device_profile(name,c.device_id,c));card.profileSaveRequested.connect(lambda name,c=card:self.save_device_profile(name,c.device_id,c));card.profileSaveAsRequested.connect(lambda name,c=card:self.save_device_profile(name,c.device_id,c,save_as=True));card.profileManageRequested.connect(self.open_profiles)
        card.brightness_slider.valueChanged.connect(lambda value,c=card:self._sync_brightness(c,value));card.mediaChanged.connect(lambda _value:self._stop_shared_decode());self._refresh_monitor_template_options(card)

    def open_supported_displays(self):
        SupportedDisplaysDialog(self).exec()

    def open_display_manager(self):
        dialog=QDialog(self);dialog.setWindowTitle("Displays");dialog.resize(620,420);layout=QVBoxLayout(dialog);layout.addWidget(QLabel(f"{len(self.cards)} connected display{'s' if len(self.cards)!=1 else ''}"))
        listing=QListWidget();observations=self.display_lifecycle.observations
        for item in observations:
            definition=item.definition;text=f"{definition.manufacturer} · {definition.model} · {definition.encoded_size[0]}×{definition.encoded_size[1]} · {item.status.title()}"
            if item.detail:text+=f"\n{item.detail}"
            listing.addItem(text)
        if not observations:listing.addItem("No supported LCD detected")
        layout.addWidget(listing);buttons=QDialogButtonBox(QDialogButtonBox.Close);scan=buttons.addButton("Scan / Refresh",QDialogButtonBox.ActionRole);supported=buttons.addButton("Supported Displays",QDialogButtonBox.ActionRole);scan.clicked.connect(lambda:(self.scan_for_displays(),dialog.accept()));supported.clicked.connect(self.open_supported_displays);buttons.rejected.connect(dialog.reject);layout.addWidget(buttons);dialog.exec()

    # --- YAN YANA / ALT ALTA MOD DEĞİŞTİRİCİSİ ---
    def set_display_layout(self,layout):
        if layout not in {"side_by_side","stacked"}:return
        if hasattr(self,"display_splitter"):
            sizes=self.display_splitter.sizes()
            if len(sizes)==2:self.settings.splitter_sizes=sizes
        self.settings.display_layout=layout
        self._rebuild_display_splitter()
        if hasattr(self,"layout_buttons"):
            for key,button in self.layout_buttons.items():button.setChecked(key==layout)
        if hasattr(self,"layout_selector"):
            idx=self.layout_selector.findData(layout)
            if idx>=0 and self.layout_selector.currentIndex()!=idx:
                self.layout_selector.blockSignals(True);self.layout_selector.setCurrentIndex(idx);self.layout_selector.blockSignals(False)

    def swap_display_order(self):
        self.settings.display_order=list(reversed(self.settings.display_order));self._rebuild_display_splitter()

    def toggle_sidebar(self):
        self.set_sidebar_expanded(not self._sidebar_expanded)

    def set_sidebar_expanded(self, expanded, save=True):
        expanded=bool(expanded); self._sidebar_expanded=expanded; self.settings.sidebar_expanded=expanded
        self.sidebar.setFixedWidth(306 if expanded else 68)
        self.brand_lbl.setVisible(expanded)
        self.sidebar_brand.setVisible(expanded)
        self.supported_displays_button.setText("Supported Displays" if expanded else "◫");self.supported_displays_button.setToolTip("Supported Displays")
        for button in self.nav.values():
            button.setText((f"{button.property('compactText')}  {button.property('fullText')}\n     {button.property('subtitle')}") if expanded else str(button.property("compactText")))
            button.setToolTip(
                f"{button.property('fullText')} — {button.property('subtitle')}"
                if expanded
                else str(button.property("fullText"))
            )
        self.ultra_low_lbl.setText(("● "+self.settings.performance_mode) if expanded else "●"); self.ultra_low_lbl.setToolTip(self.settings.performance_mode); self.version_lbl.setVisible(expanded)
        if hasattr(self,"left"):
            for card in self.cards:QTimer.singleShot(0,card._update_preview_geometry)
        if save:self.store.save(self.settings)

    def select_page(self, index, open_dialog=True):
        index = max(0, min(int(index), self.pages.count() - 1))
        previous = self.pages.currentWidget()
        workspace = getattr(self, "sensor_theme_workspace", None)
        if workspace is not None and self.pages.currentWidget() is workspace and self.pages.indexOf(workspace) != index and not workspace.request_leave():
            current = self.pages.currentIndex()
            for i, b in enumerate(self.nav.values()): b.setChecked(i == current)
            return False
        self.pages.setUpdatesEnabled(False)
        self.pages.setCurrentIndex(index)
        current = self.pages.currentWidget()
        if previous is not None and previous is not current: previous.hide()
        if current is not None: current.show(); current.raise_()
        self.pages.setUpdatesEnabled(True); self.pages.update(); self.pages.repaint()
        if isinstance(current, QScrollArea): current.viewport().update(); current.viewport().repaint()
        for i, b in enumerate(self.nav.values()): b.setChecked(i == index)
        if index == 0 and hasattr(self, "home_page"): self.home_page.refresh()
        elif index == 1 and hasattr(self, "media_page"): self.media_page.refresh()
        elif index == 2 and hasattr(self, "sensor_theme_workspace") and open_dialog: self.sensor_theme_workspace.show_browser()
        elif index == 3 and hasattr(self, "profiles_page"): self.profiles_page.refresh()
        elif index == 4 and hasattr(self, "hardware_monitor_page"): self.hardware_monitor_page.refresh()
        elif index == 5 and hasattr(self, "performance_page"): self.performance_page.refresh()
        elif index == 7 and hasattr(self, "diagnostics_page"): self.diagnostics_page.refresh()
        return True

    def _action_page(self, title, description, action, callback):
        page = QWidget(); layout = QVBoxLayout(page); layout.setContentsMargins(36, 30, 36, 30); layout.setSpacing(12)
        title_label = QLabel(title); title_label.setObjectName("sectionPageTitle"); layout.addWidget(title_label)
        detail = QLabel(description); detail.setObjectName("muted"); detail.setWordWrap(True); detail.setMaximumWidth(760); layout.addWidget(detail)
        button = QPushButton(action); button.setObjectName("primaryButton"); button.setMaximumWidth(250); button.clicked.connect(callback); layout.addWidget(button)
        layout.addStretch()
        return page

    def _hardware_monitor_page(self):
        page = QWidget(); layout = QVBoxLayout(page); layout.setContentsMargins(36, 30, 36, 30); layout.setSpacing(12)
        title = QLabel("Hardware Monitor"); title.setObjectName("sectionPageTitle"); layout.addWidget(title)
        detail = QLabel("Open the Sensor Theme designer or inspect currently discoverable sensor providers."); detail.setObjectName("muted"); detail.setWordWrap(True); layout.addWidget(detail)
        row = QHBoxLayout(); designer = QPushButton("Open Designer"); designer.setObjectName("primaryButton"); refresh = QPushButton("Scan Sensors")
        designer.clicked.connect(self.open_monitor_designer); refresh.clicked.connect(self.refresh_sensor_page)
        row.addWidget(designer); row.addWidget(refresh); row.addStretch(); layout.addLayout(row)
        self.sensor_page_summary = QLabel("Press Scan Sensors to inspect HWiNFO / Afterburner / RTSS / AIDA64 / native readings.")
        self.sensor_page_summary.setObjectName("diagnosticPanel"); self.sensor_page_summary.setWordWrap(True); self.sensor_page_summary.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.sensor_page_summary); layout.addStretch()
        return page

    def _performance_page(self):
        page = QWidget(); layout = QVBoxLayout(page); layout.setContentsMargins(36, 30, 36, 30); layout.setSpacing(12)
        title = QLabel("Performance"); title.setObjectName("sectionPageTitle"); layout.addWidget(title)
        detail = QLabel("Choose the UI/preview resource profile. This does not change the LCD transport protocol."); detail.setObjectName("muted"); detail.setWordWrap(True); layout.addWidget(detail)
        self.performance_box = QComboBox(); self.performance_box.addItems(list(MODES)); self.performance_box.setMaximumWidth(240)
        current = getattr(self.settings, "performance_mode", "Ultra Low Resource")
        if current in MODES: self.performance_box.setCurrentText(current)
        self.performance_box.currentTextChanged.connect(self.apply_resource_mode); layout.addWidget(self.performance_box)
        self.performance_description = QLabel(); self.performance_description.setObjectName("diagnosticPanel"); self.performance_description.setWordWrap(True); layout.addWidget(self.performance_description)
        layout.addStretch()
        return page

    def _settings_page(self):
        page = QWidget(); layout = QVBoxLayout(page); layout.setContentsMargins(36, 30, 36, 30); layout.setSpacing(12)
        title = QLabel("Settings"); title.setObjectName("sectionPageTitle"); layout.addWidget(title)
        self.settings_summary = QLabel(); self.settings_summary.setObjectName("diagnosticPanel"); self.settings_summary.setWordWrap(True); self.settings_summary.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.settings_summary)
        button = QPushButton("Open Settings"); button.setObjectName("primaryButton"); button.setMaximumWidth(220); button.clicked.connect(self.open_settings); layout.addWidget(button)
        layout.addStretch(); self.refresh_settings_summary()
        return page

    def _diagnostics_page(self):
        page = QWidget(); layout = QVBoxLayout(page); layout.setContentsMargins(36, 30, 36, 30); layout.setSpacing(12)
        title = QLabel("Diagnostics"); title.setObjectName("sectionPageTitle"); layout.addWidget(title)
        self.diagnostic_summary = QLabel(); self.diagnostic_summary.setObjectName("diagnosticPanel"); self.diagnostic_summary.setWordWrap(True); self.diagnostic_summary.setTextInteractionFlags(Qt.TextSelectableByMouse); layout.addWidget(self.diagnostic_summary)
        row = QHBoxLayout(); refresh = QPushButton("Refresh Runtime"); sensors = QPushButton("Scan Sensors"); export = QPushButton("Export Diagnostics")
        refresh.clicked.connect(self.refresh_runtime_diagnostics); sensors.clicked.connect(self.refresh_sensor_page); export.clicked.connect(lambda: SettingsDialog(self.settings, tuple(self.cards), self).export_diagnostics())
        row.addWidget(refresh); row.addWidget(sensors); row.addWidget(export); row.addStretch(); layout.addLayout(row)
        layout.addStretch(); QTimer.singleShot(0, self.refresh_runtime_diagnostics)
        return page

    def refresh_settings_summary(self):
        if not hasattr(self, "settings_summary"): return
        s = self.settings
        self.settings_summary.setText(
            f"Start with Windows: {'On' if getattr(s, 'start_with_windows', False) else 'Off'}\n"
            f"Start minimized: {'On' if getattr(s, 'start_minimized', False) else 'Off'}\n"
            f"Minimize to tray: {'On' if getattr(s, 'minimize_to_tray', False) else 'Off'}\n"
            f"Auto reconnect: {'On' if getattr(s, 'auto_reconnect', False) else 'Off'}\n"
            f"Hardware decode: {'On' if getattr(s, 'hardware_decode', False) else 'Off'}\n"
            f"Performance mode: {getattr(s, 'performance_mode', '—')}\n"
            f"Sensor polling: {getattr(s, 'sensor_interval_ms', '—')} ms"
        )

    def refresh_sensor_page(self):
        if not hasattr(self, "sensor_page_summary"): return
        try:
            from .sensors import SensorManager
            snapshot = SensorManager((HwinfoProvider(), AfterburnerProvider(), RtssProvider(), Aida64Provider(), NativeBasicProvider())).poll()
            if snapshot.values:
                preview = "\n".join(
                    f"{value.provider} · {value.category} · {value.name}: {value.value} {value.unit}"
                    for value in snapshot.values[:18]
                )
                more = max(0, len(snapshot.values) - 18)
                self.sensor_page_summary.setText(f"Discovered {len(snapshot.values)} sensor readings.\n\n{preview}" + (f"\n\n…and {more} more." if more else ""))
            else:
                self.sensor_page_summary.setText("No sensor provider currently exposes readings. Media playback is unaffected.")
        except Exception as exc:
            self.sensor_page_summary.setText(f"Sensor scan failed: {exc}")

    def refresh_runtime_diagnostics(self):
        if not hasattr(self, "diagnostic_summary"): return
        rows = []
        for card in self.cards:
            rows.append(
                f"{card.title_text}\n"
                f"  Device: {card.device_id} · {card.connection.text()}\n"
                f"  Media: {card.path.name if card.path else 'none'}\n"
                f"  Output FPS: {card.actual_fps():.1f} · Dropped: {card.drop_count()}\n"
                f"  Last error: {card.session.metrics.last_error or 'None'}"
            )
        self.diagnostic_summary.setText("\n\n".join(rows))

    def apply_resource_mode(self,name):
        try:mode=resource_mode(name)
        except ValueError:return
        self.settings.performance_mode=name;self.settings.sensor_interval_ms=mode.sensor_interval_ms
        if hasattr(self,"performance_box") and self.performance_box.currentText()!=name:self.performance_box.setCurrentText(name)
        if hasattr(self,"performance_description"):self.performance_description.setText(f"{mode.description}\nSensor interval: {mode.sensor_interval_ms} ms · Diagnostics interval: {mode.diagnostics_interval_ms} ms · Logging: {mode.log_level}")
        for card in self.cards:card.set_resource_mode(mode)
        if name=="Game Mode":os.environ["ONI_LCD_HW_DECODE"]="d3d11va"
        elif not self.settings.hardware_decode:os.environ.pop("ONI_LCD_HW_DECODE",None)
        self.mode_badge.setText(name if self.settings.sidebar_expanded else "●");self.mode_badge.setToolTip(name);self._update_preview_visibility()

    def open_monitor_designer(self):
        HardwareMonitorDesigner(self.settings, self.store, self).exec()
        for card in self.cards:self._refresh_monitor_template_options(card)

    def open_theme_gallery(self):
        self.select_page(2, open_dialog=False); self.sensor_theme_workspace.show_browser()

    def open_sensor_studio(self, theme_id=""):
        self.select_page(2, open_dialog=False); return self.sensor_theme_workspace.open_editor(theme_id)

    def create_sensor_theme(self):
        self.select_page(2, open_dialog=False); self.sensor_theme_workspace.new_theme()

    def open_library(self):
        self.select_page(1, open_dialog=False)

    def open_profiles(self):
        self.select_page(3, open_dialog=False)

    def open_profile_manager(self):
        ProfileManagerDialog(self.settings,self.store,tuple(self.cards),self).exec()
        for card in self.cards:card.profile_box.blockSignals(True);card.profile_box.clear();card.profile_box.addItems(sorted(self.settings.profiles));card.profile_box.setCurrentText(self.settings.active_profile);card.profile_box.blockSignals(False)
        self.profiles_page.refresh()

    def open_settings(self):
        if SettingsDialog(self.settings,tuple(self.cards),self).exec():
            self.store.save(self.settings);self.startup.set_enabled(self.settings.start_with_windows,startup_command(start_minimized=self.settings.start_minimized,start_to_tray=self.settings.minimize_to_tray));self.apply_resource_mode(self.settings.performance_mode)
            if self.settings.hardware_decode:os.environ["ONI_LCD_HW_DECODE"]="d3d11va"
            else:os.environ.pop("ONI_LCD_HW_DECODE",None)

    def save_all_profile(self,name):
        self.settings.profiles[name]={card.device_id:card.profile() for card in self.cards};self.store.save(self.settings)

    def apply_active_profile_to_both(self):
        name=self.settings.active_profile
        records=self.settings.profiles.get(name,{})
        for device_id,card in self.card_by_id.items():
            if device_id in records:card.apply_profile(records[device_id])

    def _setup_tray(self):
        self.app_icon=QIcon(str(bundled_path("assets/oni-thermal-lcd.ico")));self.setWindowIcon(self.app_icon);QApplication.instance().setWindowIcon(self.app_icon);self.tray=QSystemTrayIcon(self.app_icon,self);self.tray.setToolTip("Oni Thermal LCD Control");menu=QMenu(self);self.tray_actions={}
        for label in ("Show / Open","Hide","Pause All","Resume All","Stop All") :self.tray_actions[label]=menu.addAction(label)
        menu.addSeparator();self.tray_actions["Exit"]=menu.addAction("Exit")
        self.tray_actions["Show / Open"].triggered.connect(self.restore_window);self.tray_actions["Hide"].triggered.connect(self.hide);self.tray_actions["Pause All"].triggered.connect(lambda:[card.pause() for card in self.cards]);self.tray_actions["Resume All"].triggered.connect(lambda:[card.play() for card in self.cards]);self.tray_actions["Stop All"].triggered.connect(lambda:[card.stop() for card in self.cards]);self.tray_actions["Exit"].triggered.connect(self.exit_application)
        self.tray.activated.connect(self._tray_activated);self.tray_menu=menu;self.tray.setContextMenu(self.tray_menu);self.tray.show()

    def shutdown(self):
        if self._shutdown_done:return
        self._shutdown_done=True;self._display_scan_shutting_down=True
        profiles={card.device_id:card.profile() for card in self.cards};self.settings.profiles[self.settings.active_profile].update(profiles)
        if self.settings.remember_window_position:
            normal=self.normalGeometry();self.settings.window_geometry=[normal.x(),normal.y(),normal.width(),normal.height()];self.settings.window_maximized=self.isMaximized()
        if hasattr(self,"display_splitter"):
            sizes=self.display_splitter.sizes()
            if len(sizes)==2:self.settings.splitter_sizes=sizes
        self.settings.preview_scales.update({card.device_id:card.preview_scale for card in self.cards});self.settings.advanced_expanded.update({card.device_id:card.advanced_toggle.isChecked() for card in self.cards})
        self._shutting_down=True
        for timer in self.findChildren(QTimer):timer.stop()
        self.monitor_layouts_active.clear();self._shutdown_sensor_theme_runtime();self._stop_shared_decode();self.display_lifecycle.clear();self.store.save(self.settings);self.tray.hide();self.tray.setContextMenu(None)

    def closeEvent(self,event):
        if self.settings.close_button_behavior=="minimize_to_tray" and not self._force_exit:event.ignore();self.hide();return
        self._force_exit=True;self.shutdown();event.accept();QTimer.singleShot(0,QApplication.instance().quit)

    def restore_desired_outputs(self):
        """Restore saved user intent after every card/provider is initialized."""
        for card in self.cards:
            self._refresh_monitor_template_options(card)
            saved_mode=self.settings.output_modes.get(card.device_id,card.output_selector.currentData() or OutputMode.STOPPED.value)
            self._set_card_output_selection(card,saved_mode)
            if card.desired_playback_state!="Playing":
                if card.desired_playback_state=="Paused":card._set_status("Paused","Saved paused state restored")
                continue
            mode=OutputMode(card.output_selector.currentData())
            if mode==OutputMode.STOPPED and card.path:mode=OutputMode.MEDIA
            if mode==OutputMode.HARDWARE_MONITOR:
                if not self._restore_sensor_theme_output(card):self.start_monitor_layout(card.device_id,self._saved_monitor_layout(card))
            elif mode==OutputMode.MEDIA_WITH_SENSOR_OVERLAY:self.start_monitor_overlay(card.device_id,self._saved_monitor_layout(card))
            elif mode==OutputMode.MEDIA and card.path:card.play(coordinated=True)
            elif not card.path:card._set_status("Media missing","Saved source is unavailable")

    def _resume_waiting_devices(self):
        for card in self.cards:
            if card.desired_playback_state!="Playing" or (card.hardware_sender.enabled and card.session.state!=SessionState.ERROR):continue
            state=self._sensor_theme_runtime_state(card.device_id)
            card.reconnect()
            if not card.hardware_sender.enabled:continue
            mode=OutputMode(card.output_selector.currentData())
            if mode==OutputMode.HARDWARE_MONITOR:
                if state:
                    card.session.set_refresh_interval(1/state.fps);card.hardware_started=True;state.next_frame_at=0;self._update_sensor_theme_timer();self.render_sensor_theme_outputs()
                elif not self._restore_sensor_theme_output(card):self.start_monitor_layout(card.device_id,self._saved_monitor_layout(card))
            elif mode==OutputMode.MEDIA_WITH_SENSOR_OVERLAY and card.path:self.start_monitor_overlay(card.device_id,self._saved_monitor_layout(card))

    def _saved_monitor_layout(self,card):
        raw=self.settings.monitor_layouts.get(self.settings.active_profile,{}).get(card.device_id)
        return MonitorLayout.from_dict(raw) if raw else self._monitor_layout_by_name(card.device_id,card.monitor_template.currentText())

    def _sync_changed(self,enabled):
        self.sync_controller.set_enabled(enabled);self.settings.display_sync=bool(enabled);self.sync_toggle.setText(f"Display Sync  {'ON' if enabled else 'OFF'}")
        self.unified_toggle.setEnabled(bool(enabled))
        if not enabled:self.set_unified_view(False)

    def set_unified_view(self,enabled):
        enabled=bool(enabled and self.sync_toggle.isChecked() and len(self.cards)>1);self.settings.unified_sync_view=enabled;self.display_splitter.setVisible(bool(self.cards) and not enabled);self.unified_panel.setVisible(enabled);self.display_empty_state.setVisible(not self.cards)
        if hasattr(self,"unified_toggle") and self.unified_toggle.isChecked()!=enabled:self.unified_toggle.blockSignals(True);self.unified_toggle.setChecked(enabled);self.unified_toggle.blockSignals(False)
        if hasattr(self,"unified_timer"):
            if enabled:self.unified_timer.start()
            else:self.unified_timer.stop()

    def update_unified_view(self):
        if not self.unified_panel.isVisible() or len(self.cards)<2:return
        pixmap=self.cards[0].preview.pixmap()
        if pixmap and not pixmap.isNull():self.unified_preview.setPixmap(pixmap.scaled(self.unified_preview.size(),Qt.KeepAspectRatio,Qt.SmoothTransformation))
        self.unified_metrics.setText(" · ".join(f"{card.device_id}: {card.actual_fps():.1f} FPS" for card in self.cards))

    def _sync_brightness(self,source,value):
        if not self.sync_toggle.isChecked() or not self.link_brightness.isChecked():return
        for target in self.cards:
            if target is not source and target.brightness_slider.value()!=value:target.brightness_slider.setValue(value)

    def _prepare_shared_decode(self,epoch):
        cards=tuple(self.cards)
        if len(cards)!=2:return False
        if not all(card.path and card.media_kind is not MediaKind.PHOTO for card in cards) or cards[0].path.resolve()!=cards[1].path.resolve():self._stop_shared_decode();return False
        self._stop_shared_decode()
        for card in cards:card._stop_scheduler()
        targets=[card.output_rate(animated=True).fps or video_transport_target(card.device_id,card.quality_box.currentText()) for card in cards]
        cover=any(card.mode.currentText() in {FitMode.FILL.value,FitMode.CROP.value} or card.zoom_box.value()>1 or card.pan_x_box.value()!=0 or card.pan_y_box.value()!=0 for card in cards)
        source=open_frame_source(cards[0].path,decode_size=(1920,480),output_fps=max(targets),decode_cover=cover,decoder_backend="pyav");self.shared_hub=SharedFrameScheduler(source,{card.device_id:card._deliver_frame for card in cards},max(targets),epoch)
        for card in cards:card.shared_hub=self.shared_hub
        self.shared_hub.start();return True

    def _stop_shared_decode(self):
        hub,self.shared_hub=getattr(self,"shared_hub",None),None
        if hub:hub.stop()
        for card in self.cards:card.shared_hub=None

    def _sensor_theme_store(self):
        store=getattr(self,"_live_sensor_theme_store",None)
        if store is None:
            store=SensorThemeStore(user_directory=self.base/"sensor-themes");self._live_sensor_theme_store=store
        return store

    def _set_card_output_selection(self,card,mode):
        value=OutputMode(mode).value;index=card.output_selector.findData(value)
        if index<0 and value==OutputMode.MEDIA_WITH_SENSOR_OVERLAY.value:
            card.output_selector.addItem("Sensor + Media",value);index=card.output_selector.findData(value)
        if index>=0:
            card.output_selector.blockSignals(True);card.output_selector.setCurrentIndex(index);card.output_selector.blockSignals(False)
        for key,button in card.output_segments.items():button.setChecked(key==value)
        card.update_output_controls()

    def _monitor_layout_by_name(self,device_id,name):
        raw=self.settings.monitor_layout_library.get(device_id,{}).get(name)
        if raw:return MonitorLayout.from_dict(deepcopy(raw))
        catalog=templates(device_id)
        if name in catalog:return deepcopy(catalog[name])
        active=self.settings.monitor_layouts.get(self.settings.active_profile,{}).get(device_id)
        if active:return MonitorLayout.from_dict(deepcopy(active))
        return None

    def _refresh_monitor_template_options(self,card):
        selected=self.settings.monitor_templates.get(card.device_id,card.monitor_template.currentText())
        names=sorted(set(templates(card.device_id))|set(self.settings.monitor_layout_library.get(card.device_id,{})))
        active=self.settings.monitor_layouts.get(self.settings.active_profile,{}).get(card.device_id)
        if active and active.get("name") and active.get("name")!="Custom" and active.get("name") not in names:names.append(active["name"]);names.sort()
        card.monitor_template.blockSignals(True);card.monitor_template.clear();card.monitor_template.addItems(names)
        if selected in names:card.monitor_template.setCurrentText(selected)
        card.monitor_template.setPlaceholderText("No saved layouts")
        card.monitor_template.blockSignals(False)

    def sensor_theme_document_changed(self,event,theme,asset_root,previous_id):
        runtime=getattr(self,"sensor_theme_runtime",None);matching=[] if runtime is None else [device_id for device_id in runtime.active_device_ids if (state:=runtime.state(device_id)) and state.persisted_theme_id==previous_id]
        if event=="saved" and theme is not None:
            for device_id in matching:
                state=runtime.state(device_id);self._start_sensor_theme_output(device_id,theme,asset_root,state.fps,theme.id,save=False)
            for device_id,value in tuple(self.settings.sensor_theme_ids.items()):
                if value==previous_id:self.settings.sensor_theme_ids[device_id]=theme.id
            self.store.save(self.settings);self._refresh_sensor_theme_editor_status()
            return f"Saved · active output refreshed on {len(matching)} display{'s' if len(matching)!=1 else ''}" if matching else "Saved · not currently deployed"
        if event=="deleted":
            self.store.save(self.settings)
            for device_id in matching:self.card_by_id[device_id]._set_status("Sensor Theme",f"Deleted theme remains active until output changes · restart will stop safely")
            return "Deleted · active output retained until changed" if matching else "Deleted"
        return None

    def _ensure_sensor_theme_runtime(self):
        runtime=getattr(self,"sensor_theme_runtime",None)
        if runtime is None:
            runtime=SensorThemeOutputRuntime();self.sensor_theme_runtime=runtime;self._sensor_theme_leases={}
            self.sensor_theme_timer=QTimer(self);self.sensor_theme_timer.timeout.connect(self.render_sensor_theme_outputs)
        return runtime

    def _sensor_theme_runtime_state(self,device_id):
        runtime=getattr(self,"sensor_theme_runtime",None)
        return runtime.state(device_id) if runtime else None

    def _update_sensor_theme_timer(self):
        runtime=getattr(self,"sensor_theme_runtime",None);timer=getattr(self,"sensor_theme_timer",None)
        if timer is None:return
        states=[runtime.state(device_id) for device_id in runtime.active_device_ids if runtime.needs_updates(device_id)] if runtime else []
        states=[state for state in states if state is not None]
        if not states:timer.stop();return
        timer.setInterval(max(16,int(1000/max(state.fps for state in states))))
        if not timer.isActive():timer.start()

    def _refresh_sensor_theme_editor_status(self):
        editor=getattr(self,"sensor_theme_editor",None)
        if editor is None:return
        runtime=getattr(self,"sensor_theme_runtime",None);active=[] if runtime is None else list(runtime.active_device_ids)
        names={"0416:5408":"Display 1","0416:5302":"Display 2"}
        editor.set_active_status("Active · "+", ".join(names.get(item,item) for item in active) if active else "Not active")

    def apply_sensor_theme(self,theme,asset_root,target_ids,fps):
        targets=tuple(device_id for device_id in target_ids if device_id in self.card_by_id)
        if not targets:raise ValueError("no supported target display selected")
        for device_id in targets:self._start_sensor_theme_output(device_id,theme,asset_root,fps,theme.id,save=False)
        self.store.save(self.settings);self._refresh_sensor_theme_editor_status()
        labels={"0416:5408":"Display 1","0416:5302":"Display 2"}
        return f"Active · {theme.name} · {', '.join(labels[item] for item in targets)} · {int(fps)} FPS"

    def _start_sensor_theme_output(self,device_id,theme,asset_root,fps,persisted_theme_id,save=True):
        fps=int(fps)
        if fps not in SENSOR_THEME_FPS:fps=2
        runtime=self._ensure_sensor_theme_runtime();card=self.card_by_id[device_id]
        runtime.apply(device_id,theme,asset_root=asset_root,fps=fps,persisted_theme_id=persisted_theme_id)
        try:
            snapshot=self.monitor_service.poll();image=runtime.render_due(device_id,snapshot.values)
            if image is None:raise RuntimeError(runtime.state(device_id).last_error or "Sensor Theme did not produce an initial frame")
            prepared,encoded=card.pipeline.prepare_image(image,device_id,FitMode.FIT,0,QUALITY_PROFILES[card.quality_box.currentText()],0,0,1.0,card.brightness_slider.value())
        except Exception:
            runtime.stop(device_id)
            raise
        finally:
            if "image" in locals() and image is not None:image.close()
        self.monitor_layouts_active.pop(device_id,None);self._monitor_value_keys.pop(device_id,None)
        if not self.monitor_layouts_active:self.monitor_timer.stop()
        lease=self.set_output_mode(device_id,OutputMode.HARDWARE_MONITOR);self._sensor_theme_leases[device_id]=lease
        self._set_card_output_selection(card,OutputMode.HARDWARE_MONITOR)
        card.desired_playback_state="Playing";card.playing=True;card.hardware_started=bool(card.hardware_sender.enabled)
        card.session.set_refresh_interval(1/fps)
        if card.hardware_sender.enabled:card.session.set_media(encoded);card.session.play()
        if card.window_visible and prepared.canvas is not None:card._preview_media_path=None;card._show_image(card._qimage(prepared.canvas))
        if prepared.canvas is not None:prepared.canvas.close()
        self.settings.output_modes[device_id]=OutputMode.HARDWARE_MONITOR.value
        self.settings.sensor_theme_ids[device_id]=persisted_theme_id
        self.settings.sensor_theme_fps[device_id]=fps
        if save:self.store.save(self.settings)
        self._update_sensor_theme_timer()
        card._set_status("Sensor Theme",f"{theme.name} · {fps} FPS"+("" if card.hardware_sender.enabled else " · preview only"))
        return True

    def _restore_sensor_theme_output(self,card):
        theme_id=self.settings.sensor_theme_ids.get(card.device_id,"")
        if not theme_id:return False
        try:stored=self._sensor_theme_store().get(theme_id)
        except Exception:
            card._output_lease=card.output_ownership.transition(OutputMode.STOPPED);card.desired_playback_state="Stopped";card.playing=False;card.hardware_started=False
            card.output_selector.blockSignals(True);index=card.output_selector.findData(OutputMode.STOPPED.value)
            if index>=0:card.output_selector.setCurrentIndex(index)
            card.output_selector.blockSignals(False);card.update_output_controls();self.settings.output_modes[card.device_id]=OutputMode.STOPPED.value
            card._set_status("Sensor theme missing",f"Saved theme '{theme_id}' is unavailable")
            return True
        fps=int(self.settings.sensor_theme_fps.get(card.device_id,2))
        return self._start_sensor_theme_output(card.device_id,stored.theme,stored.root,fps,theme_id,save=False)

    def _stop_sensor_theme_output(self,device_id):
        runtime=getattr(self,"sensor_theme_runtime",None)
        if runtime:runtime.stop(device_id)
        leases=getattr(self,"_sensor_theme_leases",None)
        if leases is not None:leases.pop(device_id,None)
        self._update_sensor_theme_timer();self._refresh_sensor_theme_editor_status()

    def _shutdown_sensor_theme_runtime(self):
        timer=getattr(self,"sensor_theme_timer",None)
        if timer:timer.stop()
        runtime=getattr(self,"sensor_theme_runtime",None)
        if runtime:runtime.clear()
        leases=getattr(self,"_sensor_theme_leases",None)
        if leases is not None:leases.clear()

    def render_sensor_theme_outputs(self):
        runtime=getattr(self,"sensor_theme_runtime",None)
        if runtime is None or not runtime.active_device_ids:self._update_sensor_theme_timer();return
        try:snapshot=self.monitor_service.poll();values=snapshot.values
        except Exception:values=()
        for device_id in tuple(runtime.active_device_ids):
            state=runtime.state(device_id);card=self.card_by_id.get(device_id);lease=getattr(self,"_sensor_theme_leases",{}).get(device_id)
            if state is None or card is None or lease is None or not card.output_ownership.accepts(lease,OutputMode.HARDWARE_MONITOR):continue
            image=runtime.render_due(device_id,values)
            if image is None:
                if state.last_error:card._set_status("Sensor theme error",state.last_error)
                continue
            prepared=None
            try:
                prepared,encoded=card.pipeline.prepare_image(image,device_id,FitMode.FIT,0,QUALITY_PROFILES[card.quality_box.currentText()],0,0,1.0,card.brightness_slider.value())
                if not card.output_ownership.accepts(lease,OutputMode.HARDWARE_MONITOR):continue
                if card.hardware_sender.enabled:
                    card.session.set_media(encoded);card.session.play();card.hardware_started=True
                if card.window_visible and prepared.canvas is not None:card._preview_media_path=None;card._show_image(card._qimage(prepared.canvas))
                card.playing=True;card.desired_playback_state="Playing"
            except Exception as exc:
                state.error_count+=1;state.last_error=str(exc);card._set_status("Sensor theme error",str(exc))
            finally:
                image.close()
                if prepared is not None and prepared.canvas is not None:prepared.canvas.close()
        self._update_sensor_theme_timer()

    def start_monitor_layout(self,device_id,layout):
        if layout is None:return False
        self._stop_sensor_theme_output(device_id);self.settings.sensor_theme_ids.pop(device_id,None);card=self.card_by_id[device_id];self.set_output_mode(device_id,OutputMode.HARDWARE_MONITOR);self._set_card_output_selection(card,OutputMode.HARDWARE_MONITOR);self.settings.output_modes[device_id]=OutputMode.HARDWARE_MONITOR.value;card.playing=False;card.desired_playback_state="Playing";card.hardware_started=False;card._stop_scheduler();card.bridge.clear();self.monitor_layouts_active[device_id]=(layout,MonitorRenderer(layout),card._output_lease,OutputMode.HARDWARE_MONITOR);self.store.save(self.settings);self.monitor_timer.start();self.render_monitor_layouts()

    def start_monitor_overlay(self,device_id,layout):
        if layout is None:return False
        card=self.card_by_id[device_id]
        if not card.path:card._set_status("Choose media before enabling sensor overlay");return False
        renderer=MonitorRenderer(layout)
        try:
            raw=self._monitor_values();rendered=renderer.render_overlay(raw);overlay=cache_overlay(rendered,card.pipeline.TARGETS[device_id]);rendered.close()
        except Exception as exc:
            card._set_status("Sensor overlay error",str(exc));return False
        with card._overlay_lock:
            old=card._sensor_overlay;card._sensor_overlay=overlay
        if old is not None:old.image.close()
        lease=self.set_output_mode(device_id,OutputMode.MEDIA_WITH_SENSOR_OVERLAY);self._set_card_output_selection(card,OutputMode.MEDIA_WITH_SENSOR_OVERLAY);self.settings.output_modes[device_id]=OutputMode.MEDIA_WITH_SENSOR_OVERLAY.value;card.desired_playback_state="Playing";self.monitor_layouts_active[device_id]=(layout,renderer,lease,OutputMode.MEDIA_WITH_SENSOR_OVERLAY);self.store.save(self.settings);self.monitor_timer.start();card.play(coordinated=True);return True

    def _output_selection_changed(self,card):
        mode=OutputMode(card.output_selector.currentData())
        previous=card.output_ownership.lease().mode
        card.update_output_controls()
        if not hasattr(self,"monitor_layouts_active"):return
        self.settings.output_modes[card.device_id]=mode.value;self.settings.monitor_templates[card.device_id]=card.monitor_template.currentText()
        if mode==OutputMode.HARDWARE_MONITOR:
            if not self._restore_sensor_theme_output(card):self.start_monitor_layout(card.device_id,self._monitor_layout_by_name(card.device_id,card.monitor_template.currentText()))
        elif mode==OutputMode.MEDIA_WITH_SENSOR_OVERLAY:self.start_monitor_overlay(card.device_id,self._monitor_layout_by_name(card.device_id,card.monitor_template.currentText()))
        elif mode==OutputMode.MEDIA:
            self.set_output_mode(card.device_id,mode)
            if previous not in {OutputMode.MEDIA,OutputMode.MEDIA_WITH_SENSOR_OVERLAY} and card.path and card.media_kind is not MediaKind.PHOTO and not card.shared_hub:card._render_first_media_preview()
            if card.path:card.play(coordinated=True)
        else:card.stop(coordinated=True)

    def _monitor_template_changed(self,card):
        if not hasattr(self,"monitor_layouts_active"):return
        self.settings.sensor_theme_ids.pop(card.device_id,None);self._stop_sensor_theme_output(card.device_id)
        if card.output_selector.currentData() in {OutputMode.HARDWARE_MONITOR.value,OutputMode.MEDIA_WITH_SENSOR_OVERLAY.value}:self._output_selection_changed(card)
        if card.quick_edit.isChecked():self.set_home_edit_mode(card,True,self._monitor_layout_by_name(card.device_id,card.monitor_template.currentText()))

    def set_home_edit_mode(self,card,enabled,layout_override=None):
        existing=getattr(card,"home_quick_editor",None)
        if enabled and existing:
            card.preview_stack.setCurrentWidget(card.preview);card.preview_stack.removeWidget(existing);existing.deleteLater();card.home_quick_editor=None;existing=None
        if not enabled:
            if existing:
                card.preview_stack.setCurrentWidget(card.preview);card.preview_stack.removeWidget(existing);existing.deleteLater();card.home_quick_editor=None;card.set_preview_scale(card.preview_scale)
            card.monitor_edit_hint.setText("Turn on Edit Layout, then click an element in the preview.")
            return
        card.context_tabs.setCurrentWidget(card.monitor_tab)
        profile=self.settings.active_profile;raw=self.settings.monitor_layouts.get(profile,{}).get(card.device_id)
        layout=layout_override or (MonitorLayout.from_dict(raw) if raw else self._monitor_layout_by_name(card.device_id,card.monitor_template.currentText()))
        if layout is None:card.quick_edit.setChecked(False);return
        editor=HomeQuickEditor(layout,card);card.home_quick_editor=editor;card.preview_stack.addWidget(editor);card.preview_stack.setMaximumWidth(max(900,card.preview_stack.maximumWidth()));card.preview_stack.setFixedHeight(max(390,card.preview_stack.height()));card.preview_stack.setCurrentWidget(editor);card.monitor_edit_hint.setText("EDIT MODE · click, drag, resize or nudge · native-pixel WYSIWYG")
        editor.closeRequested.connect(lambda c=card:c.quick_edit.setChecked(False))
        editor.changed.connect(lambda c=card,l=layout:self._home_layout_changed(c,l))

    def _save_home_layout(self,card,save_as=False):
        self.save_device_profile(card.profile_box.currentText(),card.device_id,card,save_as=save_as)
        editor=getattr(card,"home_quick_editor",None)
        if editor and not save_as:editor.mark_saved()

    def _reset_home_layout(self,card):
        layout=self._monitor_layout_by_name(card.device_id,card.monitor_template.currentText())
        if layout is None:return
        self._home_layout_changed(card,layout);self.set_home_edit_mode(card,True,layout)

    def _home_layout_changed(self,card,layout):
        self.settings.monitor_layouts.setdefault(self.settings.active_profile,{})[card.device_id]=layout.to_dict();self.store.save(self.settings);self._monitor_value_keys.pop(card.device_id,None)
        active=self.monitor_layouts_active.get(card.device_id)
        if active:
            _,_,lease,mode=active;self.monitor_layouts_active[card.device_id]=(layout,MonitorRenderer(layout),lease,mode);self.render_monitor_layouts()

    def stop_monitor_layout(self,device_id):
        self._stop_sensor_theme_output(device_id);self.monitor_layouts_active.pop(device_id,None);card=self.card_by_id[device_id];card.playing=False;card.desired_playback_state="Stopped";card.hardware_started=False;card.session.stop();card._output_lease=card.output_ownership.transition(OutputMode.STOPPED);self._set_card_output_selection(card,OutputMode.STOPPED);self.settings.output_modes[device_id]=OutputMode.STOPPED.value;self.store.save(self.settings);card._set_status("Monitor stopped")
        if not self.monitor_layouts_active:self.monitor_timer.stop()

    def set_output_mode(self,device_id,mode,stop_previous=True):
        """Atomically invalidate the old final-frame producer for one LCD."""
        mode=OutputMode(mode);card=self.card_by_id[device_id];previous=card.output_ownership.lease().mode
        card._output_lease=card.output_ownership.transition(mode)
        if previous!=mode and mode!=OutputMode.STOPPED:card.session.clear_media()
        if previous in {OutputMode.HARDWARE_MONITOR,OutputMode.MEDIA_WITH_SENSOR_OVERLAY} and mode!=previous:
            self._stop_sensor_theme_output(device_id)
            self.monitor_layouts_active.pop(device_id,None)
            self._monitor_value_keys.pop(device_id,None)
            if previous==OutputMode.MEDIA_WITH_SENSOR_OVERLAY:
                with card._overlay_lock:
                    old=card._sensor_overlay;card._sensor_overlay=None
                if old is not None:old.image.close()
            if not self.monitor_layouts_active:self.monitor_timer.stop()
        if stop_previous and mode==OutputMode.HARDWARE_MONITOR:
            if card.shared_hub:card.shared_hub.set_enabled(device_id,False)
            card.playing=False;card.hardware_started=False;card._stop_scheduler();card.bridge.clear()
        return card._output_lease

    def _monitor_values(self):
        snapshot=self.monitor_service.poll();by_id={value.definition.qualified_id:value for value in snapshot.values};raw={key:value.value for key,value in by_id.items()};roles={"cpu.usage":"cpu_usage","cpu.temperature":"cpu_temp","cpu.clock":"cpu_clock","cpu.power":"cpu_power","gpu.usage":"gpu_usage","gpu.temperature":"gpu_temp","gpu.hotspot":"gpu_hotspot","gpu.clock":"gpu_clock","gpu.memory_clock":"gpu_memory_clock","gpu.power":"gpu_power","gpu.memory_used":"vram_usage","memory.usage":"ram_usage","storage.temperature":"ssd_temp","network.download":"network_download","network.upload":"network_upload","game.fps":"fps","game.frametime":"frametime","fan.rpm":"fan_rpm","pump.rpm":"pump_rpm"}
        for key,value in self.semantic_resolver.resolve(roles,snapshot.values).items():raw[key]=value.value if value else None
        return raw

    def render_monitor_layouts(self):
        if not self.monitor_layouts_active:return
        raw=self._monitor_values()
        for device_id,(layout,renderer,lease,mode) in tuple(self.monitor_layouts_active.items()):
            card=self.card_by_id[device_id]
            if not card.output_ownership.accepts(lease,mode):continue
            visible_ids={e.sensor_id for e in layout.elements if e.sensor_id};value_key=(mode,tuple((key,raw.get(key)) for key in sorted(visible_ids|set(layout.bindings.values()))))
            if self._monitor_value_keys.get(device_id)==value_key:self.monitor_render_skips+=1;continue
            editor=getattr(card,"home_quick_editor",None)
            if editor is not None:editor.scene.set_live_values(raw)
            static_output=mode==OutputMode.HARDWARE_MONITOR or not (card.path and card.media_kind is not MediaKind.PHOTO)
            if static_output and not card.static_generation_due():self.monitor_render_skips+=1;continue
            self._monitor_value_keys[device_id]=value_key
            if mode==OutputMode.MEDIA_WITH_SENSOR_OVERLAY:
                rendered=renderer.render_overlay(raw);overlay=cache_overlay(rendered,card.pipeline.TARGETS[device_id]);rendered.close()
                with card._overlay_lock:
                    old=card._sensor_overlay;card._sensor_overlay=overlay
                if old is not None:old.image.close()
                if card.path and card.media_kind is MediaKind.PHOTO:card.refresh()
                continue
            image=renderer.render(raw);prepared,encoded=card.pipeline.prepare_image(image,device_id,quality=QUALITY_PROFILES[card.quality_box.currentText()],brightness=card.brightness_slider.value());self.monitor_jpeg_encodes+=1;image.close()
            if not card.output_ownership.accepts(lease,OutputMode.HARDWARE_MONITOR):
                if prepared.canvas is not None:prepared.canvas.close()
                continue
            card.session.set_media(encoded);card.session.play();card.playing=True;card.hardware_started=True
            if card.window_visible:card._preview_media_path=None;card._show_image(card._qimage(prepared.canvas));prepared.canvas.close()

    def _center_default_window(self):
        screen=QApplication.screenAt(self.cursor().pos()) or QApplication.primaryScreen()
        if screen:
            area=screen.availableGeometry();self.move(area.center()-self.rect().center())

    def _set_default_window_geometry(self):
        screen=QApplication.screenAt(self.cursor().pos()) or QApplication.primaryScreen()
        if not screen:return
        area=screen.availableGeometry();width=max(self.minimumWidth(),min(int(area.width()*.80),1900));height=max(self.minimumHeight(),min(int(area.height()*.80),1100));width=min(width,area.width());height=min(height,area.height());target=QRect(0,0,width,height);target.moveCenter(area.center());self.setGeometry(target)

    @staticmethod
    def _recover_window_rect(candidate,areas,minimum_size,prefer_default_size=False):
        areas=[QRect(area) for area in areas if area.isValid() and not area.isEmpty()]
        if not areas:return QRect(candidate)
        candidate=QRect(candidate);min_w,min_h=minimum_size.width(),minimum_size.height()
        sufficiently_visible=any(candidate.intersected(area).width()>=min(180,max(80,candidate.width()//4)) and candidate.intersected(area).height()>=min(120,max(60,candidate.height()//4)) for area in areas)
        if sufficiently_visible and prefer_default_size:
            best=max(areas,key=lambda item:candidate.intersected(item).width()*candidate.intersected(item).height());ideal_w=min(int(best.width()*.80),1900);ideal_h=min(int(best.height()*.80),1100)
            sufficiently_visible=candidate.width()>=int(ideal_w*.60) and candidate.height()>=int(ideal_h*.60)
        if sufficiently_visible:
            area=max(areas,key=lambda item:candidate.intersected(item).width()*candidate.intersected(item).height())
            width=max(min_w,min(candidate.width(),area.width()));height=max(min_h,min(candidate.height(),area.height()));left=max(area.left(),min(candidate.left(),area.right()-width+1));top=max(area.top(),min(candidate.top(),area.bottom()-height+1));return QRect(left,top,width,height)
        area=max(areas,key=lambda item:item.width()*item.height());width=max(min_w,min(int(area.width()*.80),1900,area.width()));height=max(min_h,min(int(area.height()*.80),1100,area.height()));recovered=QRect(0,0,width,height);recovered.moveCenter(area.center());return recovered

    def _ensure_window_on_screen(self):
        screens=QApplication.screens();areas=[screen.availableGeometry() for screen in screens]
        if not areas:return
        self.setGeometry(self._recover_window_rect(self.normalGeometry() if self.isMinimized() else self.geometry(),areas,self.minimumSize()))

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if not hasattr(self,"layout_tip"):
            self.layout_tip=QFrame(self);self.layout_tip.setObjectName("layoutRecommendation");row=QHBoxLayout(self.layout_tip);row.setContentsMargins(12,7,8,7);row.setSpacing(8);message=QLabel("For the best editing experience and access to all controls, use Oni maximized or fullscreen.");message.setWordWrap(True);dismiss=QToolButton();dismiss.setText("×");dismiss.clicked.connect(self._dismiss_layout_tip);row.addWidget(message,1);row.addWidget(dismiss)
        self.layout_tip.setFixedWidth(min(620,max(360,self.width()-40)));show=self.width()<1450 or self.height()<820
        if show and not getattr(self,"_layout_tip_dismissed",False):self.layout_tip.adjustSize();self.layout_tip.move(max(10,self.width()-self.layout_tip.width()-18),14);self.layout_tip.raise_();self.layout_tip.show()
        else:self.layout_tip.hide()

    def _dismiss_layout_tip(self):
        self._layout_tip_dismissed=True;self.layout_tip.hide()

    def _restore_safe_geometry(self,geometry):
        candidate=QRectF(*geometry).toRect();areas=[screen.availableGeometry() for screen in QApplication.screens()]
        if not areas:return
        self.setGeometry(self._recover_window_rect(candidate,areas,self.minimumSize(),prefer_default_size=True))

    def rescan_sensors(self):
        if not hasattr(self,"monitor_service"):return
        self.semantic_resolver=SemanticResolverCache();self._monitor_value_keys.clear();self.monitor_service.rescan();self.refresh_sensor_diagnostics();self.render_monitor_layouts()
        runtime=getattr(self,"sensor_theme_runtime",None)
        if runtime:
            for device_id in runtime.active_device_ids:runtime.state(device_id).next_frame_at=0
            self.render_sensor_theme_outputs()

    def refresh_sensor_diagnostics(self):
        if not hasattr(self,"monitor_service") or not hasattr(self,"sensor_diagnostic_summary"):return
        d=self.monitor_service.diagnostics();snapshot=self.monitor_service.snapshot;available={v.definition.qualified_id for v in snapshot.values} if snapshot else set();visible={e.sensor_id for layout,_,_,_ in self.monitor_layouts_active.values() for e in layout.elements if e.sensor_id};unresolved=sorted(x for x in visible if x not in available and ":" in x)
        providers="\n".join(f"{x['name']} {x['version']}: {'detected' if x['available'] else 'unavailable'} · {x['values_read']} readings · {x['latency_ms']:.2f} ms"+(f" · {x['last_error']}" if x['last_error'] else "") for x in d["providers"])
        self.sensor_diagnostic_summary.setText(f"Sensor snapshot generation: {d['generation']}\nMapped readings: {d['mapped_sensor_count']}\nLast successful poll: {d['last_success_timestamp'] or 'none'}\nVisible bindings: {len(visible)} · unresolved exact bindings: {', '.join(unresolved) or 'none'}\n{providers or 'Providers have not been polled'}")

    def retry_conflicts(self):
        remaining=thermalright_processes()
        if hasattr(self,"conflict_panel"):self.conflict_panel.setVisible(bool(remaining))
        if not remaining:
            for card in self.cards:card.reconnect()

    def take_control(self):
        QMessageBox.information(self,"Take Control","Close Thermalright Control Center and its LCD helpers, then choose Retry. Oni will never terminate them silently.")

    def apply_device_profile(self,name,device_id,card):
        profile=self.settings.profiles.get(name,{}).get(device_id)
        if profile:card.apply_profile(profile)

    def _refresh_profile_boxes(self,name=None):
        selected=name or self.settings.active_profile
        for card in self.cards:
            card.profile_box.blockSignals(True);card.profile_box.clear();card.profile_box.addItems(sorted(self.settings.profiles));card.profile_box.setCurrentText(selected);card.profile_box.blockSignals(False)

    def save_device_profile(self,name,device_id,card,save_as=False):
        try:
            name=" ".join(str(name).strip().split())
            if not name:raise ValueError("Enter a profile name first.")
            exists=name in self.settings.profiles and device_id in self.settings.profiles[name]
            overwrite=not save_as
            if exists and save_as:
                answer=QMessageBox.question(self,"Replace profile",f"A profile named '{name}' already exists.\nReplace it?",QMessageBox.Yes|QMessageBox.Cancel,QMessageBox.Cancel)
                if answer!=QMessageBox.Yes:return
                overwrite=True
            source_profile=self.settings.active_profile;profile_layout=self.settings.monitor_layouts.get(source_profile,{}).get(device_id)
            save_profile_record(self.settings,name,device_id,card.profile(),overwrite=overwrite)
            if profile_layout:self.settings.monitor_layouts.setdefault(name,{})[device_id]=deepcopy(profile_layout)
            self.store.save(self.settings);self._refresh_profile_boxes(name);card.status.setText(f"{name} profile saved for this display")
        except (ValueError,OverflowError,FileExistsError) as exc:QMessageBox.warning(self,"Profile not saved",str(exc))

    def _tray_activated(self,reason):
        if reason in (QSystemTrayIcon.Trigger,QSystemTrayIcon.DoubleClick):self.restore_window()

    def restore_window(self):
        if self.isMinimized():self.showNormal()
        else:self.show()
        self._ensure_window_on_screen();self.show();self.raise_();self.activateWindow()
        QTimer.singleShot(0,self._finish_window_restore)

    def _finish_window_restore(self):
        self._ensure_window_on_screen();self.show();self.raise_();self.activateWindow()

    def _apply_window_visibility(self):
        visible=self.isVisible() and not self.isMinimized()
        for card in self.cards:card.set_window_visible(visible)
        self._update_preview_visibility()

    def showEvent(self,event):super().showEvent(event);QTimer.singleShot(0,self._apply_window_visibility)

    def hideEvent(self,event):super().hideEvent(event);QTimer.singleShot(0,self._apply_window_visibility)

    def changeEvent(self,event):
        super().changeEvent(event)
        if event.type()==QEvent.WindowStateChange:
            QTimer.singleShot(0,self._apply_window_visibility)

    def runtime_diagnostics(self):
        try:
            import psutil
            process=psutil.Process();tree=[process]+process.children(recursive=True);rss=round(sum(item.memory_info().rss for item in tree)/1048576,1);os_threads=sum(item.num_threads() for item in tree);children=len(tree)-1;logical=max(1,psutil.cpu_count() or 1);total_cpu=round(sum(item.cpu_percent(None) for item in tree)/logical,3);processes=[{"pid":item.pid,"parent_pid":item.ppid(),"name":item.name(),"rss_mb":round(item.memory_info().rss/1048576,1),"threads":item.num_threads()} for item in tree]
        except Exception:rss="unavailable";os_threads="unavailable";children="unavailable";total_cpu="sampling";processes=[]
        diagnostics=[card.runtime_diagnostics() for card in self.cards];shared=getattr(self,"shared_hub",None);shared_active=bool(shared and shared.scheduler.is_active)
        return {"pid":os.getpid(),"total_oni_cpu_percent_normalized":total_cpu,"total_oni_ram_mb":rss,"total_oni_gpu_percent":"unavailable without Windows engine counters","oni_process_count":children+1 if isinstance(children,int) else children,"process_tree_thread_count":os_threads,"child_process_count":children,"processes":processes,"shared_decoder":shared_active,"shared_decoder_backend":getattr(shared.source,"backend","None") if shared else "None","scheduler_count":sum(x["scheduler_count"] for x in diagnostics)+int(shared_active),"active_playback_workers":sum(x["playback_workers"] for x in diagnostics)+(shared.active_workers if shared else 0),"active_timers":sum(1 for x in self.findChildren(QTimer) if x.isActive()),"active_decoders":sum(x["decoder_active"] for x in diagnostics)+int(shared_active),"active_display_sessions":sum(x["display_session_active"] for x in diagnostics),"decoded_queue_sizes":[x["decoded_queue_size"] for x in diagnostics],"transport_queue_sizes":[x["transport_queue_size"] for x in diagnostics],"gui_preview_presented_fps":[round(x.actual_preview_fps(),2) for x in self.cards],"physical_lcd_completed_fps":[round(x.actual_fps(),2) for x in self.cards],"retained_full_resolution_frames":sum(x["retained_full_resolution_frames"] for x in diagnostics),"metrics_history_lengths":[x["metrics_history_length"] for x in diagnostics],"cache_sizes":[x["cache_size"] for x in diagnostics],"preview_pending":[x["preview_pending"] for x in diagnostics]}

    def exit_application(self):self._force_exit=True;self.shutdown();self.close();QApplication.instance().quit()

    def _update_preview_visibility(self):
        enabled=(self.isVisible() and not self.isMinimized()) or resource_mode(self.settings.performance_mode).preview_when_hidden
        for card in self.cards:card.set_preview_enabled(enabled)

    def _rebuild_display_splitter(self):
        orientation=Qt.Horizontal if self.settings.display_layout=="side_by_side" else Qt.Vertical
        self.display_splitter.setOrientation(orientation)
        stacked=orientation==Qt.Vertical
        for card in self.cards:
            card.set_layout_mode(not stacked)
            card.setMinimumHeight(350 if stacked else 0);card.setMaximumHeight(16777215);card.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Expanding)
        self.display_splitter.setMinimumHeight(max(710,350*len(self.cards)) if stacked and len(self.cards)>1 else 350 if stacked and self.cards else 0);self.display_splitter.setMaximumHeight(16777215)
        ordered=[self.card_by_id[device_id] for device_id in self.settings.display_order if device_id in self.card_by_id]
        ordered.extend(card for card in self.cards if card not in ordered)
        for card in ordered:self.display_splitter.addWidget(card)
        if self.settings.splitter_sizes and len(self.settings.splitter_sizes)==len(self.cards):self.display_splitter.setSizes(self.settings.splitter_sizes)
        else:self.display_splitter.setSizes([1]*len(self.cards))


STYLE = """
QWidget {
    background-color: #050611;
    color: #f2f1ff;
    font-family: 'Segoe UI Variable', 'Segoe UI', system-ui, sans-serif;
    font-size: 10pt;
    selection-background-color: #6847ee;
    selection-color: #ffffff;
}

QMainWindow, QDialog {
    background-color: #050712;
}
QWidget#appShell, QScrollArea#pageScroll,
QScrollArea#pageScroll > QWidget > QWidget, QWidget#oniHomeSurface { background: transparent; }
QStackedWidget#pageStack, QWidget#oniPageSurface {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                stop:0 #071124, stop:0.20 #07101f,
                                stop:0.52 #0b0b20, stop:0.78 #080d1b,
                                stop:1 #061322);
}
QWidget#pageViewport {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                stop:0 #071124, stop:0.18 #07101f,
                                stop:0.48 #0b0b20, stop:0.72 #080d1b,
                                stop:1 #061322);
    border-left: 1px solid rgba(107,91,216,80);
}

QLabel {
    background-color: transparent;
}

QFrame#sidebar {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                stop:0 rgba(4,7,17,247), stop:0.68 rgba(8,11,28,244), stop:1 rgba(24,27,62,226));
    border-right: 1px solid rgba(104,91,218,105);
}

QPushButton#navArtworkButton {
    background: transparent;
    border: none;
    padding: 0;
    min-height: 74px;
    max-height: 74px;
}
QPushButton#supportedDisplaysButton { min-height:28px; padding:4px 8px; color:#cbd5f4; background:#10152a; border:1px solid #303a68; }
QFrame#layoutRecommendation { background:#111831; border:1px solid #655fe0; border-radius:10px; }
QFrame#layoutRecommendation QLabel { color:#e9eaff; font-size:9.5pt; }

QPushButton#navButton {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #101322, stop:1 #15182a);
    border: 1px solid #222844;
    border-left: 3px solid #343b6d;
    border-radius: 10px;
    color: #e6e5f8;
    text-align: left;
    padding: 7px 9px 7px 11px;
    font-size: 9.5pt;
    font-weight: 650;
    min-height: 24px;
}

QPushButton#navButton:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #181b36, stop:1 #20204a);
    border-color: #5152a8;
    color: #ffffff;
}

QPushButton#navButton:checked {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                stop:0 #5b35dd, stop:0.52 #3d3bb6, stop:1 #17376b);
    border-color: #7668ff;
    border-left-color: #67dcff;
    color: #ffffff;
}
QFrame#sidebarBrand {
    background: transparent;
    border: none;
}
QLabel#sidebarBrandName { color: #ffffff; font-size: 18pt; font-weight: 900; }
QLabel#sidebarSlogan { color: #a6a7cf; font-size: 7.5pt; font-weight: 700; letter-spacing: 1px; }
QLabel#sidebarArt { background: transparent; border: none; }

QToolButton#sidebarToggle {
    background-color: transparent;
    border: none;
    border-radius: 7px;
    padding: 2px;
}
QToolButton#sidebarToggle:hover {
    background-color: #0d2b42;
    border-color: #24b9f4;
}
QLabel#sectionPageTitle {
    font-size: 22pt;
    font-weight: 800;
    color: #ffffff;
}
QLabel#diagnosticPanel {
    background-color: #081725;
    border: 1px solid #19445f;
    border-radius: 8px;
    padding: 14px;
    color: #c5dce7;
}

QLabel#pageTitle {
    font-size: 21pt;
    font-weight: 800;
    color: #ffffff;
}

QLabel#pageSubtitle {
    font-size: 11pt;
    color: #a9b9d8;
}
QWidget#oniPageHeader {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 rgba(14,24,51,235),stop:0.62 rgba(10,16,38,220),stop:1 rgba(8,13,30,205));
    border: 1px solid rgba(70,85,151,175);
    border-radius: 12px;
}

QFrame#card {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #101326, stop:1 #090c19);
    border: 1px solid #313761;
    border-radius: 12px;
}

QLabel#vendorLabel {
    font-size: 7pt;
    font-weight: 800;
    color: #16b8ff;
}

QLabel#deviceNameLabel {
    font-size: 10pt;
    font-weight: 700;
    color: #ffffff;
}

QLabel#deviceSpecLabel {
    font-size: 8pt;
    color: #7892a8;
}

QLabel#connectedDot {
    color: #20df7a;
    font-size: 10pt;
}

QLabel#connectionText {
    color: #20df7a;
    font-weight: 600;
}

QLabel#mediaBadge {
    background-color: #0b2940;
    border: 1px solid #1b5877;
    border-radius: 4px;
    color: #6fe7ff;
    padding: 2px 6px;
    font-size: 7.5pt;
    font-weight: 700;
}

QLabel#preview {
    background-color: transparent;
    border: none;
    border-radius: 8px;
    color: #7892a8;
}

QFrame#previewFooter {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #101326,stop:1 #0b1020);
    border: 1px solid #30365d;
    border-radius: 8px;
}
QFrame#previewFooter QPushButton { padding: 3px 5px; min-height: 20px; font-size: 8.5pt; }

QFrame#unifiedInspector {
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #101321,stop:1 #0a0d18);
    border: 1px solid #343961;
    border-radius: 10px;
}
QFrame#unifiedInspector QPushButton,QFrame#unifiedInspector QComboBox,QFrame#unifiedInspector QSpinBox,QFrame#unifiedInspector QDoubleSpinBox { padding: 3px 5px; min-height: 20px; font-size: 8.5pt; }

QGroupBox {
    background-color: #0d101d;
    border: 1px solid #272d50;
    border-radius: 8px;
    margin-top: 10px;
    padding-top: 6px;
    font-size: 8pt;
    font-weight: 700;
    color: #c4c5e4;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 8px;
    padding: 0 4px;
}

QPushButton, QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox {
    background-color: #14182b;
    border: 1px solid #353c68;
    border-radius: 7px;
    color: #f0efff;
    padding: 6px 10px;
    min-height: 24px;
}

QPushButton:hover, QComboBox:hover, QLineEdit:hover,
QSpinBox:hover, QDoubleSpinBox:hover {
    background-color: #202343;
    border-color: #7b6cff;
    color: #ffffff;
}

QPushButton:focus, QComboBox:focus, QLineEdit:focus,
QSpinBox:focus, QDoubleSpinBox:focus {
    border-color: #6fe7ff;
}

QPushButton:disabled {
    color: #466077;
    background-color: #0a1522;
    border-color: #142a3d;
}

QSpinBox, QDoubleSpinBox {
    padding-right: 22px;
}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
    width: 20px;
}

QPushButton#btnPlay {
    background-color: #10b981;
    border-color: #059669;
    color: #ffffff;
    font-weight: 700;
}
QPushButton#btnPlay:hover {
    background-color: #34d399;
}

QPushButton#btnPause {
    background-color: #f59e0b;
    border-color: #d97706;
    color: #ffffff;
    font-weight: 700;
}
QPushButton#btnPause:hover {
    background-color: #fbbf24;
}

QPushButton#btnStop {
    background-color: #ef4444;
    border-color: #dc2626;
    color: #ffffff;
    font-weight: 700;
}
QPushButton#btnStop:hover {
    background-color: #f87171;
}

QPushButton#btnClear {
    background-color: #374151;
    border-color: #4b5563;
    color: #ffffff;
}
QPushButton#btnClear:hover {
    background-color: #4b5563;
}

QPushButton:checked {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #6639e5,stop:1 #3769ef);
    border-color: #9a8cff;
    color: #ffffff;
}

QPushButton#primaryButton {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #7a3df0,stop:1 #3478ff);
    border-color: #9c8cff;
    color: #ffffff;
    font-weight: 700;
}

QPushButton#primaryButton:hover {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #8d55ff,stop:1 #4792ff);
    border-color: #c1b7ff;
}

QSlider::groove:horizontal {
    height: 4px;
    background: #252a49;
    border-radius: 2px;
}

QSlider::sub-page:horizontal {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #7847ef,stop:1 #39bfff);
    border-radius: 2px;
}

QSlider::handle:horizontal {
    background: #f3efff;
    border: 2px solid #8876ff;
    width: 12px;
    margin: -4px 0;
    border-radius: 6px;
}

QLabel#ultraLowLabel {
    color: #20df7a;
    font-size: 8pt;
    font-weight: 600;
}

QLabel#versionLabel {
    color: #7892a8;
    font-size: 8pt;
}

QComboBox::drop-down {
    border: 0;
    width: 24px;
}

QComboBox QAbstractItemView {
    background-color: #0b1928;
    border: 1px solid #246185;
    color: #dff5ff;
    selection-background-color: #0a638f;
    outline: 0;
}

QAbstractItemView {
    background-color: #08131f;
    alternate-background-color: #0b1928;
    border: 1px solid #173b55;
    border-radius: 7px;
    color: #cfe9f5;
    outline: 0;
}

QAbstractItemView::item:hover {
    background-color: #0d2b42;
    color: #ffffff;
}

QAbstractItemView::item:selected {
    background-color: #075f8b;
    color: #ffffff;
}

QTabWidget::pane {
    border: 1px solid #19445f;
    border-radius: 8px;
    background-color: #08131f;
}

QTabBar::tab {
    background-color: #0b1928;
    color: #7f9aae;
    border: 1px solid #173b55;
}

QTabBar::tab:hover {
    color: #dff7ff;
    border-color: #24aee7;
}

QTabBar::tab:selected {
    background-color: #0c2d45;
    color: #6fe7ff;
    border-color: #2bc8ff;
}

QCheckBox {
    color: #c9e0ea;
}

QCheckBox::indicator {
    border: 1px solid #315c78;
    border-radius: 4px;
    background-color: #08131f;
}

QCheckBox::indicator:hover {
    border-color: #42d5ff;
}

QCheckBox::indicator:checked {
    background-color: #16b8ff;
    border-color: #6fe7ff;
}

QMenu {
    background-color: #091724;
    border: 1px solid #1c526f;
    color: #dff5ff;
}

QMenu::item:selected {
    background-color: #0c5278;
    color: #ffffff;
}

QMenu::separator {
    height: 1px;
    background-color: #18394e;
}

QScrollBar:vertical {
    background: #07111c;
    width: 10px;
}

QScrollBar::handle:vertical {
    background: #1a5775;
    min-height: 24px;
    border-radius: 5px;
}

QScrollBar::handle:vertical:hover {
    background: #23a7d9;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}

QScrollBar:horizontal {
    background: #07111c;
    height: 10px;
}

QScrollBar::handle:horizontal {
    background: #1a5775;
    min-width: 24px;
    border-radius: 5px;
}

QScrollBar::handle:horizontal:hover {
    background: #23a7d9;
}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0;
}

QSplitter::handle {
    background-color: #11354c;
}

QSplitter::handle:hover {
    background-color: #25bceb;
}

QToolTip {
    background-color: #0d2234;
    color: #eafaff;
    border: 1px solid #2bc8ff;
}

QFrame#oniCard {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 rgba(18,24,50,244), stop:0.48 rgba(11,17,38,239), stop:1 rgba(6,11,26,244));
    border: 1px solid rgba(70,85,151,190);
    border-radius: 13px;
}
QFrame#oniCard:hover { border-color: #625fac; }
QFrame#oniCard[role="hero"] {
    background: #090b17;
    border-color: #4b438e;
}
QFrame#oniCard[role="metric"] {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 rgba(21,30,60,244), stop:1 rgba(8,16,36,239));
    border-color: rgba(60,88,157,175);
    border-radius: 9px;
}
QFrame#oniCard[role="device"] {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 rgba(22,31,63,245), stop:1 rgba(7,18,41,239));
    border-color: rgba(66,98,164,190);
}
QWidget#recentEmpty { background: transparent; }
QLabel#emptyArtwork { background: transparent; border: none; }
QStackedWidget#recentStack { background: transparent; border: none; }
QLabel#heroTitle {
    font-size: 34pt;
    font-weight: 900;
    color: #ffffff;
}
QLabel#heroSubtitle { color: #d8d5ff; font-size: 14pt; font-weight: 600; }
QLabel#cardTitle {
    font-size: 13pt;
    font-weight: 750;
    color: #f5f3ff;
}
QLabel#sectionTitle {
    color: #f7f6ff;
    font-size: 13pt;
    font-weight: 800;
}
QLabel#sectionDescription {
    color: #a9b7d2;
    font-size: 10.5pt;
    line-height: 1.3;
}
QLabel#fieldLabel {
    color: #78bddd;
    font-size: 8.5pt;
    font-weight: 800;
    letter-spacing: 1px;
}
QLabel#statusPill {
    color: #dff8ff;
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #153c69,stop:1 #382b7d);
    border: 1px solid #4f68aa;
    border-radius: 9px;
    padding: 6px 12px;
    font-size: 9pt;
    font-weight: 800;
}
QLabel#inlineNotice {
    color: #b7c5df;
    background: rgba(10,27,52,190);
    border: 1px solid #244a78;
    border-radius: 8px;
    padding: 10px 12px;
    font-size: 10pt;
}
QLabel#monitorPreview {
    color: #aab8d3;
    background: qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #050b18,stop:0.55 #071126,stop:1 #0c0b24);
    border: 1px solid #27446f;
    border-radius: 10px;
    font-size: 12pt;
    padding: 16px;
}
QLabel#diagnosticDot { color: #47e7b0; font-size: 15pt; }
QLabel#diagnosticSummary {
    color: #c7d4e9;
    background: rgba(5,13,29,180);
    border: 1px solid #243c69;
    border-radius: 9px;
    padding: 16px;
    font-size: 10.5pt;
}
QLabel#recentTitle {
    font-size: 14pt;
    font-weight: 800;
    color: #ffffff;
}
QLabel#sectionLabel {
    color: #7897aa;
    font-size: 9pt;
    font-weight: 700;
    letter-spacing: 1px;
}
QLabel#metricIcon {
    color: #aeeaff;
    background: qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #174f75,stop:1 #49329b);
    border: 1px solid #4d74b0;
    border-radius: 7px;
    font-size: 11pt;
    font-weight: 800;
}
QLabel#metricLabel {
    color: #aebedc;
    font-size: 10pt;
    font-weight: 650;
}
QLabel#metricValue {
    color: #ffffff;
    font-size: 23pt;
    font-weight: 850;
}
QLabel#deviceTileTitle { color: #ffffff; font-size: 12pt; font-weight: 800; }
QLabel#deviceStatusDot { color: #31ed9a; font-size: 13pt; }
QLabel#deviceStatusDotLocked { color: #9b83ff; font-size: 13pt; }
QLabel#deviceStatusText { color: #b9c7e7; font-size: 9.5pt; font-weight: 650; }
QLabel#deviceResolution { color: #79ccef; font-size: 9.5pt; font-weight: 700; }
QLabel#statusGood {
    color: #28e985;
    font-weight: 700;
}
QLabel#emptyTitle {
    color: #ffffff;
    font-size: 16pt;
    font-weight: 800;
}
QLabel#outputEmptyTitle { color:#ffffff; font-size:17pt; font-weight:850; }
QLabel#outputEmptyDetail { color:#9eadcc; font-size:10pt; font-weight:550; }
QWidget#outputEmptyState, QWidget#homePreviewSurface, QStackedWidget#outputPreviewStack { background: transparent; border: none; }
QLabel#homePreview {
    background: transparent;
    border: 1px solid #1c5a7d;
    border-radius: 9px;
    color: #6e899d;
    padding: 0;
}
QPushButton#secondaryButton {
    background-color: #0b2032;
    border-color: #1f5270;
    padding: 9px 15px;
    font-weight: 600;
}
QPushButton#dangerButton {
    background-color: #32131d;
    border-color: #7d2a3c;
    color: #ffb1bd;
}
QPushButton#ghostButton {
    background-color: transparent;
    border-color: #245a77;
    color: #b7d7e8;
    padding: 5px 10px;
}
QPushButton#ghostButton:hover { background-color: #0d2c43; border-color: #35d2ff; color: #ffffff; }
QPushButton#homePrimaryAction, QPushButton#deviceAction {
    min-height: 34px;
    padding: 6px 16px;
    border-radius: 9px;
    border: 1px solid #716cff;
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #5639d5,stop:1 #246acb);
    color: #ffffff;
    font-size: 10pt;
    font-weight: 750;
}
QPushButton#homePrimaryAction:hover, QPushButton#deviceAction:hover { border-color:#9deaff; background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #6849ee,stop:1 #2c83e8); }
QPushButton#homePrimaryAction:pressed, QPushButton#deviceAction:pressed { background:#352a8d; padding-top:7px; padding-bottom:5px; }
QPushButton#homePrimaryAction:disabled, QPushButton#deviceAction:disabled { color:#69728f; background:#171c33; border-color:#2d3457; }
QPushButton#homeSecondaryAction, QPushButton#viewAllButton {
    min-height: 30px;
    padding: 5px 13px;
    border-radius: 8px;
    border: 1px solid #36558d;
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #121d38,stop:1 #162445);
    color: #dce9ff;
    font-size: 9.5pt;
    font-weight: 700;
}
QPushButton#homeSecondaryAction:hover, QPushButton#viewAllButton:hover { border-color:#55cffa; background:#182e53; color:#ffffff; }
QPushButton#homeSecondaryAction:pressed, QPushButton#viewAllButton:pressed { background:#101a36; }
QPushButton#studioBackButton {
    background-color: transparent;
    border-color: transparent;
    color: #65dcff;
    text-align: left;
    padding: 5px 8px;
}
QListWidget#assetGrid, QListWidget#themeGrid, QListWidget#profileList {
    background-color: transparent;
    border: none;
    padding: 4px;
}
QListWidget#recentStrip { background: transparent; border: none; padding: 0; }
QListWidget#recentStrip::item { background: #071522; border: 1px solid #174a69; border-radius: 8px; padding: 6px; margin: 2px; color: #d9edf7; }
QListWidget#recentStrip::item:hover { background: #0b2940; border-color: #2bc8ff; }
QListWidget#assetGrid::item, QListWidget#themeGrid::item, QListWidget#profileList::item {
    background-color: #091827;
    border: 1px solid #173e58;
    border-radius: 9px;
    padding: 8px;
    margin: 3px;
}
QListWidget#assetGrid::item:selected, QListWidget#themeGrid::item:selected, QListWidget#profileList::item:selected {
    background-color: #0b2d45;
    border-color: #28c8ff;
}
QScrollArea#pageScroll { border: none; background: transparent; }
"""

def main():
    log_path=Path(os.environ.get("LOCALAPPDATA",Path.home()))/"OniThermalLcd"/"logs";configure_logging(log_path)
    app=QApplication(sys.argv);app.setQuitOnLastWindowClosed(False);app.setStyleSheet(STYLE);app.setApplicationName("Oni Thermal LCD Control");app.setApplicationVersion("0.1.0");app.setOrganizationName("Oni Thermal LCD contributors");app.setWindowIcon(QIcon(str(bundled_path("assets/oni-thermal-lcd.ico"))))
    instance=SingleInstance(os.environ.get("ONI_LCD_INSTANCE_NAME","OniThermalLcdControl-v1"),parent=app)
    if not instance.acquire_or_notify():return 0
    splash=OniSplash(bundled_path("assets/oni-thermal-lcd-icon.png"));splash.show();app.processEvents()
    splash_capture=os.environ.get("ONI_LCD_SPLASH_SCREENSHOT")
    if splash_capture:
        splash_target=Path(splash_capture);splash_target.parent.mkdir(parents=True,exist_ok=True);splash.grab().save(str(splash_target),"PNG")
    try:w=MainWindow()
    except Exception:
        splash.close()
        import logging
        logging.getLogger("thermalright_lcd.gui").exception("GUI startup failed")
        import traceback
        traceback.print_exc()
        return 1
    w.show();app.processEvents()
    if "--start-minimized" not in sys.argv and "--start-to-tray" not in sys.argv:w._ensure_window_on_screen();w.show();w.raise_();w.activateWindow()
    splash.finish(w)
    instance.activationRequested.connect(w.restore_window);app.aboutToQuit.connect(w.shutdown)
    evidence_path=os.environ.get("ONI_LCD_GUI_SCREENSHOT")
    if evidence_path:
        def capture_evidence():
            w.resize(int(os.environ.get("ONI_LCD_GUI_SCREENSHOT_WIDTH","1900")),int(os.environ.get("ONI_LCD_GUI_SCREENSHOT_HEIGHT","1000")))
            w.move(0,0)
            scale=int(os.environ.get("ONI_LCD_GUI_SCREENSHOT_PREVIEW_SCALE","100"))
            for card in (w.left,w.right):card.preview_scale_slider.setValue(max(50,min(200,scale)))
            evidence_layout=os.environ.get("ONI_LCD_GUI_SCREENSHOT_LAYOUT")
            if evidence_layout in {"stacked","side_by_side"}:w.set_display_layout(evidence_layout);w.layout_selector.setCurrentIndex(max(0,w.layout_selector.findData(evidence_layout)))
            if os.environ.get("ONI_LCD_GUI_SCREENSHOT_SIDEBAR")=="collapsed":w.set_sidebar_expanded(False,save=False)
            evidence_device=os.environ.get("ONI_LCD_GUI_SCREENSHOT_DEVICE")
            if evidence_device in {"0416:5408","0416:5302"}:
                keep=w.card_by_id[evidence_device];other=w.right if keep is w.left else w.left;other.hide();w.set_display_layout("stacked")
            for device_id,card in (("5408",w.left),("5302",w.right)):
                media=os.environ.get(f"ONI_LCD_GUI_SCREENSHOT_MEDIA_{device_id}")
                if media:card.load(Path(media))
                if os.environ.get(f"ONI_LCD_GUI_SCREENSHOT_PLAY_{device_id}")=="1":card.play(coordinated=True)
            if os.environ.get("ONI_LCD_GUI_SCREENSHOT_SENSOR_THEME") in {"5408","5302"}:
                card=w.left if os.environ["ONI_LCD_GUI_SCREENSHOT_SENSOR_THEME"]=="5408" else w.right
                card.output_selector.setCurrentIndex(card.output_selector.findData(OutputMode.HARDWARE_MONITOR.value))
            if os.environ.get("ONI_LCD_GUI_SCREENSHOT_MONITOR_EDIT")=="1":
                card=w.left;card.monitor_template.setCurrentText("Gaming Dashboard");card.quick_edit.setChecked(True);editor=card.home_quick_editor
                if editor and editor.layout.elements:
                    selected=editor.layout.elements[0];editor.scene.items_by_id[selected.id].setSelected(True);editor.select_element(selected.id)
                card.context_tabs.setCurrentWidget(card.monitor_tab)
            surface=w;surface_kind=os.environ.get("ONI_LCD_GUI_SCREENSHOT_SURFACE","home")
            if surface_kind=="gallery":surface=ThemeGalleryDialog(w.settings,w.store,w);surface.resize(1500,900);surface.show()
            elif surface_kind=="designer":
                theme=os.environ.get("ONI_LCD_GUI_SCREENSHOT_THEME","Oni Crimson");layout=deepcopy(templates("0416:5408")[theme]);background=os.environ.get("ONI_LCD_GUI_SCREENSHOT_BACKGROUND","")
                if background:layout.background_source="custom_image";layout.background_image=background;layout.background_fit="fill";layout.background_darken=35
                image_layer=os.environ.get("ONI_LCD_GUI_SCREENSHOT_IMAGE","")
                if image_layer:layout.elements.append(MonitorElement("image",layout.width//2-140,layout.height//2-90,280,180,image=image_layer,z_index=max((e.z_index for e in layout.elements),default=0)+1))
                if os.environ.get("ONI_LCD_GUI_SCREENSHOT_HIDDEN_LAYER")=="1" and layout.elements:layout.elements[0].visible=False
                w.settings.monitor_layouts.setdefault(w.settings.active_profile,{})["0416:5408"]=layout.to_dict();surface=HardwareMonitorDesigner(w.settings,w.store,w);surface.resize(1600,920);surface.show()
                if surface.layout.elements:surface.scene.items_by_id[surface.layout.elements[0].id].setSelected(True);surface.select_element(surface.layout.elements[0].id)
            app.processEvents();target=Path(evidence_path);target.parent.mkdir(parents=True,exist_ok=True)
            geometry_path=os.environ.get("ONI_LCD_GUI_GEOMETRY_REPORT")
            if geometry_path and surface is w:
                def rect(widget):
                    point=widget.mapTo(w,QPoint(0,0));return {"x":point.x(),"y":point.y(),"width":widget.width(),"height":widget.height()}
                report={"window":{"width":w.width(),"height":w.height()},"sidebar_width":w.sidebar.width(),"center_workspace_width":w.pages.width(),"devices":{}}
                for card in (w.left,w.right):
                    preview=rect(card.preview);inspector=rect(card.unified_inspector);body=rect(card.workspace);footer_rect=rect(card.preview_footer);header_rect=rect(card.header_widget);diagnostics_rect=rect(card.advanced_toggle)
                    pixmap=card.preview.pixmap();media_width=pixmap.width() if pixmap and not pixmap.isNull() else 0;media_height=pixmap.height() if pixmap and not pixmap.isNull() else 0;media_x=preview["x"]+(preview["width"]-media_width)//2;media_y=preview["y"]+(preview["height"]-media_height)//2
                    media_rect={"x":media_x,"y":media_y,"width":media_width,"height":media_height};used=preview["width"]*preview["height"]+inspector["width"]*inspector["height"]+footer_rect["width"]*footer_rect["height"];body_area=max(1,body["width"]*body["height"]);card_area=max(1,card.width()*card.height());useful_card=used+header_rect["width"]*header_rect["height"]
                    report["devices"][card.device_id]={"card":rect(card),"header":header_rect,"preview":preview,"preview_ratio":round(preview["width"]/max(1,preview["height"]),4),"media_rect":media_rect,"media_ratio":round(media_width/max(1,media_height),4) if media_height else 0,"unused_vertical_pixels_around_media":max(0,preview["height"]-media_height),"inspector":inspector,"inline_footer":footer_rect,"diagnostics":diagnostics_rect,"body":body,"used_body_area_ratio":round(min(1,used/body_area),4),"useful_card_area_ratio":round(min(1,useful_card/card_area),4)}
                report["total_visible_dead_space_estimate_ratio"]=round(1-sum(device["useful_card_area_ratio"] for device in report["devices"].values())/max(1,len(report["devices"])),4)
                geometry_target=Path(geometry_path);geometry_target.parent.mkdir(parents=True,exist_ok=True);geometry_target.write_text(json.dumps(report,indent=2),encoding="utf-8")
            if not surface.grab().save(str(target),"PNG"):raise RuntimeError(f"could not save frozen GUI evidence to {target}")
            if surface is not w:surface.close()
            w.exit_application()
        QTimer.singleShot(500,capture_evidence)
    # The saved preference controls how the Windows startup shortcut is built;
    # it must not hide an ordinary manual launch. Only the explicit arguments
    # emitted by startup_command() request a hidden/tray launch.
    if "--start-minimized" in sys.argv or "--start-to-tray" in sys.argv:
        QTimer.singleShot(0,w.hide)
    if os.environ.get("ONI_LCD_GUI_SMOKE_TEST")=="1":
        hold_ms=max(750,int(os.environ.get("ONI_LCD_GUI_SMOKE_HOLD_MS","750")))
        QTimer.singleShot(hold_ms,w.exit_application)
    return app.exec()

if __name__ == "__main__":
    sys.exit(main())
