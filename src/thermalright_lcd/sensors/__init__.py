"""Unified, read-only hardware sensor engine.

The provider modules are intentionally dependency free.  Native/shared-memory
resources are opened only while a provider is polled, and never for writing.
"""

from .manager import CachedSensorService, SEMANTIC_ALIASES, SemanticResolverCache, SensorManager, SensorSnapshot, rank_semantic_sensors, resolve_semantic_sensor
from .models import SensorDefinition, SensorValue
from .provider import ProviderStatus, SensorProvider
from .providers import (
    Aida64Provider,
    AfterburnerProvider,
    HWiNFOProvider,
    HwinfoProvider,
    MsiAfterburnerProvider,
    NativeBasicProvider,
    RtssProvider,
)
from .shared_memory import ReadOnlyNamedMemoryReader, SnapshotReader

__all__ = [
    "Aida64Provider", "AfterburnerProvider", "HWiNFOProvider", "HwinfoProvider",
    "MsiAfterburnerProvider",
    "NativeBasicProvider", "ProviderStatus", "ReadOnlyNamedMemoryReader",
    "RtssProvider", "SensorDefinition", "SensorManager", "SensorProvider", "CachedSensorService",
    "SEMANTIC_ALIASES", "SemanticResolverCache", "rank_semantic_sensors", "resolve_semantic_sensor",
    "SensorSnapshot", "SensorValue", "SnapshotReader",
]
