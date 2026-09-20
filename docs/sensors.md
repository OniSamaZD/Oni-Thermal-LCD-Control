# Unified sensor engine

The sensor engine in `thermalright_lcd.sensors` is an offline-safe, read-only
integration layer. It defines `SensorDefinition`, `SensorValue`,
`SensorProvider`, and `SensorManager`, with providers for HWiNFO, MSI
Afterburner, RTSS, AIDA64, and a basic native fallback.

## Safety boundary

- Windows named mappings are opened with `OpenFileMappingW(FILE_MAP_READ)` and
  `MapViewOfFile(FILE_MAP_READ)` only. The engine never creates a missing map.
- Providers never inject into, hook, automate, or scrape another process.
- A mapping is opened only for a bounded snapshot and its handle is closed
  immediately afterward.
- Missing, inaccessible, corrupt, or unknown-version providers return an empty
  result and diagnostic status. One provider failure cannot stop another
  provider or media playback.
- Tests use injected fixture readers and never access live shared memory.

## Provider behavior

- **HWiNFO** parses the public Shared Memory Viewer v2 sensor and reading
  tables, respecting the offsets and element sizes advertised by the header.
- **MSI Afterburner** recognizes the public `MAHMSharedMemory` header and stable
  hardware-monitor entry fields. New ABI revisions can supply a decoder without
  changing the sensor engine.
- **RTSS** uses `RTSSSharedMemoryV2` and reads the stable v2 application
  counters to derive FPS and frametime. Unknown/shorter raw revisions fail
  closed; a documented revision-specific decoder or decoded reader may be
  injected.
- **AIDA64** parses its External Applications shared-memory XML.
- **Windows Basic** lazily imports `psutil` and supplies CPU and memory usage
  when richer providers are absent.

`SensorManager` polls providers independently, removes invalid samples, filters
an optional set of qualified IDs (`Provider:id`), and deduplicates canonical
metrics according to provider priority. Duplicate display remains an explicit
opt-in for users who want to compare sources.
