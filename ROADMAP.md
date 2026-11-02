# Project Roadmap: Audacity to REAPER Project Converter

> **Product Goal:** Provide a standalone, cross-platform desktop application and command-line tool that reliably and cleanly converts any Audacity session into a standard Cockos REAPER project file (`.rpp`) with zero external cloud dependencies.

---

## 🗺️ Release Phases & Milestones

```mermaid
flowchart LR
    A["Phase 1: Rebrand & UI Core"] --> B["Phase 2: Stereo, Envelopes & Session Fidelity"]
    B --> C["Phase 3: Format Expansion (.aup / .aup4)"]
    C --> D["Phase 4: Cross-Platform Packaging"]
```

---

## Phase 1: Rebranding & UI Core Polish
*Status: Ready to implement*

- [x] **1.1 Application Rebrand:**
  - Rename package, window titles, CLI entry points, and documentation from `aup3-to-reaper` to **Audacity to REAPER Project Converter** (`audacity_to_reaper`).
- [x] **1.2 Minimalist Brand Icon (`A → R`):**
  - Design a clean, high-contrast, scalable vector icon (and export `.ico`, `.icns`, `.png`).
  - **Design Specification:** A clean, horizontal arrow pointing left-to-right with a bold letter **A** on the left and a bold letter **R** on the right.
  - *Constraint:* Strict avoidance of any official Audacity (soundwave headphones) or REAPER (scythe) logos or trademarked graphics.

---

## Phase 2: Stereo, Envelopes & Session Fidelity
*Status: Completed*

- [x] **2.1 Full Stereo Channel Modes:**
  - Handle interleaved 2-channel stereo tracks (extracting true 2-channel WAVs or splitting cleanly based on track definition).
  - Preserve dual-mono stereo link groupings and pan assignments in REAPER.
- [x] **2.2 Audacity Clip Colors → REAPER Item Colors:**
  - Read Audacity's clip `colorindex` attribute (Audacity 3.2+ color-coding palette).
  - Map each index to REAPER's item color tag (`SETCOLOR` / `PEAKCOL`) so clip color-coding is visually preserved in REAPER's arrange view.
- [x] **2.3 Configurable Volume Envelope Conversion (Clip vs. Track):**
  - Provide an option allowing users to choose whether Audacity volume envelope control points are converted as REAPER take/clip envelopes (`VOLENV`) or track-level automation envelopes (`VOLENV2`).
  - Normalize timestamps, scaling, and dB curve values appropriately for the selected target envelope mode.
- [x] **2.4 Timeline Tempo & Grid Synchronization:**
  - Detect session tempo (BPM) and time signature settings from Audacity's timeline and write standard REAPER `<TEMPO` markers to keep project grid divisions aligned.
- [x] **2.5 Clip Gain Slider & Pitch Shift Preservation:**
  - Parse Audacity 3.2+ clip gain attributes (per-clip dB trim) from `<waveclip>` and map to REAPER item `VOLPAN`.
  - Parse Audacity 3.1+ non-destructive clip pitch attributes (semitones/cents) and map to REAPER item `PITCH` parameters without destructive re-rendering.
- [x] **2.6 Direct REAPER `<FXCHAIN>` Embedding for Stock FX & VST/VST3 Plugins:**
  - Directly serialize standard REAPER `<FXCHAIN>` and `<MASTERFXCHAIN>` chunks into `.rpp` track blocks.
  - Automatically instantiate Cockos Rea-family stock equivalents (ReaComp, ReaEQ, ReaDelay, ReaVerbate, ReaLimit) and third-party VST/VST3 plugins in their respective track insert slots.
  - Preserve bypass flags (`BYPASS 0 0 0` vs `BYPASS 1 0 0`), unique `FXID` GUIDs, floating window geometry, and base64 binary state chunk blobs when present in Audacity project data.
  - Provide `--embed-fx` / `--no-embed-fx` CLI and GUI toggles while retaining optional companion ReaScript (`session_load_fx.lua`) for manual parameter slider fine-tuning.

---

## Phase 3: Extended Format Support (`.aup` and `.aup4`)
*Status: Planned*

- [ ] **3.1 Legacy Audacity (`.aup` + `_data` folder) Support:**
  - Parse legacy Audacity 1.x–2.x XML session trees.
  - Stitch block files from the project's `_data/` directory (standard Sun/NeXT `.au` format).
  - Map legacy track pan/gain, envelope control points, and labels directly into `.rpp`.
- [ ] **3.2 Future-Proof Audacity 4 (`.aup4`) Support:**
  - Ensure compatibility with Muse Group's next-gen Audacity 4 SQLite schemas.
  - Implement dynamic table and column inspection to automatically handle upcoming schema additions (e.g., non-destructive clip pitch attributes, track hierarchy).

---

## Phase 4: Cross-Platform Packaging & CI/CD Automation
*Status: Planned*

- [ ] **4.1 Qt Desktop Application Hardening:**
  - Ensure the PySide6 UI adheres strictly to a clean, focused single-window design without extraneous tabs, menus, or unrequested graphics.
- [ ] **4.2 Native Drag-and-Drop:**
  - Enable dragging and dropping project files directly onto the Qt application window to populate the source file path automatically.
- [ ] **4.3 Non-Intrusive Update Checker:**
  - Background check against the GitHub Releases API on startup.
  - If a newer release exists, display a subtle clickable link/pill in the status bar (*"Update available: v1.1.0"*). No modal popups or blocking behavior.
- [ ] **4.4 Build Specifications:**
  - Windows: Single portable `.exe` and Inno Setup installer (`.exe`) with Start Menu shortcuts and clean uninstall.
  - macOS: Apple Disk Image (`.dmg`) bundling an arm64 / universal `.app` bundle.
  - Linux: Self-contained `.AppImage` with desktop integration metadata.
- [ ] **4.5 Automated GitHub Actions Workflow:**
  - Matrix build pipeline (`windows-latest`, `macos-latest`, `ubuntu-latest`).
  - Automated compilation, testing, and release asset publishing upon tagging git releases.
