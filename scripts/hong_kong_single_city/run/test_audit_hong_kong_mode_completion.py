from __future__ import annotations

import unittest
import xml.etree.ElementTree as ET

from audit_hong_kong_mode_completion import selected_trip_modes, summarize


class ModeCompletionAuditTest(unittest.TestCase):
    def test_selected_trip_modes_groups_pt_interactions(self) -> None:
        person = ET.fromstring(
            '<person id="p"><plan selected="yes">'
            '<activity type="home"/><leg mode="walk"><attributes>'
            '<attribute name="routingMode">pt</attribute></attributes></leg>'
            '<activity type="pt interaction"/><leg mode="pt"/>'
            '<activity type="work"/><leg mode="taxi"/><activity type="home"/>'
            '</plan></person>'
        )
        self.assertEqual(["pt", "taxi"], selected_trip_modes(person))

    def test_summary_uses_planned_mode_denominator(self) -> None:
        summary = summarize(
            {"p_1": "pt", "p_2": "pt", "q_1": "car"},
            {"p_1": "pt", "q_1": "car"},
        )
        self.assertEqual(0.5, summary["by_planned_main_mode"]["pt"]["completion_rate"])
        self.assertEqual(1.0, summary["by_planned_main_mode"]["car"]["completion_rate"])


if __name__ == "__main__":
    unittest.main()
