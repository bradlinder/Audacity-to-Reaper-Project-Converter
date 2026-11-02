"""Audacity .aup3 project reader and parser.

Handles SQLite connection, binary XML stream decoding (Audacity 3+ ProjectSerializer),
plaintext XML fallback, and schema inspection fallbacks.
"""

from __future__ import annotations

import io
import logging
import sqlite3
import struct
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .models import (
    AudacityProject,
    Clip,
    Effect,
    Marker,
    Region,
    SampleBlock,
    Track,
)

logger = logging.getLogger(__name__)

# Audacity ProjectSerializer Field Types
FT_CharSize = 0
FT_StartTag = 1
FT_EndTag = 2
FT_String = 3
FT_Int = 4
FT_Bool = 5
FT_Long = 6
FT_LongLong = 7
FT_SizeT = 8
FT_Float = 9
FT_Double = 10
FT_Data = 11
FT_Raw = 12
FT_Push = 13
FT_Pop = 14
FT_Name = 15


def decode_audacity_binary_xml(stream_bytes: bytes) -> Optional[ET.Element]:
    """Decode Audacity 3+ binary XML stream into an ElementTree Element.
    
    Audacity packs the static name dictionary (dict) and document stream (doc)
    using ProjectSerializer. Numbers and strings are written in little-endian format.
    """
    if not stream_bytes:
        return None

    bio = io.BytesIO(stream_bytes)
    total_len = len(stream_bytes)
    id_map: Dict[int, str] = {}
    id_stack: List[Dict[int, str]] = []
    char_size = 2  # default UTF-16LE on Windows / Audacity

    def read_str(byte_length: int) -> str:
        raw = bio.read(byte_length)
        if char_size == 1:
            return raw.decode("utf-8", errors="replace")
        elif char_size == 2:
            return raw.decode("utf-16le", errors="replace")
        elif char_size == 4:
            return raw.decode("utf-32le", errors="replace")
        return raw.decode("utf-8", errors="replace")

    root: Optional[ET.Element] = None
    stack: List[ET.Element] = []
    pending_tag: Optional[str] = None
    pending_attrs: Dict[str, str] = {}

    def commit_pending() -> None:
        nonlocal pending_tag, pending_attrs, root
        if pending_tag is not None:
            elem = ET.Element(pending_tag, pending_attrs)
            if not stack:
                root = elem
            else:
                stack[-1].append(elem)
            stack.append(elem)
            pending_tag = None
            pending_attrs = {}

    while bio.tell() < total_len:
        b = bio.read(1)
        if not b:
            break
        ft = b[0]

        try:
            if ft == FT_CharSize:
                cs = bio.read(1)
                if cs:
                    char_size = cs[0]
            elif ft == FT_Push:
                id_stack.append(dict(id_map))
                id_map.clear()
            elif ft == FT_Pop:
                if id_stack:
                    id_map = id_stack.pop()
            elif ft == FT_Name:
                nid, nlen = struct.unpack("<HH", bio.read(4))
                name = read_str(nlen)
                id_map[nid] = name
            elif ft == FT_StartTag:
                commit_pending()
                nid = struct.unpack("<H", bio.read(2))[0]
                tag_name = id_map.get(nid, f"tag_{nid}")
                pending_tag = tag_name
                pending_attrs = {}
            elif ft == FT_EndTag:
                commit_pending()
                nid = struct.unpack("<H", bio.read(2))[0]
                tag_name = id_map.get(nid, f"tag_{nid}")
                if stack and stack[-1].tag == tag_name:
                    stack.pop()
            elif ft == FT_String:
                nid, slen = struct.unpack("<Hi", bio.read(6))
                val = read_str(slen)
                attr_name = id_map.get(nid, f"attr_{nid}")
                pending_attrs[attr_name] = val
            elif ft == FT_Int:
                nid, val = struct.unpack("<Hi", bio.read(6))
                attr_name = id_map.get(nid, f"attr_{nid}")
                pending_attrs[attr_name] = str(val)
            elif ft == FT_Bool:
                nid = struct.unpack("<H", bio.read(2))[0]
                val = bio.read(1)[0]
                attr_name = id_map.get(nid, f"attr_{nid}")
                pending_attrs[attr_name] = "1" if val else "0"
            elif ft == FT_Long:
                nid, val = struct.unpack("<Hi", bio.read(6))
                attr_name = id_map.get(nid, f"attr_{nid}")
                pending_attrs[attr_name] = str(val)
            elif ft == FT_LongLong:
                nid, val = struct.unpack("<Hq", bio.read(10))
                attr_name = id_map.get(nid, f"attr_{nid}")
                pending_attrs[attr_name] = str(val)
            elif ft == FT_SizeT:
                nid, val = struct.unpack("<HI", bio.read(6))
                attr_name = id_map.get(nid, f"attr_{nid}")
                pending_attrs[attr_name] = str(val)
            elif ft == FT_Float:
                nid = struct.unpack("<H", bio.read(2))[0]
                val = struct.unpack("<f", bio.read(4))[0]
                _digits = struct.unpack("<i", bio.read(4))[0]
                attr_name = id_map.get(nid, f"attr_{nid}")
                pending_attrs[attr_name] = f"{val:.8f}".rstrip("0").rstrip(".")
            elif ft == FT_Double:
                nid = struct.unpack("<H", bio.read(2))[0]
                val = struct.unpack("<d", bio.read(8))[0]
                _digits = struct.unpack("<i", bio.read(4))[0]
                attr_name = id_map.get(nid, f"attr_{nid}")
                pending_attrs[attr_name] = f"{val:.8f}".rstrip("0").rstrip(".")
            elif ft == FT_Data:
                commit_pending()
                dlen = struct.unpack("<i", bio.read(4))[0]
                text = read_str(dlen)
                if stack:
                    stack[-1].text = (stack[-1].text or "") + text
            elif ft == FT_Raw:
                rlen = struct.unpack("<i", bio.read(4))[0]
                bio.read(rlen)
            else:
                logger.debug("Unknown or unaligned field type %d at offset %d", ft, bio.tell() - 1)
                break
        except Exception as exc:
            logger.debug("Binary XML parsing error at byte %d: %s", bio.tell(), exc)
            break

    commit_pending()
    return root


