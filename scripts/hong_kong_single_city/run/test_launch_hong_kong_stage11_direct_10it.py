import unittest
import xml.etree.ElementTree as ET

from launch_hong_kong_stage11_direct_10it import (
    freeze_canonical_plan_innovation,
    require_canonical_plan_innovation_frozen,
    require_physical_transit_modes,
    require_pt_teleported_routing,
    require_scoring_function_creation_after_replanning,
    require_taxi_scoring_contract,
    require_car_passenger_time_only,
    set_scoring_function_creation_after_replanning,
    set_physical_transit_modes,
    set_pt_teleported_routing,
    set_taxi_scoring_contract,
    set_car_passenger_time_only,
)


def config_with_mode_params(mode_sets: str) -> ET.Element:
    return ET.fromstring(
        "<config><module name='scoring'>" + mode_sets + "</module></config>"
    )


class TaxiScoringContractTest(unittest.TestCase):

    def test_missing_taxi_mode_is_added_with_authorized_formula(self) -> None:
        root = config_with_mode_params(
            "<parameterset type='modeParams'>"
            "<param name='mode' value='car'/>"
            "</parameterset>"
        )
        set_taxi_scoring_contract(root)
        require_taxi_scoring_contract(root)

    def test_explicit_zero_distance_terms_are_accepted(self) -> None:
        root = config_with_mode_params(
            "<parameterset type='modeParams'>"
            "<param name='mode' value='taxi'/>"
            "<param name='marginalUtilityOfDistance' value='0'/>"
            "<param name='monetaryDistanceRate' value='0.0'/>"
            "</parameterset>"
        )
        set_taxi_scoring_contract(root)
        require_taxi_scoring_contract(root)

    def test_existing_values_are_replaced_by_authorized_formula(self) -> None:
        root = config_with_mode_params(
            "<parameterset type='modeParams'>"
            "<param name='mode' value='taxi'/>"
            "<param name='marginalUtilityOfDistance' value='0'/>"
            "<param name='monetaryDistanceRate' value='-0.0015'/>"
            "</parameterset>"
        )
        set_taxi_scoring_contract(root)
        require_taxi_scoring_contract(root)


class CarPassengerScoringContractTest(unittest.TestCase):

    def test_provisional_distance_money_is_removed(self) -> None:
        root = config_with_mode_params(
            "<parameterset type='modeParams'>"
            "<param name='mode' value='car_passenger'/>"
            "<param name='constant' value='-1.5'/>"
            "<param name='marginalUtilityOfTraveling_util_hr' value='-6'/>"
            "<param name='marginalUtilityOfDistance_util_m' value='0'/>"
            "<param name='monetaryDistanceRate' value='-0.0015'/>"
            "<param name='dailyMonetaryConstant' value='0'/>"
            "<param name='dailyUtilityConstant' value='0'/>"
            "</parameterset>"
        )
        set_car_passenger_time_only(root)
        require_car_passenger_time_only(root)
        block = root.find("./module/parameterset")
        values = {
            item.get("name"): item.get("value") for item in block.findall("./param")
        }
        self.assertEqual("0", values["monetaryDistanceRate"])

class ScoringLifecycleContractTest(unittest.TestCase):

    def test_missing_controller_parameter_is_added(self) -> None:
        root = ET.fromstring("<config><module name='controller'/></config>")
        set_scoring_function_creation_after_replanning(root)
        require_scoring_function_creation_after_replanning(root)

    def test_iteration_starts_is_replaced_with_before_mobsim(self) -> None:
        root = ET.fromstring(
            "<config><module name='controller'>"
            "<param name='createScoringFunctionType' "
            "value='IterationStarts'/>"
            "</module></config>"
        )
        set_scoring_function_creation_after_replanning(root)
        require_scoring_function_creation_after_replanning(root)


class PhysicalTransitModesContractTest(unittest.TestCase):

    def test_generic_pt_is_replaced_by_physical_vehicle_modes(self) -> None:
        root = ET.fromstring(
            "<config><module name='transit'>"
            "<param name='transitModes' value='pt'/>"
            "</module></config>"
        )
        set_physical_transit_modes(root)
        require_physical_transit_modes(root)
        self.assertEqual(
            "bus,gmb,train,light_rail,ferry",
            root.find("./module/param").get("value"),
        )

    def test_generic_pt_teleported_router_is_explicit(self) -> None:
        root = ET.fromstring("<config><module name='routing'/></config>")
        set_pt_teleported_routing(root)
        require_pt_teleported_routing(root)

class CanonicalPlanContractTest(unittest.TestCase):

    def test_innovation_is_frozen_for_each_subpopulation(self) -> None:
        settings = "".join(
            "<parameterset type='strategysettings'>"
            f"<param name='strategyName' value='{strategy}'/>"
            "<param name='weight' value='0.25'/>"
            f"<param name='subpopulation' value='{subpopulation}'/>"
            "</parameterset>"
            for subpopulation in ("resident", "visitor")
            for strategy in (
                "ChangeExpBeta",
                "ReRoute",
                "SubtourModeChoice",
                "TimeAllocationMutator",
            )
        )
        root = ET.fromstring(
            "<config><module name='replanning'>" + settings + "</module></config>"
        )
        freeze_canonical_plan_innovation(root)
        require_canonical_plan_innovation_frozen(root)

if __name__ == "__main__":
    unittest.main()
