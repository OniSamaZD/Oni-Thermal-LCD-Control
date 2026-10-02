"""Startup-only ONI splash screen."""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QLabel,
    QVBoxLayout,
    QWidget,
)
from .themes import theme_tokens


class OniSplash(QWidget):
    """Borderless, non-blocking splash matching the ONI application palette."""

    def __init__(self, icon_path: Path):
        super().__init__(None, Qt.SplashScreen | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        app=QApplication.instance();tokens=theme_tokens(app.property("oniThemeName") if app is not None else "ONI Blue")
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(520, 300)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 22, 22, 22)
        panel = QFrame()
        panel.setObjectName("oniSplashPanel")
        panel.setStyleSheet(
            "QFrame#oniSplashPanel {"
            "background: qlineargradient(x1:0,y1:0,x2:1,y2:1,"
            f"stop:0 {tokens.app_background}, stop:0.55 {tokens.surface}, stop:1 {tokens.accent_subtle});"
            f"border: 1px solid {tokens.focus}; border-radius: 22px; }}"
        )
        shadow = QGraphicsDropShadowEffect(panel)
        shadow.setBlurRadius(42)
        shadow.setOffset(0, 0)
        shadow_color=QColor(tokens.accent_hover);shadow_color.setAlpha(115);shadow.setColor(shadow_color)
        panel.setGraphicsEffect(shadow)
        outer.addWidget(panel)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(44, 28, 44, 26)
        layout.setSpacing(5)

        mark = QLabel()
        mark.setAlignment(Qt.AlignCenter)
        mark.setFixedHeight(104)
        pixmap = QPixmap(str(icon_path))
        if not pixmap.isNull():
            mark.setPixmap(pixmap.scaled(96, 96, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        layout.addWidget(mark)

        title = QLabel("ONI")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(f"color:{tokens.text_primary};font:800 32pt 'Segoe UI Variable','Segoe UI';letter-spacing:4px;")
        layout.addWidget(title)

        subtitle = QLabel("Thermal LCD Control")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet(f"color:{tokens.focus};font:600 12pt 'Segoe UI Variable','Segoe UI';letter-spacing:1px;")
        layout.addWidget(subtitle)

        divider = QFrame()
        divider.setFixedHeight(1)
        divider.setStyleSheet(f"background-color:{tokens.divider};border:none;")
        layout.addSpacing(8)
        layout.addWidget(divider)
        layout.addSpacing(6)

        self.status = QLabel("Initializing displays…")
        self.status.setAlignment(Qt.AlignCenter)
        self.status.setStyleSheet(f"color:{tokens.text_muted};font:9pt 'Segoe UI Variable','Segoe UI';")
        layout.addWidget(self.status)

    def center_on_screen(self) -> None:
        screen = self.screen() or QApplication.primaryScreen()
        if screen is not None:
            self.move(screen.availableGeometry().center() - self.rect().center())

    def showEvent(self, event) -> None:
        self.center_on_screen()
        super().showEvent(event)

    def finish(self, _window: QWidget) -> None:
        self.close()

