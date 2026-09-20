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


class OniSplash(QWidget):
    """Borderless, non-blocking splash matching the ONI application palette."""

    def __init__(self, icon_path: Path):
        super().__init__(None, Qt.SplashScreen | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(520, 300)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 22, 22, 22)
        panel = QFrame()
        panel.setObjectName("oniSplashPanel")
        panel.setStyleSheet(
            "QFrame#oniSplashPanel {"
            "background: qlineargradient(x1:0,y1:0,x2:1,y2:1,"
            "stop:0 #03070d, stop:0.55 #071522, stop:1 #0b2940);"
            "border: 1px solid #2bc8ff; border-radius: 22px; }"
        )
        shadow = QGraphicsDropShadowEffect(panel)
        shadow.setBlurRadius(42)
        shadow.setOffset(0, 0)
        shadow.setColor(QColor(22, 184, 255, 115))
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
        title.setStyleSheet("color:#ffffff;font:800 32pt 'Segoe UI Variable','Segoe UI';letter-spacing:4px;")
        layout.addWidget(title)

        subtitle = QLabel("Thermal LCD Control")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet("color:#6fe7ff;font:600 12pt 'Segoe UI Variable','Segoe UI';letter-spacing:1px;")
        layout.addWidget(subtitle)

        divider = QFrame()
        divider.setFixedHeight(1)
        divider.setStyleSheet("background-color:#1b5877;border:none;")
        layout.addSpacing(8)
        layout.addWidget(divider)
        layout.addSpacing(6)

        self.status = QLabel("Initializing displays…")
        self.status.setAlignment(Qt.AlignCenter)
        self.status.setStyleSheet("color:#7892a8;font:9pt 'Segoe UI Variable','Segoe UI';")
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

