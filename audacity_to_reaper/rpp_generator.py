"""REAPER project file (.rpp) generator.

Translates Audacity project tracks, wave clips, markers, regions, and project notes
into clean, standard REAPER plain-text project syntax.
"""

from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path
from typing import List, Optional, Tuple

from .models import AudacityProject, Clip, Marker, Region, Track

logger = logging.getLogger(__name__)

# Audacity 3.2+ clip color palette (RGB)
AUDACITY_CLIP_PALETTE: List[Tuple[int, int, int]] = [
    (59, 130, 246),   # 0: Blue (Default)
    (239, 68, 68),    # 1: Red
    (16, 185, 129),   # 2: Green
    (6, 182, 212),    # 3: Cyan
    (139, 92, 246),   # 4: Purple / Magenta
    (245, 158, 11),   # 5: Orange / Yellow
    (100, 116, 139),  # 6: Slate / Charcoal
    (20, 184, 166),   # 7: Teal
]


def get_reaper_color(clip: Clip) -> Optional[int]:
    """Calculate REAPER native 24-bit color integer (0x01BBGGRR) for a clip."""
    rgb = None
    if clip.color_rgb is not None:
        rgb = clip.color_rgb
    elif clip.color_index is not None:
        idx = clip.color_index % len(AUDACITY_CLIP_PALETTE)
        rgb = AUDACITY_CLIP_PALETTE[idx]

    if rgb:
        r, g, b = rgb
        # In REAPER, SETCOLOR uses 0x01000000 | (R | (G << 8) | (B << 16))
        return 0x01000000 | (r & 0xFF) | ((g & 0xFF) << 8) | ((b & 0xFF) << 16)
    return None


def generate_guid() -> str:
    """Generate uppercase GUID enclosed in braces as used by REAPER."""
    return f"{{{str(uuid.uuid4()).upper()}}}"


