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


if __name__ == "__main__":
    unittest.main()
