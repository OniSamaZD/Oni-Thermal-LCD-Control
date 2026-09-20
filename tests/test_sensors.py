import io
import struct
import unittest
from unittest.mock import Mock, patch

from thermalright_lcd.sensors import (
    Aida64Provider, AfterburnerProvider, HwinfoProvider, NativeBasicProvider,
    ReadOnlyNamedMemoryReader, RtssProvider, SensorManager,
)
from thermalright_lcd.sensors.shared_memory import FixtureSnapshotReader


def reader(records): return FixtureSnapshotReader(records)


class SensorProviderTests(unittest.TestCase):
    def test_absent_provider_is_graceful(self):
        class Missing:
            def read(self): raise FileNotFoundError("not running")
        provider = HwinfoProvider(Missing())
        self.assertEqual(provider.poll(), ())
        self.assertFalse(provider.status.available)
        self.assertIn("not running", provider.status.last_error)

    def test_all_integrations_accept_injectable_decoded_snapshots(self):
        classes = (HwinfoProvider, AfterburnerProvider, RtssProvider, Aida64Provider)
        for cls in classes:
            with self.subTest(cls=cls.__name__):
                provider = cls(reader([{"id": "gpu.temp", "name": "GPU Temperature",
                                       "category": "GPU", "unit": "C", "value": 61.5}]))
                values = provider.poll()
                self.assertEqual(len(values), 1)
                self.assertEqual(values[0].value, 61.5)
                self.assertTrue(provider.status.available)

    def test_aida64_external_applications_xml(self):
        xml = '<AIDA64><temp id="TGPU" label="GPU Temperature" unit="C">62.5</temp>' \
              '<fan id="FCPU" label="CPU Fan" unit="RPM">1200</fan></AIDA64>'
        values = Aida64Provider(reader(xml)).poll()
        self.assertEqual([(x.id, x.value) for x in values], [("TGPU", 62.5), ("FCPU", 1200.0)])

    def test_hwinfo_v2_binary_fixture(self):
        sensor_size, reading_size = 264, 316
        sensor_off, reading_off = 44, 44 + sensor_size
        data = bytearray(reading_off + reading_size)
        data[:4] = b"HWiS"
        struct.pack_into("<II", data, 4, 2, 1)
        struct.pack_into("<q", data, 12, 123)
        struct.pack_into("<III", data, 20, sensor_off, sensor_size, 1)
        struct.pack_into("<III", data, 32, reading_off, reading_size, 1)
        struct.pack_into("<II", data, sensor_off, 7, 0)
        data[sensor_off + 8:sensor_off + 11] = b"GPU"
        struct.pack_into("<III", data, reading_off, 0, 0, 42)
        data[reading_off + 12:reading_off + 27] = b"GPU Temperature"
        data[reading_off + 268:reading_off + 269] = b"C"
        struct.pack_into("<d", data, reading_off + 284, 64.25)
        provider=HwinfoProvider(reader(bytes(data)));value = provider.poll()[0]
        self.assertEqual(value.id, "0:42")
        self.assertEqual(value.category, "GPU")
        self.assertAlmostEqual(value.value, 64.25)
        self.assertEqual((provider.version,provider.mapped_sensor_count,provider.mapped_reading_count),("2.1",1,1))

    def test_afterburner_public_entry_fixture(self):
        header_size, entry_size = 32, 128
        data = bytearray(header_size + entry_size)
        data[:4] = b"MAHM"
        struct.pack_into("<IIII", data, 4, 0x20000, header_size, 1, entry_size)
        data[header_size:header_size + 9] = b"GPU usage"
        data[header_size + 32:header_size + 33] = b"%"
        struct.pack_into("<f", data, header_size + 112, 78.0)
        value = AfterburnerProvider(reader(bytes(data))).poll()[0]
        self.assertEqual(value.name, "GPU usage")
        self.assertEqual(value.value, 78.0)

    def test_rtss_v2_application_fixture(self):
        header_size, entry_size = 32, 320
        data = bytearray(header_size + entry_size)
        data[:4] = b"RTSS"
        struct.pack_into("<IIII", data, 4, 0x20000, entry_size, header_size, 1)
        struct.pack_into("<I", data, header_size, 1234)
        data[header_size + 4:header_size + 12] = b"game.exe"
        struct.pack_into("<IIII", data, header_size + 268, 1000, 2000, 144, 6944)
        values = RtssProvider(reader(bytes(data))).poll()
        self.assertAlmostEqual(values[0].value, 144.0)
        self.assertAlmostEqual(values[1].value, 6.944)

    def test_unknown_rtss_abi_fails_closed(self):
        provider = RtssProvider(reader(b"RTSS" + b"\0" * 64))
        self.assertEqual(provider.poll(), ())
        self.assertIn("unsupported RTSS ABI", provider.status.last_error)

    def test_read_only_mapping_boundary_closes_handle(self):
        opened = []
        class Handle(io.BytesIO):
            def close(self): opened.append("closed"); super().close()
        def opener(name, size):
            opened.append((name, size)); return Handle(b"abc" + b"\0" * 5)
        source = ReadOnlyNamedMemoryReader("fixture", 8, opener)
        self.assertEqual(source.read(), b"abc" + b"\0" * 5)
        self.assertEqual(opened, [("fixture", 8), "closed"])


