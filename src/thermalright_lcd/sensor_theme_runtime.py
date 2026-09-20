"""Per-display live runtime for data-driven sensor themes.

This module is deliberately transport agnostic.  It renders at most one image
when a display is due; the GUI remains the sole owner of DisplaySession and of
the physical device handle.
"""

from __future__ import annotations

from collections import deque
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
import math
from pathlib import Path
import time
from typing import Iterable, Mapping

from PIL import Image

from .sensor_theme import DISPLAY_PRESETS, SensorBindingResolver, SensorTheme
from .sensor_theme_renderer import SensorThemeRenderer
from .sensors import SensorValue


SENSOR_THEME_FPS = (1, 2, 5, 10, 15, 30)
MAX_HISTORY_SAMPLES = 36_000


@dataclass(slots=True)
class ActiveSensorTheme:
    device_id: str
    theme: SensorTheme
    asset_root: Path | None
    fps: int
    persisted_theme_id: str
    renderer: SensorThemeRenderer = field(default_factory=SensorThemeRenderer)
    history: dict[str, deque[tuple[float, float]]] = field(default_factory=dict)
    history_durations: dict[str, float] = field(default_factory=dict)
    next_frame_at: float = 0.0
    last_signature: tuple[object, ...] | None = None
    rendered_once: bool = False
    render_count: int = 0
    skipped_count: int = 0
    error_count: int = 0
    last_error: str = ""


class SensorThemeOutputRuntime:
    """Bounded scheduler state for independent LCD theme outputs.

    The caller owns the timer, sensor service, encoder, and DisplaySession.  A
    runtime instance therefore cannot open a USB session or create a polling
    thread accidentally.
    """

    def __init__(self, *, clock=time.perf_counter) -> None:
        self.clock = clock
        self._states: dict[str, ActiveSensorTheme] = {}
        self.resolver = SensorBindingResolver()

    @property
    def active_device_ids(self) -> tuple[str, ...]:
        return tuple(self._states)

    def state(self, device_id: str) -> ActiveSensorTheme | None:
        return self._states.get(device_id)

    def needs_updates(self, device_id: str) -> bool:
        state = self._states.get(device_id)
        if state is None:
            return False
        if not state.rendered_once:
            return True
        return any(
            element.visible and (bool(element.sensor_binding) or element.type in {"clock", "date", "line_graph"})
            for element in state.theme.elements
        )

    def apply(
        self, device_id: str, theme: SensorTheme, *, asset_root: Path | None = None,
        fps: int = 2, persisted_theme_id: str | None = None,
    ) -> ActiveSensorTheme:
        if device_id not in DISPLAY_PRESETS:
            raise ValueError(f"unsupported display: {device_id}")
        fps = int(fps)
        if fps not in SENSOR_THEME_FPS:
            raise ValueError(f"unsupported sensor theme FPS: {fps}")
        # Runtime state is detached from the editor so unsaved edits can keep
        # rendering safely while the user continues editing the document.
        runtime_theme = SensorTheme.from_dict(deepcopy(theme.to_dict()))
        durations: dict[str, float] = {}
        for element in runtime_theme.elements:
            if element.visible and element.type == "line_graph":
                durations[element.sensor_binding] = max(
                    durations.get(element.sensor_binding, 0.0), float(element.history_duration),
                )
        history = {
            binding: deque(maxlen=min(MAX_HISTORY_SAMPLES, max(2, math.ceil(duration * fps) + 2)))
            for binding, duration in durations.items()
        }
        state = ActiveSensorTheme(
            device_id=device_id,
            theme=runtime_theme,
            asset_root=Path(asset_root) if asset_root is not None else None,
            fps=fps,
            persisted_theme_id=persisted_theme_id or runtime_theme.id,
            history=history,
            history_durations=durations,
        )
        self._states[device_id] = state
        return state

    def stop(self, device_id: str) -> ActiveSensorTheme | None:
        return self._states.pop(device_id, None)

    def clear(self) -> None:
        self._states.clear()

    def render_due(
        self, device_id: str, values: Mapping[str, object] | Iterable[SensorValue], *,
        monotonic_now: float | None = None, wall_time: datetime | None = None,
    ) -> Image.Image | None:
        state = self._states.get(device_id)
        if state is None:
            return None
        now = self.clock() if monotonic_now is None else float(monotonic_now)
        if now + 1e-9 < state.next_frame_at:
            state.skipped_count += 1
            return None
        interval = 1.0 / state.fps
        if state.next_frame_at <= 0:
            state.next_frame_at = now + interval
        else:
            missed = max(0, math.floor((now - state.next_frame_at) / interval))
            state.next_frame_at += (missed + 1) * interval

        self._sample_history(state, values, now)
        signature = self._signature(state, values, wall_time or datetime.now())
        has_graph = bool(state.history)
        has_time = any(element.visible and element.type in {"clock", "date"} for element in state.theme.elements)
        if state.rendered_once and not has_graph and not has_time and signature == state.last_signature:
            state.skipped_count += 1
            return None
        try:
            image = state.renderer.render(
                state.theme, values, history=state.history, asset_root=state.asset_root,
                output_size=DISPLAY_PRESETS[device_id], now=wall_time,
            )
        except Exception as exc:
            state.error_count += 1; state.last_error = str(exc)
            return None
        state.last_signature = signature
        state.rendered_once = True
        state.render_count += 1
        state.last_error = ""
        return image

    def _sample_history(
        self, state: ActiveSensorTheme, values: Mapping[str, object] | Iterable[SensorValue], now: float,
    ) -> None:
        for binding, samples in state.history.items():
            resolved = self.resolver.resolve(binding, values)
            if resolved.available:
                try:
                    samples.append((now, float(resolved.value)))
                except (TypeError, ValueError):
                    pass
            cutoff = now - state.history_durations[binding]
            while samples and samples[0][0] < cutoff:
                samples.popleft()

    def _signature(
        self, state: ActiveSensorTheme, values: Mapping[str, object] | Iterable[SensorValue], wall_time: datetime,
    ) -> tuple[object, ...]:
        bindings = sorted({element.sensor_binding for element in state.theme.elements if element.visible and element.sensor_binding})
        resolved = []
        for binding in bindings:
            value = self.resolver.resolve(binding, values)
            resolved.append((binding, value.available, value.value, value.unit, value.label))
        time_key = wall_time.replace(microsecond=0) if any(
            element.visible and element.type in {"clock", "date"} for element in state.theme.elements
        ) else None
        return (*resolved, time_key)

    def diagnostics(self) -> dict[str, dict[str, object]]:
        return {
            device_id: {
                "theme_id": state.theme.id,
                "fps": state.fps,
                "render_count": state.render_count,
                "skipped_count": state.skipped_count,
                "error_count": state.error_count,
                "last_error": state.last_error,
                "history_samples": sum(len(samples) for samples in state.history.values()),
            }
            for device_id, state in self._states.items()
        }
