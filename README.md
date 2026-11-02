# Audacity to REAPER Project Converter

A standalone, offline cross-platform tool and GUI that converts Audacity projects into native Cockos REAPER project files (`.rpp`).

---

## Features

- **Direct Audacity Project Inspection:**
  - Connects in read-only mode to Audacity's SQLite 3 database container (`.aup3`).
  - Decodes Audacity's binary XML ProjectSerializer stream (`dict` + `doc`) as well as plaintext XML representations.
  - Defensive fallback parsing to reconstruct timeline and tracks from `sampleblocks` if project XML tables are corrupted.
- **Audio Extraction (`./media/`):**
  - Stitches sample blocks sequentially per clip.
  - Automatically handles 16-bit PCM and 32-bit IEEE float uncompressed `.wav` formats.
  - Produces unique, human-readable audio filenames: `TrackName_ClipIndex_Timestamp.wav`.
  - Intelligent block-sequence deduplication prevents writing duplicate gigabytes for split or repeated clips.
- **REAPER Project Generation (`session.rpp`):**
  - Translates tracks (`<TRACK`), names, volume/pan (`VOLPAN`), mute/solo (`MUTESOLO`), and stereo channel layouts.
  - Translates clips (`<ITEM`), precise timeline positions, lengths, trim offsets (`SOFFS`), stretch factors (`PLAYRATE`), and fade curves.
  - Translates Audacity volume envelope curves into native REAPER Take Volume Envelopes (`<VOLENV>`).
  - Translates label tracks into REAPER timeline markers (`MARKER`) and regions.
  - Embeds migration summary notes into the REAPER `<NOTES` chunk.
- **ReaScript FX Loader (`session_load_fx.lua`):**
  - Generates a standalone REAPER Lua script to automate plugin instantiation and parameter setting.
  - Maps stock Audacity effects to native Cockos equivalents:
    - Audacity Compressor -> `VST:ReaComp (Cockos)` (Threshold, Ratio, Attack, Release).
    - Audacity EQ / FilterCurve -> `VST:ReaEQ (Cockos)` (Highpass, Lowpass, frequency bands).
    - Audacity Delay -> `VST:ReaDelay (Cockos)`.
    - Audacity Reverb -> `VST:ReaVerbate (Cockos)`.
  - Maps third-party VST/VST3 plugins with dynamic parameter name matching at runtime.
- **Comprehensive Migration Report (`session_MIGRATION_REPORT.md`):**
  - Detailed overview of tracks, items, sample rate, and audio duration.
  - Manifest of extracted audio clips and their timeline positions.
  - Compatibility guide with recommendations for REAPER routing and mixing.

---

## Installation & Requirements

- **Python:** 3.10 or newer (tested on Python 3.10–3.14 on Windows, macOS, and Linux).
- **Dependencies:** Strictly standard library (`sqlite3`, `struct`, `xml.etree.ElementTree`, `wave`, `pathlib`, `argparse`). Optional `PySide6` for modern Qt GUI.

Install locally via `pip`:
```bash
pip install -e .
```

Or run directly without installation:
```bash
python audacity_to_reaper.py <path_to_aup3>
```

---

## Graphical Interface (GUI)

You can launch the GUI in any of the following ways:

```bash
# Launch GUI directly
python audacity_to_reaper_gui.py

# Or via the CLI runner
python audacity_to_reaper.py --gui
```

### GUI Features:
- **Clean A → R Brand Identity:** Clean, minimalist visual icon and dark theme.
- **Drag & Drop:** Drag an Audacity project file directly into the application window.
- **Smart Output Path:** Automatically sets up `<session_name>_reaper/` next to the project file.
- **Responsive Threading:** Audio block extraction runs in a background worker thread, ensuring the UI never stutters.
- **Live Activity Log:** Real-time log reporting track counts, media block sizes, and conversion metrics.
- **Quick Actions:** "Open Output Folder" and "View Migration Report" buttons upon completion.
- **Adaptive Backend:** Uses `PySide6` when available; seamlessly falls back to standard library `tkinter` on headless or minimal systems.

---

## CLI Usage

```bash
python audacity_to_reaper.py <path_to_aup3> [-o output_dir] [--extract-fx-script] [--dry-run]
```

### Options:
- `<path_to_aup3>`: Path to the Audacity project file (`.aup3`).
- `-o`, `--output-dir`: Output directory for generated project, media, and reports. Defaults to `<session_name>_reaper/` in the same directory.
- `--extract-fx-script`: Generate the companion `session_load_fx.lua` ReaScript FX loader (enabled by default).
- `--no-fx-script`: Disable ReaScript FX loader generation.
- `--dry-run`: Inspect project structure and preview the conversion plan without extracting audio or writing files to disk.
- `-v`, `--verbose`: Enable detailed debug logging.
- `--version`: Display version information.

### Examples:
```bash
# Convert a session into default folder (MySession_reaper/)
python audacity_to_reaper.py MySession.aup3

# Specify custom output directory
python audacity_to_reaper.py MySession.aup3 -o "D:/ReaperProjects/MySession"

# Preview project metrics without writing files
python audacity_to_reaper.py MySession.aup3 --dry-run
```

---

## Running Tests

Run the full test suite using standard Python unittest:
```bash
python -m unittest discover -s tests -v
```

---

## License

MIT License.
