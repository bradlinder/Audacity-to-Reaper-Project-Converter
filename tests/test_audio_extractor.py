"""Tests for sampleblocks extraction and WAV file generation."""

import struct
import tempfile
import unittest
import wave
from pathlib import Path

from audacity_to_reaper.audio_extractor import AudioExtractor, sanitize_filename, write_wav_file
from audacity_to_reaper.models import Clip, SampleBlock


class TestAudioExtractor(unittest.TestCase):
    """Test suite for WAV writer and audio block stitching."""

    def test_sanitize_filename(self):
        self.assertEqual(sanitize_filename("Vocal: Lead? / Master*"), "Vocal_Lead_Master")
        self.assertEqual(sanitize_filename("Track #1 (Bass)"), "Track_#1_(Bass)")
        self.assertEqual(sanitize_filename("   "), "audio")

    def test_write_16bit_wav(self):
        """Test writing 16-bit integer PCM WAV."""
        samples_pcm = struct.pack("<4h", 0, 16384, -16384, 0)
        with tempfile.TemporaryDirectory() as tmp_dir:
            wav_path = Path(tmp_dir) / "test_16bit.wav"
            bytes_written = write_wav_file(
                output_path=wav_path,
                raw_samples=samples_pcm,
                sample_rate=44100,
                channels=1,
                sample_format=131073,  # 16-bit PCM
            )
            self.assertTrue(wav_path.exists())
            self.assertGreater(bytes_written, len(samples_pcm))

            with wave.open(str(wav_path), "rb") as w:
                self.assertEqual(w.getnchannels(), 1)
                self.assertEqual(w.getsampwidth(), 2)
                self.assertEqual(w.getframerate(), 44100)
                self.assertEqual(w.getnframes(), 4)

    def test_write_32bit_float_wav(self):
        """Test writing 32-bit IEEE float WAV."""
        samples_float = struct.pack("<4f", 0.0, 0.5, -0.5, 0.0)
        with tempfile.TemporaryDirectory() as tmp_dir:
            wav_path = Path(tmp_dir) / "test_float.wav"
            bytes_written = write_wav_file(
                output_path=wav_path,
                raw_samples=samples_float,
                sample_rate=48000,
                channels=1,
                sample_format=262159,  # 32-bit float
            )
            self.assertTrue(wav_path.exists())
            self.assertEqual(bytes_written, 44 + 16)

            # Read back header directly
            with open(wav_path, "rb") as f:
                header = f.read(44)
                format_tag, channels, rate = struct.unpack("<HHI", header[20:28])
                self.assertEqual(format_tag, 3)  # WAVE_FORMAT_IEEE_FLOAT
                self.assertEqual(channels, 1)
                self.assertEqual(rate, 48000)

    def test_filename_deduplication(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            extractor = AudioExtractor(Path("dummy.aup3"), Path(tmp_dir))
            f1 = extractor.generate_clip_filename("Track A", 0, 1.25)
            f2 = extractor.generate_clip_filename("Track A", 0, 1.25)
            self.assertNotEqual(f1, f2)
            self.assertEqual(f1, "Track_A_0_001.250s.wav")
            self.assertEqual(f2, "Track_A_0_001.250s_1.wav")

    def test_interleave_stereo_channels_16bit(self):
        """Test interleaving 16-bit signed PCM left and right channels."""
        from audacity_to_reaper.audio_extractor import interleave_stereo_channels
        left = struct.pack("<3h", 100, 200, 300)
        right = struct.pack("<3h", 1000, 2000, 3000)

        interleaved = interleave_stereo_channels(left, right, sample_width=2)
        # Should be L0, R0, L1, R1, L2, R2
        unpacked = struct.unpack("<6h", interleaved)
        self.assertEqual(unpacked, (100, 1000, 200, 2000, 3000 // 10 * 1, 3000))
        self.assertEqual(unpacked, (100, 1000, 200, 2000, 300, 3000))

    def test_interleave_stereo_channels_32bit_float(self):
        """Test interleaving 32-bit float left and right channels."""
        from audacity_to_reaper.audio_extractor import interleave_stereo_channels
        left = struct.pack("<2f", 0.25, 0.75)
        right = struct.pack("<2f", -0.25, -0.75)

        interleaved = interleave_stereo_channels(left, right, sample_width=4)
        unpacked = struct.unpack("<4f", interleaved)
        self.assertAlmostEqual(unpacked[0], 0.25)
        self.assertAlmostEqual(unpacked[1], -0.25)
        self.assertAlmostEqual(unpacked[2], 0.75)
        self.assertAlmostEqual(unpacked[3], -0.75)

    def test_interleave_unequal_lengths_padding(self):
        """Test that shorter channel is zero-padded to match the longer channel."""
        from audacity_to_reaper.audio_extractor import interleave_stereo_channels
        left = struct.pack("<3h", 10, 20, 30)
        right = struct.pack("<1h", 99)

        interleaved = interleave_stereo_channels(left, right, sample_width=2)
        unpacked = struct.unpack("<6h", interleaved)
        self.assertEqual(unpacked, (10, 99, 20, 0, 30, 0))

    def test_extract_stereo_clip_audio_wav(self):
        """Test end-to-end stereo WAV extraction with distinct Left and Right sample blocks."""
        import sqlite3
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_db = Path(tmp_dir) / "test.aup3"
            conn = sqlite3.connect(str(tmp_db))
            conn.execute("CREATE TABLE sampleblocks (blockid INTEGER PRIMARY KEY, sampleformat INTEGER, samples BLOB);")

            # Left channel sample block: 4 samples of float 0.5
            l_data = struct.pack("<4f", 0.1, 0.2, 0.3, 0.4)
            # Right channel sample block: 4 samples of float -0.5
            r_data = struct.pack("<4f", -0.1, -0.2, -0.3, -0.4)

            conn.execute("INSERT INTO sampleblocks VALUES (101, 262159, ?);", (l_data,))
            conn.execute("INSERT INTO sampleblocks VALUES (102, 262159, ?);", (r_data,))
            conn.commit()

            media_dir = Path(tmp_dir) / "media"
            extractor = AudioExtractor(tmp_db, media_dir)

            clip = Clip(
                name="Stereo Music",
                clip_index=0,
                offset=0.0,
                sample_rate=44100,
                channels=2,
                sample_format=262159,
                blocks=[SampleBlock(block_id=101, start=0, length=4)],
                right_blocks=[SampleBlock(block_id=102, start=0, length=4)],
            )

            out_path, dur, bytes_written = extractor.extract_clip_audio(clip, "Synth", conn)
            conn.close()

            self.assertIsNotNone(out_path)
            self.assertTrue(out_path.exists())

            # Read back header directly to verify 2-channel float WAV
            with open(out_path, "rb") as f:
                header = f.read(44)
                format_tag, channels, rate = struct.unpack("<HHI", header[20:28])
                self.assertEqual(format_tag, 3)  # IEEE Float
                self.assertEqual(channels, 2)    # 2 Channels (True Stereo)
                self.assertEqual(rate, 44100)

                # Check interleaved sample data: 4 frames * 2 channels = 8 floats = 32 bytes
                body = f.read(32)
                samples = struct.unpack("<8f", body)
                self.assertAlmostEqual(samples[0], 0.1)   # L0
                self.assertAlmostEqual(samples[1], -0.1)  # R0
                self.assertAlmostEqual(samples[2], 0.2)   # L1
                self.assertAlmostEqual(samples[3], -0.2)  # R1


if __name__ == "__main__":
    unittest.main()
