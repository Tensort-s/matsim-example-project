#!/usr/bin/env python3
"""Independently validate the all-student v6 school-mode candidate registry."""

from __future__ import annotations

import argparse
from collections import Counter
import gzip
import json
from pathlib import Path

import pandas as pd
from lxml import etree as ET


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CANDIDATES = (
    REPO_ROOT
    / "data/school/hongkong/processed/school_bus_plan_candidates_5pct_v6"
)
DEFAULT_SUPPLY = (
    REPO_ROOT
    / "data/transit/hongkong/processed"
    / "matsim_road_pt_school_bus_supply_2026_v6_adoption_ready"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-dir", type=Path, default=DEFAULT_CANDIDATES)
    parser.add_argument("--supply-dir", type=Path, default=DEFAULT_SUPPLY)
    parser.add_argument("--max-route-candidates", type=int, default=3)
    parser.add_argument("--max-walk-distance-m", type=float, default=5_000.0)
    return parser.parse_args()


def local_name(element: ET._Element) -> str:
    return ET.QName(element).localname


def schedule_inventory(path: Path) -> dict[str, set[str]]:
    inventory = {
        "facilities": set(),
        "lines": set(),
        "routes": set(),
        "departures": set(),
        "vehicles": set(),
    }
    with gzip.open(path, "rb") as handle:
        context = ET.iterparse(handle, events=("end",))
        for _, element in context:
            name = local_name(element)
            identifier = element.get("id", "")
            if name == "stopFacility" and identifier.startswith("sbv6_"):
                inventory["facilities"].add(identifier)
            elif name == "transitLine" and identifier.startswith("line_school_bus_v6_"):
                inventory["lines"].add(identifier)
                for route in [child for child in element if local_name(child) == "transitRoute"]:
                    inventory["routes"].add(route.get("id", ""))
                    departures = next(child for child in route if local_name(child) == "departures")
                    for departure in departures:
                        if local_name(departure) != "departure":
                            continue
                        inventory["departures"].add(departure.get("id", ""))
                        inventory["vehicles"].add(departure.get("vehicleRefId", ""))
                element.clear()
    return inventory


def main() -> None:
    args = parse_args()
    universe = pd.read_csv(args.candidate_dir / "school_trip_universe_v6.csv", dtype=str).fillna("")
    modes = pd.read_csv(args.candidate_dir / "school_mode_candidates_v6.csv", dtype=str).fillna("")
    school_bus = pd.read_csv(
        args.candidate_dir / "school_bus_physical_route_candidates_v6.csv", dtype=str
    ).fillna("")
    inventory = schedule_inventory(
        args.supply_dir / "transitSchedule_5pct_school_bus_v6.xml.gz"
    )

    trip_ids = set(universe["trip_id"])
    mode_trip_ids = set(modes["trip_id"])
    bus_trip_ids = set(school_bus["trip_id"])
    by_trip_mode = modes.groupby(["trip_id", "candidate_mode"]).size()
    bus_counts = school_bus.groupby("trip_id").size()
    direction_per_person = universe.groupby("person_id")["direction"].agg(set)
    eligible_flags = universe.set_index("trip_id")["school_bus_eligible"].str.lower().eq("true")
    walk = modes[modes["candidate_mode"].eq("walk")]
    walk_distances = pd.to_numeric(walk["estimated_walk_distance_m"], errors="coerce")
    crowfly = pd.to_numeric(
        universe.set_index("trip_id").loc[walk["trip_id"], "crowfly_distance_m"],
        errors="coerce",
    ).to_numpy()

    checks = {
        "trip_ids_unique": not universe["trip_id"].duplicated().any(),
        "candidate_ids_unique": not modes["candidate_id"].duplicated().any(),
        "school_bus_candidate_ids_unique": not school_bus["candidate_id"].duplicated().any(),
        "all_students_have_exactly_inbound_and_outbound": all(
            directions == {"inbound_am", "outbound_pm"}
            for directions in direction_per_person
        ),
        "candidate_catalog_covers_only_known_trips": mode_trip_ids.issubset(trip_ids),
        "every_trip_has_pt_once": all(
            by_trip_mode.get((trip_id, "pt"), 0) == 1 for trip_id in trip_ids
        ),
        "every_trip_has_taxi_once": all(
            by_trip_mode.get((trip_id, "taxi"), 0) == 1 for trip_id in trip_ids
        ),
        "walk_candidates_obey_distance_threshold": bool(
            (crowfly <= args.max_walk_distance_m + 1e-6).all()
            and walk_distances.notna().all()
        ),
        "bus_eligibility_matches_bus_candidate_presence": {
            trip_id for trip_id, eligible in eligible_flags.items() if eligible
        } == bus_trip_ids,
        "bus_candidate_limit_obeyed": bool((bus_counts <= args.max_route_candidates).all()),
        "bus_mode_rows_match_physical_rows": set(
            modes.loc[modes["candidate_mode"].eq("school_bus"), "candidate_id"]
        ) == set(school_bus["candidate_id"]),
        "all_bus_lines_exist": set(school_bus["transit_line_id"]).issubset(inventory["lines"]),
        "all_bus_routes_exist": set(school_bus["transit_route_id"]).issubset(inventory["routes"]),
        "all_bus_departures_exist": set(school_bus["departure_id"]).issubset(inventory["departures"]),
        "all_bus_vehicles_exist": set(school_bus["vehicle_id"]).issubset(inventory["vehicles"]),
        "all_boarding_facilities_exist": set(school_bus["boarding_facility_id"]).issubset(
            inventory["facilities"]
        ),
        "all_alighting_facilities_exist": set(school_bus["alighting_facility_id"]).issubset(
            inventory["facilities"]
        ),
        "all_bus_candidates_have_links": bool(
            school_bus["boarding_link_id"].ne("").all()
            and school_bus["alighting_link_id"].ne("").all()
        ),
        "old_mode_declared_audit_only": universe[
            "old_mode_used_for_eligibility_or_ranking"
        ].str.lower().eq("false").all(),
        "no_candidate_marked_selected": modes["selection_status"].eq(
            "unselected_candidate"
        ).all(),
    }
    checks = {name: bool(passed) for name, passed in checks.items()}
    failed = [name for name, passed in checks.items() if not passed]
    result = {
        "status": "passed" if not failed else "failed",
        "counts": {
            "students": int(universe["person_id"].nunique()),
            "school_trips": int(len(universe)),
            "mode_candidate_rows": int(len(modes)),
            "physical_school_bus_candidate_rows": int(len(school_bus)),
            "school_bus_eligible_trips": int(len(bus_trip_ids)),
            "candidate_modes": dict(Counter(modes["candidate_mode"])),
        },
        "checks": checks,
        "failed_checks": failed,
    }
    output = args.candidate_dir / "school_mode_candidate_validation_v6.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
