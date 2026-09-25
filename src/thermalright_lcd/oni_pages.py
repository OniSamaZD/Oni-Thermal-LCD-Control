"""Integrated ONI application pages built on the existing runtime APIs."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys
from typing import Callable

from PySide6.QtCore import Qt, QTimer, Signal, QSize
from PySide6.QtGui import QColor, QIcon, QLinearGradient, QRadialGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QFileDialog, QFrame,
    QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QInputDialog, QMessageBox, QPushButton, QScrollArea, QSizePolicy, QStackedWidget,
    QToolButton, QVBoxLayout, QWidget,
)

from .media_types import MediaKind, detect_media_kind, media_filter
from .modes import MODES, resource_mode
from .output_mode import OutputMode
from .sensor_theme_editor import SensorThemeEditorPage, _image_to_pixmap, SAMPLE_SENSOR_VALUES, SAMPLE_HISTORY
from .sensor_theme import SensorBindingResolver
from .sensor_theme_renderer import SensorThemeRenderer
from .sensor_theme_store import SensorThemeStore


class OniCard(QFrame):
    def __init__(self, parent: QWidget | None = None, *, role: str = "default") -> None:
        super().__init__(parent); self.setObjectName("oniCard"); self.setProperty("role", role)

    def paintEvent(self, event) -> None:
        painter=QPainter(self); painter.setRenderHint(QPainter.Antialiasing); bounds=self.rect().adjusted(1,1,-1,-1); role=self.property("role")
        fill=QLinearGradient(bounds.topLeft(),bounds.bottomRight())
        if role == "metric": colors=(QColor(20,30,60,238),QColor(7,15,34,242)); border=QColor(66,96,168,155)
        elif role == "device": colors=(QColor(22,32,65,240),QColor(7,17,39,242)); border=QColor(74,108,179,175)
        else: colors=(QColor(16,23,49,237),QColor(6,11,27,243)); border=QColor(68,79,145,165)
        fill.setColorAt(0,colors[0]); fill.setColorAt(1,colors[1]); painter.setBrush(fill); painter.setPen(QPen(border,1)); painter.drawRoundedRect(bounds,12,12); painter.end()


def _ui_asset(name: str) -> Path:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return root / "assets" / "ui" / name


class OniArtworkCard(OniCard):
    """Responsive artwork-backed card; children remain normal live Qt controls."""
    def __init__(self, asset_name: str, parent=None, *, role: str = "hero") -> None:
        super().__init__(parent, role=role); self._art = QPixmap(str(_ui_asset(asset_name)))

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self._art.isNull(): return
        painter = QPainter(self); painter.setRenderHint(QPainter.SmoothPixmapTransform)
        target = self.rect().adjusted(1, 1, -1, -1); clip = QPainterPath(); clip.addRoundedRect(target, 13, 13); painter.setClipPath(clip)
        scaled = self._art.scaled(target.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        source_x = max(0, (scaled.width() - target.width()) // 2); source_y = max(0, (scaled.height() - target.height()) // 2)
        painter.drawPixmap(target, scaled, scaled.rect().adjusted(source_x, source_y, -source_x, -source_y))
        shade = QLinearGradient(target.left(), target.top(), target.right(), target.top()); shade.setColorAt(0, QColor(3, 7, 17, 242)); shade.setColorAt(.48, QColor(7, 8, 24, 198)); shade.setColorAt(.78, QColor(8, 9, 26, 70)); shade.setColorAt(1, QColor(4, 6, 15, 22)); painter.fillRect(target, shade); painter.end()


class OniPageHeader(QWidget):
    def __init__(self, title: str, subtitle: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent); self.setObjectName("oniPageHeader"); self.setMinimumHeight(70); self.setAttribute(Qt.WA_StyledBackground, True); row = QHBoxLayout(self); row.setContentsMargins(18, 11, 14, 11); row.setSpacing(16)
        text = QVBoxLayout(); text.setSpacing(3); heading = QLabel(title); heading.setObjectName("pageTitle"); heading.setMinimumHeight(32); text.addWidget(heading)
        if subtitle:
            detail = QLabel(subtitle); detail.setObjectName("pageSubtitle"); detail.setWordWrap(True); text.addWidget(detail)
        row.addLayout(text); row.addStretch(); self.actions = QHBoxLayout(); self.actions.setSpacing(8); row.addLayout(self.actions)

    def add_action(self, text: str, callback: Callable, *, primary: bool = False) -> QPushButton:
        button = QPushButton(text); button.setObjectName("primaryButton" if primary else "secondaryButton"); button.clicked.connect(callback); self.actions.addWidget(button); return button


class OniEmptyState(OniCard):
    def __init__(self, title: str, detail: str, action: str = "", callback: Callable | None = None, parent=None) -> None:
        super().__init__(parent); layout = QVBoxLayout(self); layout.setContentsMargins(24, 28, 24, 28); layout.setSpacing(8); layout.addStretch()
        heading = QLabel(title); heading.setObjectName("emptyTitle"); heading.setAlignment(Qt.AlignCenter); layout.addWidget(heading)
        body = QLabel(detail); body.setObjectName("muted"); body.setAlignment(Qt.AlignCenter); body.setWordWrap(True); layout.addWidget(body)
        if action and callback:
            row = QHBoxLayout(); row.addStretch(); button = QPushButton(action); button.setObjectName("primaryButton"); button.clicked.connect(callback); row.addWidget(button); row.addStretch(); layout.addLayout(row)
        layout.addStretch()


class OniDisplayGlyph(QWidget):
    """Small, non-interactive LCD outline for the truthful output empty state."""
    def __init__(self, parent=None) -> None:
        super().__init__(parent); self.setFixedSize(104, 66); self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def paintEvent(self, event) -> None:
        painter=QPainter(self); painter.setRenderHint(QPainter.Antialiasing)
        glow=QRadialGradient(52,30,48); glow.setColorAt(0,QColor(57,178,255,70)); glow.setColorAt(1,QColor(86,57,212,0)); painter.fillRect(self.rect(),glow)
        shell=self.rect().adjusted(10,9,-10,-17); painter.setPen(QPen(QColor("#7bdcff"),2)); painter.setBrush(QColor(10,20,48,210)); painter.drawRoundedRect(shell,7,7)
        screen=shell.adjusted(6,6,-6,-6); fill=QLinearGradient(screen.topLeft(),screen.bottomRight()); fill.setColorAt(0,QColor("#26388f")); fill.setColorAt(1,QColor("#4f268a")); painter.setBrush(fill); painter.setPen(QPen(QColor(143,120,255,150),1)); painter.drawRoundedRect(screen,4,4)
        painter.setPen(QPen(QColor(123,220,255,120),1)); painter.drawLine(screen.left()+8,screen.bottom()-7,screen.left()+23,screen.top()+10); painter.drawLine(screen.left()+23,screen.top()+10,screen.left()+36,screen.bottom()-13); painter.drawLine(screen.left()+36,screen.bottom()-13,screen.right()-8,screen.top()+8)
        painter.setPen(QPen(QColor("#6977ad"),2)); painter.drawLine(44,52,60,52); painter.drawLine(36,57,68,57); painter.end()


class OniMetricCard(OniCard):
    def __init__(self, label: str, icon: str = "•", parent=None) -> None:
        super().__init__(parent, role="metric"); layout = QVBoxLayout(self); layout.setContentsMargins(14, 10, 14, 11); layout.setSpacing(4)
        heading=QHBoxLayout(); heading.setSpacing(7); self.icon=QLabel(icon); self.icon.setObjectName("metricIcon"); self.icon.setAlignment(Qt.AlignCenter); self.icon.setFixedSize(27,27); self.icon.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.label = QLabel(label); self.label.setObjectName("metricLabel"); heading.addWidget(self.icon); heading.addWidget(self.label); heading.addStretch(); self.value = QLabel("—"); self.value.setObjectName("metricValue")
        layout.addLayout(heading); layout.addWidget(self.value)


class OniMediaGrid(QListWidget):
    filesDropped = Signal(object)
    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls(): event.acceptProposedAction()
        else: super().dragEnterEvent(event)
    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasUrls(): event.acceptProposedAction()
        else: super().dragMoveEvent(event)
    def dropEvent(self, event) -> None:
        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]
        if paths: self.filesDropped.emit(paths); event.acceptProposedAction()
        else: super().dropEvent(event)


def scroll_page(content: QWidget) -> QScrollArea:
    scroll = QScrollArea(); scroll.setObjectName("pageScroll"); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.NoFrame)
    scroll.setAutoFillBackground(False); scroll.viewport().setObjectName("pageViewport")
    content.setObjectName("oniPageSurface" if not isinstance(content, OniHomePage) else "oniHomeSurface")
    content.setAutoFillBackground(False); content.setAttribute(Qt.WA_TranslucentBackground, False); content.setAttribute(Qt.WA_StyledBackground, True); scroll.setWidget(content); return scroll


class OniHomePage(QWidget):
    displayWorkspaceRequested = Signal()

    SENSOR_BINDINGS = (
        ("CPU Temp", "cpu.temperature", "♨"), ("GPU Temp", "gpu.temperature", "◈"),
        ("CPU Load", "cpu.usage", "◌"), ("GPU Load", "gpu.usage", "◆"),
        ("RAM", "memory.usage", "▤"), ("FPS", "game.fps", "↗"),
    )

    def paintEvent(self, event) -> None:
        painter=QPainter(self); painter.setRenderHint(QPainter.Antialiasing); rect=self.rect()
        base=QLinearGradient(rect.topLeft(),rect.bottomRight()); base.setColorAt(0,QColor("#071224")); base.setColorAt(.45,QColor("#0b0c21")); base.setColorAt(1,QColor("#061321")); painter.fillRect(rect,base)
        for x,y,radius,color in ((.06,.35,.44,QColor(25,118,179,34)),(.61,.03,.38,QColor(103,48,194,32)),(.93,.70,.34,QColor(31,122,166,25))):
            glow=QRadialGradient(rect.width()*x,rect.height()*y,max(rect.width(),rect.height())*radius); glow.setColorAt(0,color); glow.setColorAt(1,QColor(color.red(),color.green(),color.blue(),0)); painter.fillRect(rect,glow)
        painter.setPen(QPen(QColor(99,121,222,13),1))
        for offset in (.16,.43,.71):
            path=QPainterPath(); path.moveTo(rect.width()*offset,-20); path.cubicTo(rect.width()*(offset+.08),rect.height()*.30,rect.width()*(offset+.15),rect.height()*.63,rect.width()*(offset+.30),rect.height()+20); painter.drawPath(path)
        painter.end()

    def __init__(self, owner, parent=None) -> None:
        super().__init__(parent); self.owner = owner; self.selected_device_id = ""; self._card_signature = (); self._preview_key = 0; self._preview_size = QSize(); self._recent_signature = ()
        outer = QVBoxLayout(self); outer.setContentsMargins(22, 18, 22, 22); outer.setSpacing(14)
        top = QHBoxLayout(); top.setSpacing(14)
        hero = OniArtworkCard("oni-display-studio-hero.jpg", role="hero"); hero.setMinimumHeight(245); hero.setMaximumHeight(286); hero_layout = QVBoxLayout(hero); hero_layout.setContentsMargins(34, 26, 34, 24); hero_layout.setSpacing(8)
        welcome = QLabel("Display Studio"); welcome.setObjectName("heroTitle"); tagline = QLabel("Create beautiful visuals for your LCD screens"); tagline.setObjectName("heroSubtitle"); tagline.setWordWrap(True); hero_layout.addWidget(welcome); hero_layout.addWidget(tagline); hero_layout.addStretch()
        actions = QHBoxLayout(); actions.setSpacing(10)
        for index, (text, callback) in enumerate((("Import Media", owner.open_library), ("New Project", owner.create_sensor_theme), ("Templates", owner.open_theme_gallery))):
            button = QPushButton(text); button.setObjectName("primaryButton" if index == 0 else "secondaryButton"); button.setMinimumHeight(42); button.setMinimumWidth(132); button.clicked.connect(callback); actions.addWidget(button)
        actions.addStretch(); hero_layout.addLayout(actions); top.addWidget(hero, 3)
        devices = OniCard(); devices.setMinimumHeight(245); devices.setMaximumHeight(286); devices_layout = QVBoxLayout(devices); devices_layout.setContentsMargins(17, 15, 17, 15); devices_layout.setSpacing(8); devices_title = QLabel("Connected Displays"); devices_title.setObjectName("cardTitle"); devices_layout.addWidget(devices_title)
        self.displays_host = QWidget(); self.displays_grid = QGridLayout(self.displays_host); self.displays_grid.setContentsMargins(0, 0, 0, 0); self.displays_grid.setSpacing(8); devices_layout.addWidget(self.displays_host, 1); top.addWidget(devices, 2); outer.addLayout(top)

        body = QHBoxLayout(); body.setSpacing(12)
        output = OniCard(); output_layout = QVBoxLayout(output); output_layout.setContentsMargins(14, 13, 14, 13); output_layout.setSpacing(9)
        output_header = QHBoxLayout(); output_title = QLabel("Current Display Output"); output_title.setObjectName("cardTitle"); output_header.addWidget(output_title); output_header.addStretch(); self.display_tabs = QHBoxLayout(); self.display_tabs.setSpacing(5); output_header.addLayout(self.display_tabs); output_layout.addLayout(output_header)
        self.preview_stack=QStackedWidget(); self.preview_stack.setObjectName("outputPreviewStack"); self.preview_stack.setMinimumHeight(240); self.preview_stack.setMaximumHeight(300); self.preview_stack.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Preferred)
        self.preview_surface=QWidget(); self.preview_surface.setObjectName("homePreviewSurface"); preview_surface_layout=QVBoxLayout(self.preview_surface); preview_surface_layout.setContentsMargins(0,0,0,0); preview_surface_layout.addStretch(); preview_row=QHBoxLayout(); preview_row.addStretch(); self.preview = QLabel(); self.preview.setObjectName("homePreview"); self.preview.setAlignment(Qt.AlignCenter); preview_row.addWidget(self.preview); preview_row.addStretch(); preview_surface_layout.addLayout(preview_row); preview_surface_layout.addStretch(); self.preview_stack.addWidget(self.preview_surface)
        self.output_empty=QWidget(); self.output_empty.setObjectName("outputEmptyState"); empty_layout=QVBoxLayout(self.output_empty); empty_layout.setContentsMargins(18,12,18,14); empty_layout.setSpacing(6); empty_layout.addStretch(); glyph=OniDisplayGlyph(); empty_layout.addWidget(glyph,alignment=Qt.AlignCenter); empty_title=QLabel("No output frame yet"); empty_title.setObjectName("outputEmptyTitle"); empty_title.setAlignment(Qt.AlignCenter); empty_layout.addWidget(empty_title); empty_detail=QLabel("Choose media or a Sensor Theme, then open the display workspace."); empty_detail.setObjectName("outputEmptyDetail"); empty_detail.setAlignment(Qt.AlignCenter); empty_layout.addWidget(empty_detail); empty_action=QPushButton("Open Display Workspace"); empty_action.setObjectName("homePrimaryAction"); empty_action.clicked.connect(self.displayWorkspaceRequested); empty_row=QHBoxLayout(); empty_row.addStretch(); empty_row.addWidget(empty_action); empty_row.addStretch(); empty_layout.addLayout(empty_row); empty_layout.addStretch(); self.preview_stack.addWidget(self.output_empty); output_layout.addWidget(self.preview_stack)
        preview_footer = QHBoxLayout(); self.preview_status = QLabel("Waiting for display output"); self.preview_status.setObjectName("muted"); preview_footer.addWidget(self.preview_status); preview_footer.addStretch(); self.manage_output = QPushButton("Open Display Workspace"); self.manage_output.setObjectName("homeSecondaryAction"); self.manage_output.clicked.connect(self.displayWorkspaceRequested); preview_footer.addWidget(self.manage_output); output_layout.addLayout(preview_footer); body.addWidget(output, 3)
        sensors = OniCard(); sensor_layout = QVBoxLayout(sensors); sensor_layout.setContentsMargins(14, 13, 14, 13); sensor_layout.setSpacing(9); title = QLabel("Essential Sensors"); title.setObjectName("cardTitle"); sensor_layout.addWidget(title)
        metrics = QGridLayout(); metrics.setSpacing(8); self.metrics = {}
        for index, (label, binding, icon) in enumerate(self.SENSOR_BINDINGS):
            metric = OniMetricCard(label,icon); metrics.addWidget(metric, index // 2, index % 2); self.metrics[binding] = metric
        sensor_layout.addLayout(metrics); sensor_layout.addStretch(); output.setMaximumHeight(390); sensors.setMaximumHeight(390); body.addWidget(sensors, 2); outer.addLayout(body)

        recent = QHBoxLayout(); recent.setSpacing(12); self.recent_media = self._recent_card("Recent Media", owner.open_library); self.recent_themes = self._recent_card("Recent Sensor Themes", owner.open_theme_gallery); recent.addWidget(self.recent_media, 1); recent.addWidget(self.recent_themes, 1); outer.addLayout(recent, 1)
        self.timer = QTimer(self); self.timer.setInterval(750); self.timer.timeout.connect(self.refresh); self.timer.start(); QTimer.singleShot(0, self.refresh)

    def _recent_card(self, title: str, callback: Callable) -> OniCard:
        card = OniCard(); card.setMinimumHeight(245); card.setMaximumHeight(330); layout = QVBoxLayout(card); layout.setContentsMargins(18, 15, 18, 16); layout.setSpacing(9); heading_row = QHBoxLayout(); heading = QLabel(title); heading.setObjectName("recentTitle"); view = QPushButton("View All"); view.setObjectName("viewAllButton"); view.clicked.connect(callback); heading_row.addWidget(heading); heading_row.addStretch(); heading_row.addWidget(view); layout.addLayout(heading_row)
        stack = QStackedWidget(); stack.setObjectName("recentStack")
        empty = QWidget(); empty.setObjectName("recentEmpty"); empty_layout = QVBoxLayout(empty); empty_layout.setContentsMargins(16, 6, 16, 12); empty_layout.setSpacing(7); empty_layout.addStretch()
        art = QLabel(); art.setObjectName("emptyArtwork"); art.setAlignment(Qt.AlignCenter); asset = "empty-media.jpg" if title == "Recent Media" else "empty-sensor-themes.jpg"; pixmap = QPixmap(str(_ui_asset(asset)))
        if not pixmap.isNull(): art.setPixmap(pixmap.scaled(180, 94, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        art.setFixedHeight(96); empty_layout.addWidget(art)
        empty_title = QLabel("No recent media" if title == "Recent Media" else "No sensor themes yet"); empty_title.setObjectName("emptyTitle"); empty_title.setAlignment(Qt.AlignCenter); empty_layout.addWidget(empty_title)
        empty_detail = QLabel("Import an image, video or GIF to begin." if title == "Recent Media" else "Create or import a dashboard theme."); empty_detail.setObjectName("muted"); empty_detail.setAlignment(Qt.AlignCenter); empty_layout.addWidget(empty_detail)
        action_row = QHBoxLayout(); action_row.addStretch(); action = QPushButton("Import Media" if title == "Recent Media" else "Create / Import"); action.setObjectName("homeSecondaryAction"); action.clicked.connect(callback); action_row.addWidget(action); action_row.addStretch(); empty_layout.addLayout(action_row); empty_layout.addStretch()
        listing = QListWidget(); listing.setObjectName("recentStrip"); listing.setViewMode(QListWidget.IconMode); listing.setMovement(QListWidget.Static); listing.setResizeMode(QListWidget.Adjust); listing.setIconSize(QSize(150, 72)); listing.setGridSize(QSize(170, 112)); listing.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded); listing.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        stack.addWidget(empty); stack.addWidget(listing); layout.addWidget(stack, 1); card.listing = listing; card.empty = empty; card.stack = stack; card.empty_artwork_loaded = not pixmap.isNull(); return card

    def _clear_layout(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0); widget = item.widget()
            if widget: widget.deleteLater()

    def _select_display(self, device_id: str) -> None:
        if device_id in self.owner.card_by_id: self.selected_device_id = device_id
        self._refresh_tabs(); self._refresh_preview()

    def _refresh_tabs(self) -> None:
        self._clear_layout(self.display_tabs)
        for card in self.owner.cards:
            definition = self.owner._definition_for_card(card); button = QPushButton(definition.model); button.setCheckable(True); button.setChecked(card.device_id == self.selected_device_id); button.clicked.connect(lambda _checked=False, value=card.device_id: self._select_display(value)); self.display_tabs.addWidget(button)

    def _refresh_displays(self) -> None:
        signature = tuple((getattr(card, "physical_id", card.device_id), card.device_id, card.connection.text()) for card in self.owner.cards)
        if signature == self._card_signature: return
        self._card_signature = signature; self._clear_layout(self.displays_grid)
        if not self.owner.cards:
            self.displays_grid.addWidget(OniEmptyState("No LCD Connected", "Connect a reviewed Thermalright LCD, then scan again.", "Scan for Displays", self.owner.scan_for_displays), 0, 0); self.selected_device_id = ""; self._refresh_tabs(); return
        if self.selected_device_id not in self.owner.card_by_id: self.selected_device_id = self.owner.cards[0].device_id
        for index, card in enumerate(self.owner.cards):
            definition = self.owner._definition_for_card(card); tile = OniCard(role="device"); row = QHBoxLayout(tile); row.setContentsMargins(14, 11, 13, 11); row.setSpacing(11); indicator=QLabel("●"); indicator.setObjectName("deviceStatusDot" if card.hardware_sender.enabled else "deviceStatusDotLocked"); indicator.setAlignment(Qt.AlignTop|Qt.AlignHCenter); indicator.setFixedWidth(16); row.addWidget(indicator); text = QVBoxLayout(); text.setSpacing(3); name = QLabel(definition.model); name.setObjectName("deviceTileTitle"); status = QLabel(card.connection.text()); status.setObjectName("deviceStatusText"); details = QLabel(f"{definition.encoded_size[0]} × {definition.encoded_size[1]}"); details.setObjectName("deviceResolution"); text.addWidget(name); text.addWidget(status); text.addWidget(details); row.addLayout(text, 1); open_button = QPushButton("Manage"); open_button.setObjectName("deviceAction"); open_button.clicked.connect(self.displayWorkspaceRequested); row.addWidget(open_button); self.displays_grid.addWidget(tile, index, 0)
        self._refresh_tabs()

    def _refresh_preview(self) -> None:
        card = self.owner.card_by_id.get(self.selected_device_id)
        if card is None:
            self.preview.clear(); self.preview_stack.setCurrentWidget(self.output_empty); self.manage_output.hide(); self.preview_status.setText("No active display"); return
        pixmap = card.preview.pixmap()
        if pixmap and not pixmap.isNull():
            available=self.preview_stack.contentsRect().size(); aspect=card.size_target[0]/max(1,card.size_target[1]); width=max(1,min(available.width(),round(available.height()*aspect))); height=max(1,round(width/aspect))
            if height>available.height():height=max(1,available.height());width=max(1,round(height*aspect))
            target=QSize(width,height); key = pixmap.cacheKey()
            if key != self._preview_key or target != self._preview_size:
                self._preview_key = key; self._preview_size = target; self.preview.setFixedSize(target); self.preview.setPixmap(pixmap.scaled(target, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.preview_stack.setCurrentWidget(self.preview_surface); self.manage_output.show()
        else:
            self.preview.setPixmap(QPixmap()); self.preview_stack.setCurrentWidget(self.output_empty); self.manage_output.hide()
        mode = card.output_ownership.lease().mode.value.replace("_", " ").title(); self.preview_status.setText(f"{mode} · {card.actual_fps():.1f} FPS · {card.connection.text()}")

    def resizeEvent(self,event) -> None:
        super().resizeEvent(event); QTimer.singleShot(0,self._refresh_preview)

    def _refresh_sensors(self) -> None:
        try: values = self.owner.monitor_service.poll().values
        except Exception: values = ()
        resolver = SensorBindingResolver()
        for binding, metric in self.metrics.items():
            resolved = resolver.resolve(binding, values)
            if resolved.available:
                unit = resolved.unit or ("%" if binding.endswith("usage") else "")
                try: value = f"{float(resolved.value):.0f}{unit}"
                except (TypeError, ValueError): value = f"{resolved.value}{unit}"
            else: value = "—"
            metric.value.setText(value)

    def _refresh_recent(self) -> None:
        media = [Path(value) for value in self.owner.settings.media_library if Path(value).is_file()][:4]
        try: themes = (self.owner._sensor_theme_store().list_user() + self.owner._sensor_theme_store().list_builtin())[:4]
        except Exception: themes = []
        signature = (tuple((str(path), path.stat().st_mtime_ns) for path in media), tuple((item.theme.id, item.theme.name) for item in themes), tuple(sorted(self.owner.settings.sensor_theme_ids.items())))
        if signature == self._recent_signature: return
        self._recent_signature = signature; self.recent_media.listing.clear(); self.recent_themes.listing.clear()
        for path in media:
            item = QListWidgetItem(path.name); pixmap = QPixmap(str(path))
            if not pixmap.isNull(): item.setIcon(QIcon(pixmap.scaled(150, 72, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)))
            item.setToolTip(str(path)); self.recent_media.listing.addItem(item)
        self.recent_media.stack.setCurrentWidget(self.recent_media.listing if media else self.recent_media.empty)
        active_ids = set(self.owner.settings.sensor_theme_ids.values())
        for stored in themes:
            label = stored.theme.name + ("  ·  Active" if stored.theme.id in active_ids else ""); item = QListWidgetItem(label)
            try:
                image = SensorThemeRenderer(stored.theme, stored.root).render(SAMPLE_SENSOR_VALUES, SAMPLE_HISTORY); pixmap = _image_to_pixmap(image); image.close(); item.setIcon(QIcon(pixmap.scaled(150, 72, Qt.KeepAspectRatio, Qt.SmoothTransformation)))
            except Exception: pass
            self.recent_themes.listing.addItem(item)
        self.recent_themes.stack.setCurrentWidget(self.recent_themes.listing if themes else self.recent_themes.empty)
        if not themes: self.recent_themes.listing.addItem("Create or import a Sensor Theme")

    def refresh(self) -> None:
        self._refresh_displays(); self._refresh_preview(); self._refresh_sensors(); self._refresh_recent()


class OniMediaLibraryPage(QWidget):
    def __init__(self, owner, parent=None) -> None:
        super().__init__(parent); self.owner = owner; outer = QVBoxLayout(self); outer.setContentsMargins(18, 16, 18, 18); outer.setSpacing(12)
        header = OniPageHeader("Media Library", "Images, video and GIF assets for every connected display."); header.add_action("Add Media", self.add_media, primary=True); outer.addWidget(header)
        tools = QHBoxLayout(); self.search = QLineEdit(); self.search.setPlaceholderText("Search media…"); self.search.setClearButtonEnabled(True); self.filter = QComboBox(); self.filter.addItems(("All", "Images", "Video", "GIF")); tools.addWidget(self.search, 1); tools.addWidget(self.filter); outer.addLayout(tools)
        self.list = OniMediaGrid(); self.list.setObjectName("assetGrid"); self.list.setViewMode(QListWidget.IconMode); self.list.setResizeMode(QListWidget.Adjust); self.list.setMovement(QListWidget.Static); self.list.setSelectionMode(QAbstractItemView.SingleSelection); self.list.setIconSize(QSize(220, 110)); self.list.setGridSize(QSize(245, 175)); self.list.setSpacing(8); self.list.setAcceptDrops(True); self.list.filesDropped.connect(self.add_dropped)
        self.content = QStackedWidget(); self.empty = OniEmptyState("No Media Yet", "Drop images, videos or GIFs here, or use Add Media.", "Add Media", self.add_media); self.content.addWidget(self.empty); self.content.addWidget(self.list); outer.addWidget(self.content, 1)
        row = QHBoxLayout(); self.target = QComboBox(); row.addWidget(QLabel("Target display")); row.addWidget(self.target); preview = QPushButton("Preview / Use"); remove = QPushButton("Remove Reference"); remove.setObjectName("dangerButton"); preview.clicked.connect(self.use_selected); remove.clicked.connect(self.remove_selected); row.addStretch(); row.addWidget(preview); row.addWidget(remove); outer.addLayout(row)
        self.search.textChanged.connect(self.refresh); self.filter.currentTextChanged.connect(self.refresh); QTimer.singleShot(0, self.refresh)

    def refresh(self, *_args) -> None:
        self.target.clear()
        for card in self.owner.cards: self.target.addItem(self.owner._definition_for_card(card).model, card.device_id)
        needle = self.search.text().casefold(); selected_filter = self.filter.currentText(); self.list.clear()
        for raw in self.owner.settings.media_library:
            path = Path(raw); kind = detect_media_kind(path) if path.is_file() else None
            if kind is None or (needle and needle not in path.name.casefold()): continue
            if selected_filter == "Images" and kind is not MediaKind.PHOTO or selected_filter == "Video" and kind is not MediaKind.VIDEO or selected_filter == "GIF" and kind is not MediaKind.GIF: continue
            item = QListWidgetItem(f"{path.name}\n{kind.value}"); item.setData(Qt.UserRole, str(path)); pixmap = QPixmap(str(path))
            if not pixmap.isNull(): item.setIcon(QIcon(pixmap.scaled(220, 110, Qt.KeepAspectRatio, Qt.SmoothTransformation)))
            item.setToolTip(str(path)); self.list.addItem(item)
        self.content.setCurrentWidget(self.list if self.list.count() else self.empty)

    def add_media(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Add media", self.owner._media_dialog_directory(), media_filter())
        for value in files:
            if detect_media_kind(value) is not None and value not in self.owner.settings.media_library: self.owner.settings.media_library.append(value)
        if files: self.owner._remember_media_directory(Path(files[0]).parent); self.owner.store.save(self.owner.settings); self.refresh()

    def add_dropped(self, paths) -> None:
        changed = False
        for path in paths:
            if path.is_file() and detect_media_kind(path) is not None and str(path) not in self.owner.settings.media_library: self.owner.settings.media_library.append(str(path)); changed = True
        if changed: self.owner.store.save(self.owner.settings); self.refresh()

    def use_selected(self) -> bool:
        item = self.list.currentItem(); card = self.owner.card_by_id.get(self.target.currentData())
        if item is None or card is None: return False
        return bool(card.load(Path(item.data(Qt.UserRole))))

    def remove_selected(self) -> None:
        item = self.list.currentItem()
        if item and item.data(Qt.UserRole) in self.owner.settings.media_library:
            self.owner.settings.media_library.remove(item.data(Qt.UserRole)); self.owner.store.save(self.owner.settings); self.refresh()


class OniSensorThemesBrowser(QWidget):
    editRequested = Signal(str)
    createRequested = Signal()

    def __init__(self, owner, store: SensorThemeStore, parent=None) -> None:
        super().__init__(parent); self.owner = owner; self.store = store; outer = QVBoxLayout(self); outer.setContentsMargins(18, 16, 18, 18); outer.setSpacing(12)
        header = OniPageHeader("Sensor Themes", "Browse, deploy and customize exact-pixel ONI layouts."); header.add_action("Import", self.import_theme); header.add_action("Create Theme", self.createRequested, primary=True); outer.addWidget(header)
        tools = QHBoxLayout(); self.search = QLineEdit(); self.search.setPlaceholderText("Search themes…"); self.search.setClearButtonEnabled(True); self.origin = QComboBox(); self.origin.addItems(("All themes", "Built-in", "Custom")); self.target = QComboBox(); tools.addWidget(self.search, 1); tools.addWidget(self.origin); tools.addWidget(self.target); outer.addLayout(tools)
        self.list = QListWidget(); self.list.setObjectName("themeGrid"); self.list.setViewMode(QListWidget.IconMode); self.list.setResizeMode(QListWidget.Adjust); self.list.setMovement(QListWidget.Static); self.list.setIconSize(QSize(310, 95)); self.list.setGridSize(QSize(335, 165)); self.list.setSpacing(9)
        self.content = QStackedWidget(); self.empty = OniCard(); empty_layout = QVBoxLayout(self.empty); empty_layout.addStretch(); empty_title = QLabel("No Sensor Themes Yet"); empty_title.setObjectName("emptyTitle"); empty_title.setAlignment(Qt.AlignCenter); empty_detail = QLabel("Create a theme or import one to get started."); empty_detail.setObjectName("muted"); empty_detail.setAlignment(Qt.AlignCenter); empty_actions = QHBoxLayout(); empty_actions.addStretch(); create_empty = QPushButton("Create Theme"); create_empty.setObjectName("primaryButton"); import_empty = QPushButton("Import Theme"); create_empty.clicked.connect(self.createRequested); import_empty.clicked.connect(self.import_theme); empty_actions.addWidget(create_empty); empty_actions.addWidget(import_empty); empty_actions.addStretch(); empty_layout.addWidget(empty_title); empty_layout.addWidget(empty_detail); empty_layout.addLayout(empty_actions); empty_layout.addStretch(); self.content.addWidget(self.empty); self.content.addWidget(self.list); outer.addWidget(self.content, 1)
        actions = QHBoxLayout(); edit = QPushButton("Edit"); duplicate = QPushButton("Duplicate"); rename = QPushButton("Rename"); export = QPushButton("Export"); delete = QPushButton("Delete"); delete.setObjectName("dangerButton"); apply_button = QPushButton("Apply to Display"); apply_button.setObjectName("primaryButton"); actions.addStretch()
        for button in (edit, duplicate, rename, export, delete, apply_button): actions.addWidget(button)
        outer.addLayout(actions); edit.clicked.connect(self.edit); duplicate.clicked.connect(self.duplicate); rename.clicked.connect(self.rename); export.clicked.connect(self.export); delete.clicked.connect(self.delete); apply_button.clicked.connect(self.apply); self.list.itemDoubleClicked.connect(lambda _item: self.edit()); self.search.textChanged.connect(self.refresh); self.origin.currentTextChanged.connect(self.refresh); QTimer.singleShot(0, self.refresh)

    def selected(self):
        item = self.list.currentItem()
        if item is None: return None
        try: return self.store.get(item.data(Qt.UserRole))
        except Exception: return None

    def refresh(self, *_args) -> None:
        current = self.list.currentItem().data(Qt.UserRole) if self.list.currentItem() else ""; self.list.clear(); self.target.clear()
        for card in self.owner.cards: self.target.addItem(self.owner._definition_for_card(card).model, card.device_id)
        needle = self.search.text().casefold(); origin = self.origin.currentText(); renderer = SensorThemeRenderer()
        for stored in self.store.list_builtin() + self.store.list_user():
            if needle and needle not in stored.theme.name.casefold(): continue
            if origin == "Built-in" and not stored.built_in or origin == "Custom" and stored.built_in: continue
            try: image = renderer.render(stored.theme, SAMPLE_SENSOR_VALUES, history=SAMPLE_HISTORY, asset_root=stored.root, output_size=(310, 95)); icon = QIcon(_image_to_pixmap(image))
            except Exception: icon = QIcon()
            canvas = stored.theme.canvas; label = f"{stored.theme.name}\n{canvas.width} × {canvas.height} · {'Built-in' if stored.built_in else 'Custom'}"; item = QListWidgetItem(icon, label); item.setData(Qt.UserRole, stored.theme.id); self.list.addItem(item)
            if stored.theme.id == current: self.list.setCurrentItem(item)
        if self.list.count() and self.list.currentRow() < 0: self.list.setCurrentRow(0)
        self.content.setCurrentWidget(self.list if self.list.count() else self.empty)

    def edit(self) -> None:
        stored = self.selected()
        if stored: self.editRequested.emit(stored.theme.id)

    def duplicate(self) -> None:
        stored = self.selected()
        if not stored: return
        name, ok = QInputDialog.getText(self, "Duplicate Sensor Theme", "New name:", text=f"{stored.theme.name} Copy")
        if ok and name.strip(): self.store.duplicate(stored.theme.id, name.strip()); self.refresh()

    def rename(self) -> None:
        stored = self.selected()
        if not stored: return
        if stored.built_in: QMessageBox.information(self, "Built-in theme", "Duplicate a built-in theme before renaming it."); return
        name, ok = QInputDialog.getText(self, "Rename Sensor Theme", "Name:", text=stored.theme.name)
        if ok and name.strip(): self.store.rename(stored.theme.id, name.strip()); self.refresh()

    def export(self) -> None:
        stored = self.selected()
        if not stored: return
        path, _ = QFileDialog.getSaveFileName(self, "Export Sensor Theme", f"{stored.theme.id}.oni-theme", "ONI Sensor Theme (*.oni-theme)")
        if not path: return
        preview = SensorThemeRenderer().thumbnail(stored.theme, SAMPLE_SENSOR_VALUES, asset_root=stored.root); self.store.export_package(stored.theme.id, Path(path), preview=preview)

    def delete(self) -> None:
        stored = self.selected()
        if not stored: return
        if stored.built_in: QMessageBox.information(self, "Built-in theme", "Built-in themes cannot be deleted."); return
        if QMessageBox.question(self, "Delete Sensor Theme", f"Delete '{stored.theme.name}'?", QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            self.store.delete(stored.theme.id); self.refresh()

    def apply(self) -> None:
        stored = self.selected(); device_id = self.target.currentData()
        if stored and device_id: self.owner.apply_sensor_theme(stored.theme, stored.root, (device_id,), 2)

    def import_theme(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import Sensor Theme", "", "ONI Sensor Theme (*.oni-theme)")
        if not path: return
        try: self.store.import_package(Path(path)); self.refresh()
        except Exception as exc: QMessageBox.warning(self, "Import failed", str(exc))


class OniSensorThemesWorkspace(QWidget):
    def __init__(self, owner, store: SensorThemeStore, parent=None) -> None:
        super().__init__(parent); self.owner = owner; self.store = store; layout = QVBoxLayout(self); layout.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget(); self.browser = OniSensorThemesBrowser(owner, store); live_values = lambda: owner.monitor_service.poll() if hasattr(owner, "monitor_service") else {}
        self.editor = SensorThemeEditorPage(store, self.stack, live_value_provider=live_values, apply_handler=owner.apply_sensor_theme, deployment_handler=owner.sensor_theme_document_changed)
        back = QPushButton("← Sensor Themes"); back.setObjectName("studioBackButton"); back.clicked.connect(self.show_browser); self.editor.layout().insertWidget(0, back)
        self.stack.addWidget(self.browser); self.stack.addWidget(self.editor); layout.addWidget(self.stack)
        self.browser.editRequested.connect(self.open_editor); self.browser.createRequested.connect(self.new_theme)

    def show_browser(self) -> bool:
        if self.stack.currentWidget() is self.editor and not self.editor.request_leave(): return False
        self.browser.refresh(); self.stack.setCurrentWidget(self.browser); return True

    def open_editor(self, theme_id: str) -> bool:
        if theme_id and not self.editor.load_theme(theme_id): return False
        self.stack.setCurrentWidget(self.editor); QTimer.singleShot(0, self.editor.fit_canvas); return True

    def new_theme(self) -> None:
        self.stack.setCurrentWidget(self.editor); self.editor.new_theme()

    def request_leave(self) -> bool:
        return self.stack.currentWidget() is not self.editor or self.editor.request_leave()


class OniProfilesPage(QWidget):
    def __init__(self, owner, parent=None) -> None:
        super().__init__(parent); self.owner = owner; outer = QVBoxLayout(self); outer.setContentsMargins(30, 24, 30, 30); outer.setSpacing(18)
        header = OniPageHeader("Profiles", "Saved output state for media, themes, brightness and displays."); header.add_action("Manage / Import / Export", owner.open_profile_manager, primary=True); outer.addWidget(header)
        summary = OniCard(role="metric"); summary_layout = QHBoxLayout(summary); summary_layout.setContentsMargins(20, 14, 20, 14); summary_layout.setSpacing(18)
        summary_text = QVBoxLayout(); summary_text.setSpacing(3); summary_title = QLabel("Output profiles"); summary_title.setObjectName("sectionTitle"); summary_detail = QLabel("Keep display-specific media, output mode and brightness together."); summary_detail.setObjectName("sectionDescription"); summary_text.addWidget(summary_title); summary_text.addWidget(summary_detail); summary_layout.addLayout(summary_text); summary_layout.addStretch(); self.profile_count = QLabel("0 saved"); self.profile_count.setObjectName("statusPill"); summary_layout.addWidget(self.profile_count); outer.addWidget(summary)
        list_card = OniCard(); list_layout = QVBoxLayout(list_card); list_layout.setContentsMargins(18, 16, 18, 18); list_layout.setSpacing(12); list_title = QLabel("Saved profiles"); list_title.setObjectName("cardTitle"); list_layout.addWidget(list_title)
        self.list = QListWidget(); self.list.setObjectName("profileList"); self.list.setMinimumHeight(340); list_layout.addWidget(self.list, 1); row = QHBoxLayout(); hint = QLabel("Select a profile to apply it to its saved displays."); hint.setObjectName("sectionDescription"); row.addWidget(hint); row.addStretch(); apply_button = QPushButton("Apply Selected"); apply_button.setObjectName("primaryButton"); apply_button.clicked.connect(self.apply); row.addWidget(apply_button); list_layout.addLayout(row); outer.addWidget(list_card, 1); outer.addStretch(); QTimer.singleShot(0, self.refresh)

    def refresh(self) -> None:
        self.list.clear()
        for name, displays in sorted(self.owner.settings.profiles.items()):
            details = []
            for device_id, profile in displays.items(): details.append(f"{device_id} · {profile.output_mode.replace('_', ' ').title()} · {profile.brightness}%")
            item = QListWidgetItem(f"{name}{'  ·  ACTIVE' if name == self.owner.settings.active_profile else ''}\n" + "\n".join(details)); item.setData(Qt.UserRole, name); self.list.addItem(item)
        self.profile_count.setText(f"{self.list.count()} saved")
        if not self.list.count():
            item = QListWidgetItem("No saved profiles yet\nSave a display profile from Display Studio to see it here."); item.setFlags(Qt.NoItemFlags); self.list.addItem(item)

    def apply(self) -> None:
        item = self.list.currentItem()
        if not item: return
        name = item.data(Qt.UserRole); self.owner.settings.active_profile = name
        for device_id, card in self.owner.card_by_id.items():
            profile = self.owner.settings.profiles.get(name, {}).get(device_id)
            if profile: card.apply_profile(profile)
        self.owner.store.save(self.owner.settings); self.refresh()


class OniHardwareMonitorPage(QWidget):
    def __init__(self, owner, parent=None) -> None:
        super().__init__(parent); self.owner = owner; outer = QVBoxLayout(self); outer.setContentsMargins(30, 24, 30, 30); outer.setSpacing(18)
        header = OniPageHeader("Hardware Monitor", "Named sensor layouts, live bindings and media overlays."); header.add_action("Open Designer", owner.open_monitor_designer, primary=True); outer.addWidget(header)
        selection = OniCard(role="metric"); controls = QHBoxLayout(selection); controls.setContentsMargins(18, 14, 18, 14); controls.setSpacing(12); display_label = QLabel("TARGET DISPLAY"); display_label.setObjectName("fieldLabel"); self.target = QComboBox(); self.target.setMinimumWidth(250); layout_label = QLabel("SAVED LAYOUT"); layout_label.setObjectName("fieldLabel"); self.layout = QComboBox(); self.layout.setMinimumWidth(310); refresh = QPushButton("Refresh Layouts"); refresh.setObjectName("secondaryButton"); controls.addWidget(display_label); controls.addWidget(self.target); controls.addSpacing(14); controls.addWidget(layout_label); controls.addWidget(self.layout, 1); controls.addWidget(refresh); outer.addWidget(selection)
        preview_card = OniCard(); preview_layout = QVBoxLayout(preview_card); preview_layout.setContentsMargins(18, 16, 18, 18); preview_layout.setSpacing(12); title_row = QHBoxLayout(); preview_title = QLabel("Live layout preview"); preview_title.setObjectName("cardTitle"); title_row.addWidget(preview_title); title_row.addStretch(); self.status_badge = QLabel("IDLE"); self.status_badge.setObjectName("statusPill"); title_row.addWidget(self.status_badge); preview_layout.addLayout(title_row)
        self.preview = QLabel("No saved layouts\n\nOpen Designer to create a Hardware Monitor layout."); self.preview.setObjectName("monitorPreview"); self.preview.setAlignment(Qt.AlignCenter); self.preview.setMinimumHeight(310); self.preview.setMaximumHeight(520); preview_layout.addWidget(self.preview, 1)
        self.status = QLabel("Choose a display and a saved layout. Output uses the existing display session and shared sensor service."); self.status.setObjectName("inlineNotice"); self.status.setWordWrap(True); preview_layout.addWidget(self.status)
        row = QHBoxLayout(); self.play_button = QPushButton("Play / Apply"); self.overlay_button = QPushButton("Sensor + Media"); stop = QPushButton("Stop"); self.play_button.setObjectName("primaryButton"); self.overlay_button.setObjectName("secondaryButton"); stop.setObjectName("dangerButton"); row.addStretch(); row.addWidget(self.play_button); row.addWidget(self.overlay_button); row.addWidget(stop); preview_layout.addLayout(row); outer.addWidget(preview_card, 1); outer.addStretch()
        refresh.clicked.connect(self.refresh); self.target.currentIndexChanged.connect(self.refresh_layouts); self.layout.currentTextChanged.connect(self.render_preview); self.play_button.clicked.connect(self.play); self.overlay_button.clicked.connect(self.overlay); stop.clicked.connect(self.stop); QTimer.singleShot(0, self.refresh)

    def refresh(self, *_args) -> None:
        current = self.target.currentData(); self.target.blockSignals(True); self.target.clear()
        for card in self.owner.cards: self.target.addItem(self.owner._definition_for_card(card).model, card.device_id)
        index = self.target.findData(current); self.target.setCurrentIndex(max(0, index)); self.target.blockSignals(False); self.refresh_layouts()

    def refresh_layouts(self, *_args) -> None:
        device_id = self.target.currentData(); self.layout.clear()
        names = sorted(set(self.owner._monitor_layout_names(device_id))) if device_id else []
        self.layout.addItems(names); self.layout.setPlaceholderText("No saved layouts"); self.play_button.setEnabled(bool(names)); self.overlay_button.setEnabled(bool(names)); self.render_preview()

    def current_layout(self):
        device_id = self.target.currentData()
        if not device_id and self.target.count(): device_id = self.target.itemData(0)
        name = self.layout.currentText() or (self.layout.itemText(0) if self.layout.count() else "")
        return self.owner._monitor_layout_by_name(device_id, name) if device_id and name else None

    def render_preview(self, *_args) -> None:
        layout = self.current_layout()
        if layout is None: self.preview.setPixmap(QPixmap()); self.preview.setText("No saved layouts\n\nOpen Designer to create and save a Hardware Monitor layout."); self.status.setText("No layout is selected. Physical display output remains unchanged."); self.status_badge.setText("IDLE"); return
        try:
            image = self.owner._monitor_renderer_preview(layout)
            try: pixmap = _image_to_pixmap(image)
            finally: image.close()
            self.preview.setPixmap(pixmap.scaled(self.preview.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)); self.status.setText(f"{self.layout.currentText()} · preview uses live cached sensor values"); self.status_badge.setText("READY")
        except Exception as exc: self.preview.setPixmap(QPixmap()); self.preview.setText(f"Preview unavailable\n\n{exc}"); self.status.setText("The physical output was not changed."); self.status_badge.setText("UNAVAILABLE")

    def play(self) -> None:
        layout = self.current_layout()
        if layout: self.owner.start_monitor_layout(self.target.currentData(), layout)

    def overlay(self) -> None:
        layout = self.current_layout()
        if layout: self.owner.start_monitor_overlay(self.target.currentData(), layout)

    def stop(self) -> None:
        if self.target.currentData(): self.owner.stop_monitor_layout(self.target.currentData())


class OniPerformancePage(QWidget):
    def __init__(self, owner, parent=None) -> None:
        super().__init__(parent); self.owner = owner; outer = QVBoxLayout(self); outer.setContentsMargins(30, 24, 30, 30); outer.setSpacing(18)
        header = OniPageHeader("Performance", "Live bounded runtime metrics — no decorative polling stack."); outer.addWidget(header)
        controls = OniCard(role="metric"); row = QHBoxLayout(controls); row.setContentsMargins(18, 14, 18, 14); label_group = QVBoxLayout(); label_group.setSpacing(3); profile_title = QLabel("Resource profile"); profile_title.setObjectName("sectionTitle"); profile_hint = QLabel("Changes UI and preview policy without changing LCD transport."); profile_hint.setObjectName("sectionDescription"); label_group.addWidget(profile_title); label_group.addWidget(profile_hint); row.addLayout(label_group); row.addStretch(); self.mode = QComboBox(); self.mode.setMinimumWidth(250); self.mode.addItems(MODES); self.mode.setCurrentText(owner.settings.performance_mode); self.mode.currentTextChanged.connect(owner.apply_resource_mode); row.addWidget(self.mode); outer.addWidget(controls)
        metrics_card = OniCard(); metrics_layout = QVBoxLayout(metrics_card); metrics_layout.setContentsMargins(18, 16, 18, 18); metrics_layout.setSpacing(12); metrics_title = QLabel("Runtime overview"); metrics_title.setObjectName("cardTitle"); metrics_layout.addWidget(metrics_title); self.grid = QGridLayout(); self.grid.setSpacing(10); self.metrics = {}
        for index, key in enumerate(("CPU", "Memory", "Active sessions", "Workers", "Decoders", "Timers", "Preview FPS", "LCD FPS")):
            metric = OniMetricCard(key); self.grid.addWidget(metric, index // 4, index % 4); self.metrics[key] = metric
        metrics_layout.addLayout(self.grid); outer.addWidget(metrics_card)
        details = QHBoxLayout(); details.setSpacing(12); policy_card = OniCard(); policy_layout = QVBoxLayout(policy_card); policy_layout.setContentsMargins(18, 16, 18, 18); policy_title = QLabel("Active policy"); policy_title.setObjectName("cardTitle"); policy_layout.addWidget(policy_title); self.detail = QLabel(); self.detail.setObjectName("sectionDescription"); self.detail.setWordWrap(True); policy_layout.addWidget(self.detail); policy_layout.addStretch(); details.addWidget(policy_card, 1)
        displays_card = OniCard(); displays_layout = QVBoxLayout(displays_card); displays_layout.setContentsMargins(18, 16, 18, 18); displays_title = QLabel("Per-display runtime"); displays_title.setObjectName("cardTitle"); displays_layout.addWidget(displays_title); self.displays = QLabel(); self.displays.setObjectName("sectionDescription"); self.displays.setWordWrap(True); self.displays.setAlignment(Qt.AlignLeft | Qt.AlignTop); displays_layout.addWidget(self.displays); displays_layout.addStretch(); details.addWidget(displays_card, 1); outer.addLayout(details); outer.addStretch()
        self.timer = QTimer(self); self.timer.setInterval(2000); self.timer.timeout.connect(self.refresh); self.timer.start(); QTimer.singleShot(0, self.refresh)

    def refresh(self) -> None:
        data = self.owner.runtime_diagnostics(); values = {"CPU": f"{data['total_oni_cpu_percent_normalized']}%", "Memory": f"{data['total_oni_ram_mb']} MB", "Active sessions": str(data['active_display_sessions']), "Workers": str(data['active_playback_workers']), "Decoders": str(data['active_decoders']), "Timers": str(data['active_timers']), "Preview FPS": " / ".join(map(str, data['gui_preview_presented_fps'])) or "0", "LCD FPS": " / ".join(map(str, data['physical_lcd_completed_fps'])) or "0"}
        for key, value in values.items(): self.metrics[key].value.setText(value)
        mode = resource_mode(self.owner.settings.performance_mode); self.detail.setText(f"{mode.description}\nSensor refresh: {mode.sensor_interval_ms} ms · Diagnostics: {mode.diagnostics_interval_ms} ms")
        rows = []
        for card in self.owner.cards:
            definition = self.owner._definition_for_card(card); rows.append(f"{definition.model}  ·  {card.output_ownership.lease().mode.value.replace('_', ' ').title()}  ·  Preview {card.actual_fps():.1f} FPS  ·  Session {card.session.state.value}")
        self.displays.setText("\n".join(rows) if rows else "No active display sessions.")


class OniSettingsPage(QWidget):
    FIELDS = (("start_with_windows", "Start with Windows"), ("start_minimized", "Start minimized"), ("minimize_to_tray", "Minimize to tray"), ("restore_previous_media", "Restore previous media"), ("auto_reconnect", "Auto reconnect"), ("stale_frame_dropping", "Drop stale frames"), ("resume_playback", "Resume playback"), ("hardware_decode", "Hardware video decode"))
    def __init__(self, owner, parent=None) -> None:
        super().__init__(parent); self.owner = owner; outer = QVBoxLayout(self); outer.setContentsMargins(30, 24, 30, 30); outer.setSpacing(18)
        header = OniPageHeader("Settings", "General, startup, media, displays, sensors and performance."); header.add_action("Save Settings", self.save, primary=True); outer.addWidget(header)
        grid = QGridLayout(); grid.setHorizontalSpacing(14); grid.setVerticalSpacing(14); self.checks = {}
        groups = (("General & Startup", self.FIELDS[:5]), ("Media & Performance", self.FIELDS[5:]))
        for column, (title, fields) in enumerate(groups):
            card = OniCard(); layout = QVBoxLayout(card); layout.setContentsMargins(20, 18, 20, 20); layout.setSpacing(10); heading = QLabel(title); heading.setObjectName("cardTitle"); layout.addWidget(heading); description = QLabel("Choose how Oni starts and restores your workspace." if column == 0 else "Control playback recovery and decode behavior."); description.setObjectName("sectionDescription"); description.setWordWrap(True); layout.addWidget(description); layout.addSpacing(6)
            for field, label in fields:
                box = QCheckBox(label); box.setChecked(bool(getattr(owner.settings, field))); self.checks[field] = box; layout.addWidget(box)
            layout.addStretch(); grid.addWidget(card, 0, column)
        display_card = OniCard(); display_layout = QVBoxLayout(display_card); display_layout.setContentsMargins(20, 18, 20, 20); display_layout.setSpacing(10); heading = QLabel("Displays & Sensors"); heading.setObjectName("cardTitle"); display_layout.addWidget(heading); description = QLabel("Tune the central sensor snapshot cadence shared by all pages."); description.setObjectName("sectionDescription"); description.setWordWrap(True); display_layout.addWidget(description); self.sensor_interval = QComboBox(); self.sensor_interval.addItems(("250", "500", "1000", "2000")); self.sensor_interval.setCurrentText(str(owner.settings.sensor_interval_ms)); sensor_label = QLabel("SENSOR POLLING INTERVAL (MS)"); sensor_label.setObjectName("fieldLabel"); display_layout.addWidget(sensor_label); display_layout.addWidget(self.sensor_interval); display_layout.addStretch(); grid.addWidget(display_card, 1, 0)
        advanced_card = OniCard(); advanced = QVBoxLayout(advanced_card); advanced.setContentsMargins(20, 18, 20, 20); advanced.setSpacing(9); heading = QLabel("Defaults & Advanced"); heading.setObjectName("cardTitle"); advanced.addWidget(heading); description = QLabel("Defaults used for new media and window-close behavior."); description.setObjectName("sectionDescription"); description.setWordWrap(True); advanced.addWidget(description)
        self.close_behavior = QComboBox(); self.close_behavior.addItem("Minimize to tray", "minimize_to_tray"); self.close_behavior.addItem("Exit application", "exit_application"); self.close_behavior.setCurrentIndex(max(0, self.close_behavior.findData(owner.settings.close_button_behavior)))
        self.default_fps = QComboBox(); self.default_fps.addItems(("Auto", "1", "2", "5", "10", "15", "30")); self.default_fps.setCurrentText(owner.settings.default_fps)
        self.default_mode = QComboBox(); self.default_mode.addItems(("Fit", "Fill", "Center")); self.default_mode.setCurrentText(owner.settings.default_display_mode)
        for label_text, control in (("CLOSE BUTTON BEHAVIOR", self.close_behavior), ("DEFAULT OUTPUT FPS", self.default_fps), ("DEFAULT MEDIA FIT", self.default_mode)):
            label = QLabel(label_text); label.setObjectName("fieldLabel"); advanced.addWidget(label); advanced.addWidget(control)
        advanced.addStretch(); grid.addWidget(advanced_card, 1, 1); outer.addLayout(grid); outer.addStretch()

    def save(self) -> None:
        for field, box in self.checks.items(): setattr(self.owner.settings, field, box.isChecked())
        interval = int(self.sensor_interval.currentText()); self.owner.settings.close_button_behavior = self.close_behavior.currentData(); self.owner.settings.close_to_tray = self.owner.settings.close_button_behavior == "minimize_to_tray"; self.owner.settings.default_fps = self.default_fps.currentText(); self.owner.settings.default_display_mode = self.default_mode.currentText()
        self.owner.apply_resource_mode(self.owner.settings.performance_mode); self.owner.settings.sensor_interval_ms = interval; self.owner.monitor_service.minimum_interval = max(0.1, interval / 1000); self.owner.monitor_timer.setInterval(max(500, interval)); self.owner.store.save(self.owner.settings)


class OniDiagnosticsPage(QWidget):
    def __init__(self, owner, parent=None) -> None:
        super().__init__(parent); self.owner = owner; outer = QVBoxLayout(self); outer.setContentsMargins(30, 24, 30, 30); outer.setSpacing(18)
        header = OniPageHeader("Diagnostics", "Devices, sessions, workers, decoders, providers and application paths."); header.add_action("Open Logs", owner._open_logs); header.add_action("Refresh", self.refresh, primary=True); outer.addWidget(header)
        overview = OniCard(role="metric"); overview_layout = QHBoxLayout(overview); overview_layout.setContentsMargins(20, 14, 20, 14); overview_layout.setSpacing(12); state_dot = QLabel("●"); state_dot.setObjectName("diagnosticDot"); overview_layout.addWidget(state_dot); state_text = QVBoxLayout(); state_text.setSpacing(2); state_title = QLabel("Runtime snapshot"); state_title.setObjectName("sectionTitle"); state_detail = QLabel("Read-only application and display-session information."); state_detail.setObjectName("sectionDescription"); state_text.addWidget(state_title); state_text.addWidget(state_detail); overview_layout.addLayout(state_text); overview_layout.addStretch(); outer.addWidget(overview)
        summary_card = OniCard(); summary_layout = QVBoxLayout(summary_card); summary_layout.setContentsMargins(20, 18, 20, 20); summary_layout.setSpacing(12); summary_title = QLabel("System details"); summary_title.setObjectName("cardTitle"); summary_layout.addWidget(summary_title); self.summary = QLabel(); self.summary.setObjectName("diagnosticSummary"); self.summary.setWordWrap(True); self.summary.setAlignment(Qt.AlignLeft | Qt.AlignTop); self.summary.setTextInteractionFlags(Qt.TextSelectableByMouse); self.summary.setMinimumHeight(360); summary_layout.addWidget(self.summary, 1)
        copy = QPushButton("Copy Diagnostics"); copy.setObjectName("secondaryButton"); copy.clicked.connect(lambda: QApplication.clipboard().setText(self.summary.text())); row = QHBoxLayout(); row.addStretch(); row.addWidget(copy); summary_layout.addLayout(row); outer.addWidget(summary_card, 1); outer.addStretch(); QTimer.singleShot(0, self.refresh)

    def refresh(self) -> None:
        runtime = self.owner.runtime_diagnostics(); rows = [f"Application data: {self.owner.base}", f"Process: {runtime['pid']} · RAM {runtime['total_oni_ram_mb']} MB · Threads {runtime['process_tree_thread_count']}", f"Sessions: {runtime['active_display_sessions']} · Workers: {runtime['active_playback_workers']} · Decoders: {runtime['active_decoders']} · Timers: {runtime['active_timers']}"]
        for card in self.owner.cards:
            definition = self.owner._definition_for_card(card); rows.append(f"\n{definition.model}\n  Identity: {getattr(card, 'physical_id', card.device_id)}\n  Resolution: {definition.encoded_size[0]} × {definition.encoded_size[1]}\n  Session: {card.session.state.value} · Sender: {'enabled' if card.hardware_sender.enabled else 'disabled'}\n  Decoder: {'active' if card.scheduler else 'inactive'} · Error: {card.session.metrics.last_error or 'None'}")
        self.summary.setText("\n".join(rows))
