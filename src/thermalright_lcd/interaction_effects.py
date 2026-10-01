from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class InteractionTokens:
    """Small, theme-neutral state tokens for the application interaction layer."""

    focus: str = "#7ee7ff"
    hover_border: str = "#5a73c8"
    pressed_background: str = "#0a1022"
    disabled_text: str = "#68718d"


TOKENS = InteractionTokens()


def interaction_stylesheet(enabled: bool) -> str:
    """Return state-only QSS; it never changes widget metrics or geometry."""

    common = f"""
QPushButton:focus, QToolButton:focus, QComboBox:focus, QLineEdit:focus,
QSpinBox:focus, QDoubleSpinBox:focus, QCheckBox:focus, QRadioButton:focus,
QAbstractItemView:focus {{ border: 2px solid {TOKENS.focus}; }}
QSlider:focus {{ border: 1px solid {TOKENS.focus}; border-radius: 5px; }}
QPushButton:pressed, QToolButton:pressed {{ background-color: {TOKENS.pressed_background}; }}
QPushButton:disabled, QToolButton:disabled, QComboBox:disabled, QLineEdit:disabled,
QSpinBox:disabled, QDoubleSpinBox:disabled, QCheckBox:disabled {{
    color: {TOKENS.disabled_text};
    border-color: #2a3049;
}}
QCheckBox:checked {{ color: #ffffff; }}
QCheckBox:focus {{ color: #ffffff; }}
QAbstractItemView::item:selected {{ border: 1px solid {TOKENS.focus}; }}
"""
    if enabled:
        return common + f"""
QPushButton:hover, QToolButton:hover, QComboBox:hover, QLineEdit:hover,
QSpinBox:hover, QDoubleSpinBox:hover {{ border-color: {TOKENS.hover_border}; }}
QAbstractItemView::item:hover {{ border-color: {TOKENS.focus}; }}
QSlider::handle:horizontal:hover {{ background: #9cecff; border-color: #ffffff; }}
QFrame#oniCard:hover {{ border-color: #625fac; }}
"""
    return common + """
QPushButton:hover, QToolButton:hover, QComboBox:hover, QLineEdit:hover,
QSpinBox:hover, QDoubleSpinBox:hover { border-color: #3c466f; }
QAbstractItemView::item:hover { border-color: #435078; }
QSlider::handle:horizontal:hover { background: #6fcde9; border-color: #8de9ff; }
QFrame#oniCard:hover { border-color: #41486f; }
"""


def apply_interaction_effects(application, base_stylesheet: str, enabled: bool) -> None:
    """Apply the selected interaction policy immediately and without timers."""

    application.setProperty("oniEffectsEnabled", bool(enabled))
    application.setStyleSheet(base_stylesheet + interaction_stylesheet(bool(enabled)))
