import tempfile
import unittest
from pathlib import Path

from thermalright_lcd.encoder import encode_5302,encode_5408,validate_5302,validate_5408,prepare_generated_transaction,write_encoded,jpeg_payload,reframe_encoded

ROOT=Path(__file__).resolve().parents[1]


class EncoderTests(unittest.TestCase):
    def test_reframe_rebuilds_objects_but_preserves_exact_jpeg_and_wire_bytes(self):
        for pid,path in (("0416:5408",ROOT/"captures/generated/test-media/dual-generated-pid5408.jpg"),("0416:5302",ROOT/"captures/generated/test-media/dual-generated-pid5302.jpg")):
            jpeg=path.read_bytes();encoded=encode_5408(jpeg) if pid.endswith("5408") else encode_5302(jpeg);fresh=reframe_encoded(encoded)
            self.assertIsNot(fresh,encoded);self.assertEqual(jpeg_payload(fresh),jpeg);self.assertEqual(fresh.writes,encoded.writes)
            self.assertTrue((validate_5408(fresh) if pid.endswith("5408") else validate_5302(fresh))["valid"])
    def test_5408_capture_jpeg_roundtrip(self):
        jpeg=(ROOT/"analysis/display_9_16/extracted_frames/frame_0001.jpg").read_bytes()
        e=encode_5408(jpeg); r=validate_5408(e)
        self.assertTrue(r["valid"]); self.assertTrue(r["indices_contiguous"]); self.assertTrue(r["padding_zero"])
        self.assertEqual(r["command"],1)
        self.assertEqual(r["declared_chunk_count"],615)
        self.assertTrue(r["headers_valid"]); self.assertTrue(r["payload_lengths_valid"])
        self.assertEqual((len(e.writes),e.total_bytes),(77,315392))
    def test_5302_capture_jpeg_roundtrip(self):
        jpeg=(ROOT/"analysis/display_6/extracted_frames/frame_0001.jpg").read_bytes()
        e=encode_5302(jpeg); r=validate_5302(e)
        self.assertTrue(r["valid"]); self.assertTrue(r["padding_zero"])
    def test_dimension_and_eoi_rejection(self):
        a=(ROOT/"analysis/display_9_16/extracted_frames/frame_0001.jpg").read_bytes()
        b=(ROOT/"analysis/display_6/extracted_frames/frame_0001.jpg").read_bytes()
        with self.assertRaises(ValueError): encode_5302(a)
        with self.assertRaises(ValueError): encode_5408(b)
        with self.assertRaises(ValueError): encode_5408(a[:-2])
    def test_generated_5408_live_sequence_preparation(self):
        out=ROOT/"analysis/display_9_16/generated-static-9.16"
        target=ROOT/"analysis/display_9_16/generated-sequence-test.json"
        report=prepare_generated_transaction(out,ROOT/"analysis/pid5408-new-session-first-frame.json",target)
        self.assertEqual(report["source_kind"],"generated")
        data=__import__('json').loads(target.read_text())
        tx=data["devices"]["0416:5408"]["transactions"][0]
        self.assertEqual(int.from_bytes(bytes.fromhex(tx["header_hex"])[9:11],"little"),tx["protocol_chunk_count"] if "protocol_chunk_count" in tx else 296)
        self.assertEqual(tx["transfer_count"],37)
    def test_generated_5408_half_host_write_boundary(self):
        jpeg=(ROOT/"captures/generated/test-media/dual-generated-pid5408.jpg").read_bytes();e=encode_5408(jpeg);r=validate_5408(e)
        self.assertTrue(r["valid"]);self.assertEqual(e.writes[-1].__len__(),2048);self.assertEqual(r["declared_chunk_count"],234)
        target=ROOT/"analysis/pid5408-dual-generated-test-regression.json"
        report=prepare_generated_transaction(ROOT/"analysis/display_9_16/dual-generated-test",ROOT/"analysis/pid5408-new-session-first-frame.json",target)
        self.assertEqual((report["write_count"],report["frame_bytes"]),(30,120832))
    def test_generated_5302_live_sequence_preparation(self):
        out=ROOT/"analysis/display_6/generated-static-6"
        target=ROOT/"analysis/display_6/generated-sequence-test.json"
        report=prepare_generated_transaction(out,ROOT/"analysis/pid5302-same-session-first-frame.json",target)
        self.assertEqual(report["sequence_id"],"0416:5302/generated-sequence-test-transaction-1")
        data=__import__('json').loads(target.read_text());tx=data["devices"]["0416:5302"]["transactions"][0]
        self.assertEqual(bytes.fromhex(tx["header_hex"])[:4],bytes.fromhex("dadbdcdd"));self.assertIsNone(tx["expected_response"])
    def test_reencoding_removes_stale_tail_writes(self):
        with tempfile.TemporaryDirectory() as d:
            out=Path(d);large=ROOT/"analysis/live-5302-hid-transmitted-frame.jpg";small=ROOT/"captures/generated/test-media/dual-generated-pid5302.jpg"
            first=write_encoded(large,out,"0416:5302");second=write_encoded(small,out,"0416:5302")
            self.assertLess(second["write_count"],first["write_count"]);self.assertEqual(len(list(out.glob("write_*.bin"))),second["write_count"])
