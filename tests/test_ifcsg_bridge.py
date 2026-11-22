"""Tests for the IFC+SG semantic bridge and Obsidian exporter helpers."""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "_tools"))
from export_obsidian import safe_note_name, tag_for_type
from ifcsg_bridge import format_checklist, format_entity_view, load_bridge, validate_bridge


class IfcSgBridgeTests(unittest.TestCase):
    def test_bridge_validates_against_multicode_sources_and_concepts(self):
        result = validate_bridge(check_full_graph=False)
        self.assertTrue(result["ok"], msg=f"Bridge validation errors: {result['errors']}")
        self.assertGreaterEqual(result["entities"], 10)
        self.assertGreaterEqual(result["checks"], 13)

    def test_fire_safety_checklist_links_scdf_to_ifcsg(self):
        text = format_checklist("fire_safety")
        self.assertIn("CHK-FIRE-01", text)
        self.assertIn("IfcDoor", text)
        self.assertIn("IfcStair", text)
        self.assertIn("IfcDamper", text)
        self.assertIn("IfcTransportElement", text)

    def test_washroom_checklist_separates_geometry_property_and_submittal_checks(self):
        text = format_checklist("washroom")
        self.assertIn("IfcSpace", text)
        self.assertIn("IfcAlarm", text)
        self.assertIn("geometry_clearance", text)
        self.assertIn("submittal_or_drawing", text)
        self.assertIn("property_lookup", text)
        self.assertIn("6.3.5c.(1)(a)(i)", text)

    def test_entity_view_resolves_ramp_and_washroom_ifc_classes(self):
        ramp = format_entity_view("IfcRamp")
        self.assertIn("CHK-RAMP-01", ramp)
        self.assertIn("SGPset_RampDimension", ramp)
        self.assertIn("verified_corenet_x_2026_09", ramp)

        space = format_entity_view("IfcSpace")
        self.assertIn("CHK-WASH-01", space)
        self.assertIn("SGPset_Space", space)
        self.assertIn("LargerAccessible", space)

    def test_obsidian_note_names_are_windows_safe_and_unique(self):
        used = set()
        first = safe_note_name("BCA", 'CLAUSE 5.2.2(d): "Washroom" / [LWC]?', used)
        second = safe_note_name("BCA", 'CLAUSE 5.2.2(d): "Washroom" / [LWC]?', used)
        self.assertNotEqual(first, second)
        for bad in '<>:"/\\|?*[]':
            self.assertNotIn(bad, first)
        self.assertEqual(tag_for_type("BUILDING ELEMENT"), "#BUILDING_ELEMENT")

    def test_deterministic_ifcsg_graph_builder_helpers(self):
        from build_ifcsg_graph import _norm_agency, _stable_id
        self.assertEqual(_norm_agency("BCA "), "BCA")
        self.assertEqual(_norm_agency("NPARKS"), "NParks")
        self.assertEqual(_norm_agency("ALL"), "All")
        self.assertEqual(_stable_id("entity", "IfcSpace"), _stable_id("entity", "IfcSpace"))

    def test_ui_synonym_expansion_maps_toilet_to_water_closet_and_lwc(self):
        from ui_app import expand_terms
        raw, expanded = expand_terms("toilet")
        self.assertEqual(raw, ["toilet"])
        self.assertIn("water closet", expanded)
        self.assertIn("lwc", expanded)
        self.assertIn("largeraccessible", expanded)


if __name__ == "__main__":
    unittest.main()
