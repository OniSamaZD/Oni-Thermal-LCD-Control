from __future__ import annotations

import colorsys
import re
from dataclasses import dataclass, fields


@dataclass(frozen=True)
class ThemeTokens:
    name: str
    app_background: str
    surface: str
    surface_elevated: str
    surface_hover: str
    surface_pressed: str
    border: str
    border_subtle: str
    divider: str
    text_primary: str
    text_secondary: str
    text_muted: str
    accent: str
    accent_hover: str
    accent_pressed: str
    accent_subtle: str
    focus: str
    selection: str
    success: str
    warning: str
    error: str
    unsupported: str
    disabled_foreground: str
    disabled_background: str
    scrollbar: str
    input_background: str
    input_border: str
    button_background: str
    button_border: str
    card_background: str
    card_border: str
    tooltip_background: str
    tooltip_foreground: str
    slider_background: str
    slider_fill: str


def _theme(name, accent, hover, pressed, subtle, focus, selection, *, tint="#071124", success="#20df7a", warning="#e3a84b", error="#ff5d6c"):
    return ThemeTokens(
        name, "#050611", tint, "#101326", subtle, "#090c19", "#313761", "#222844", "#252a49",
        "#f2f1ff", "#cbd5f4", "#7892a8", accent, hover, pressed, subtle, focus, selection,
        success, warning, error, "#8290a4", "#69728f", "#171c33", "#315c78", "#101321", "#30365d",
        "#101322", "#343b6d", "#101326", "#313761", "#08131f", "#f2f1ff", "#29334a", accent,
    )


THEMES = {
    "ONI Blue": _theme("ONI Blue", "#6847ee", "#42d5ff", "#352a8d", "#0b2940", "#7ee7ff", "#0b2d45"),
    "Crimson": _theme("Crimson", "#d9365f", "#ff6b83", "#7d2039", "#32131d", "#ff9bac", "#4b1828", tint="#140a12", success="#2bdc8c", error="#ff765f"),
    "Cyberpunk": _theme("Cyberpunk", "#00d8d8", "#61ffff", "#006b78", "#082b31", "#f0e64a", "#133a40", tint="#06141a", success="#3ce8a0", warning="#f0e64a", error="#ff4d91"),
    "Neon Purple": _theme("Neon Purple", "#a64dff", "#df7dff", "#58238c", "#251139", "#ef9dff", "#36194d", tint="#10091d", success="#32dfa0", error="#ff5f80"),
    "Emerald": _theme("Emerald", "#16b982", "#55e6b2", "#09694e", "#092d25", "#75f0c4", "#103c31", tint="#061713", success="#79e69d", warning="#f2b84b", error="#ff6471"),
    "Monochrome": _theme("Monochrome", "#aeb6c9", "#eef1f6", "#565e6d", "#222630", "#ffffff", "#343a46", tint="#0d1015", success="#79d69b", warning="#e2bd68", error="#ee7480"),
}
THEME_NAMES = tuple(THEMES)
DEFAULT_THEME = "ONI Blue"
REQUIRED_TOKEN_NAMES = tuple(field.name for field in fields(ThemeTokens))


def normalize_theme_name(value) -> str:
    return value if isinstance(value, str) and value in THEMES else DEFAULT_THEME


def theme_tokens(value) -> ThemeTokens:
    return THEMES[normalize_theme_name(value)]


def validate_theme(theme: ThemeTokens) -> bool:
    return all(isinstance(getattr(theme, name), str) and getattr(theme, name) for name in REQUIRED_TOKEN_NAMES)


_HEX = re.compile(r"#[0-9a-fA-F]{6}(?![0-9a-fA-F])")
_RGBA = re.compile(r"rgba\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)")
_BASE_STATUS = {
    "#20df7a": "success", "#10b981": "success", "#059669": "success", "#28e985": "success", "#31ed9a": "success", "#34d399": "success", "#47e7b0": "success",
    "#e3a84b": "warning", "#f59e0b": "warning", "#fbbf24": "warning", "#d97706": "warning",
    "#ff5d6c": "error", "#ef4444": "error", "#dc2626": "error", "#f87171": "error", "#ff416f": "error", "#ffb1bd": "error",
}


def _rgb(value: str) -> tuple[int, int, int]:
    return tuple(int(value[index:index + 2], 16) for index in (1, 3, 5))


