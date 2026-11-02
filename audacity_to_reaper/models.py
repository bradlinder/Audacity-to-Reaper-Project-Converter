"""Domain models representing extracted Audacity project elements."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple


@dataclass
class SampleBlock:
    """A reference to an audio block stored in the Audacity database."""
    block_id: int
    start: int = 0
    length: int = 0
    sample_format: int = 262159  # default: floatSample (0x0004000F)
    byte_count: int = 0


@dataclass
class EffectParameter:
    """A single parameter in an effect."""
    name: str
    value: str


@dataclass
class Effect:
    """A realtime or insert effect on a track or project master."""
    effect_id: str
    name: str = ""
    version: str = ""
    active: bool = True
    parameters: Dict[str, str] = field(default_factory=dict)
    chunk_data: Optional[str] = None  # Base64 string or binary preset chunk data

    def clean_name(self) -> str:
        """Derive a human-readable display name for this plugin."""
        if self.name:
            return self.name
        # Format might be e.g. "Audacity:Audacity:builtin:compressor:Compressor" or "VST3:ReaComp"
        parts = self.effect_id.split(":")
        return parts[-1] if parts else self.effect_id


@dataclass
class Clip:
    """A single wave clip within a track."""
    name: str
    clip_index: int
    offset: float = 0.0  # Timeline start position in seconds
    trim_left: float = 0.0  # Left trim offset in seconds
    trim_right: float = 0.0  # Right trim offset in seconds
    stretch_ratio: float = 1.0  # Time stretch ratio (1.0 = normal)
    sample_rate: float = 44100.0
    num_samples: int = 0
    sample_format: int = 262159
    channels: int = 1  # 1: Mono, 2: Stereo
    blocks: List[SampleBlock] = field(default_factory=list)  # Left (or mono) sample blocks
    right_blocks: List[SampleBlock] = field(default_factory=list)  # Right sample blocks (stereo)
    group_id: int = 0  # REAPER item group ID (links stereo pair items)
    fade_in_len: float = 0.0
    fade_out_len: float = 0.0
    fade_in_shape: int = 1
    fade_out_shape: int = 1
    gain: float = 1.0
    pitch_semitones: float = 0.0  # Non-destructive clip pitch shift in semitones
    color_index: Optional[int] = None  # Audacity clip color index (0-7)
    color_rgb: Optional[Tuple[int, int, int]] = None  # Explicit (R, G, B) if specified
    envelope_points: List[Tuple[float, float]] = field(default_factory=list)  # (item_time_sec, linear_val)

    # Calculated / Extracted media properties
    extracted_filename: Optional[str] = None
    extracted_path: Optional[Path] = None
    extracted_duration: float = 0.0

    @property
    def timeline_offset(self) -> float:
        """Timeline start position in seconds on the REAPER timeline.
        
        In Audacity 3+, 'offset' represents the anchor position of the untrimmed sequence,
        and 'trimLeft' is the offset into that sequence where the clip begins.
        Therefore, the visible timeline start position is offset + trim_left.
        """
        return self.offset + self.trim_left

    @property
    def raw_duration(self) -> float:
        """Original untrimmed audio duration in seconds."""
        if self.sample_rate > 0 and self.num_samples > 0:
            return self.num_samples / self.sample_rate
        return self.extracted_duration

    @property
    def play_rate(self) -> float:
        """REAPER playrate is inverse of Audacity stretch ratio."""
        if self.stretch_ratio > 0:
            return 1.0 / self.stretch_ratio
        return 1.0

    @property
    def timeline_duration(self) -> float:
        """Active duration on REAPER timeline after trimming and stretching."""
        raw = self.raw_duration
        trimmed = max(0.0, raw - self.trim_left - self.trim_right)
        if self.play_rate > 0:
            return trimmed / self.play_rate
        return trimmed


@dataclass
class Track:
    """An audio or label track."""
    track_id: int
    name: str
    channel: int = 0  # 0: Left/Mono, 1: Right, 2: Stereo/Aux
    linked: bool = False
    sample_rate: float = 44100.0
    gain: float = 1.0  # Linear amplitude (1.0 = 0 dB)
    pan: float = 0.0  # -1.0 (Left) to +1.0 (Right)
    mute: bool = False
    solo: bool = False
    clips: List[Clip] = field(default_factory=list)
    effects: List[Effect] = field(default_factory=list)
    stereo_pair_id: Optional[int] = None  # Group identifier linking paired Left and Right tracks


@dataclass
class Marker:
    """A timeline point marker."""
    marker_id: int
    position: float  # In seconds
    name: str = ""


@dataclass
class Region:
    """A timeline region / time range."""
    region_id: int
    start_position: float  # In seconds
    end_position: float  # In seconds
    name: str = ""


@dataclass
class AudacityProject:
    """In-memory representation of an entire parsed Audacity project."""
    project_path: Path
    name: str = ""
    version: str = ""
    audacity_version: str = ""
    sample_rate: float = 44100.0
    tempo: float = 120.0  # Project BPM
    time_sig_numerator: int = 4  # Time signature numerator
    time_sig_denominator: int = 4  # Time signature denominator
    tracks: List[Track] = field(default_factory=list)
    markers: List[Marker] = field(default_factory=list)
    regions: List[Region] = field(default_factory=list)
    master_effects: List[Effect] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    unsupported_features: List[str] = field(default_factory=list)

    @property
    def total_clips(self) -> int:
        return sum(len(t.clips) for t in self.tracks)

    @property
    def total_duration(self) -> float:
        """Total project duration spanning the latest clip or marker end."""
        max_end = 0.0
        for track in self.tracks:
            for clip in track.clips:
                clip_end = clip.timeline_offset + clip.timeline_duration
                if clip_end > max_end:
                    max_end = clip_end
        for region in self.regions:
            if region.end_position > max_end:
                max_end = region.end_position
        for marker in self.markers:
            if marker.position > max_end:
                max_end = marker.position
        return max_end
