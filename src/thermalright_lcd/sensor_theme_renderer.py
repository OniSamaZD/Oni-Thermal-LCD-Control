"""Transport-independent Pillow renderer for data-driven sensor themes."""

from __future__ import annotations

from datetime import datetime
from io import BytesIO
import math
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps

from .sensor_theme import (
    DISPLAY_PRESETS,
    ResolvedSensor,
    SensorBindingResolver,
    SensorTheme,
    ThemeElement,
    format_sensor_value,
)
from .sensors import SensorValue


def _rgba(value: str) -> tuple[int, int, int, int]:
    if value == "transparent":
        return (0, 0, 0, 0)
    text = value.removeprefix("#")
    if len(text) == 6:
        text += "ff"
    return tuple(int(text[index:index + 2], 16) for index in range(0, 8, 2))


class SensorThemeRenderer:
    """Render themes to images without importing or mutating device/session code."""

    def __init__(self, resolver: SensorBindingResolver | None = None) -> None:
        self.resolver = resolver or SensorBindingResolver()
        self._font_cache: dict[tuple[str, int, int, bool], ImageFont.ImageFont] = {}
        self._smooth_values: dict[str, tuple[float, float, float]] = {}
        self.render_count = 0

    def render(
        self,
        theme: SensorTheme,
        values: Mapping[str, object] | Iterable[SensorValue],
        *,
        history: Mapping[str, Sequence[object]] | None = None,
        asset_root: Path | None = None,
        output_size: tuple[int, int] | str | None = None,
        scale_mode: str | None = None,
        now: datetime | None = None,
    ) -> Image.Image:
        self.render_count += 1
        asset_root = Path(asset_root) if asset_root is not None else None
        now = now or datetime.now()
        canvas = Image.new("RGBA", (theme.canvas.width, theme.canvas.height), _rgba(theme.background_color))
        if theme.background_asset and asset_root is not None:
            background_path = asset_root.joinpath(*theme.background_asset.split("/"))
            try:
                with Image.open(background_path) as source:
                    background = self._background_layer(source.convert("RGBA"), canvas.size, theme.background_fit)
                if theme.background_opacity < 1:
                    background.putalpha(background.getchannel("A").point(lambda value: round(value * theme.background_opacity)))
                canvas.alpha_composite(background)
                background.close()
            except (OSError, ValueError):
                pass
        for element in sorted(theme.elements, key=lambda item: item.z_index):
            if not element.visible:
                continue
            sensor = self.resolver.resolve(element.sensor_binding, values) if element.sensor_binding else ResolvedSensor("", None)
            layer = self._element_layer(element, sensor, history or {}, asset_root, now)
            animated_opacity = element.opacity
            if element.animation in {"fade", "pulse"}:
                phase = (now.timestamp() % element.animation_duration) / element.animation_duration
                wave = (1 - math.cos(phase * math.tau)) / 2
                floor = .25 if element.animation == "fade" else .65
                animated_opacity *= floor + (1 - floor) * wave
            if animated_opacity < 1:
                alpha = layer.getchannel("A").point(lambda value: round(value * animated_opacity))
                layer.putalpha(alpha)
            if element.rotation % 360:
                layer = layer.rotate(-element.rotation, expand=True, resample=Image.Resampling.BICUBIC)
            x = round(element.x + (element.width - layer.width) / 2)
            y = round(element.y + (element.height - layer.height) / 2)
            canvas.alpha_composite(layer, (x, y))
        if output_size is None:
            return canvas.convert("RGB")
        if isinstance(output_size, str):
            if output_size not in DISPLAY_PRESETS:
                raise ValueError(f"unknown output display preset: {output_size}")
            output_size = DISPLAY_PRESETS[output_size]
        return self._scale(canvas, output_size, scale_mode or theme.canvas.scale_mode).convert("RGB")

    def thumbnail(
        self, theme: SensorTheme, values: Mapping[str, object] | Iterable[SensorValue],
        *, asset_root: Path | None = None, size: tuple[int, int] = (480, 120),
    ) -> Image.Image:
        return self.render(theme, values, asset_root=asset_root, output_size=size, scale_mode="contain")

    @staticmethod
    def _scale(source: Image.Image, output_size: tuple[int, int], mode: str) -> Image.Image:
        width, height = map(int, output_size)
        if width < 1 or height < 1:
            raise ValueError("output dimensions must be positive")
        if mode == "stretch":
            return source.resize((width, height), Image.Resampling.LANCZOS)
        ratio = max(width / source.width, height / source.height) if mode == "cover" else min(width / source.width, height / source.height)
        resized = source.resize((max(1, round(source.width * ratio)), max(1, round(source.height * ratio))), Image.Resampling.LANCZOS)
        if mode == "cover":
            left, top = (resized.width - width) // 2, (resized.height - height) // 2
            return resized.crop((left, top, left + width, top + height))
        out = Image.new("RGBA", (width, height), (0, 0, 0, 255))
        out.alpha_composite(resized, ((width - resized.width) // 2, (height - resized.height) // 2))
        return out

    @staticmethod
    def _background_layer(source: Image.Image, size: tuple[int, int], mode: str) -> Image.Image:
        width,height=size
        if mode=="stretch":return source.resize(size,Image.Resampling.LANCZOS)
        if mode in {"center","native"}:
            out=Image.new("RGBA",size,(0,0,0,0));out.alpha_composite(source,((width-source.width)//2,(height-source.height)//2));return out
        ratio=max(width/source.width,height/source.height) if mode=="cover" else min(width/source.width,height/source.height)
        resized=source.resize((max(1,round(source.width*ratio)),max(1,round(source.height*ratio))),Image.Resampling.LANCZOS)
        if mode=="cover":
            left,top=(resized.width-width)//2,(resized.height-height)//2
            return resized.crop((left,top,left+width,top+height))
        out=Image.new("RGBA",size,(0,0,0,0));out.alpha_composite(resized,((width-resized.width)//2,(height-resized.height)//2));return out

    def _element_layer(
        self, element: ThemeElement, sensor: ResolvedSensor, history: Mapping[str, Sequence[object]],
        asset_root: Path | None, now: datetime,
    ) -> Image.Image:
        size = (max(1, round(element.width)), max(1, round(element.height)))
        layer = Image.new("RGBA", size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer, "RGBA")
        if element.animation == "smooth":
            sensor = self._smooth_sensor(element, sensor, now)
        radius = max(0, round(min(element.corner_radius, min(size) / 2)))
        if element.background_color != "transparent":
            draw.rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius, fill=_rgba(element.background_color))

        if element.type in {"text", "sensor_value", "sensor_label", "sensor_label_value", "value_unit", "clock", "date", "fps", "frametime"}:
            if element.type == "text":
                text = element.text
            elif element.type == "sensor_label":
                text = element.text or sensor.label or element.sensor_binding
            elif element.type in {"sensor_value", "value_unit", "fps", "frametime"}:
                text = format_sensor_value(element, sensor)
            elif element.type == "sensor_label_value":
                text=f"{element.text or sensor.label or element.sensor_binding}  {format_sensor_value(element,sensor)}"
            elif element.type == "clock":
                text = now.strftime(element.time_format)
            else:
                text = now.strftime(element.date_format)
            self._draw_text(layer, element, text, asset_root)
        elif element.type in {"progress_bar", "progress_indicator", "horizontal_bar", "vertical_bar"}:
            self._draw_bar(draw, element, sensor)
        elif element.type in {"ring_gauge", "arc_gauge"}:
            self._draw_gauge(draw, element, sensor)
        elif element.type in {"line_graph", "area_graph"}:
            self._draw_graph(draw, element, sensor, history)
        elif element.type in {"image", "icon"}:
            self._draw_image(layer, element, asset_root)

        if element.border_width > 0 and element.border_color != "transparent":
            draw.rounded_rectangle(
                (0, 0, size[0] - 1, size[1] - 1), radius,
                outline=_rgba(element.border_color), width=max(1, round(element.border_width)),
            )

        return self._effects(layer, element)

    def _smooth_sensor(self, element: ThemeElement, sensor: ResolvedSensor, now: datetime) -> ResolvedSensor:
        if not sensor.available:
            self._smooth_values.pop(element.id, None)
            return sensor
        try:
            target = float(sensor.value)
        except (TypeError, ValueError):
            return sensor
        timestamp = now.timestamp(); previous = self._smooth_values.get(element.id)
        if previous is None:
            self._smooth_values[element.id] = (target, target, timestamp)
            return sensor
        start_value, previous_target, started = previous
        progress = max(0.0, min(1.0, (timestamp - started) / element.animation_duration))
        current = start_value + (previous_target - start_value) * (progress * progress * (3 - 2 * progress))
        if target != previous_target:
            self._smooth_values[element.id] = (current, target, timestamp)
            value = current
        else:
            value = current
            if progress >= 1:
                self._smooth_values[element.id] = (target, target, timestamp)
                value = target
        return ResolvedSensor(sensor.binding, value, sensor.unit, sensor.label, True)

    def _font(self, element: ThemeElement, asset_root: Path | None) -> ImageFont.ImageFont:
        size = max(1, round(element.font_size))
        key = (element.font_file or element.font_family, size, element.font_weight, element.italic)
        if key in self._font_cache:
            return self._font_cache[key]
        candidates: list[str] = []
        if element.font_file and asset_root is not None:
            candidates.append(str(asset_root / PureResource(element.font_file)))
        family = element.font_family or "Segoe UI"
        if element.font_weight >= 600 and element.italic:
            candidates.extend((f"{family} Bold Italic.ttf", "segoeuiz.ttf"))
        elif element.font_weight >= 600:
            candidates.extend((f"{family} Bold.ttf", "segoeuib.ttf"))
        elif element.italic:
            candidates.extend((f"{family} Italic.ttf", "segoeuii.ttf"))
        candidates.extend((f"{family}.ttf", "segoeui.ttf"))
        for candidate in candidates:
            try:
                font = ImageFont.truetype(candidate, size)
                self._font_cache[key] = font
                return font
            except OSError:
                continue
        font = ImageFont.load_default(size=max(8, size))
        self._font_cache[key] = font
        return font

    def _draw_text(self, layer: Image.Image, element: ThemeElement, text: str, asset_root: Path | None) -> None:
        draw = ImageDraw.Draw(layer, "RGBA")
        font = self._font(element, asset_root)
        spacing = element.letter_spacing
        if spacing:
            widths = [draw.textlength(character, font=font) for character in text]
            text_width = sum(widths) + max(0, len(text) - 1) * spacing
        else:
            text_width = draw.textlength(text, font=font)
        bbox = draw.textbbox((0, 0), text or " ", font=font)
        text_height = bbox[3] - bbox[1]
        padding = min(element.padding, layer.width / 2, layer.height / 2)
        x = padding if element.alignment == "left" else (layer.width - text_width) / 2 if element.alignment == "center" else layer.width - text_width - padding
        y = padding - bbox[1] if element.vertical_alignment == "top" else (layer.height - text_height) / 2 - bbox[1] if element.vertical_alignment == "middle" else layer.height - text_height - padding - bbox[1]
        fill = _rgba(element.text_color)
        stroke_width = max(0, round(element.text_outline_width)); stroke_fill = _rgba(element.text_outline_color)
        if spacing:
            cursor = x
            for character, width in zip(text, widths):
                draw.text((cursor, y), character, font=font, fill=fill, stroke_width=stroke_width, stroke_fill=stroke_fill)
                cursor += width + spacing
        else:
            draw.text((x, y), text, font=font, fill=fill, stroke_width=stroke_width, stroke_fill=stroke_fill)

    @staticmethod
    def _ratio(element: ThemeElement, sensor: ResolvedSensor) -> float:
        try:
            return max(0.0, min(1.0, (float(sensor.value) - element.minimum) / (element.maximum - element.minimum))) if sensor.available else 0.0
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _value_color(element: ThemeElement, sensor: ResolvedSensor) -> tuple[int, int, int, int]:
        try:
            value = float(sensor.value)
        except (TypeError, ValueError):
            return _rgba(element.value_color)
        if element.critical_threshold is not None and value >= element.critical_threshold:
            return _rgba(element.critical_color)
        if element.warning_threshold is not None and value >= element.warning_threshold:
            return _rgba(element.warning_color)
        return _rgba(element.value_color)

    def _draw_bar(self, draw: ImageDraw.ImageDraw, element: ThemeElement, sensor: ResolvedSensor) -> None:
        width, height = draw._image.size
        ratio = self._ratio(element, sensor)
        radius = max(0, round(min(element.corner_radius, min(width, height) / 2)))
        draw.rounded_rectangle((0, 0, width - 1, height - 1), radius, fill=_rgba(element.track_color))
        color = self._value_color(element, sensor)
        direction = element.direction
        vertical = element.type == "vertical_bar" or direction in {"bottom_to_top", "top_to_bottom"}
        if vertical:
            amount = round(height * ratio)
            box = (0, height - amount, width - 1, height - 1) if direction != "top_to_bottom" else (0, 0, width - 1, max(0, amount - 1))
        else:
            amount = round(width * ratio)
            box = (width - amount, 0, width - 1, height - 1) if direction == "right_to_left" else (0, 0, max(0, amount - 1), height - 1)
        if amount > 0:
            draw.rounded_rectangle(box, radius, fill=color)

    def _draw_gauge(self, draw: ImageDraw.ImageDraw, element: ThemeElement, sensor: ResolvedSensor) -> None:
        width, height = draw._image.size
        inset = max(1, math.ceil(element.thickness / 2))
        box = (inset, inset, width - inset - 1, height - inset - 1)
        if box[2] <= box[0] or box[3] <= box[1]:
            return
        start, end = element.start_angle, element.end_angle
        sweep = end - start
        ratio = self._ratio(element, sensor)
        if element.type == "ring_gauge" and math.isclose(abs(sweep), 270.0):
            end = start + 360.0
            sweep = 360.0
        draw.arc(box, start=start, end=end, fill=_rgba(element.track_color), width=max(1, round(element.thickness)))
        value_end = start + sweep * ratio
        if element.direction == "counterclockwise":
            draw.arc(box, start=start - sweep * ratio, end=start, fill=self._value_color(element, sensor), width=max(1, round(element.thickness)))
        else:
            draw.arc(box, start=start, end=value_end, fill=self._value_color(element, sensor), width=max(1, round(element.thickness)))

    def _draw_graph(
        self, draw: ImageDraw.ImageDraw, element: ThemeElement, sensor: ResolvedSensor,
        history: Mapping[str, Sequence[object]],
    ) -> None:
        points = self._history_values(history.get(element.sensor_binding, ()), element.history_duration)
        if not points and sensor.available:
            try:
                points = [float(sensor.value)]
            except (TypeError, ValueError):
                points = []
        if element.smoothing and len(points) > 2:
            points = [sum(points[max(0, index - 2):index + 1]) / len(points[max(0, index - 2):index + 1]) for index in range(len(points))]
        if len(points) < 2:
            return
        minimum, maximum = (min(points), max(points)) if element.automatic_scale else (element.scale_min, element.scale_max)
        if math.isclose(minimum, maximum):
            minimum, maximum = minimum - 1, maximum + 1
        width, height = draw._image.size
        coordinates = [
            (index * (width - 1) / (len(points) - 1), (height - 1) - (value - minimum) / (maximum - minimum) * (height - 1))
            for index, value in enumerate(points)
        ]
        if element.fill:
            draw.polygon([(coordinates[0][0], height - 1), *coordinates, (coordinates[-1][0], height - 1)], fill=_rgba(element.fill_color))
        draw.line(coordinates, fill=self._value_color(element, sensor), width=max(1, round(element.line_width)), joint="curve")

    @staticmethod
    def _history_values(raw: Sequence[object], duration: float) -> list[float]:
        values: list[float] = []
        timestamps: list[float] = []
        for item in raw:
            try:
                if isinstance(item, (tuple, list)) and len(item) == 2:
                    timestamps.append(float(item[0]))
                    values.append(float(item[1]))
                else:
                    values.append(float(item))
            except (TypeError, ValueError):
                continue
        if timestamps and len(timestamps) == len(values):
            cutoff = timestamps[-1] - duration
            return [value for timestamp, value in zip(timestamps, values) if timestamp >= cutoff]
        return values

    @staticmethod
    def _draw_image(layer: Image.Image, element: ThemeElement, asset_root: Path | None) -> None:
        if asset_root is None:
            return
        path = asset_root / PureResource(element.asset)
        if not path.is_file():
            draw = ImageDraw.Draw(layer)
            draw.line((0, 0, layer.width - 1, layer.height - 1), fill=_rgba(element.critical_color), width=2)
            draw.line((layer.width - 1, 0, 0, layer.height - 1), fill=_rgba(element.critical_color), width=2)
            return
        with Image.open(path) as opened:
            image = opened.convert("RGBA")
        if element.image_fit == "stretch":
            image = image.resize(layer.size, Image.Resampling.LANCZOS)
        elif element.image_fit == "cover":
            image = ImageOps.fit(image, layer.size, Image.Resampling.LANCZOS)
        elif element.image_fit == "crop":
            left, top, right, bottom = element.crop
            image = image.crop((round(left * image.width), round(top * image.height), round(right * image.width), round(bottom * image.height)))
            image = image.resize(layer.size, Image.Resampling.LANCZOS)
        else:
            image.thumbnail(layer.size, Image.Resampling.LANCZOS)
        layer.alpha_composite(image, ((layer.width - image.width) // 2, (layer.height - image.height) // 2))

    @staticmethod
    def _effects(layer: Image.Image, element: ThemeElement) -> Image.Image:
        if not element.shadow and not element.glow:
            return layer
        result = Image.new("RGBA", layer.size, (0, 0, 0, 0))
        alpha = layer.getchannel("A")
        if element.glow:
            glow_alpha = alpha.filter(ImageFilter.GaussianBlur(max(0.1, element.glow_strength)))
            glow = Image.new("RGBA", layer.size, _rgba(element.glow_color))
            glow.putalpha(ImageChops.multiply(glow.getchannel("A"), glow_alpha))
            result.alpha_composite(glow)
        if element.shadow:
            shadow_alpha = alpha.filter(ImageFilter.GaussianBlur(max(0.1, element.shadow_blur)))
            shadow = Image.new("RGBA", layer.size, _rgba(element.shadow_color))
            shadow.putalpha(ImageChops.multiply(shadow.getchannel("A"), shadow_alpha))
            result.alpha_composite(shadow, (round(element.shadow_offset_x), round(element.shadow_offset_y)))
        result.alpha_composite(layer)
        return result


def PureResource(value: str) -> Path:
    """Convert a prevalidated POSIX package member to a local relative path."""
    return Path(*value.split("/"))