def _hex(rgb: tuple[int, int, int]) -> str:
    return "#" + "".join(f"{max(0, min(255, round(channel))):02x}" for channel in rgb)


def _mix(left: str, right: str, amount: float) -> str:
    a, b = _rgb(left), _rgb(right)
    return _hex(tuple(x + (y - x) * amount for x, y in zip(a, b)))


def _semantic_color(value: str, tokens: ThemeTokens) -> str:
    value = value.lower()
    status = _BASE_STATUS.get(value)
    if status: return getattr(tokens, status)
    red, green, blue = (channel / 255 for channel in _rgb(value)); hue, lightness, saturation = colorsys.rgb_to_hls(red, green, blue)
    if lightness <= .055: return tokens.app_background
    if lightness <= .105: return tokens.surface
    if lightness <= .17: return tokens.surface_elevated if saturation < .35 else tokens.accent_subtle
    if lightness >= .88: return tokens.text_primary
    if lightness >= .68: return tokens.text_secondary
    if saturation < .16:
        if lightness < .28: return tokens.border_subtle
        if lightness < .48: return tokens.disabled_foreground
        return tokens.text_muted
    if lightness < .30: return _mix(tokens.accent_subtle, tokens.accent, min(1, lightness / .30))
    if lightness < .58: return _mix(tokens.accent_pressed, tokens.accent, (lightness - .30) / .28)
    return _mix(tokens.accent, tokens.focus, min(1, (lightness - .58) / .32))


def compile_theme_stylesheet(base_stylesheet: str, theme_name: str) -> str:
    """Compile existing role-bearing QSS through one semantic palette contract."""
    name = normalize_theme_name(theme_name)
    if name == DEFAULT_THEME: return base_stylesheet
    tokens = THEMES[name]
    result = _HEX.sub(lambda match: _semantic_color(match.group(0), tokens), base_stylesheet)
    def rgba(match):
        color = _semantic_color(_hex(tuple(int(match.group(i)) for i in range(1, 4))), tokens)
        red, green, blue = _rgb(color)
        return f"rgba({red},{green},{blue},{match.group(4)})"
    return _RGBA.sub(rgba, result).replace("color: white", f"color: {tokens.text_primary}")


SENSOR_STUDIO_BASE_STYLE = """
QWidget#oniSensorStudio { background: #030912; color: #d8e9f6; }
QLabel#studioTitle { font-size: 20px; font-weight: 700; color: #f2fbff; }
QLabel#studioMuted { color: #7894a8; }
QLabel#studioState { color: #66d9ff; font-weight: 600; padding: 5px 10px; }
QFrame#studioBar, QFrame#studioCanvasPanel, QFrame#studioInspectorPanel { background: #06111d; border: 1px solid #123149; border-radius: 8px; }
QPushButton, QToolButton, QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox { min-height: 28px; background: #0a1b2b; border: 1px solid #1a4766; border-radius: 5px; padding: 2px 8px; color: #d9edf8; }
QPushButton:hover, QToolButton:hover { border-color: #25b9ef; background: #0d2639; }
QPushButton#studioAccent { background: #0879a8; border-color: #19bce8; color: white; font-weight: 600; }
QTabWidget#studioLeftTabs::pane { border: 1px solid #123149; background: #06111d; }
QTabBar::tab { background: #071522; border: 1px solid #123149; padding: 8px 10px; }
QTabBar::tab:selected { background: #0b2940; color: #6fe7ff; border-bottom: 2px solid #21c7f3; }
QListWidget#studioBrowser { background: #030a12; border: 1px solid #102b40; border-radius: 5px; }
QListWidget#studioBrowser::item { padding: 6px; border-bottom: 1px solid #0b2030; }
QListWidget#studioBrowser::item:selected { background: #0d3852; color: white; }
QGraphicsView#studioCanvas { background: #02060b; border: 1px solid #153b55; border-radius: 6px; }
QGroupBox { border: 1px solid #16384f; border-radius: 6px; margin-top: 10px; padding-top: 8px; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; color: #7fdfff; }
QScrollArea#studioProperties { border: 0; background: transparent; }
"""


def sensor_studio_stylesheet(theme_name: str) -> str:
    return compile_theme_stylesheet(SENSOR_STUDIO_BASE_STYLE, theme_name)