class SensorManagerTests(unittest.TestCase):
    def test_cached_service_reuses_provider_and_snapshot_inside_interval(self):
        from thermalright_lcd.sensors import CachedSensorService
        provider=Mock();provider.poll.return_value=[];provider.status=Mock()
        service=CachedSensorService([provider],minimum_interval=10)
        first=service.poll();second=service.poll()
        self.assertIs(first,second);self.assertEqual(service.poll_count,1);provider.poll.assert_called_once()
    def test_rescan_forces_new_snapshot_and_exposes_failure_diagnostics(self):
        from thermalright_lcd.sensors import CachedSensorService,HwinfoProvider
        class Missing:
            def read(self):raise FileNotFoundError("shared memory unavailable")
        service=CachedSensorService([HwinfoProvider(Missing())],minimum_interval=10);first=service.poll();second=service.rescan();diagnostics=service.diagnostics()
        self.assertIsNot(first,second);self.assertEqual((service.poll_count,service.generation),(2,2));self.assertEqual(diagnostics["mapped_sensor_count"],0);self.assertFalse(diagnostics["providers"][0]["available"]);self.assertIn("shared memory unavailable",diagnostics["providers"][0]["last_error"])

    def test_semantic_ranking_prefers_matching_sensor(self):
        from thermalright_lcd.sensors import SensorDefinition,SensorValue,rank_semantic_sensors
        unrelated=SensorValue.now(SensorDefinition("x","HWiNFO","GPU Fan","GPU","RPM"),1000)
        fps=SensorValue.now(SensorDefinition("fps","RTSS","Framerate","Game","FPS","fps"),60)
        self.assertIs(rank_semantic_sensors("fps",[unrelated,fps])[0],fps)
    def test_semantic_resolution_rejects_power_as_temperature(self):
        from thermalright_lcd.sensors import SensorDefinition,SensorValue,resolve_semantic_sensor
        power=SensorValue.now(SensorDefinition("p","HWiNFO","CPU Package Power","CPU","W"),50)
        temp=SensorValue.now(SensorDefinition("t","HWiNFO","CPU (Tctl/Tdie)","CPU","°C"),65)
        self.assertIs(resolve_semantic_sensor("cpu_temp",[power,temp]),temp)
    def test_provider_late_start_stop_and_reconnect_without_manager_restart(self):
        from thermalright_lcd.sensors import CachedSensorService,HwinfoProvider
        class Reader:
            state="off"
            def read(self):
                if self.state=="off":raise FileNotFoundError("shared memory unavailable")
                return [{"id":"temp","name":"CPU (Tctl/Tdie)","category":"CPU","unit":"°C","value":42,"canonical_key":"cpu.temperature"}]
        reader=Reader();service=CachedSensorService([HwinfoProvider(reader)],minimum_interval=.1)
        self.assertFalse(service.poll(force=True).provider_status[0].available);reader.state="on";self.assertTrue(service.poll(force=True).provider_status[0].available);reader.state="off";self.assertFalse(service.poll(force=True).values);reader.state="on";self.assertEqual(service.poll(force=True).values[0].value,42);self.assertEqual(service.poll_count,4)
    def test_priority_and_deduplication(self):
        hw = HwinfoProvider(reader([{"id": "cpu", "name": "CPU Usage", "unit": "%",
                                    "value": 20, "canonical_key": "cpu.usage"}]))
        native = NativeBasicProvider(type("P", (), {
            "cpu_percent": staticmethod(lambda interval=None: 99),
            "virtual_memory": staticmethod(lambda: type("M", (), {"percent": 40})()),
        }))
        snapshot = SensorManager([native, hw]).poll()
        values = {value.definition.dedup_key: value for value in snapshot.values}
        self.assertEqual(values["cpu.usage"].provider, "HWiNFO")
        self.assertEqual(values["cpu.usage"].value, 20)
        self.assertIn("memory.usage", values)

    def test_explicit_selection_uses_qualified_ids(self):
        provider = RtssProvider(reader([
            {"id": "fps", "name": "FPS", "unit": "FPS", "value": 144},
            {"id": "frametime", "name": "Frametime", "unit": "ms", "value": 6.9},
        ]))
        manager = SensorManager([provider]); manager.select(["RTSS:fps"])
        self.assertEqual([value.id for value in manager.poll().values], ["fps"])

    def test_provider_failure_isolation(self):
        bad = HwinfoProvider(reader([]), decoder=lambda _snapshot: (_ for _ in ()).throw(ValueError("corrupt")))
        good = Aida64Provider(reader([{"id": "ok", "name": "CPU Temperature", "value": 55}]))
        snapshot = SensorManager([bad, good]).poll()
        self.assertEqual([value.id for value in snapshot.values], ["ok"])
        self.assertFalse(snapshot.provider_status[0].available)
        self.assertTrue(snapshot.provider_status[1].available)

    def test_duplicate_opt_in_preserves_both_sources(self):
        record = [{"id": "temp", "name": "GPU Temperature", "unit": "C", "value": 60,
                   "canonical_key": "gpu.temperature"}]
        result = SensorManager([HwinfoProvider(reader(record)), Aida64Provider(reader(record))],
                               include_duplicates=True).poll()
        self.assertEqual(len(result.values), 2)

    def test_semantic_mapping_is_cached_until_definition_set_changes(self):
        from thermalright_lcd.sensors import SemanticResolverCache,SensorDefinition,SensorValue
        cache=SemanticResolverCache();definition=SensorDefinition("temp","HWiNFO","CPU (Tctl/Tdie)","CPU","°C");roles={"cpu.temperature":"cpu_temp"}
        first=SensorValue.now(definition,60);second=SensorValue.now(definition,61)
        self.assertEqual(cache.resolve(roles,[first])["cpu.temperature"].value,60);self.assertEqual(cache.resolve(roles,[second])["cpu.temperature"].value,61);self.assertEqual(cache.rebuilds,1)
        extra=SensorValue.now(SensorDefinition("fps","RTSS","Framerate","Game","FPS"),120);cache.resolve(roles,[second,extra]);self.assertEqual(cache.rebuilds,2)


if __name__ == "__main__": unittest.main()
