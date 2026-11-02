"""ReaScript FX Loader (.lua) generator and effect mapper.

Translates Audacity realtime effect chains to REAPER equivalents:
- Stock Audacity effects -> Cockos stock plugins (ReaComp, ReaEQ, ReaDelay, ReaVerbate)
- Third-party VST/VST3 effects -> automated TrackFX_AddByName and parameter binding
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .models import AudacityProject, Effect, Track

logger = logging.getLogger(__name__)


@dataclass
class ReaperFXEntry:
    """Represents a formatted plugin entry for REAPER <FXCHAIN> embedding."""
    tag: str  # "VST" or "VST3"
    display_name: str  # e.g. "VST: ReaComp (Cockos)" or "VST3: FabFilter Pro-Q 3"
    dll_name: str  # e.g. "reacomp.dll" or "FabFilter Pro-Q 3.vst3"
    plugin_id: int  # 1919247213 for ReaComp, 0 for generic VST/VST3
    chunk_data: Optional[str] = None  # Base64 plugin state blob
    active: bool = True
    mapped_type: str = "custom"
    parameters: Dict[str, Any] = field(default_factory=dict)


def safe_float(val: Any, default: float = 0.0) -> float:
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


class FXMapper:
    """Maps Audacity effect chains to REAPER ReaScript Lua code and native <FXCHAIN> chunks."""

    def __init__(self, project: AudacityProject) -> None:
        self.project = project

    def is_stock_audacity_effect(self, effect: Effect) -> bool:
        """Check if an effect is an Audacity built-in stock effect."""
        eid = effect.effect_id.lower()
        return any(
            k in eid
            for k in [
                "builtin:compressor",
                "builtin:equalizer",
                "builtin:filtercurve",
                "builtin:graphiceq",
                "builtin:delay",
                "builtin:reverb",
                "builtin:limiter",
                "audacity:audacity:builtin",
            ]
        )

    def classify_effect(self, effect: Effect) -> Tuple[str, str, Dict[str, Any]]:
        """Classify effect and return (target_plugin_name, plugin_type, mapped_params)."""
        eid = effect.effect_id.lower()

        # 1. Audacity Compressor -> ReaComp (Cockos)
        if "compressor" in eid:
            thresh_db = safe_float(effect.parameters.get("Threshold", "-12.0"))
            ratio = safe_float(effect.parameters.get("Ratio", "3.0"))
            # Audacity attack/release are in seconds; ReaComp uses milliseconds
            attack_s = safe_float(effect.parameters.get("AttackTime", "0.2"))
            release_s = safe_float(effect.parameters.get("ReleaseTime", "1.0"))
            attack_ms = attack_s * 1000.0
            release_ms = release_s * 1000.0

            return (
                "VST:ReaComp (Cockos)",
                "reacomp",
                {
                    "Threshold": thresh_db,
                    "Ratio": max(1.0, ratio),
                    "Attack": max(0.0, attack_ms),
                    "Release": max(1.0, release_ms),
                },
            )

        # 2. Audacity Equalizer / FilterCurve / GraphicEQ -> ReaEQ (Cockos)
        elif any(k in eid for k in ["equalizer", "filtercurve", "graphiceq"]):
            params = {}
            # Check for cutoff / frequency attributes
            hp_cutoff = safe_float(
                effect.parameters.get("HighpassCutoff", effect.parameters.get("LowCut", "80.0"))
            )
            lp_cutoff = safe_float(
                effect.parameters.get("LowpassCutoff", effect.parameters.get("HighCut", "16000.0"))
            )
            params["Band1_Freq"] = hp_cutoff
            params["Band4_Freq"] = lp_cutoff

            # Graphic EQ slider gains if present
            for k, v in effect.parameters.items():
                if k.startswith("Band_") or k.startswith("f_"):
                    params[k] = safe_float(v)

            return ("VST:ReaEQ (Cockos)", "reaeq", params)

        # 3. Audacity Delay -> ReaDelay (Cockos)
        elif "delay" in eid:
            delay_s = safe_float(effect.parameters.get("DelayTime", "0.3"))
            feedback = safe_float(effect.parameters.get("Feedback", "30.0"))
            return (
                "VST:ReaDelay (Cockos)",
                "readelay",
                {
                    "Delay_ms": delay_s * 1000.0,
                    "Feedback": feedback,
                },
            )

        # 4. Audacity Reverb -> ReaVerbate (Cockos)
        elif "reverb" in eid:
            room_size = safe_float(effect.parameters.get("RoomSize", "75.0"))
            damping = safe_float(effect.parameters.get("Damping", "50.0"))
            wet_gain = safe_float(effect.parameters.get("WetGain", "0.0"))
            dry_gain = safe_float(effect.parameters.get("DryGain", "0.0"))
            return (
                "VST:ReaVerbate (Cockos)",
                "reaverbate",
                {
                    "RoomSize": room_size,
                    "Damping": damping,
                    "Wet": wet_gain,
                    "Dry": dry_gain,
                },
            )

        # 5. Audacity Limiter -> ReaLimit (Cockos)
        elif "limiter" in eid:
            thresh_db = safe_float(effect.parameters.get("Threshold", "-1.0"))
            return (
                "VST:ReaLimit (Cockos)",
                "realimit",
                {"Threshold": thresh_db},
            )

        # 6. Third-party VST3 or VST
        else:
            plugin_ident = effect.effect_id
            if not (plugin_ident.startswith("VST3:") or plugin_ident.startswith("VST:")):
                if "vst3" in eid:
                    clean = effect.clean_name()
                    plugin_ident = f"VST3:{clean}"
                else:
                    clean = effect.clean_name()
                    plugin_ident = f"VST:{clean}"

            raw_params: Dict[str, Any] = {}
            for k, v in effect.parameters.items():
                val_num = safe_float(v, None)
                raw_params[k] = val_num if val_num is not None else v

            return (plugin_ident, "third_party", raw_params)

    def get_reaper_vst_entry(self, effect: Effect) -> ReaperFXEntry:
        """Derive standard REAPER <VST / <VST3 metadata for direct <FXCHAIN> embedding."""
        target_name, ptype, params = self.classify_effect(effect)
        eid = effect.effect_id.lower()

        if ptype == "reacomp":
            return ReaperFXEntry(
                tag="VST",
                display_name="VST: ReaComp (Cockos)",
                dll_name="reacomp.dll",
                plugin_id=1919247213,
                chunk_data=effect.chunk_data,
                active=effect.active,
                mapped_type="reacomp",
                parameters=params,
            )
        elif ptype == "reaeq":
            return ReaperFXEntry(
                tag="VST",
                display_name="VST: ReaEQ (Cockos)",
                dll_name="reaeq.dll",
                plugin_id=1919247729,
                chunk_data=effect.chunk_data,
                active=effect.active,
                mapped_type="reaeq",
                parameters=params,
            )
        elif ptype == "readelay":
            return ReaperFXEntry(
                tag="VST",
                display_name="VST: ReaDelay (Cockos)",
                dll_name="readelay.dll",
                plugin_id=1919247212,
                chunk_data=effect.chunk_data,
                active=effect.active,
                mapped_type="readelay",
                parameters=params,
            )
        elif ptype == "reaverbate":
            return ReaperFXEntry(
                tag="VST",
                display_name="VST: ReaVerbate (Cockos)",
                dll_name="reaverbate.dll",
                plugin_id=1919251058,
                chunk_data=effect.chunk_data,
                active=effect.active,
                mapped_type="reaverbate",
                parameters=params,
            )
        elif ptype == "realimit":
            return ReaperFXEntry(
                tag="VST",
                display_name="VST: ReaLimit (Cockos)",
                dll_name="realimit.dll",
                plugin_id=1919251053,
                chunk_data=effect.chunk_data,
                active=effect.active,
                mapped_type="realimit",
                parameters=params,
            )
        else:
            clean = effect.clean_name()
            if clean.startswith("VST3:"):
                clean = clean[5:].strip()
            elif clean.startswith("VST:"):
                clean = clean[4:].strip()

            is_vst3 = ("vst3" in eid) or target_name.startswith("VST3:")
            tag = "VST3" if is_vst3 else "VST"
            display_name = f"{tag}: {clean}"
            dll_ext = ".vst3" if is_vst3 else ".dll"
            dll_name = f"{clean}{dll_ext}"

            return ReaperFXEntry(
                tag=tag,
                display_name=display_name,
                dll_name=dll_name,
                plugin_id=0,
                chunk_data=effect.chunk_data,
                active=effect.active,
                mapped_type="vst3" if is_vst3 else "vst",
                parameters=params,
            )

    def generate_lua_script(self, output_path: Path) -> str:
        """Generate REAPER ReaScript Lua script."""
        lines: List[str] = [
            "-- ===================================================================",
            f"-- ReaScript FX Loader for {self.project.name}",
            "-- Generated automatically by aup3-to-reaper",
            "-- Instructions: In REAPER, open Actions -> Show action list ->",
            "--               New Action -> Load ReaScript -> Select this file -> Run.",
            "-- ===================================================================",
            "",
            "reaper.ClearConsole()",
            f'reaper.ShowConsoleMsg("=== Loading FX Chains for {self.project.name} ===\\n")',
            "",
            'reaper.Undo_BeginBlock2(0, "AUP3 to REAPER: Restore Realtime FX Chains")',
            "",
            "-- Helper function to find a track by name or index",
            "local function find_track(track_idx, track_name)",
            "    local count = reaper.CountTracks(0)",
            "    -- Try matching track name first",
            "    for i = 0, count - 1 do",
            "        local tr = reaper.GetTrack(0, i)",
            '        local retval, cur_name = reaper.GetTrackName(tr, "")',
            "        if retval and cur_name == track_name then",
            "            return tr",
            "        end",
            "    end",
            "    -- Fallback to index if within bounds",
            "    if track_idx >= 0 and track_idx < count then",
            "        return reaper.GetTrack(0, track_idx)",
            "    end",
            "    return nil",
            "end",
            "",
            "-- Helper function to set parameter by name or index on an instantiated FX",
            "local function set_fx_param(track, fx_idx, param_key, param_value)",
            '    if type(param_key) == "number" then',
            "        reaper.TrackFX_SetParam(track, fx_idx, param_key, param_value)",
            "        return true",
            "    end",
            "",
            "    local num_params = reaper.TrackFX_GetNumParams(track, fx_idx)",
            "    local search_key = tostring(param_key):lower():gsub('[%s_]', '')",
            "    for p = 0, num_params - 1 do",
            '        local retval, pname = reaper.TrackFX_GetParamName(track, fx_idx, p, "")',
            "        if retval then",
            "            local clean_p = pname:lower():gsub('[%s_]', '')",
            "            if clean_p == search_key or clean_p:find(search_key, 1, true) then",
            '                if type(param_value) == "number" then',
            "                    reaper.TrackFX_SetParam(track, fx_idx, p, param_value)",
            "                else",
            "                    -- Try setting normalized or native",
            "                    local num = tonumber(param_value)",
            "                    if num then reaper.TrackFX_SetParam(track, fx_idx, p, num) end",
            "                end",
            "                return true",
            "            end",
            "        end",
            "    end",
            "    return false",
            "end",
            "",
        ]

        total_effects = 0

        # Loop through tracks with effects
        for tr_idx, track in enumerate(self.project.tracks):
            if not track.effects:
                continue

            escaped_track_name = track.name.replace('"', '\\"')
            lines.append(f"-- Track {track.track_id}: {track.name}")
            lines.append("do")
            lines.append(f'    local track = find_track({tr_idx}, "{escaped_track_name}")')
            lines.append("    if not track then")
            lines.append(
                f'        reaper.ShowConsoleMsg("[-] Track not found: {escaped_track_name}\\n")'
            )
            lines.append("    else")
            lines.append(
                f'        reaper.ShowConsoleMsg("[+] Configuring FX on track: {escaped_track_name}\\n")'
            )

            for eff in track.effects:
                total_effects += 1
                target_plugin, ptype, params = self.classify_effect(eff)
                escaped_target = target_plugin.replace('"', '\\"')
                active_str = "true" if eff.active else "false"

                lines.append(f'        -- Effect: {eff.clean_name()} ({eff.effect_id})')
                lines.append(
                    f'        local fx_idx = reaper.TrackFX_AddByName(track, "{escaped_target}", false, -1)'
                )
                lines.append("        if fx_idx < 0 then")
                lines.append(
                    f'            reaper.ShowConsoleMsg("    [!] Could not instantiate plugin: {escaped_target}\\n")'
                )
                lines.append("        else")
                lines.append(
                    f'            reaper.TrackFX_SetEnabled(track, fx_idx, {active_str})'
                )

                if ptype == "reacomp":
                    # ReaComp parameters: 0: Threshold (dB), 1: Ratio, 2: Attack (ms), 3: Release (ms)
                    thresh = params.get("Threshold", -12.0)
                    ratio = params.get("Ratio", 3.0)
                    att = params.get("Attack", 200.0)
                    rel = params.get("Release", 1000.0)
                    lines.append(f"            -- Set ReaComp parameters")
                    lines.append(f"            reaper.TrackFX_SetParam(track, fx_idx, 0, {thresh}) -- Threshold (dB)")
                    lines.append(f"            reaper.TrackFX_SetParam(track, fx_idx, 1, {ratio})  -- Ratio")
                    lines.append(f"            reaper.TrackFX_SetParam(track, fx_idx, 2, {att})    -- Attack (ms)")
                    lines.append(f"            reaper.TrackFX_SetParam(track, fx_idx, 3, {rel})    -- Release (ms)")

                elif ptype == "reaeq":
                    # ReaEQ: Band 1 freq, Band 4 freq
                    b1 = params.get("Band1_Freq", 80.0)
                    b4 = params.get("Band4_Freq", 16000.0)
                    lines.append(f"            -- Set ReaEQ frequency parameters")
                    lines.append(f"            set_fx_param(track, fx_idx, 'Freq-Low Shelf', {b1})")
                    lines.append(f"            set_fx_param(track, fx_idx, 'Freq-High Shelf', {b4})")

                elif ptype == "readelay":
                    dms = params.get("Delay_ms", 300.0)
                    fb = params.get("Feedback", 30.0)
                    lines.append(f"            -- Set ReaDelay parameters")
                    lines.append(f"            set_fx_param(track, fx_idx, 'Length', {dms})")
                    lines.append(f"            set_fx_param(track, fx_idx, 'Feedback', {fb})")

                elif ptype == "reaverbate":
                    room = params.get("RoomSize", 75.0)
                    damp = params.get("Damping", 50.0)
                    lines.append(f"            -- Set ReaVerbate parameters")
                    lines.append(f"            set_fx_param(track, fx_idx, 'Room size', {room})")
                elif ptype == "realimit":
                    thresh = params.get("Threshold", -1.0)
                    lines.append(f"            -- Set ReaLimit parameters")
                    lines.append(f"            set_fx_param(track, fx_idx, 'Threshold', {thresh})")

                else:
                    # Third-party VST3 or generic parameter assignment
                    for pk, pv in params.items():
                        escaped_pk = str(pk).replace('"', '\\"')
                        if isinstance(pv, (int, float)):
                            lines.append(
                                f'            set_fx_param(track, fx_idx, "{escaped_pk}", {pv})'
                            )
                        else:
                            escaped_pv = str(pv).replace('"', '\\"')
                            lines.append(
                                f'            set_fx_param(track, fx_idx, "{escaped_pk}", "{escaped_pv}")'
                            )

                lines.append(
                    f'            reaper.ShowConsoleMsg("    [+] Added {escaped_target}\\n")'
                )
                lines.append("        end")

            lines.append("    end")
            lines.append("end")
            lines.append("")

        lines.append('reaper.Undo_EndBlock2(0, "AUP3 to REAPER: Restore Realtime FX Chains", -1)')
        lines.append('reaper.UpdateArrange()')
        lines.append('reaper.ShowConsoleMsg("=== Finished restoring FX chains! ===\\n")')

        content = "\n".join(lines) + "\n"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(content)

        logger.info("Generated ReaScript FX loader script: %s (%d effects)", output_path, total_effects)
        return content
