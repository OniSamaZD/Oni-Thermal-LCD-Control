import math

import pytest

from thermalright_lcd.preview_layout import PhysicalPreviewSpec, physical_preview_sizes
from thermalright_lcd.devices.registry import device_definition


def test_known_physical_diagonals_share_one_preview_scale():
    specs = (
        PhysicalPreviewSpec((1920, 462), 9.16),
        PhysicalPreviewSpec((1280, 480), 6.86),
    )
    wide, compact = physical_preview_sizes(specs, ((900, 320), (900, 320)))
    assert wide[0] > compact[0]
    assert math.hypot(*wide) / math.hypot(*compact) == pytest.approx(9.16 / 6.86, rel=0.01)
    assert wide[0] / wide[1] == pytest.approx(1920 / 462, rel=0.01)
    assert compact[0] / compact[1] == pytest.approx(1280 / 480, rel=0.01)


def test_verified_trofeo_definitions_expose_physical_diagonal_metadata():
    assert device_definition("0416:5408").physical_diagonal_inches == 9.16
    assert device_definition("0416:5302").physical_diagonal_inches == 6.86


def test_unknown_physical_size_uses_safe_non_authoritative_fallback():
    known = PhysicalPreviewSpec((1920, 462), 9.16)
    unknown = PhysicalPreviewSpec((800, 480), None)
    first, second = physical_preview_sizes((known, unknown), ((700, 300), (700, 300)))
    assert first[0] <= 700 and first[1] <= 300
    assert second[0] <= 700 and second[1] <= 300
    assert second[0] / second[1] == pytest.approx(800 / 480, rel=0.01)
    assert second[0] < 700 and second[1] < 300


def test_all_unknown_displays_remain_contained_and_aspect_correct():
    specs = (PhysicalPreviewSpec((320, 320)), PhysicalPreviewSpec((800, 480)))
    sizes = physical_preview_sizes(specs, ((180, 120), (260, 100)))
    assert sizes[0][0] <= 180 and sizes[0][1] <= 120
    assert sizes[1][0] <= 260 and sizes[1][1] <= 100
    assert sizes[0][0] / sizes[0][1] == pytest.approx(1.0, rel=0.01)
    assert sizes[1][0] / sizes[1][1] == pytest.approx(800 / 480, rel=0.02)


def test_invalid_geometry_is_rejected():
    with pytest.raises(ValueError):
        physical_preview_sizes((PhysicalPreviewSpec((0, 480)),), ((100, 100),))
    with pytest.raises(ValueError):
        physical_preview_sizes((PhysicalPreviewSpec((800, 480)),), ())
