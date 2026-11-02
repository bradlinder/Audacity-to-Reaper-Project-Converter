"""End-to-end integration tests for aup3-to-reaper."""

import sqlite3
import struct
import tempfile
import unittest
from pathlib import Path

from audacity_to_reaper.converter import convert_audacity_to_reaper


def create_sample_aup3(db_path: Path) -> None:
    """Create a realistic SQLite .aup3 database with XML, tracks, clips, and sample blocks."""
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()

    xml_content = """<?xml version="1.0" standalone="no" ?>
<project xmlns="http://audacity.sourceforge.net/xml/" projname="Podcast_Ep1" version="1.3.0" audacityversion="3.4.2" rate="48000">
  <wavetrack name="Host Mic" channel="0" linked="0" mute="0" solo="0" rate="48000" gain="1.2" pan="-0.1">
    <waveclip offset="1.50000000" trimLeft="0.10000000" trimRight="0.05000000" clipStretchRatio="1.00000000">
      <sequence maxsamples="262144" sampleformat="262159" numsamples="48000">
        <waveblock start="0">
          <simpleblockfile blockid="101" len="24000"/>
        </waveblock>
        <waveblock start="24000">
          <simpleblockfile blockid="102" len="24000"/>
        </waveblock>
      </sequence>
    </waveclip>
    <effects active="1">
      <effect id="Audacity:Audacity:builtin:compressor:Compressor" active="1" version="1.0">
        <parameters>
          <parameter name="Threshold" value="-16.0" />
          <parameter name="Ratio" value="3.5" />
          <parameter name="AttackTime" value="0.08" />
          <parameter name="ReleaseTime" value="0.6" />
        </parameters>
      </effect>
    </effects>
  </wavetrack>
  <wavetrack name="Guest Mic" channel="0" linked="0" mute="0" solo="0" rate="48000" gain="0.9" pan="0.2">
    <waveclip offset="3.00000000" trimLeft="0.00000000" trimRight="0.00000000" clipStretchRatio="1.00000000">
      <sequence maxsamples="262144" sampleformat="131073" numsamples="24000">
        <waveblock start="0">
          <simpleblockfile blockid="201" len="24000"/>
        </waveblock>
      </sequence>
    </waveclip>
  </wavetrack>
  <labeltrack name="Episode Markers" numlabels="2">
    <label t="1.50000000" t1="1.50000000" title="Intro Voice" />
    <label t="3.00000000" t1="10.00000000" title="Interview Segment" />
  </labeltrack>
</project>"""

    cur.execute("CREATE TABLE project (id INTEGER PRIMARY KEY, dict TEXT, doc TEXT);")
    cur.execute("INSERT INTO project (id, dict, doc) VALUES (1, '', ?);", (xml_content,))

    cur.execute("""
        CREATE TABLE sampleblocks (
            blockid INTEGER PRIMARY KEY,
            sampleformat INTEGER,
            summin REAL,
            summax REAL,
            sumrms REAL,
            summary256 BLOB,
            summary64k BLOB,
            samples BLOB
        );
    """)

    # 101 & 102: 32-bit float (24000 samples each = 96000 bytes each)
    samples_float1 = struct.pack("<24000f", *([0.05] * 24000))
    samples_float2 = struct.pack("<24000f", *([-0.05] * 24000))
    cur.execute(
        "INSERT INTO sampleblocks VALUES (101, 262159, -0.05, 0.05, 0.05, NULL, NULL, ?);",
        (samples_float1,),
    )
    cur.execute(
        "INSERT INTO sampleblocks VALUES (102, 262159, -0.05, 0.05, 0.05, NULL, NULL, ?);",
        (samples_float2,),
    )

    # 201: 16-bit PCM (24000 samples = 48000 bytes)
    samples_pcm = struct.pack("<24000h", *([1000] * 24000))
    cur.execute(
        "INSERT INTO sampleblocks VALUES (201, 131073, -1000.0, 1000.0, 1000.0, NULL, NULL, ?);",
        (samples_pcm,),
    )

    conn.commit()
    conn.close()


class TestEndToEndConversion(unittest.TestCase):
    """End-to-end integration tests."""

    def test_full_conversion(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            aup3_file = tmp_path / "Podcast_Ep1.aup3"
            out_dir = tmp_path / "output_reaper"

            create_sample_aup3(aup3_file)

            result = convert_audacity_to_reaper(
                aup3_path=aup3_file,
                output_dir=out_dir,
                extract_fx_script=True,
                dry_run=False,
            )

            self.assertTrue(result.success)
            self.assertEqual(result.total_tracks, 2)
            self.assertEqual(result.total_clips, 2)
            self.assertEqual(result.total_extracted_files, 2)

            # Check that deliverables exist
            self.assertTrue(result.rpp_file.exists())
            self.assertTrue(result.report_file.exists())
            self.assertTrue(result.fx_script_file.exists())
            self.assertTrue(result.media_dir.exists())

            # Check extracted media WAV files
            media_files = list(result.media_dir.glob("*.wav"))
            self.assertEqual(len(media_files), 2)

            # Check .rpp content
            with open(result.rpp_file, "r", encoding="utf-8") as f:
                rpp_text = f.read()
                self.assertIn('<REAPER_PROJECT 0.1 "7.0"', rpp_text)
                self.assertIn("SAMPLERATE 48000 0 0", rpp_text)
                self.assertIn('NAME "Host Mic"', rpp_text)
                self.assertIn('NAME "Guest Mic"', rpp_text)
                self.assertIn('MARKER 1 1.500000 "Intro Voice" 0 0 1', rpp_text)
                self.assertIn('MARKER 1 3.000000 "Interview Segment" 1 0 1', rpp_text)
                self.assertIn('MARKER 1 10.000000 "" 1', rpp_text)
                self.assertIn("POSITION 1.600000", rpp_text)
                self.assertIn("SOFFS 0.100000", rpp_text)

            # Check ReaScript Lua
            with open(result.fx_script_file, "r", encoding="utf-8") as f:
                lua_text = f.read()
                self.assertIn("VST:ReaComp (Cockos)", lua_text)
                self.assertIn("reaper.TrackFX_SetParam(track, fx_idx, 0, -16.0)", lua_text)
                self.assertIn("reaper.TrackFX_SetParam(track, fx_idx, 1, 3.5)", lua_text)
                self.assertIn("reaper.TrackFX_SetParam(track, fx_idx, 2, 80.0)", lua_text)
                self.assertIn("reaper.TrackFX_SetParam(track, fx_idx, 3, 600.0)", lua_text)

            # Check migration report
            with open(result.report_file, "r", encoding="utf-8") as f:
                report_text = f.read()
                self.assertIn("# Audacity to REAPER Migration Report", report_text)
                self.assertIn("Podcast_Ep1", report_text)
                self.assertIn("Host Mic", report_text)
                self.assertIn("Guest Mic", report_text)
                self.assertIn("ReaComp (Cockos)", report_text)

    def test_dry_run_mode(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            aup3_file = tmp_path / "Podcast_Ep1.aup3"
            out_dir = tmp_path / "output_dry"

            create_sample_aup3(aup3_file)

            result = convert_audacity_to_reaper(
                aup3_path=aup3_file,
                output_dir=out_dir,
                extract_fx_script=True,
                dry_run=True,
            )

            self.assertTrue(result.success)
            self.assertTrue(result.is_dry_run)
            self.assertFalse(out_dir.exists())  # No files or directories created!


if __name__ == "__main__":
    unittest.main()
