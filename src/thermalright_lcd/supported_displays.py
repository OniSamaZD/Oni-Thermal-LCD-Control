from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .devices.catalog import CatalogModel


def normalize_identifier(value: str) -> str:
    return str(value or "").strip().casefold().replace("0x", "")


@dataclass(frozen=True, slots=True)
class LiveDisplayState:
    stable_id: str
    device_id: str
    model: str = ""
    connected: bool = True
    active: bool = False
    catalog_key: str = ""


@dataclass(frozen=True, slots=True)
class CatalogDisplayState:
    model: CatalogModel
    connected: bool = False
    active: bool = False
    physical_count: int = 0


def match_catalog_model(model: CatalogModel, live: LiveDisplayState, ambiguous_identifiers: frozenset[str] = frozenset()) -> bool:
    """Match exact protocol identity, never presentation-name substrings."""
    if live.catalog_key:return normalize_identifier(live.catalog_key)==normalize_identifier(model.key)
    device_id = normalize_identifier(live.device_id)
    identifiers = {normalize_identifier(item) for item in model.identifiers}
    if device_id in identifiers:
        # Shared bridge identifiers need the exact resolved model name before
        # one catalog row may claim the physical device.
        candidates = identifiers & ({"4e58:1001", "4e58:1002", "1a86:5722"} | set(ambiguous_identifiers))
        return not candidates or normalize_identifier(live.model) == normalize_identifier(model.model)
    return bool(live.model and normalize_identifier(live.model) == normalize_identifier(model.model))


def catalog_live_states(models: Iterable[CatalogModel], live: Iterable[LiveDisplayState]) -> tuple[CatalogDisplayState, ...]:
    models=tuple(models);live = tuple(live);counts={}
    for model in models:
        for identifier in model.identifiers:
            key=normalize_identifier(identifier);counts[key]=counts.get(key,0)+1
    ambiguous=frozenset(key for key,count in counts.items() if count>1)
    rows = []
    for model in models:
        matches = tuple(item for item in live if item.connected and match_catalog_model(model, item, ambiguous))
        rows.append(CatalogDisplayState(model, bool(matches), any(item.active for item in matches), len(matches)))
    return tuple(rows)


def filter_catalog_states(
    rows: Iterable[CatalogDisplayState], query: str = "", status: str = "All", connected_only: bool = False,
) -> tuple[CatalogDisplayState, ...]:
    query = query.strip().casefold(); status = status.strip()
    result = []
    for row in rows:
        model = row.model
        haystack = " ".join((model.manufacturer, model.family, model.model, *model.identifiers, model.connection_type, model.key)).casefold()
        if query and query not in haystack:continue
        if status != "All" and model.status != status:continue
        if connected_only and not row.connected:continue
        result.append(row)
    return tuple(result)
