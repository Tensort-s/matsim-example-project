"""Quote Hong Kong MTR adult Octopus station-OD fares offline.

The interface accepts only explicit ordered station IDs.  It never reads
production plans and never infers a mode, route, station, direction, distance,
path, or transfer concession.
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import pandas as pd


ALLOWED_SCOPES = {
    "domestic_mtr_station_od",
    "airport_express_station_od",
}
REQUIRED_INPUT_COLUMNS = [
    "quote_id",
    "actual_transport_mode",
    "fare_network_scope",
    "boarding_station_id",
    "alighting_station_id",
    "passenger_type",
    "payment_medium",
    "travel_date",
]
OUTPUT_COLUMNS = [
    "quote_id",
    "actual_transport_mode",
    "fare_network_scope",
    "boarding_station_id",
    "alighting_station_id",
    "passenger_type",
    "payment_medium",
    "travel_date",
    "cost_component",
    "cost_hkd",
    "cost_source",
    "cost_effective_date",
    "cost_quality",
    "mapping_status",
    "source_record_id",
    "unresolved_reason",
    "transfer_concession_hkd",
    "transfer_concession_status",
]


def repository_root() -> Path:
    return Path(__file__).resolve().parents[4]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Quote explicit ordered Hong Kong MTR station-OD adult Octopus "
            "fares from the offline v1 rule table."
        )
    )
    parser.add_argument(
        "--input",
        type=Path,
        required=True,
        help="Input CSV containing explicit station-OD quote requests.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Output CSV for fare quotes and unresolved reasons.",
    )
    parser.add_argument(
        "--rules",
        type=Path,
        default=None,
        help=(
            "Station-OD rule Parquet. Defaults to the repository "
            "mtr_station_od_v1 output."
        ),
    )
    return parser.parse_args()


def require_columns(frame: pd.DataFrame, columns: list[str], label: str) -> None:
    missing = sorted(set(columns) - set(frame.columns))
    if missing:
        raise ValueError(f"{label} missing columns: {missing}")


def clean_text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def valid_iso_date(value: str) -> bool:
    try:
        date.fromisoformat(value)
    except (TypeError, ValueError):
        return False
    return True


def quote_dataframe(requests: pd.DataFrame, rules: pd.DataFrame) -> pd.DataFrame:
    """Return deterministic quotes for explicit ordered station-OD requests."""

    require_columns(requests, REQUIRED_INPUT_COLUMNS, "quote input")
    require_columns(
        rules,
        [
            "fare_network_scope",
            "boarding_station_id",
            "alighting_station_id",
            "adult_octopus_fare_hkd",
            "cost_component",
            "cost_source",
            "cost_effective_date",
            "cost_effective_date_status",
            "source_record_id",
            "record_status",
            "unresolved_reason",
        ],
        "MTR station-OD rules",
    )

    rules = rules.copy()
    for column in [
        "fare_network_scope",
        "boarding_station_id",
        "alighting_station_id",
        "record_status",
    ]:
        rules[column] = rules[column].map(clean_text)

    scope_stations: dict[str, set[str]] = {}
    for scope, group in rules.groupby("fare_network_scope", sort=True):
        scope_stations[str(scope)] = set(group["boarding_station_id"]) | set(
            group["alighting_station_id"]
        )
    all_stations = set().union(*scope_stations.values()) if scope_stations else set()

    output_rows: list[dict[str, object]] = []
    for request in requests.to_dict("records"):
        quote_id = clean_text(request.get("quote_id"))
        actual_mode = clean_text(request.get("actual_transport_mode"))
        scope = clean_text(request.get("fare_network_scope"))
        boarding = clean_text(request.get("boarding_station_id"))
        alighting = clean_text(request.get("alighting_station_id"))
        passenger_type = clean_text(request.get("passenger_type"))
        payment_medium = clean_text(request.get("payment_medium"))
        travel_date = clean_text(request.get("travel_date"))

        result: dict[str, object] = {
            "quote_id": quote_id,
            "actual_transport_mode": actual_mode,
            "fare_network_scope": scope,
            "boarding_station_id": boarding,
            "alighting_station_id": alighting,
            "passenger_type": passenger_type,
            "payment_medium": payment_medium,
            "travel_date": travel_date,
            "cost_component": "public_transport_fare",
            "cost_hkd": pd.NA,
            "cost_source": "",
            "cost_effective_date": "",
            "cost_quality": "U",
            "mapping_status": "unresolved",
            "source_record_id": "",
            "unresolved_reason": "",
            "transfer_concession_hkd": pd.NA,
            "transfer_concession_status": "not_modelled",
        }

        reason = ""
        if not actual_mode:
            reason = "missing_actual_transport_mode"
        elif actual_mode != "train":
            reason = "unsupported_actual_transport_mode"
        elif not scope:
            reason = "missing_fare_network_scope"
        elif scope not in ALLOWED_SCOPES:
            reason = "unsupported_fare_network_scope"
        elif not passenger_type:
            reason = "missing_passenger_type"
        elif passenger_type != "adult":
            reason = "unsupported_passenger_type"
        elif not payment_medium:
            reason = "missing_payment_medium"
        elif payment_medium != "Octopus":
            reason = "unsupported_payment_medium"
        elif not boarding:
            reason = "missing_boarding_station_id"
        elif not alighting:
            reason = "missing_alighting_station_id"
        elif not travel_date:
            reason = "missing_travel_date"
        elif not valid_iso_date(travel_date):
            reason = "invalid_travel_date"
        elif boarding not in all_stations:
            reason = "unknown_boarding_station_id"
        elif alighting not in all_stations:
            reason = "unknown_alighting_station_id"
        elif boarding not in scope_stations.get(scope, set()):
            reason = "boarding_station_not_in_requested_fare_scope"
        elif alighting not in scope_stations.get(scope, set()):
            reason = "alighting_station_not_in_requested_fare_scope"

        if reason:
            result["unresolved_reason"] = reason
            output_rows.append(result)
            continue

        candidates = rules[
            rules["fare_network_scope"].eq(scope)
            & rules["boarding_station_id"].eq(boarding)
            & rules["alighting_station_id"].eq(alighting)
        ]
        if len(candidates) == 0:
            result["unresolved_reason"] = "official_ordered_od_record_missing"
            output_rows.append(result)
            continue
        if len(candidates) != 1:
            result["mapping_status"] = "ambiguous"
            result["unresolved_reason"] = "multiple_rule_rows_for_ordered_od_key"
            output_rows.append(result)
            continue

        rule = candidates.iloc[0]
        record_status = clean_text(rule["record_status"])
        if record_status == "ambiguous":
            result["mapping_status"] = "ambiguous"
            result["unresolved_reason"] = (
                clean_text(rule["unresolved_reason"])
                or "conflicting_official_ordered_od_fares"
            )
            output_rows.append(result)
            continue
        if record_status != "available" or pd.isna(
            rule["adult_octopus_fare_hkd"]
        ):
            result["unresolved_reason"] = (
                clean_text(rule["unresolved_reason"])
                or "official_ordered_od_fare_unavailable"
            )
            output_rows.append(result)
            continue

        effective_date = clean_text(rule["cost_effective_date"])
        if not effective_date or not valid_iso_date(effective_date):
            result["unresolved_reason"] = "fare_effective_date_unresolved"
            output_rows.append(result)
            continue
        if date.fromisoformat(travel_date) < date.fromisoformat(effective_date):
            result["unresolved_reason"] = "travel_date_precedes_fare_effective_date"
            output_rows.append(result)
            continue

        result.update(
            {
                "cost_component": clean_text(rule["cost_component"]),
                "cost_hkd": float(rule["adult_octopus_fare_hkd"]),
                "cost_source": clean_text(rule["cost_source"]),
                "cost_effective_date": effective_date,
                "cost_quality": (
                    "A"
                    if clean_text(rule["cost_effective_date_status"])
                    == "local_source_proven"
                    else "B"
                ),
                "mapping_status": "exact",
                "source_record_id": clean_text(rule["source_record_id"]),
                "unresolved_reason": "",
            }
        )
        output_rows.append(result)

    output = pd.DataFrame(output_rows, columns=OUTPUT_COLUMNS)
    output["cost_hkd"] = pd.array(output["cost_hkd"], dtype="Float64")
    output["transfer_concession_hkd"] = pd.array(
        output["transfer_concession_hkd"], dtype="Float64"
    )
    return output


def main() -> None:
    args = parse_args()
    rules_path = (
        args.rules.resolve()
        if args.rules
        else repository_root()
        / "data/transport_costs/hongkong/pt_fare_v1/mtr_station_od_v1/"
        "mtr_station_od_fare_rules.parquet"
    )
    requests = pd.read_csv(
        args.input.resolve(), dtype=str, keep_default_na=False
    )
    rules = pd.read_parquet(rules_path)
    output = quote_dataframe(requests, rules)
    output_path = args.output.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(output_path, index=False, encoding="utf-8")
    print(
        f"Wrote {len(output)} quotes: "
        f"{int(output['cost_hkd'].notna().sum())} priced, "
        f"{int(output['cost_hkd'].isna().sum())} unresolved."
    )


if __name__ == "__main__":
    main()
