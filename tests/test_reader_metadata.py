"""Unit tests for Audacity XML parsing of clip color, gain, pitch, and project tempo."""

import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from audacity_to_reaper.aup3_reader import AUP3Reader
from audacity_to_reaper.models import AudacityProject


class TestReaderMetadata(unittest.TestCase):
    """Test suite for Audacity XML metadata extraction."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".aup3", delete=False)
        self.tmp_path = Path(self.tmp.name)
        self.tmp.close()
        self.reader = AUP3Reader(self.tmp_path)

    def tearDown(self):
        if self.tmp_path.exists():
            self.tmp_path.unlink()

    def test_parse_project_tempo_and_timesig(self):
        xml_text = """<project tempo="136" timesig="6/8" rate="48000">
            <wavetrack name="Acoustic Guitar" rate="48000" gain="1.0" pan="0.0">
            </wavetrack>
        </project>"""
        root = ET.fromstring(xml_text)
        proj = AudacityProject(project_path=self.tmp_path)
        self.reader._parse_from_xml(root, proj)

        self.assertEqual(proj.tempo, 136.0)
        self.assertEqual(proj.time_sig_numerator, 6)
        self.assertEqual(proj.time_sig_denominator, 8)
        self.assertEqual(proj.sample_rate, 48000.0)

    def test_parse_waveclip_gain_pitch_color(self):
        xml_text = """<project rate="44100">
            <wavetrack name="Lead" rate="44100">
                <waveclip name="Vocal Take 2" offset="1.5" trimLeft="0.2" clipStretchRatio="1.0"
                          gain="1.25" pitch="2.5" colorindex="3">
                    <sequence numsamples="44100" sampleformat="262159">
                    </sequence>
                </waveclip>
            </wavetrack>
        </project>"""
        root = ET.fromstring(xml_text)
        proj = AudacityProject(project_path=self.tmp_path)
        self.reader._parse_from_xml(root, proj)

        self.assertEqual(len(proj.tracks), 1)
        self.assertEqual(len(proj.tracks[0].clips), 1)
        clip = proj.tracks[0].clips[0]

        self.assertEqual(clip.name, "Vocal Take 2")
        self.assertAlmostEqual(clip.gain, 1.25)
        self.assertAlmostEqual(clip.pitch_semitones, 2.5)
        self.assertEqual(clip.color_index, 3)

    def test_parse_waveclip_custom_hex_color(self):
        xml_text = """<project rate="44100">
            <wavetrack name="Bass" rate="44100">
                <waveclip name="Bass Loop" offset="0.0" color="#10B981">
                    <sequence numsamples="44100" sampleformat="262159">
                    </sequence>
                </waveclip>
            </wavetrack>
        </project>"""
        root = ET.fromstring(xml_text)
        proj = AudacityProject(project_path=self.tmp_path)
        self.reader._parse_from_xml(root, proj)

        clip = proj.tracks[0].clips[0]
        self.assertEqual(clip.color_rgb, (16, 185, 129))

    def test_parse_true_stereo_track_and_clip(self):
        """Verify parsing a true stereo track with two <sequence> elements."""
        xml_text = """<project rate="48000">
            <wavetrack name="Stereo Beats" rate="48000" channel="2">
                <waveclip name="Drum Loop" offset="0.0">
                    <sequence channel="0" numsamples="48000" sampleformat="262159">
                        <waveblock start="0" blockid="1"/>
                    </sequence>
                    <sequence channel="1" numsamples="48000" sampleformat="262159">
                        <waveblock start="0" blockid="2"/>
                    </sequence>
                </waveclip>
            </wavetrack>
        </project>"""
        root = ET.fromstring(xml_text)
        proj = AudacityProject(project_path=self.tmp_path)
        self.reader._parse_from_xml(root, proj)

        self.assertEqual(len(proj.tracks), 1)
        track = proj.tracks[0]
        self.assertEqual(track.channel, 2)
        self.assertEqual(len(track.clips), 1)

        clip = track.clips[0]
        self.assertEqual(clip.channels, 2)
        self.assertEqual(len(clip.blocks), 1)
        self.assertEqual(clip.blocks[0].block_id, 1)
        self.assertEqual(len(clip.right_blocks), 1)
        self.assertEqual(clip.right_blocks[0].block_id, 2)

    def test_parse_linked_stereo_track_pairs(self):
        """Verify that consecutive linked tracks (ch 0 linked + ch 1) form stereo pairs and group clips."""
        xml_text = """<project rate="44100">
            <wavetrack name="Overheads" rate="44100" channel="0" linked="1">
                <waveclip name="OH L" offset="1.0">
                    <sequence numsamples="44100" sampleformat="262159">
                        <waveblock start="0" blockid="11"/>
                    </sequence>
                </waveclip>
            </wavetrack>
            <wavetrack name="Overheads" rate="44100" channel="1" linked="0">
                <waveclip name="OH R" offset="1.0">
                    <sequence numsamples="44100" sampleformat="262159">
                        <waveblock start="0" blockid="12"/>
                    </sequence>
                </waveclip>
            </wavetrack>
        </project>"""
        root = ET.fromstring(xml_text)
        proj = AudacityProject(project_path=self.tmp_path)
        self.reader._parse_from_xml(root, proj)

        self.assertEqual(len(proj.tracks), 2)
        t_left = proj.tracks[0]
        t_right = proj.tracks[1]

        self.assertEqual(t_left.stereo_pair_id, 1)
        self.assertEqual(t_right.stereo_pair_id, 1)

        # Both clips should be assigned the same group_id
        self.assertGreater(t_left.clips[0].group_id, 0)
        self.assertEqual(t_left.clips[0].group_id, t_right.clips[0].group_id)


if __name__ == "__main__":
    unittest.main()
