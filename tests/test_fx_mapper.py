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


if __name__ == "__main__":
    unittest.main()
