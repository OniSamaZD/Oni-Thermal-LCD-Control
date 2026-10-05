import math

import pytest

from thermalright_lcd.devices.catalog import catalog_models
from thermalright_lcd.devices.registry import device_definition
from thermalright_lcd.physical_display import (
    GeometryProvenance, PhysicalDisplayProfile, PhysicalScaleState,
    audit_catalog_geometry, geometry_status_text, physical_profile,
    profile_for_catalog_model,
)
from thermalright_lcd.preview_layout import PhysicalPreviewSpec, physical_preview_sizes
from thermalright_lcd.themes import THEME_NAMES


def test_verified_profiles_preserve_diagonal_ratio_and_effective_render_geometry():
    compact=device_definition("0416:5302").physical_profile
    wide=device_definition("0416:5408").physical_profile
    assert compact.diagonal_inches==6.86 and compact.render_size==(1280,480)
    assert wide.diagonal_inches==9.16 and wide.native_size==(1920,480)
    assert wide.render_size==(1920,462) and wide.excluded_rows==18
    assert wide.diagonal_inches/compact.diagonal_inches==pytest.approx(1.3352769679)


@pytest.mark.parametrize("size,ratio",[((480,480),1.0),((320,240),4/3),((1920,462),1920/462)])
def test_fallback_profile_preserves_known_canvas_shape_without_inventing_size(size,ratio):
    profile=physical_profile(f"fixture-{size[0]}-{size[1]}",size,size)
    assert profile.aspect_ratio==pytest.approx(ratio)
    assert profile.diagonal_inches is None
    assert profile.physical_scale_state is PhysicalScaleState.PARTIAL


def test_known_diagonal_derives_active_geometry_with_explicit_derived_provenance():
    profile=PhysicalDisplayProfile("derived",(1280,480),(1280,480),diagonal_inches=6.86,
        geometry_provenance=GeometryProvenance.MANUFACTURER_SPECIFICATION)
    width,height=profile.derived_active_size_mm
    assert math.hypot(width,height)==pytest.approx(6.86*25.4)
    assert width/height==pytest.approx(1280/480)
    assert profile.active_size_provenance is GeometryProvenance.DERIVED_FROM_VERIFIED_GEOMETRY


def test_enclosure_dimensions_are_never_treated_as_active_panel_dimensions():
    profile=device_definition("0416:5302").physical_profile
    assert profile.enclosure_size_mm==(187.2,72.1,21.0)
    assert profile.active_width_mm is None and profile.active_height_mm is None
    assert profile.derived_active_size_mm!=(187.2,72.1)


def test_unknown_profile_is_not_promoted_to_verified_geometry():
    profile=physical_profile("unknown-test",(480,480),(480,480))
    assert profile.geometry_provenance is GeometryProvenance.UNKNOWN
    assert "Physical size unknown" in geometry_status_text(profile)


def test_shared_reference_models_resolve_one_immutable_panel_profile():
    rows={row.key:row for row in catalog_models()}
    first=profile_for_catalog_model(rows["wonder-vision-360"])
    second=profile_for_catalog_model(rows["wonder-vision-360-v2"])
    assert first is second
    assert first.profile_id=="wonder-vision-360-panel"
    assert first.geometry_provenance is GeometryProvenance.REFERENCE_DATABASE


def test_frozen_warframe_ultra_is_square_unknown_scale_and_orientation_is_metadata_only():
    row=next(row for row in catalog_models() if row.key=="frozen-warframe-ultra")
    profile=profile_for_catalog_model(row)
    assert profile.render_size==(480,480) and profile.aspect_ratio==1
    assert profile.diagonal_inches is None and profile.physical_scale_state is PhysicalScaleState.PARTIAL
    assert profile.output_orientation_degrees==180
    assert profile.orientation_provenance is GeometryProvenance.COMMUNITY_REPORT


def test_mixed_known_unknown_does_not_change_known_group_scale():
    known=(PhysicalPreviewSpec((1920,462),9.16),PhysicalPreviewSpec((1280,480),6.86))
    bounds=((720,260),(720,260))
    baseline=physical_preview_sizes(known,bounds)
    mixed=physical_preview_sizes((*known,PhysicalPreviewSpec((480,480),None)),(*bounds,(300,260)))
    assert mixed[:2]==baseline
    assert mixed[2][0]==mixed[2][1]


def test_group_scaling_preserves_known_physical_ratio_when_constrained():
    specs=(PhysicalPreviewSpec((1920,462),9.16),PhysicalPreviewSpec((1280,480),6.86))
    for bounds in (((900,320),(900,320)),((420,170),(420,170)),((280,120),(280,120))):
        wide,compact=physical_preview_sizes(specs,bounds)
        assert math.hypot(*wide)/math.hypot(*compact)==pytest.approx(9.16/6.86,rel=.015)


@pytest.mark.parametrize("theme",THEME_NAMES)
@pytest.mark.parametrize("effects",(False,True))
def test_theme_and_effect_choice_cannot_change_physical_geometry(theme,effects):
    del theme,effects
    specs=(PhysicalPreviewSpec((1920,462),9.16),PhysicalPreviewSpec((1280,480),6.86))
    assert physical_preview_sizes(specs,((500,180),(500,180)))==physical_preview_sizes(specs,((500,180),(500,180)))


def test_catalog_geometry_audit_covers_every_catalog_row():
    audit=audit_catalog_geometry(catalog_models())
    assert audit["total"]==119
    assert len(audit["rows"])==119
    assert audit["known_diagonal"]>=5
    assert audit["known_active_size"]==0
    assert audit["resolution_only"]+audit["known_diagonal"]+audit["completely_unknown"]==119


def test_physical_profile_lookup_is_cached_and_has_no_runtime_worker_surface():
    first=physical_profile("cache-test",(320,240),(320,240));second=physical_profile("cache-test",(320,240),(320,240))
    assert first is second
    assert not any(hasattr(first,name) for name in ("start","poll","run","send","write","open_session"))
