"""Audio block extractor and WAV file writer.

Stitches Audacity sample blocks per clip and writes standard uncompressed WAV files
(16-bit signed PCM or 32-bit IEEE float) with unique, human-readable filenames.
"""

from __future__ import annotations

import logging
import re
import sqlite3
import struct
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from .models import AudacityProject, Clip, Track

logger = logging.getLogger(__name__)


def sanitize_filename(name: str) -> str:
    """Sanitize string for safe cross-platform filesystem use."""
    # Replace illegal filesystem characters with underscores
    clean = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip()
    clean = re.sub(r"\s+", "_", clean)
    clean = re.sub(r"_+", "_", clean)
    clean = clean.strip("_")
    return clean or "audio"


def write_wav_file(
    output_path: Path,
    raw_samples: bytes,
    sample_rate: int = 44100,
    channels: int = 1,
    sample_format: int = 262159,
) -> int:
    """Write raw audio bytes to a clean standard WAV file.
    
    Supports:
    - 32-bit IEEE Float (format code 3, 4 bytes/sample)
    - 16-bit Signed PCM (format code 1, 2 bytes/sample)
    - 24-bit Signed PCM (format code 1, 3 bytes/sample)
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Determine format code and bit depth
    # 262159 = 0x0004000F (floatSample)
    # 131073 = 0x00020001 (int16Sample)
    # 262145 = 0x00040001 (int24Sample)
    if sample_format in (262159, 2):
        format_code = 3  # WAVE_FORMAT_IEEE_FLOAT
        bits_per_sample = 32
        sample_width = 4
    elif sample_format in (131073, 0, 16):
        format_code = 1  # WAVE_FORMAT_PCM
        bits_per_sample = 16
        sample_width = 2
    elif sample_format in (262145, 1, 24):
        format_code = 1  # WAVE_FORMAT_PCM
        bits_per_sample = 24
        sample_width = 3
    else:
        # Fallback based on high 16 bits if encoded as sample_width << 16
        sw = sample_format >> 16
        if sw == 4:
            format_code = 3
            bits_per_sample = 32
            sample_width = 4
        elif sw == 2:
            format_code = 1
            bits_per_sample = 16
            sample_width = 2
        else:
            format_code = 3
            bits_per_sample = 32
            sample_width = 4

    block_align = channels * sample_width
    byte_rate = sample_rate * block_align
    data_size = len(raw_samples)
    riff_chunk_size = 36 + data_size

    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        riff_chunk_size,
        b"WAVE",
        b"fmt ",
        16,  # Subchunk1Size for PCM/Float
        format_code,
        channels,
        int(sample_rate),
        byte_rate,
        block_align,
        bits_per_sample,
        b"data",
        data_size,
    )

    with open(output_path, "wb") as f:
        f.write(header)
        f.write(raw_samples)

    return len(header) + len(raw_samples)


class AudioExtractor:
    """Extracts raw sample blocks from SQLite database and writes WAV files per clip."""

    def __init__(self, db_path: Path, media_dir: Path) -> None:
        self.db_path = Path(db_path).resolve()
        self.media_dir = Path(media_dir).resolve()
        self.used_filenames: Set[str] = set()
        self.sequence_cache: Dict[Tuple[Any, ...], Tuple[Path, str, float, int]] = {}

    def _open_connection(self) -> sqlite3.Connection:
        """Open read-only SQLite connection to project database."""
        try:
            conn = sqlite3.connect(f"file:{self.db_path.as_posix()}?mode=ro", uri=True)
            return conn
        except sqlite3.OperationalError:
            return sqlite3.connect(str(self.db_path))

    def generate_clip_filename(self, track_name: str, clip_idx: int, offset_sec: float) -> str:
        """Generate unique, human-readable filename: TrackName_ClipIndex_Timestamp.wav."""
        clean_track = sanitize_filename(track_name)
        timestamp_str = f"{max(0.0, offset_sec):07.3f}s"
        base_name = f"{clean_track}_{clip_idx}_{timestamp_str}"
        candidate = f"{base_name}.wav"

        counter = 1
        while candidate.lower() in self.used_filenames:
            candidate = f"{base_name}_{counter}.wav"
            counter += 1

        self.used_filenames.add(candidate.lower())
        return candidate

    def extract_clip_audio(
        self,
        clip: Clip,
        track_name: str,
        conn: sqlite3.Connection,
    ) -> Tuple[Optional[Path], float, int]:
        """Stitch all sample blocks of a clip and write to WAV file.
        
        Returns: (output_path, duration_seconds, bytes_written)
        """
        if not clip.blocks:
            logger.warning("Clip '%s' has no sample blocks defined.", clip.name)
            return None, 0.0, 0

        # Sort blocks by start position
        sorted_blocks = sorted(clip.blocks, key=lambda b: b.start)

        # Check sequence cache: if multiple clips share the exact same sequence of blocks,
        # reuse the already extracted audio WAV file. REAPER items reference this WAV with their
        # individual SOFFS (start trim offset) and LENGTH, avoiding multi-gigabyte duplicates.
        block_signature = (
            tuple(b.block_id for b in sorted_blocks),
            int(clip.sample_rate),
            clip.sample_format,
        )
        if block_signature in self.sequence_cache:
            cached_path, cached_fname, cached_dur, cached_bytes = self.sequence_cache[block_signature]
            clip.extracted_filename = cached_fname
            clip.extracted_path = cached_path
            clip.extracted_duration = cached_dur
            logger.debug(
                "Reusing extracted audio for clip '%s' -> %s",
                clip.name,
                cached_fname,
            )
            return cached_path, cached_dur, 0

        cur = conn.cursor()
        stitched_data = bytearray()
        sample_format = clip.sample_format

        for block in sorted_blocks:
            cur.execute("SELECT sampleformat, samples FROM sampleblocks WHERE blockid = ?;", (block.block_id,))
            row = cur.fetchone()
            if not row or not row[1]:
                logger.warning("Missing sample block ID %d in sampleblocks table.", block.block_id)
                # Pad with silence if block is missing
                sample_width = 4 if sample_format in (262159, 2) else 2
                silence_len = (block.length or 262144) * sample_width
                stitched_data.extend(b"\x00" * silence_len)
                continue

            blk_fmt, blk_data = row[0], bytes(row[1])
            if blk_fmt is not None:
                sample_format = blk_fmt

            sample_width = 4 if sample_format in (262159, 2) else 2

            # Truncate if explicit length specified
            if block.length > 0 and len(blk_data) > block.length * sample_width:
                blk_data = blk_data[: block.length * sample_width]

            stitched_data.extend(blk_data)

        if not stitched_data:
            return None, 0.0, 0

        filename = self.generate_clip_filename(track_name, clip.clip_index, clip.timeline_offset)
        out_path = self.media_dir / filename

        sample_width = 4 if sample_format in (262159, 2) else 2
        total_samples = len(stitched_data) // sample_width
        duration = total_samples / clip.sample_rate if clip.sample_rate > 0 else 0.0

        if out_path.exists() and out_path.stat().st_size > 44:
            # File already extracted; reuse to avoid rewriting gigabytes and handle open REAPER locks
            bytes_written = out_path.stat().st_size
            logger.info("Media file already exists: %s (reusing)", filename)
        else:
            try:
                bytes_written = write_wav_file(
                    output_path=out_path,
                    raw_samples=bytes(stitched_data),
                    sample_rate=int(clip.sample_rate),
                    channels=1,
                    sample_format=sample_format,
                )
            except PermissionError:
                if out_path.exists() and out_path.stat().st_size > 44:
                    bytes_written = out_path.stat().st_size
                    logger.warning("Permission denied writing %s (file open in REAPER?); reusing existing file.", filename)
                else:
                    raise

        clip.extracted_filename = filename
        clip.extracted_path = out_path
        clip.extracted_duration = duration

        # Cache extracted file info for sequence deduplication
        self.sequence_cache[block_signature] = (out_path, filename, duration, bytes_written)

        logger.info(
            "Extracted clip '%s' -> %s (%.2f s, %d bytes)",
            clip.name,
            filename,
            duration,
            bytes_written,
        )

        return out_path, duration, bytes_written

    def extract_all(self, project: AudacityProject) -> Dict[str, Any]:
        """Extract media for all tracks and clips in the project.
        
        Returns a summary report of extraction.
        """
        self.media_dir.mkdir(parents=True, exist_ok=True)
        total_files = 0
        total_bytes = 0
        total_extracted_duration = 0.0
        extracted_files: List[Dict[str, Any]] = []

        conn = self._open_connection()
        try:
            for track in project.tracks:
                for clip in track.clips:
                    out_path, duration, bytes_written = self.extract_clip_audio(
                        clip=clip,
                        track_name=track.name,
                        conn=conn,
                    )
                    if out_path:
                        total_bytes += bytes_written
                        total_extracted_duration += duration
                        extracted_files.append(
                            {
                                "track": track.name,
                                "clip": clip.name,
                                "path": str(out_path),
                                "filename": clip.extracted_filename,
                                "duration": duration,
                                "bytes": bytes_written,
                                "sample_rate": clip.sample_rate,
                                "sample_format": clip.sample_format,
                            }
                        )
        finally:
            conn.close()

        total_files = len(self.sequence_cache) if self.sequence_cache else len(extracted_files)

        return {
            "media_dir": str(self.media_dir),
            "total_files": total_files,
            "total_bytes": total_bytes,
            "total_extracted_duration": total_extracted_duration,
            "files": extracted_files,
        }
