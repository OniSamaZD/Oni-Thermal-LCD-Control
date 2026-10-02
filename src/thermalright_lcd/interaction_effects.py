from __future__ import annotations

def interaction_stylesheet(enabled: bool, tokens=None) -> str:
    """Return state-only QSS; it never changes widget metrics or geometry."""
    if tokens is None:
        from .themes import theme_tokens
        tokens = theme_tokens("ONI Blue")
    common = f"""
QPushButton:focus, QToolButton:focus, QComboBox:focus, QLineEdit:focus,
QSpinBox:focus, QDoubleSpinBox:focus, QCheckBox:focus, QRadioButton:focus,
QAbstractItemView:focus {{ border: 2px solid {tokens.focus}; }}
QSlider:focus {{ border: 1px solid {tokens.focus}; border-radius: 5px; }}
QPushButton:pressed, QToolButton:pressed {{ background-color: {tokens.surface_pressed}; }}
QPushButton:disabled, QToolButton:disabled, QComboBox:disabled, QLineEdit:disabled,
QSpinBox:disabled, QDoubleSpinBox:disabled, QCheckBox:disabled {{
    color: {tokens.disabled_foreground};
    background-color: {tokens.disabled_background};
    border-color: {tokens.border_subtle};
}}
QCheckBox:checked {{ color: {tokens.text_primary}; }}
QCheckBox:focus {{ color: {tokens.text_primary}; }}
QAbstractItemView::item:selected {{ border: 1px solid {tokens.focus}; }}
"""
    if enabled:
        return common + f"""
QPushButton:hover, QToolButton:hover, QComboBox:hover, QLineEdit:hover,
QSpinBox:hover, QDoubleSpinBox:hover {{ border-color: {tokens.accent_hover}; }}
QAbstractItemView::item:hover {{ border-color: {tokens.focus}; }}
QSlider::handle:horizontal:hover {{ background: {tokens.focus}; border-color: {tokens.text_primary}; }}
QFrame#oniCard:hover {{ border-color: {tokens.accent_hover}; }}
"""
    return common + f"""
QPushButton:hover, QToolButton:hover, QComboBox:hover, QLineEdit:hover,
QSpinBox:hover, QDoubleSpinBox:hover {{ border-color: {tokens.border}; }}
QAbstractItemView::item:hover {{ border-color: {tokens.border}; }}
QSlider::handle:horizontal:hover {{ background: {tokens.slider_fill}; border-color: {tokens.focus}; }}
QFrame#oniCard:hover {{ border-color: {tokens.border}; }}
"""


def apply_interaction_effects(application, base_stylesheet: str, enabled: bool, theme_name="ONI Blue") -> None:
    """Apply the selected interaction policy immediately and without timers."""

    from .themes import compile_theme_stylesheet, normalize_theme_name, theme_tokens
    name = normalize_theme_name(theme_name)
    application.setProperty("oniEffectsEnabled", bool(enabled)); application.setProperty("oniThemeName", name)
    application.setStyleSheet(compile_theme_stylesheet(base_stylesheet, name) + interaction_stylesheet(bool(enabled), theme_tokens(name)))
