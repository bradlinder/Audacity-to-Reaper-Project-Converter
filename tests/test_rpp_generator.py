"""Tests for REAPER .rpp project generator."""

import tempfile
import unittest
from pathlib import Path

from audacity_to_reaper.models import AudacityProject, Clip, Marker, Region, Track
from audacity_to_reaper.rpp_generator import RPPGenerator


class TestRPPGenerator(unittest.TestCase):
    """Test suite for REAPER RPP plain-text generation."""

    def test_rpp_structure(self):
        project = AudacityProject(
            project_path=Path("demo.aup3"),
            name="DemoSession",
            sample_rate=48000,
        )

        track1 = Track(
            track_id=1,
            name="Lead Vocals",
            gain=0.8,
            pan=-0.25,
            mute=False,
            solo=True,
        )
        clip1 = Clip(
            name="Verse 1",
            clip_index=0,
            offset=5.0,
            trim_left=0.5,
            trim_right=0.2,
            stretch_ratio=1.0,
            sample_rate=48000,
            num_samples=48000 * 4,  # 4 seconds raw
            extracted_filename="Lead_Vocals_0_005.000s.wav",
        )
        track1.clips.append(clip1)
        project.tracks.append(track1)

        # Markers and Regions
        project.markers.append(Marker(marker_id=1, position=5.0, name="Verse Start"))
        project.regions.append(Region(region_id=1, start_position=5.0, end_position=15.0, name="Verse Section"))

        with tempfile.TemporaryDirectory() as tmp_dir:
            out_rpp = Path(tmp_dir) / "demo.rpp"
            gen = RPPGenerator(project, out_rpp)
            text = gen.generate()

            # Verify header
            self.assertIn('<REAPER_PROJECT 0.1 "7.0"', text)
            self.assertIn("SAMPLERATE 48000 0 0", text)

            # Verify Notes chunk
            self.assertIn("<NOTES", text)
            self.assertIn("|Migrated from Audacity: DemoSession.aup3", text)

            # Verify Marker & Region
            self.assertIn('MARKER 1 5.000000 "Verse Start" 0 0 1', text)
            self.assertIn('MARKER 1 5.000000 "Verse Section" 1 0 1', text)
            self.assertIn('MARKER 1 15.000000 "" 1', text)

            # Verify Track & Item
            self.assertIn('NAME "Lead Vocals"', text)
            self.assertIn("VOLPAN 0.800000 -0.250000", text)
            self.assertIn("MUTESOLO 0 1 0", text)  # Mute=0, Solo=1
            self.assertIn("<ITEM", text)
            self.assertIn("POSITION 5.500000", text)
            self.assertIn("SOFFS 0.500000", text)
            # Duration: 4.0 - 0.5 - 0.2 = 3.3s
            self.assertIn("LENGTH 3.300000", text)
            self.assertIn('FILE "media/Lead_Vocals_0_005.000s.wav"', text)

            # Ensure invalid tokens are not present
            self.assertNotIn("ENVFADETYPE", text)
            for line in text.splitlines():
                stripped = line.strip()
                self.assertFalse(stripped.startswith("PAN "), f"Invalid standalone PAN token found: {line}")

    def test_take_volume_envelope(self):
        """Verify that Audacity envelope control points translate into REAPER <VOLENV> chunks."""
        project = AudacityProject(project_path=Path("demo.aup3"), name="EnvTest", sample_rate=44100)
        track = Track(track_id=1, name="Ambient")
        clip = Clip(
            name="Opening chatter",
            clip_index=0,
            offset=0.0,
            trim_left=0.0,
            trim_right=0.0,
            sample_rate=44100,
            num_samples=44100 * 10,
            envelope_points=[(0.0, 0.5), (2.0, 1.0), (8.0, 0.4), (10.0, 0.0)],
        )
        track.clips.append(clip)
        project.tracks.append(track)

        with tempfile.TemporaryDirectory() as tmp_dir:
            out_rpp = Path(tmp_dir) / "env_test.rpp"
            gen = RPPGenerator(project, out_rpp)
            text = gen.generate()

            self.assertIn("<VOLENV", text)
            self.assertIn("PT 0.000000 0.500000 0 0", text)
            self.assertIn("PT 2.000000 1.000000 0 0", text)
            self.assertIn("PT 8.000000 0.400000 0 0", text)
            self.assertIn("PT 10.000000 0.000000 0 0", text)


if __name__ == "__main__":
    unittest.main()
