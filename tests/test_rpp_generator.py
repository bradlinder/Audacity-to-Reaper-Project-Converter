"""Tests for REAPER .rpp project generator."""

import tempfile
import unittest
from pathlib import Path

from audacity_to_reaper.models import AudacityProject, Clip, Effect, Marker, Region, Track
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
            self.assertIn("<VOLENV\n", text)
            self.assertNotIn("<VOLENV2", text)
            self.assertIn("|Volume Envelope Mode: Take/Clip Envelopes (VOLENV)", text)

    def test_track_volume_envelope_mode(self):
        """Verify that envelope_mode='track' emits <VOLENV2> under <TRACK> with absolute timestamps and omits take <VOLENV>."""
        project = AudacityProject(project_path=Path("demo.aup3"), name="TrackEnvTest", sample_rate=44100)
        track = Track(track_id=1, name="Dialogue")
        # Clip starting at timeline 5.0 seconds
        clip = Clip(
            name="Speech",
            clip_index=0,
            offset=5.0,
            trim_left=0.0,
            trim_right=0.0,
            sample_rate=44100,
            num_samples=44100 * 4,
            envelope_points=[(0.0, 0.2), (1.5, 0.8), (4.0, 0.0)],
        )
        track.clips.append(clip)
        project.tracks.append(track)

        with tempfile.TemporaryDirectory() as tmp_dir:
            out_rpp = Path(tmp_dir) / "track_env.rpp"
            gen = RPPGenerator(project, out_rpp, envelope_mode="track")
            text = gen.generate()

            # Should contain <VOLENV2 in track chunk
            self.assertIn("<VOLENV2", text)
            # Timestamps must be shifted by timeline_offset (5.0):
            # 0.0 -> 5.0, 1.5 -> 6.5, 4.0 -> 9.0
            self.assertIn("PT 5.000000 0.200000 0 0", text)
            self.assertIn("PT 6.500000 0.800000 0 0", text)
            self.assertIn("PT 9.000000 0.000000 0 0", text)

            # Should NOT contain take-level <VOLENV
            self.assertNotIn("<VOLENV\n", text)
            self.assertIn("|Volume Envelope Mode: Track Automation Lanes (VOLENV2)", text)

    def test_tempo_and_grid_synchronization(self):
        """Verify that project tempo and time signature write to REAPER header, TEMPOENV, and NOTES."""
        project = AudacityProject(
            project_path=Path("demo.aup3"),
            name="TempoTest",
            sample_rate=44100,
            tempo=142.5,
            time_sig_numerator=3,
            time_sig_denominator=4,
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            out_rpp = Path(tmp_dir) / "tempo_test.rpp"
            gen = RPPGenerator(project, out_rpp)
            text = gen.generate()

            self.assertIn("TEMPO 142.500000 3 4", text)
            self.assertIn("<TEMPOENV", text)
            self.assertIn("PT 0.000000 142.500000 1 3 4 0", text)
            self.assertIn("|Tempo: 142.50 BPM (3/4)", text)

    def test_clip_colors_and_reaper_setcolor(self):
        """Verify that Audacity clip colorindex and custom RGB map to REAPER SETCOLOR integer tags."""
        project = AudacityProject(project_path=Path("demo.aup3"), name="ColorTest", sample_rate=44100)
        track = Track(track_id=1, name="ColorTrack")

        # Clip with Audacity palette index 1 (Red: RGB 239, 68, 68)
        clip_red = Clip(
            name="RedClip",
            clip_index=0,
            offset=0.0,
            sample_rate=44100,
            num_samples=44100,
            color_index=1,
        )
        # Clip with custom RGB (10, 20, 30) -> 0x01000000 | 10 | (20 << 8) | (30 << 16)
        clip_custom = Clip(
            name="CustomClip",
            clip_index=1,
            offset=2.0,
            sample_rate=44100,
            num_samples=44100,
            color_rgb=(10, 20, 30),
        )
        track.clips.extend([clip_red, clip_custom])
        project.tracks.append(track)

        with tempfile.TemporaryDirectory() as tmp_dir:
            out_rpp = Path(tmp_dir) / "color_test.rpp"
            gen = RPPGenerator(project, out_rpp)
            text = gen.generate()

            # Red: R=239 (0xEF), G=68 (0x44), B=68 (0x44) -> 0x01000000 | 239 | (68 << 8) | (68 << 16)
            expected_red = 0x01000000 | 239 | (68 << 8) | (68 << 16)
            self.assertIn(f"SETCOLOR {expected_red}", text)

            expected_custom = 0x01000000 | 10 | (20 << 8) | (30 << 16)
            self.assertIn(f"SETCOLOR {expected_custom}", text)

    def test_clip_gain_and_pitch_shift(self):
        """Verify that per-clip gain and non-destructive pitch shift emit to VOLPAN and PITCH in REAPER."""
        project = AudacityProject(project_path=Path("demo.aup3"), name="GainPitchTest", sample_rate=44100)
        track = Track(track_id=1, name="Synth")
        clip = Clip(
            name="Lead Solo",
            clip_index=0,
            offset=1.0,
            sample_rate=44100,
            num_samples=44100 * 2,
            gain=1.414,
            pitch_semitones=3.5,
        )
        track.clips.append(clip)
        project.tracks.append(track)

        with tempfile.TemporaryDirectory() as tmp_dir:
            out_rpp = Path(tmp_dir) / "gain_pitch_test.rpp"
            gen = RPPGenerator(project, out_rpp)
            text = gen.generate()

            self.assertIn("VOLPAN 1.414000 0 1 -1", text)
            self.assertIn("PITCH 3.500000 0 0 -1 0 0.0025", text)

    def test_dual_mono_stereo_linked_tracks(self):
        """Verify that linked stereo track pairs get discrete Left/Right pans and shared GROUP IDs."""
        project = AudacityProject(project_path=Path("demo.aup3"), name="StereoPairTest", sample_rate=44100)

        # Left channel track
        track_l = Track(track_id=1, name="Stereo Piano", channel=0, linked=True)
        clip_l = Clip(
            name="Piano L",
            clip_index=0,
            offset=0.0,
            group_id=1001,
            sample_rate=44100,
            num_samples=44100,
        )
        track_l.clips.append(clip_l)

        # Right channel track
        track_r = Track(track_id=2, name="Stereo Piano", channel=1, linked=False)
        clip_r = Clip(
            name="Piano R",
            clip_index=0,
            offset=0.0,
            group_id=1001,
            sample_rate=44100,
            num_samples=44100,
        )
        track_r.clips.append(clip_r)

        project.tracks.extend([track_l, track_r])

        with tempfile.TemporaryDirectory() as tmp_dir:
            out_rpp = Path(tmp_dir) / "stereo_pair.rpp"
            gen = RPPGenerator(project, out_rpp)
            text = gen.generate()

            # Track L has pan -1.0 (Left), Track R has pan 1.0 (Right)
            self.assertIn("VOLPAN 1.000000 -1.000000 -1.0 -1.0 1.0", text)
            self.assertIn("VOLPAN 1.000000 1.000000 -1.0 -1.0 1.0", text)

            # Both items have the shared REAPER GROUP tag
            self.assertEqual(text.count("GROUP 1001"), 2)

    def test_true_stereo_track_generation(self):
        """Verify true 2-channel stereo track emission with NCHAN 2 and stereo clips."""
        project = AudacityProject(project_path=Path("demo.aup3"), name="TrueStereoTest", sample_rate=48000)
        track = Track(track_id=1, name="Master Synth", channel=2, pan=0.0)
        clip = Clip(
            name="Synth Pad",
            clip_index=0,
            offset=0.0,
            channels=2,
            sample_rate=48000,
            num_samples=48000 * 2,
        )
        track.clips.append(clip)
        project.tracks.append(track)

        with tempfile.TemporaryDirectory() as tmp_dir:
            out_rpp = Path(tmp_dir) / "true_stereo.rpp"
            gen = RPPGenerator(project, out_rpp)
            text = gen.generate()

            self.assertIn("NCHAN 2", text)
            self.assertIn("VOLPAN 1.000000 0.000000 -1.0 -1.0 1.0", text)
            self.assertIn("CHANMODE 0", text)

    def test_embedded_track_fxchain(self):
        """Verify that track effects embed directly into standard REAPER <FXCHAIN> blocks."""
        project = AudacityProject(project_path=Path("demo.aup3"), name="FXTest", sample_rate=44100)
        track = Track(track_id=1, name="Vocal Stem")
        track.effects.append(
            Effect(
                effect_id="Audacity:builtin:compressor",
                parameters={"Threshold": "-16.0", "Ratio": "3.5"},
                active=True,
            )
        )
        track.effects.append(
            Effect(
                effect_id="Audacity:builtin:equalizer",
                parameters={"HighpassCutoff": "90.0"},
                active=False,  # Bypassed
            )
        )
        project.tracks.append(track)

        with tempfile.TemporaryDirectory() as tmp_dir:
            out_rpp = Path(tmp_dir) / "fx_test.rpp"
            gen = RPPGenerator(project, out_rpp, embed_fx=True)
            text = gen.generate()

            # Verify <FXCHAIN block exists inside track
            self.assertIn("<FXCHAIN", text)
            self.assertIn("WNDRECT 0 0 0 0", text)

            # First effect: ReaComp (Active -> BYPASS 0 0 0)
            self.assertIn("BYPASS 0 0 0", text)
            self.assertIn('<VST "VST: ReaComp (Cockos)" "reacomp.dll" 0 "" 1919247213 ""', text)
            self.assertIn("FLOATPOS 0 0 0 0", text)
            self.assertIn("FXID {", text)
            self.assertIn("WAK 0 0", text)

            # Second effect: ReaEQ (Bypassed -> BYPASS 1 0 0)
            self.assertIn("BYPASS 1 0 0", text)
            self.assertIn('<VST "VST: ReaEQ (Cockos)" "reaeq.dll" 0 "" 1919247729 ""', text)

            # Verify Notes summary
            self.assertIn("Realtime FX Chains: 2 track effect(s) embedded directly in <FXCHAIN>", text)

    def test_vst3_chunk_data_embedding(self):
        """Verify third-party VST3 preserves binary chunk states and emits valid <VST3 chunk."""
        project = AudacityProject(project_path=Path("demo.aup3"), name="VST3ChunkTest", sample_rate=48000)
        track = Track(track_id=1, name="Master Track")
        chunk_payload = "QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVphYmNkZWZnaGlqa2xtbm9wcXJzdHV2d3h5ejAxMjM0NTY3ODk="
        track.effects.append(
            Effect(
                effect_id="VST3:FabFilter Pro-L 2",
                active=True,
                chunk_data=chunk_payload,
            )
        )
        project.tracks.append(track)

        with tempfile.TemporaryDirectory() as tmp_dir:
            out_rpp = Path(tmp_dir) / "vst3_test.rpp"
            gen = RPPGenerator(project, out_rpp, embed_fx=True)
            text = gen.generate()

            self.assertIn('<VST3 "VST3: FabFilter Pro-L 2" "FabFilter Pro-L 2.vst3" 0 "" 0 ""', text)
            self.assertIn(chunk_payload, text)
            self.assertIn("FXID {", text)

    def test_embed_fx_disabled_option(self):
        """Verify embed_fx=False omits <FXCHAIN> chunk from track."""
        project = AudacityProject(project_path=Path("demo.aup3"), name="NoFXTest", sample_rate=44100)
        track = Track(track_id=1, name="Track With FX")
        track.effects.append(Effect(effect_id="builtin:compressor"))
        project.tracks.append(track)

        with tempfile.TemporaryDirectory() as tmp_dir:
            out_rpp = Path(tmp_dir) / "no_fx.rpp"
            gen = RPPGenerator(project, out_rpp, embed_fx=False)
            text = gen.generate()

            self.assertNotIn("<FXCHAIN", text)

    def test_master_fxchain_embedding(self):
        """Verify master effects generate <MASTERFXCHAIN> chunk."""
        project = AudacityProject(project_path=Path("demo.aup3"), name="MasterFXTest", sample_rate=44100)
        project.master_effects.append(Effect(effect_id="builtin:limiter", active=True))

        with tempfile.TemporaryDirectory() as tmp_dir:
            out_rpp = Path(tmp_dir) / "master_fx.rpp"
            gen = RPPGenerator(project, out_rpp, embed_fx=True)
            text = gen.generate()

            self.assertIn("<MASTERFXCHAIN", text)
            self.assertIn('<VST "VST: ReaLimit (Cockos)" "realimit.dll" 0 "" 1919251053 ""', text)


if __name__ == "__main__":
    unittest.main()