class RPPGenerator:
    """Generates standard REAPER .rpp project files."""

    def __init__(
        self,
        project: AudacityProject,
        output_rpp_path: Path,
        envelope_mode: str = "clip",
    ) -> None:
        self.project = project
        self.output_rpp_path = Path(output_rpp_path).resolve()
        self.project_dir = self.output_rpp_path.parent
        self.envelope_mode = envelope_mode.lower() if envelope_mode in ("clip", "track") else "clip"

    def generate(self) -> str:
        """Construct the complete .rpp file text."""
        lines: List[str] = []

        # REAPER Project Header
        lines.append('<REAPER_PROJECT 0.1 "7.0" 1700000000')
        lines.append("  RIPPLE 0")
        lines.append("  GROUPOVERRIDE 0 0 0")
        lines.append("  AUTOXFADE 1")
        lines.append(f"  SAMPLERATE {int(self.project.sample_rate)} 0 0")
        lines.append(f"  TEMPO {self.project.tempo:.6f} {self.project.time_sig_numerator} {self.project.time_sig_denominator}")
        lines.append('  RECORD_PATH "" ""')

        # Project Tempo Envelope
        lines.append("  <TEMPOENV")
        lines.append(f"    PT 0.000000 {self.project.tempo:.6f} 1 {self.project.time_sig_numerator} {self.project.time_sig_denominator} 0")
        lines.append("  >")

        # Project Summary Notes Chunk
        notes_chunk = self._generate_notes_chunk()
        lines.extend(notes_chunk)

        # Timeline Markers and Regions
        lines.extend(self._generate_markers_and_regions())

        # Tracks
        for track in self.project.tracks:
            track_chunk = self._generate_track_chunk(track)
            lines.extend(track_chunk)

        # End of project
        lines.append(">")
        return "\n".join(lines) + "\n"

    def write(self) -> Path:
        """Write the generated .rpp text to disk."""
        content = self.generate()
        self.output_rpp_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.output_rpp_path, "w", encoding="utf-8") as f:
            f.write(content)
        logger.info("Generated REAPER project file: %s", self.output_rpp_path)
        return self.output_rpp_path

    def _generate_notes_chunk(self) -> List[str]:
        """Generate <NOTES chunk with project migration summary."""
        notes: List[str] = [
            "  <NOTES",
            f"    |Migrated from Audacity: {self.project.name}.aup3",
            f"    |Source File: {self.project.project_path.name}",
            f"    |Sample Rate: {int(self.project.sample_rate)} Hz",
            f"    |Tempo: {self.project.tempo:.2f} BPM ({self.project.time_sig_numerator}/{self.project.time_sig_denominator})",
            f"    |Total Tracks: {len(self.project.tracks)}",
            f"    |Total Clips/Items: {self.project.total_clips}",
            f"    |Timeline Duration: {self.project.total_duration:.2f} seconds",
            "    |Tool: Audacity to REAPER Project Converter (offline converter)",
        ]

        if self.project.markers or self.project.regions:
            notes.append(
                f"    |Timeline Cues: {len(self.project.markers)} markers, {len(self.project.regions)} regions"
            )

        effects_count = sum(len(t.effects) for t in self.project.tracks)
        if effects_count > 0:
            notes.append(f"    |Realtime FX Chains: {effects_count} track effects detected")
            notes.append("    |Use session_load_fx.lua to restore FX chains and mapped parameters in REAPER.")

        env_desc = "Track Automation Lanes (VOLENV2)" if self.envelope_mode == "track" else "Take/Clip Envelopes (VOLENV)"
        notes.append(f"    |Volume Envelope Mode: {env_desc}")

        if self.project.unsupported_features:
            notes.append("    |Notice - Review Migration Report for manual adjustment suggestions.")

        notes.append("  >")
        return notes

    def _generate_markers_and_regions(self) -> List[str]:
        """Generate MARKER lines for markers and regions."""
        lines: List[str] = []

        # Point Markers: MARKER id position name flags color isrgn
        for marker in self.project.markers:
            clean_name = marker.name.replace('"', "'")
            lines.append(f'  MARKER {marker.marker_id} {marker.position:.6f} "{clean_name}" 0 0 1')

        # Regions: pair of lines: start (flag 1) and end (flag 1)
        for region in self.project.regions:
            clean_name = region.name.replace('"', "'")
            lines.append(f'  MARKER {region.region_id} {region.start_position:.6f} "{clean_name}" 1 0 1')
            lines.append(f'  MARKER {region.region_id} {region.end_position:.6f} "" 1')

        return lines

    def _generate_track_chunk(self, track: Track) -> List[str]:
        """Generate <TRACK chunk with track parameters and clips."""
        guid = generate_guid()
        clean_name = track.name.replace('"', "'")
        mute_flag = 1 if track.mute else 0
        solo_flag = 1 if track.solo else 0

        # Determine effective pan: stereo split pairs in Audacity use channel 0 (left) and 1 (right)
        effective_pan = track.pan
        if track.channel == 1 and abs(track.pan) < 0.001:
            effective_pan = 1.0  # 100% Right
        elif track.channel == 0 and track.linked and abs(track.pan) < 0.001:
            effective_pan = -1.0  # 100% Left

        lines: List[str] = [
            f"  <TRACK {guid}",
            f'    NAME "{clean_name}"',
            "    NCHAN 2",
            f"    VOLPAN {track.gain:.6f} {effective_pan:.6f} -1.0 -1.0 1.0",
            f"    MUTESOLO {mute_flag} {solo_flag} 0",
            "    IPHASE 0",
            "    ISBUS 0 0",
            "    BUSCOMP 0 0 0 0 0",
            "    SHOWINMIX 1 0.6667 0.5 1 0.5 0 0 0",
            "    FREEMODE 0",
        ]

        # Collect track volume automation points if in track envelope mode
        track_envelope_points: List[Tuple[float, float]] = []
        if self.envelope_mode == "track":
            for clip in track.clips:
                if clip.envelope_points:
                    for item_t, val in clip.envelope_points:
                        abs_t = clip.timeline_offset + item_t
                        track_envelope_points.append((abs_t, val))

            if track_envelope_points:
                track_envelope_points.sort(key=lambda p: p[0])
                dedup_pts: List[Tuple[float, float]] = []
                for pt in track_envelope_points:
                    if dedup_pts and abs(dedup_pts[-1][0] - pt[0]) < 0.001:
                        dedup_pts[-1] = pt
                    else:
                        dedup_pts.append(pt)
                track_envelope_points = dedup_pts

        # Items (clips)
        for clip in track.clips:
            item_chunk = self._generate_item_chunk(clip)
            lines.extend(item_chunk)

        # Track Volume Automation Lane (VOLENV2)
        if self.envelope_mode == "track" and track_envelope_points:
            lines.append("    <VOLENV2")
            lines.append("      ACT 1 0")
            lines.append("      VIS 1 1 0")
            lines.append("      LANEHEIGHT 0 0")
            lines.append("      ARM 0")
            lines.append("      DEFSHAPE 0 -1 -1")
            for t_pt, v_pt in track_envelope_points:
                lines.append(f"      PT {t_pt:.6f} {v_pt:.6f} 0 0")
            lines.append("    >")

        lines.append("  >")
        return lines

    def _generate_item_chunk(self, clip: Clip) -> List[str]:
        """Generate <ITEM chunk for an audio clip."""
        item_guid = generate_guid()
        take_guid = generate_guid()
        clean_name = clip.name.replace('"', "'")

        # Determine relative media path if extracted
        media_path = ""
        if clip.extracted_path:
            try:
                # Use relative path so REAPER project is portable
                media_path = os.path.relpath(clip.extracted_path, self.project_dir).replace("\\", "/")
            except ValueError:
                media_path = str(clip.extracted_path).replace("\\", "/")
        elif clip.extracted_filename:
            media_path = f"media/{clip.extracted_filename}"
        else:
            media_path = f"media/{clean_name}.wav"

        lines: List[str] = [
            "    <ITEM",
            f"      POSITION {clip.timeline_offset:.6f}",
            "      SNAPOFFS 0",
            f"      LENGTH {clip.timeline_duration:.6f}",
            "      LOOP 1",
            "      ALLTAKES 0",
            f"      FADEIN 1 {clip.fade_in_len:.6f} 0 1 0 0 0 1 0 0 1 0 0",
            f"      FADEOUT 1 {clip.fade_out_len:.6f} 0 1 0 0 0 1 0 0 1 0 0",
            "      MUTE 0 0",
            "      SEL 0",
        ]

        # Group ID links stereo pair items together in REAPER
        if clip.group_id > 0:
            lines.append(f"      GROUP {clip.group_id}")

        lines.extend([
            f"      IGUID {item_guid}",
            f'      NAME "{clean_name}"',
        ])

        # Clip Color (Audacity 3.2+ color index or custom RGB -> REAPER native SETCOLOR)
        color_int = get_reaper_color(clip)
        if color_int is not None:
            lines.append(f"      SETCOLOR {color_int}")

        lines.extend([
            f"      VOLPAN {clip.gain:.6f} 0 1 -1",
            f"      SOFFS {clip.trim_left:.6f}",
            f"      PLAYRATE {clip.play_rate:.6f} 1 0 -1 0 0.0025",
        ])

        # Non-destructive Clip Pitch Shift (Audacity 3.1+)
        if abs(clip.pitch_semitones) > 1e-4:
            lines.append(f"      PITCH {clip.pitch_semitones:.6f} 0 0 -1 0 0.0025")

        lines.extend([
            "      CHANMODE 0",
            f"      GUID {take_guid}",
            "      <SOURCE WAVE",
            f'        FILE "{media_path}"',
            "      >",
        ])

        # Take Volume Envelope (only generated in 'clip' envelope mode)
        if self.envelope_mode == "clip" and clip.envelope_points:
            lines.append("      <VOLENV")
            lines.append("        ACT 1 0")
            lines.append("        VIS 1 1 0")
            lines.append("        LANEHEIGHT 0 0")
            for t_pt, v_pt in clip.envelope_points:
                lines.append(f"        PT {t_pt:.6f} {v_pt:.6f} 0 0")
            lines.append("      >")

        lines.append("    >")
        return lines