def strip_ns(tag: str) -> str:
    """Strip XML namespace prefix from tag name."""
    if "}" in tag:
        return tag.split("}", 1)[1].lower()
    return tag.lower()


class AUP3Reader:
    """Reader for modern Audacity 3+ .aup3 project files."""

    def __init__(self, file_path: str | Path) -> None:
        self.file_path = Path(file_path).resolve()
        if not self.file_path.exists():
            raise FileNotFoundError(f"Audacity project file not found: {self.file_path}")
        if self.file_path.suffix.lower() != ".aup3":
            raise ValueError(f"Expected .aup3 file, got: {self.file_path.suffix}")

    def _open_connection(self) -> sqlite3.Connection:
        """Open read-only SQLite connection to project database."""
        try:
            conn = sqlite3.connect(f"file:{self.file_path.as_posix()}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row
            return conn
        except sqlite3.OperationalError:
            conn = sqlite3.connect(str(self.file_path))
            conn.row_factory = sqlite3.Row
            return conn

    def get_database_tables(self) -> List[str]:
        """List all table names present in the SQLite database."""
        conn = self._open_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;")
            return [row[0] for row in cur.fetchall()]
        finally:
            conn.close()

    def extract_project_xml_element(self) -> Tuple[Optional[ET.Element], List[str]]:
        """Extract and parse the project tree from the project or autosave table."""
        warnings: List[str] = []
        tables = self.get_database_tables()
        candidate_tables = [t for t in ["project", "autosave", "project_history"] if t in tables]

        if not candidate_tables:
            warnings.append(f"No standard project tables found in database (available: {tables})")
            return None, warnings

        conn = self._open_connection()
        try:
            cur = conn.cursor()
            for tbl in candidate_tables:
                try:
                    cur.execute(f"SELECT * FROM {tbl} LIMIT 1;")
                    row = cur.fetchone()
                    if not row:
                        continue

                    col_names = [col[0].lower() for col in cur.description]

                    # 1. Plaintext XML in doc or xml column
                    for col in ["doc", "xml", "project"]:
                        if col in col_names and isinstance(row[col], str):
                            text_val = row[col].strip()
                            if text_val.startswith("<"):
                                try:
                                    root = ET.fromstring(text_val)
                                    logger.info("Parsed plaintext XML from table '%s', column '%s'", tbl, col)
                                    return root, warnings
                                except ET.ParseError as pe:
                                    warnings.append(f"Found XML string in {tbl}.{col} but parsing failed: {pe}")

                    # 2. Binary XML with dict + doc blobs
                    dict_blob = b""
                    doc_blob = b""
                    if "dict" in col_names and row["dict"] is not None:
                        dict_blob = bytes(row["dict"]) if not isinstance(row["dict"], str) else row["dict"].encode()
                    if "doc" in col_names and row["doc"] is not None:
                        doc_blob = bytes(row["doc"]) if not isinstance(row["doc"], str) else row["doc"].encode()

                    if dict_blob or doc_blob:
                        # Stream is dict followed by doc
                        stream = dict_blob + doc_blob
                        root = decode_audacity_binary_xml(stream)
                        if root is not None and (strip_ns(root.tag) in ("project", "audacityproject") or len(root) > 0):
                            logger.info("Successfully decoded binary XML from '%s' table", tbl)
                            return root, warnings

                    # Try doc alone in case dict was embedded
                    if doc_blob:
                        root = decode_audacity_binary_xml(doc_blob)
                        if root is not None and len(root) > 0:
                            logger.info("Successfully decoded binary XML from doc blob in '%s'", tbl)
                            return root, warnings

                except Exception as exc:
                    warnings.append(f"Error querying table '{tbl}': {exc}")
        finally:
            conn.close()

        return None, warnings

    def parse_project(self) -> AudacityProject:
        """Parse the full project structure into an AudacityProject model."""
        proj = AudacityProject(
            project_path=self.file_path,
            name=self.file_path.stem,
        )

        xml_root, xml_warnings = self.extract_project_xml_element()
        proj.warnings.extend(xml_warnings)

        if xml_root is not None:
            self._parse_from_xml(xml_root, proj)
        else:
            # Fallback: extract bare tracks and blocks from sampleblocks table
            proj.warnings.append("Could not extract project XML tree; falling back to sampleblocks table schema recovery.")
            self._parse_from_sampleblocks_fallback(proj)

        return proj

    def _parse_from_xml(self, root: ET.Element, proj: AudacityProject) -> None:
        """Populate project model from XML element tree."""
        # Top level project attributes
        proj.version = root.attrib.get("version", "1.3.0")
        proj.audacity_version = root.attrib.get("audacityversion", "3.0+")
        proj.name = root.attrib.get("projname", proj.name)

        rate_str = root.attrib.get("rate")
        if rate_str:
            try:
                proj.sample_rate = float(rate_str)
            except ValueError:
                pass

        # Project Tempo (BPM) and Time Signature
        for key in ["tempo", "bpm", "beatsperminute", "projectbpm"]:
            if key in root.attrib:
                try:
                    proj.tempo = float(root.attrib[key])
                    break
                except ValueError:
                    pass

        for key in ["timesig", "timeSignature", "time_signature", "meter"]:
            if key in root.attrib:
                val = root.attrib[key].strip()
                if "/" in val:
                    parts = val.split("/")
                    try:
                        proj.time_sig_numerator = int(parts[0])
                        proj.time_sig_denominator = int(parts[1])
                    except ValueError:
                        pass
                break

        # Check child tags for tempo, time signature, or snap settings
        for child in root:
            tag = strip_ns(child.tag)
            if tag in ("timesignature", "meter"):
                num = child.attrib.get("numerator") or child.attrib.get("num")
                denom = child.attrib.get("denominator") or child.attrib.get("denom")
                if num and denom:
                    try:
                        proj.time_sig_numerator = int(num)
                        proj.time_sig_denominator = int(denom)
                    except ValueError:
                        pass
                bpm_val = child.attrib.get("bpm") or child.attrib.get("tempo")
                if bpm_val:
                    try:
                        proj.tempo = float(bpm_val)
                    except ValueError:
                        pass
            elif tag in ("tempo", "bpm"):
                bpm_val = child.attrib.get("value") or child.attrib.get("bpm") or child.attrib.get("tempo")
                if bpm_val:
                    try:
                        proj.tempo = float(bpm_val)
                    except ValueError:
                        pass
            elif tag == "snapto":
                bpm_val = child.attrib.get("tempo") or child.attrib.get("bpm")
                if bpm_val:
                    try:
                        proj.tempo = float(bpm_val)
                    except ValueError:
                        pass

        # Check for unsupported project-level features
        for child in root:
            tag = strip_ns(child.tag)
            if tag == "timetrack":
                proj.unsupported_features.append(
                    "Audacity Time Track (tempo/speed envelope) detected. REAPER tempo envelopes must be aligned manually."
                )

        # Parse tracks
        track_index = 0
        for child in root:
            tag = strip_ns(child.tag)

            if tag == "wavetrack":
                track = self._parse_wavetrack(child, track_index, proj.sample_rate)
                proj.tracks.append(track)
                track_index += 1

            elif tag == "labeltrack":
                self._parse_labeltrack(child, proj)

            elif tag == "effects":
                # Master / Project-level effect list
                for eff_child in child:
                    if strip_ns(eff_child.tag) == "effect":
                        eff = self._parse_effect(eff_child)
                        if eff:
                            proj.master_effects.append(eff)

        # Establish dual-mono linked stereo pairs
        self._link_stereo_pairs(proj)

    def _link_stereo_pairs(self, proj: AudacityProject) -> None:
        """Establish stereo link pairs between consecutive tracks:
        Track i (channel=0, linked=True) and Track i+1 (channel=1).
        
        Assigns stereo_pair_id to tracks and synchronized group_id to items
        so that moving or editing in REAPER operates on both channels in sync.
        """
        pair_counter = 1
        i = 0
        while i < len(proj.tracks) - 1:
            t_left = proj.tracks[i]
            t_right = proj.tracks[i + 1]
            if t_left.channel == 0 and t_left.linked and t_right.channel == 1:
                t_left.stereo_pair_id = pair_counter
                t_right.stereo_pair_id = pair_counter

                # Group corresponding clips so REAPER links them
                num_clips = min(len(t_left.clips), len(t_right.clips))
                for c_idx in range(num_clips):
                    group_val = pair_counter * 1000 + c_idx + 1
                    t_left.clips[c_idx].group_id = group_val
                    t_right.clips[c_idx].group_id = group_val

                pair_counter += 1
                i += 2
            else:
                i += 1

    def _parse_wavetrack(self, elem: ET.Element, track_idx: int, default_rate: float) -> Track:
        """Parse a <wavetrack> element into a Track model."""
        name = elem.attrib.get("name", f"Track {track_idx + 1}")
        channel_raw = elem.attrib.get("channel", "0")
        try:
            channel = int(channel_raw)
        except ValueError:
            if channel_raw.lower() in ("stereo", "2"):
                channel = 2
            elif channel_raw.lower() in ("right", "1"):
                channel = 1
            else:
                channel = 0

        # Check explicit channels attribute: e.g. channels="2"
        if elem.attrib.get("channels") == "2":
            channel = 2

        linked_raw = elem.attrib.get("linked", "0")
        try:
            linked = int(linked_raw) > 0
        except ValueError:
            linked = linked_raw.lower() in ("true", "yes")
        mute = elem.attrib.get("mute", "0") in ("1", "true", "True")
        solo = elem.attrib.get("solo", "0") in ("1", "true", "True")

        try:
            rate = float(elem.attrib.get("rate", str(default_rate)))
        except ValueError:
            rate = default_rate

        try:
            gain = float(elem.attrib.get("gain", "1.0"))
        except ValueError:
            gain = 1.0

        try:
            pan = float(elem.attrib.get("pan", "0.0"))
        except ValueError:
            pan = 0.0

        track = Track(
            track_id=track_idx + 1,
            name=name,
            channel=channel,
            linked=linked,
            sample_rate=rate,
            gain=gain,
            pan=pan,
            mute=mute,
            solo=solo,
        )

        clip_idx = 0
        for child in elem:
            ctag = strip_ns(child.tag)
            if ctag == "waveclip":
                clip = self._parse_waveclip(child, name, clip_idx, rate, track_channel=channel)
                track.clips.append(clip)
                clip_idx += 1
            elif ctag == "effects":
                for eff_elem in child:
                    if strip_ns(eff_elem.tag) == "effect":
                        eff = self._parse_effect(eff_elem)
                        if eff:
                            track.effects.append(eff)

        return track

    def _parse_waveclip(
        self,
        elem: ET.Element,
        track_name: str,
        clip_idx: int,
        track_rate: float,
        track_channel: int = 0,
    ) -> Clip:
        """Parse a <waveclip> element into a Clip model."""
        try:
            offset = float(elem.attrib.get("offset", "0.0"))
        except ValueError:
            offset = 0.0

        # Defensive lookup for trimming and stretching
        trim_left = 0.0
        for key in ["trimLeft", "trim_left", "trimleft"]:
            if key in elem.attrib:
                try:
                    trim_left = float(elem.attrib[key])
                    break
                except ValueError:
                    pass

        trim_right = 0.0
        for key in ["trimRight", "trim_right", "trimright"]:
            if key in elem.attrib:
                try:
                    trim_right = float(elem.attrib[key])
                    break
                except ValueError:
                    pass

        stretch_ratio = 1.0
        for key in ["clipStretchRatio", "clip_stretch_ratio", "stretchratio"]:
            if key in elem.attrib:
                try:
                    stretch_ratio = float(elem.attrib[key])
                    break
                except ValueError:
                    pass

        # Per-clip gain slider (Audacity 3.2+)
        clip_gain = 1.0
        for key in ["gain", "clipGain", "clip_gain", "volume"]:
            if key in elem.attrib:
                try:
                    clip_gain = float(elem.attrib[key])
                    break
                except ValueError:
                    pass
        for key in ["gain_db", "clipGainDb", "gainDb"]:
            if key in elem.attrib:
                try:
                    clip_gain = 10.0 ** (float(elem.attrib[key]) / 20.0)
                    break
                except ValueError:
                    pass

        # Non-destructive clip pitch shift in semitones (Audacity 3.1+)
        pitch_semitones = 0.0
        for key in ["pitch", "clipPitch", "clip_pitch", "pitchShift", "pitch_shift", "semitones"]:
            if key in elem.attrib:
                try:
                    pitch_semitones = float(elem.attrib[key])
                    break
                except ValueError:
                    pass
        if abs(pitch_semitones) < 1e-5:
            for key in ["cents", "clipCents", "clip_cents"]:
                if key in elem.attrib:
                    try:
                        pitch_semitones = float(elem.attrib[key]) / 100.0
                        break
                    except ValueError:
                        pass

        # Clip color index (Audacity 3.2+ color coding)
        color_index = None
        color_rgb = None
        for key in ["colorindex", "colorIndex", "color_index", "color"]:
            if key in elem.attrib:
                val = elem.attrib[key].strip()
                try:
                    color_index = int(val)
                    break
                except ValueError:
                    if val.startswith("#") and len(val) == 7:
                        try:
                            r = int(val[1:3], 16)
                            g = int(val[3:5], 16)
                            b = int(val[5:7], 16)
                            color_rgb = (r, g, b)
                            break
                        except ValueError:
                            pass

        clip_name = elem.attrib.get("name", f"{track_name}_Clip{clip_idx + 1}")

        # Determine clip channel mode (1: Mono, 2: Stereo)
        clip_channels = 2 if track_channel == 2 else 1
        if elem.attrib.get("channels") == "2" or elem.attrib.get("channel") in ("2", "stereo", "Stereo"):
            clip_channels = 2

        clip = Clip(
            name=clip_name,
            clip_index=clip_idx,
            offset=offset,
            trim_left=trim_left,
            trim_right=trim_right,
            stretch_ratio=stretch_ratio,
            sample_rate=track_rate,
            channels=clip_channels,
            gain=clip_gain,
            pitch_semitones=pitch_semitones,
            color_index=color_index,
            color_rgb=color_rgb,
        )

        # Parse <sequence> and <envelope>
        sequences: List[Tuple[ET.Element, int]] = []
        for child in elem:
            ctag = strip_ns(child.tag)
            if ctag == "sequence":
                seq_ch = 0
                ch_attr = child.attrib.get("channel")
                if ch_attr is not None:
                    try:
                        seq_ch = int(ch_attr)
                    except ValueError:
                        seq_ch = len(sequences)
                else:
                    seq_ch = len(sequences)
                sequences.append((child, seq_ch))

            elif ctag == "envelope":
                # Parse volume envelope adjustments and fades
                self._parse_envelope(child, clip)

        if len(sequences) >= 2:
            clip.channels = 2
            for seq_elem, seq_ch in sequences:
                try:
                    seq_num_samples = int(seq_elem.attrib.get("numsamples", "0"))
                    if seq_num_samples > clip.num_samples:
                        clip.num_samples = seq_num_samples
                except ValueError:
                    pass

                try:
                    clip.sample_format = int(seq_elem.attrib.get("sampleformat", "262159"))
                except ValueError:
                    pass

                target_blocks = clip.right_blocks if seq_ch == 1 else clip.blocks
                for block_elem in seq_elem:
                    if strip_ns(block_elem.tag) == "waveblock":
                        block = self._parse_waveblock(block_elem, clip.sample_format)
                        if block:
                            target_blocks.append(block)

        elif len(sequences) == 1:
            seq_elem, _ = sequences[0]
            try:
                clip.num_samples = int(seq_elem.attrib.get("numsamples", "0"))
            except ValueError:
                clip.num_samples = 0

            try:
                clip.sample_format = int(seq_elem.attrib.get("sampleformat", "262159"))
            except ValueError:
                clip.sample_format = 262159

            for block_elem in seq_elem:
                if strip_ns(block_elem.tag) == "waveblock":
                    block = self._parse_waveblock(block_elem, clip.sample_format)
                    if block:
                        clip.blocks.append(block)

        # Sort blocks by their start sample position
        clip.blocks.sort(key=lambda b: b.start)
        clip.right_blocks.sort(key=lambda b: b.start)
        return clip

    def _parse_waveblock(self, elem: ET.Element, default_format: int) -> Optional[SampleBlock]:
        """Parse a <waveblock> and its blockfile reference."""
        try:
            start = int(elem.attrib.get("start", "0"))
        except ValueError:
            start = 0

        # Look for blockid on waveblock itself or on nested blockfile
        block_id: Optional[int] = None
        length = 0

        if "blockid" in elem.attrib:
            try:
                block_id = int(elem.attrib["blockid"])
            except ValueError:
                pass

        for sub in elem:
            stag = strip_ns(sub.tag)
            if stag in ("simpleblockfile", "databaseblockfile", "silentblockfile"):
                if "blockid" in sub.attrib:
                    try:
                        block_id = int(sub.attrib["blockid"])
                    except ValueError:
                        pass
                if "len" in sub.attrib:
                    try:
                        length = int(sub.attrib["len"])
                    except ValueError:
                        pass

        if block_id is not None:
            return SampleBlock(
                block_id=block_id,
                start=start,
                length=length,
                sample_format=default_format,
            )
        return None

    def _parse_envelope(self, env_elem: ET.Element, clip: Clip) -> None:
        """Parse Audacity envelope control points into REAPER item volume envelope points and edge fades."""
        raw_pts: List[Tuple[float, float]] = []
        for pt in env_elem:
            tag = strip_ns(pt.tag).lower()
            if tag in ("controlpoint", "point"):
                try:
                    t_str = pt.attrib.get("t") or pt.attrib.get("time", "0.0")
                    v_str = pt.attrib.get("val") or pt.attrib.get("value") or pt.attrib.get("v", "1.0")
                    t = float(t_str)
                    val = float(v_str)
                    raw_pts.append((t, val))
                except ValueError:
                    continue

        if not raw_pts:
            return

        # Sort by timestamp
        raw_pts.sort(key=lambda p: p[0])

        # Deduplicate consecutive timestamps within 0.001s (keep later point)
        dedup: List[Tuple[float, float]] = []
        for p in raw_pts:
            if dedup and abs(dedup[-1][0] - p[0]) < 0.001:
                dedup[-1] = p
            else:
                dedup.append(p)
        raw_pts = dedup

        # Check edge fade-in / fade-out
        if len(raw_pts) >= 2:
            if raw_pts[0][1] < 0.1 and raw_pts[1][1] >= 0.9:
                clip.fade_in_len = max(0.0, raw_pts[1][0] - raw_pts[0][0])
            if raw_pts[-2][1] >= 0.9 and raw_pts[-1][1] < 0.1:
                clip.fade_out_len = max(0.0, raw_pts[-1][0] - raw_pts[-2][0])

        # If all points are practically 1.0 (unity gain), no envelope needed
        if all(abs(p[1] - 1.0) < 0.01 for p in raw_pts):
            return

        t_start = clip.trim_left
        dur = clip.timeline_duration
        t_end = t_start + dur

        # Interpolate value at any time query
        def val_at(t_query: float) -> float:
            if not raw_pts:
                return 1.0
            if t_query <= raw_pts[0][0]:
                return raw_pts[0][1]
            if t_query >= raw_pts[-1][0]:
                return raw_pts[-1][1]
            for i in range(len(raw_pts) - 1):
                t0, v0 = raw_pts[i]
                t1, v1 = raw_pts[i + 1]
                if t0 <= t_query <= t1:
                    if abs(t1 - t0) < 1e-6:
                        return v1
                    return v0 + ((t_query - t0) / (t1 - t0)) * (v1 - v0)
            return raw_pts[-1][1]

        item_pts: List[Tuple[float, float]] = []

        # Start point at 0.0
        v_start = val_at(t_start)
        item_pts.append((0.0, v_start))

        # Intermediate points within (t_start, t_end)
        for t_raw, v in raw_pts:
            if t_start + 0.001 < t_raw < t_end - 0.001:
                item_t = t_raw - t_start
                # Ensure monotonically increasing and separated by at least 1ms
                if not item_pts or item_t - item_pts[-1][0] >= 0.001:
                    item_pts.append((item_t, v))
                else:
                    item_pts[-1] = (item_t, v)

        # End point at dur
        if dur > 0:
            v_end = val_at(t_end)
            if not item_pts or dur - item_pts[-1][0] >= 0.001:
                item_pts.append((dur, v_end))
            else:
                item_pts[-1] = (dur, v_end)

        # If any point differs from 1.0, assign to clip
        if any(abs(v - 1.0) >= 0.01 for _, v in item_pts):
            clip.envelope_points = item_pts

    def _parse_labeltrack(self, elem: ET.Element, proj: AudacityProject) -> None:
        """Parse a <labeltrack> element into markers and regions."""
        marker_id = len(proj.markers) + 1
        region_id = len(proj.regions) + 1

        for child in elem:
            if strip_ns(child.tag) == "label":
                title = child.attrib.get("title", "")
                try:
                    t0 = float(child.attrib.get("t", "0.0"))
                except ValueError:
                    t0 = 0.0

                try:
                    t1 = float(child.attrib.get("t1", str(t0)))
                except ValueError:
                    t1 = t0

                if abs(t1 - t0) < 0.001:
                    # Point Marker
                    proj.markers.append(Marker(marker_id=marker_id, position=t0, name=title))
                    marker_id += 1
                else:
                    # Time Region
                    proj.regions.append(
                        Region(
                            region_id=region_id,
                            start_position=min(t0, t1),
                            end_position=max(t0, t1),
                            name=title,
                        )
                    )
                    region_id += 1

    def _parse_effect(self, elem: ET.Element) -> Optional[Effect]:
        """Parse an <effect> element and its key-value parameters or state blobs."""
        eff_id = elem.attrib.get("id", "")
        if not eff_id:
            return None

        name = elem.attrib.get("name", "")
        version = elem.attrib.get("version", "")
        active = elem.attrib.get("active", "1") in ("1", "true", "True")
        params: Dict[str, str] = {}
        chunk_data: Optional[str] = (
            elem.attrib.get("data")
            or elem.attrib.get("chunk")
            or elem.attrib.get("state")
            or elem.attrib.get("preset")
        )

        for child in elem:
            ctag = strip_ns(child.tag).lower()
            if ctag == "parameters":
                for param in child:
                    if strip_ns(param.tag).lower() == "parameter":
                        pname = param.attrib.get("name")
                        pval = param.attrib.get("value")
                        if pname and pval is not None:
                            params[pname] = pval
            elif ctag == "parameter":
                pname = child.attrib.get("name")
                pval = child.attrib.get("value")
                if pname and pval is not None:
                    params[pname] = pval
            elif ctag in ("data", "chunk", "state", "raw", "preset", "blob") and child.text:
                chunk_data = child.text.strip()

        return Effect(
            effect_id=eff_id,
            name=name,
            version=version,
            active=active,
            parameters=params,
            chunk_data=chunk_data,
        )

    def _parse_from_sampleblocks_fallback(self, proj: AudacityProject) -> None:
        """Fallback when project XML cannot be read: reconstruct tracks from sampleblocks."""
        conn = self._open_connection()
        try:
            cur = conn.cursor()
            try:
                cur.execute("SELECT blockid, sampleformat, LENGTH(samples) FROM sampleblocks ORDER BY blockid;")
                rows = cur.fetchall()
            except sqlite3.OperationalError:
                proj.warnings.append("Table 'sampleblocks' does not exist in SQLite database.")
                return

            if not rows:
                proj.warnings.append("Table 'sampleblocks' is empty.")
                return

            # Group all blocks into a single recovered track
            recovered_track = Track(
                track_id=1,
                name="Recovered Audio",
                sample_rate=proj.sample_rate,
            )

            blocks: List[SampleBlock] = []
            cur_start = 0
            for row in rows:
                bid = row[0]
                fmt = row[1] if row[1] is not None else 262159
                byte_len = row[2] or 0
                sample_width = 4 if fmt in (262159, 2) else 2
                sample_count = byte_len // sample_width
                blocks.append(
                    SampleBlock(
                        block_id=bid,
                        start=cur_start,
                        length=sample_count,
                        sample_format=fmt,
                        byte_count=byte_len,
                    )
                )
                cur_start += sample_count

            total_samples = sum(b.length for b in blocks)
            clip = Clip(
                name="Recovered_Clip_1",
                clip_index=0,
                offset=0.0,
                num_samples=total_samples,
                sample_rate=proj.sample_rate,
                blocks=blocks,
            )
            recovered_track.clips.append(clip)
            proj.tracks.append(recovered_track)
        finally:
            conn.close()
