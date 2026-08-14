import importlib.util
from pathlib import Path
import tempfile
import unittest


MODULE_PATH = Path(__file__).with_name("audit_hong_kong_open_innovation.py")
SPEC = importlib.util.spec_from_file_location("open_innovation_audit", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def population(route: str, *, template: bool = False, binding: bool = True) -> str:
    template_value = "true" if template else "false"
    binding_attribute = (
        '<attribute name="hkHouseholdEscortBindingKey" class="java.lang.String">b1</attribute>'
        if binding else ""
    )
    return f"""<?xml version="1.0" encoding="utf-8"?>
<population>
  <person id="p1">
    <plan selected="yes">
      <attributes>
        <attribute name="hkHouseholdJointTemplate" class="java.lang.Boolean">{template_value}</attribute>
        <attribute name="hkHouseholdJointPlanRole" class="java.lang.String">passenger</attribute>
      </attributes>
      <act type="home" />
      <leg mode="car"><route type="links" start_link="a" end_link="c">{route}</route></leg>
      <act type="work" />
      <leg mode="car_passenger"><attributes>{binding_attribute}</attributes></leg>
      <act type="home" />
    </plan>
  </person>
</population>
"""


class SelectedPlanAuditTests(unittest.TestCase):

    def test_detects_route_change_and_integrity_flags(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            before = root / "before.xml"
            after = root / "after.xml"
            before.write_text(population("b", template=True, binding=False), encoding="utf-8")
            after.write_text(population("x y", template=False, binding=True), encoding="utf-8")

            result = MODULE.compare_selected_plans(before, after)

        self.assertEqual(
            1,
            result["private_car_route_innovation"]["changed_network_route_sequences"],
        )
        self.assertEqual(
            1,
            result["baseline_selected_plan_integrity"]["selected_temporary_template_plans"],
        )
        self.assertEqual(
            0,
            result["final_selected_plan_integrity"]["selected_unbound_car_passenger_legs"],
        )


if __name__ == "__main__":
    unittest.main()
