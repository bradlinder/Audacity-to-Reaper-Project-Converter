"""Tests for effect mapping and ReaScript Lua generation."""

import tempfile
import unittest
from pathlib import Path

from audacity_to_reaper.fx_mapper import FXMapper
from audacity_to_reaper.models import AudacityProject, Effect, Track


class TestFXMapper(unittest.TestCase):
    """Test suite for FX classification, translation, and Lua script output."""

    def test_compressor_mapping(self):
        project = AudacityProject(project_path=Path("proj.aup3"), name="proj")
        eff = Effect(
            effect_id="Audacity:Audacity:builtin:compressor:Compressor",
            parameters={
                "Threshold": "-18.0",
                "Ratio": "4.0",
                "AttackTime": "0.05",
                "ReleaseTime": "0.5",
            },
        )
        mapper = FXMapper(project)
        plugin, ptype, params = mapper.classify_effect(eff)

        self.assertEqual(plugin, "VST:ReaComp (Cockos)")
        self.assertEqual(ptype, "reacomp")
        self.assertEqual(params["Threshold"], -18.0)
        self.assertEqual(params["Ratio"], 4.0)
        self.assertEqual(params["Attack"], 50.0)  # 0.05s * 1000 = 50ms
        self.assertEqual(params["Release"], 500.0)  # 0.5s * 1000 = 500ms

    def test_equalizer_mapping(self):
        project = AudacityProject(project_path=Path("proj.aup3"), name="proj")
        eff = Effect(
            effect_id="Audacity:Audacity:builtin:filtercurve:FilterCurve",
            parameters={
                "HighpassCutoff": "100.0",
                "LowpassCutoff": "12000.0",
            },
        )
        mapper = FXMapper(project)
        plugin, ptype, params = mapper.classify_effect(eff)

        self.assertEqual(plugin, "VST:ReaEQ (Cockos)")
        self.assertEqual(ptype, "reaeq")
        self.assertEqual(params["Band1_Freq"], 100.0)
        self.assertEqual(params["Band4_Freq"], 12000.0)

    def test_third_party_vst3_mapping(self):
        project = AudacityProject(project_path=Path("proj.aup3"), name="proj")
        eff = Effect(
            effect_id="VST3:FabFilter Pro-Q 3",
            parameters={"Gain": "3.5", "Frequency": "2500.0"},
        )
        mapper = FXMapper(project)
        plugin, ptype, params = mapper.classify_effect(eff)

        self.assertEqual(plugin, "VST3:FabFilter Pro-Q 3")
        self.assertEqual(ptype, "third_party")
        self.assertEqual(params["Gain"], 3.5)
        self.assertEqual(params["Frequency"], 2500.0)

    def test_lua_script_generation(self):
        project = AudacityProject(project_path=Path("proj.aup3"), name="TestSession")
        tr = Track(track_id=1, name="Dialogue")
        tr.effects.append(
            Effect(
                effect_id="Audacity:builtin:compressor",
                parameters={"Threshold": "-15.0", "Ratio": "2.5", "AttackTime": "0.1", "ReleaseTime": "0.8"},
            )
        )
        project.tracks.append(tr)

        with tempfile.TemporaryDirectory() as tmp_dir:
            lua_path = Path(tmp_dir) / "test_fx.lua"
            mapper = FXMapper(project)
            script = mapper.generate_lua_script(lua_path)

            self.assertTrue(lua_path.exists())
            self.assertIn("VST:ReaComp (Cockos)", script)
            self.assertIn("reaper.TrackFX_AddByName", script)
            self.assertIn("reaper.TrackFX_SetParam(track, fx_idx, 0, -15.0)", script)
            self.assertIn("reaper.TrackFX_SetParam(track, fx_idx, 1, 2.5)", script)
            self.assertIn("reaper.TrackFX_SetParam(track, fx_idx, 2, 100.0)", script)
            self.assertIn("reaper.TrackFX_SetParam(track, fx_idx, 3, 800.0)", script)


    def test_reaper_vst_entry_stock_effects(self):
        """Verify ReaperFXEntry creation for all Cockos stock Rea-family plugins."""
        project = AudacityProject(project_path=Path("proj.aup3"), name="proj")
        mapper = FXMapper(project)

        # 1. Compressor -> ReaComp
        comp = Effect(effect_id="builtin:compressor", parameters={"Threshold": "-12.0"})
        e_comp = mapper.get_reaper_vst_entry(comp)
        self.assertEqual(e_comp.tag, "VST")
        self.assertEqual(e_comp.display_name, "VST: ReaComp (Cockos)")
        self.assertEqual(e_comp.dll_name, "reacomp.dll")
        self.assertEqual(e_comp.plugin_id, 1919247213)
        self.assertTrue(e_comp.active)

        # 2. Equalizer -> ReaEQ
        eq = Effect(effect_id="builtin:equalizer", parameters={"HighpassCutoff": "80.0"})
        e_eq = mapper.get_reaper_vst_entry(eq)
        self.assertEqual(e_eq.tag, "VST")
        self.assertEqual(e_eq.display_name, "VST: ReaEQ (Cockos)")
        self.assertEqual(e_eq.dll_name, "reaeq.dll")
        self.assertEqual(e_eq.plugin_id, 1919247729)

        # 3. Delay -> ReaDelay
        delay = Effect(effect_id="builtin:delay", parameters={"DelayTime": "0.25"})
        e_delay = mapper.get_reaper_vst_entry(delay)
        self.assertEqual(e_delay.tag, "VST")
        self.assertEqual(e_delay.display_name, "VST: ReaDelay (Cockos)")
        self.assertEqual(e_delay.dll_name, "readelay.dll")
        self.assertEqual(e_delay.plugin_id, 1919247212)

        # 4. Reverb -> ReaVerbate
        reverb = Effect(effect_id="builtin:reverb", parameters={"RoomSize": "60.0"})
        e_reverb = mapper.get_reaper_vst_entry(reverb)
        self.assertEqual(e_reverb.tag, "VST")
        self.assertEqual(e_reverb.display_name, "VST: ReaVerbate (Cockos)")
        self.assertEqual(e_reverb.dll_name, "reaverbate.dll")
        self.assertEqual(e_reverb.plugin_id, 1919251058)

        # 5. Limiter -> ReaLimit
        limiter = Effect(effect_id="builtin:limiter", parameters={"Threshold": "-0.5"})
        e_limiter = mapper.get_reaper_vst_entry(limiter)
        self.assertEqual(e_limiter.tag, "VST")
        self.assertEqual(e_limiter.display_name, "VST: ReaLimit (Cockos)")
        self.assertEqual(e_limiter.dll_name, "realimit.dll")
        self.assertEqual(e_limiter.plugin_id, 1919251053)

    def test_reaper_vst_entry_vst3_with_chunk_data(self):
        """Verify ReaperFXEntry for third-party VST3 preserves binary chunk blobs."""
        project = AudacityProject(project_path=Path("proj.aup3"), name="proj")
        mapper = FXMapper(project)

        sample_chunk = "c2FlcgEAAAACAAAAAQAAAAAAAAACAAAAAAAAAA=="
        eff = Effect(
            effect_id="VST3:iZotope Ozone 11",
            active=False,
            parameters={"Ceiling": "-0.3"},
            chunk_data=sample_chunk,
        )
        entry = mapper.get_reaper_vst_entry(eff)
        self.assertEqual(entry.tag, "VST3")
        self.assertEqual(entry.display_name, "VST3: iZotope Ozone 11")
        self.assertEqual(entry.dll_name, "iZotope Ozone 11.vst3")
        self.assertEqual(entry.plugin_id, 0)
        self.assertFalse(entry.active)
        self.assertEqual(entry.chunk_data, sample_chunk)


if __name__ == "__main__":
    unittest.main()
