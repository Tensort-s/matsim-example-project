from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name(
    "audit_hong_kong_household_car_passenger_candidates.py"
)
SPEC = importlib.util.spec_from_file_location("household_audit", MODULE_PATH)
audit = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = audit
SPEC.loader.exec_module(audit)


def leg(
    person: str,
    household: str,
    mode: str,
    departure: float,
    origin: tuple[float, float],
    destination: tuple[float, float],
    *,
    vehicle: str = "",
    route_vehicle: str = "",
    index: int = 0,
) -> audit.TripLeg:
    return audit.TripLeg(
        person_id=person,
        household_id=household,
        role="fixed_worker",
        leg_index=index,
        mode=mode,
        assigned_vehicle_id=vehicle,
        route_vehicle_id=route_vehicle,
        departure_time_s=departure,
        travel_time_s=600,
        origin_type="home",
        origin_facility_id=f"home_{household}",
        origin_x=origin[0],
        origin_y=origin[1],
        destination_type="work",
        destination_facility_id=f"destination_{person}",
        destination_x=destination[0],
        destination_y=destination[1],
        route_distance_m=10_000,
    )


class CandidateClassificationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.thresholds = audit.Thresholds()

    def test_direct_candidate_requires_same_household(self) -> None:
        passenger = leg("p", "h1", "car_passenger", 1000, (0, 0), (10000, 0))
        driver = leg(
            "d", "h1", "car", 1100, (50, 0), (10020, 0),
            vehicle="v1", route_vehicle="v1"
        )
        other = leg(
            "x", "h2", "car", 1000, (0, 0), (10000, 0),
            vehicle="v2", route_vehicle="v2"
        )
        rows, direct, default = audit.classify_passengers(
            [passenger], [driver, other], self.thresholds
        )
        self.assertEqual("existing_car_leg_direct", rows[0]["candidate_status"])
        self.assertEqual({"d"}, direct[("p", 0)])
        self.assertEqual({"d"}, default[("p", 0)])

    def test_detour_and_no_compatible_categories(self) -> None:
        passenger = leg("p", "h", "car_passenger", 1000, (0, 0), (8000, 0))
        detour_driver = leg(
            "d", "h", "car", 1100, (0, 0), (10000, 1000),
            vehicle="v", route_vehicle="v"
        )
        rows, _, default = audit.classify_passengers(
            [passenger], [detour_driver], self.thresholds
        )
        self.assertEqual(
            "existing_car_leg_detour_screen", rows[0]["candidate_status"]
        )
        self.assertEqual({"d"}, default[("p", 0)])

        late_driver = leg(
            "d", "h", "car", 10_000, (0, 0), (8000, 0),
            vehicle="v", route_vehicle="v"
        )
        rows, _, _ = audit.classify_passengers(
            [passenger], [late_driver], self.thresholds
        )
        self.assertEqual(
            "real_driver_no_compatible_existing_leg",
            rows[0]["candidate_status"],
        )

    def test_no_real_driver_and_vehicle_validation(self) -> None:
        passenger = leg("p", "h", "car_passenger", 1000, (0, 0), (1000, 0))
        rows, _, _ = audit.classify_passengers([passenger], [], self.thresholds)
        self.assertEqual("no_real_driver_current_plan", rows[0]["candidate_status"])

        private = leg(
            "d1", "h", "car", 1000, (0, 0), (1000, 0),
            vehicle="v1", route_vehicle="v1"
        )
        motorcycle = leg(
            "d2", "h", "car", 1000, (0, 0), (1000, 0),
            vehicle="v2", route_vehicle="v2"
        )
        mismatch = leg(
            "d3", "h", "car", 1000, (0, 0), (1000, 0),
            vehicle="v3", route_vehicle="other"
        )
        accepted, counts = audit.valid_driver_legs(
            [private, motorcycle, mismatch],
            {"v1": "private_car", "v2": "motorcycle", "v3": "private_car"},
        )
        self.assertEqual([private], accepted)
        self.assertEqual(1, counts["excluded_vehicle_type::motorcycle"])
        self.assertEqual(1, counts["route_vehicle_mismatch"])

    def test_person_requires_same_driver_for_complete_tour(self) -> None:
        rows = [
            {
                "person_id": "p",
                "leg_index": 0,
                "household_id": "h",
                "role": "day_school_student",
                "allocation_source": "student",
                "student_stage": "primary",
                "age": 8,
                "sex": "F",
                "relationship_role": "child",
                "household_private_vehicle_count": 1,
                "real_driver_person_count": 2,
            },
            {
                "person_id": "p",
                "leg_index": 1,
                "household_id": "h",
                "role": "day_school_student",
                "allocation_source": "student",
                "student_stage": "primary",
                "age": 8,
                "sex": "F",
                "relationship_role": "child",
                "household_private_vehicle_count": 1,
                "real_driver_person_count": 2,
            },
        ]
        keys = {("p", 0): {"d1"}, ("p", 1): {"d2"}}
        people = audit.person_rows(rows, keys, keys)
        self.assertEqual(
            "complete_detour_screen_different_drivers",
            people[0]["candidate_tour_status"],
        )

    def test_legacy_school_escort_crosscheck(self) -> None:
        people = [
            {
                "person_id": "student",
                "candidate_tour_status": "complete_direct_same_driver",
                "candidate_same_driver_person_id": "driver",
            }
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "escort.csv"
            path.write_text(
                "student_person_id,driver_person_id,accepted\n"
                "student,driver,True\n",
                encoding="utf-8",
            )
            result = audit.crosscheck_school_escorts(people, path)
        self.assertTrue(result["exact_match"])
        self.assertEqual(1, result["person_id_intersection"])


if __name__ == "__main__":
    unittest.main()
