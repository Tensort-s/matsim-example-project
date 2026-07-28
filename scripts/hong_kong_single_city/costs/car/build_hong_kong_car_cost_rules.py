#!/usr/bin/env python3
"""Collect pinned sources and build Hong Kong private-car cost rules v1."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import ssl
import urllib.request
from datetime import date
from pathlib import Path

import geopandas as gpd
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_OUTPUT = REPO_ROOT / "data/transport_costs/hongkong/car_cost_v1"
CANONICAL_PROJECT = Path(r"F:\Matsim\matsim-example-project")
DEFAULT_INPUT_PROJECT = CANONICAL_PROJECT if CANONICAL_PROJECT.exists() else REPO_ROOT
SNAPSHOT_DATE = "2026-07-28"

SOURCES = {
    "consumer_oil_price.html": {
        "url": "https://oil-price.consumer.org.hk/en",
        "role": "Consumer Council standard-petrol pump and walk-in-discount prices.",
        "effective_date": "2026-07-28",
    },
    "government_private_car_energy_consumption.html": {
        "url": "https://www.info.gov.hk/gia/general/202005/06/P2020050600552.htm",
        "role": (
            "Government reply citing EMSD 1501-2500cc petrol-car consumption "
            "and the most common electric-private-car consumption."
        ),
        "effective_date": "2020-05-06",
    },
    "government_electricity_tariff_2026.html": {
        "url": "https://www.info.gov.hk/gia/general/202511/18/P2025111800787p.htm",
        "role": "Government announcement of CLP and HK Electric 2026 average net tariffs.",
        "effective_date": "2026-01-01",
    },
    "td_toll_rates.html": {
        "url": (
            "https://www.td.gov.hk/en/transport_in_hong_kong/tunnels_and_bridges_n/"
            "toll_matters/toll_rates_of_road_tunnels_and_lantau_link/index.html"
        ),
        "role": "Transport Department flat and time-varying road-toll overview.",
        "effective_date": "2026-07-17",
    },
    "td_harbour_tvt.html": {
        "url": (
            "https://www.td.gov.hk/en/transport_in_hong_kong/"
            "tunnels_and_bridges_n/tvt/index.html"
        ),
        "role": "Transport Department road-harbour-crossing time-varying toll rules.",
        "effective_date": "2023-12-17",
    },
    "td_tai_lam_tvt.html": {
        "url": (
            "https://www.td.gov.hk/en/transport_in_hong_kong/"
            "tunnels_and_bridges_n/tlt/index.html"
        ),
        "role": "Transport Department Tai Lam Tunnel time-varying toll rules.",
        "effective_date": "2025-05-31",
    },
    "td_government_car_parks.html": {
        "url": (
            "https://www.td.gov.hk/en/transport_in_hong_kong/parking/"
            "carparks/gov_car_parks_managed_by_td/index.html"
        ),
        "role": "Transport Department 2026 government-car-park hourly, pass and subscription fees.",
        "effective_date": "2026-03-01",
    },
    "td_parking_meters.html": {
        "url": (
            "https://www.td.gov.hk/en/transport_in_hong_kong/parking/"
            "parking_meters/index.html"
        ),
        "role": "Transport Department maximum private-car meter fee.",
        "effective_date": "2025-09-28",
    },
    "td_parking_fees_2026.pdf": {
        "url": "https://www.td.gov.hk/filemanager/en/content_4841/ParkingFeeRev2026en.pdf",
        "role": "Transport Department 11 government public car parks fee schedule.",
        "effective_date": "2026-03-01",
    },
    "housing_authority_carpark_fees_2026.pdf": {
        "url": (
            "https://www.housingauthority.gov.hk/en/common/pdf/about-us/housing-authority/"
            "ha-paper-library/CPC09-2025EN.pdf"
        ),
        "role": "Hong Kong Housing Authority 2026 hourly and monthly parking fees.",
        "effective_date": "2026-01-01",
    },
    "td_vehicle_licence_fees_2026.pdf": {
        "url": "https://www.td.gov.hk/filemanager/common/td341_2_2026_eng.pdf",
        "role": "Transport Department petrol and electric private-car annual licence fees.",
        "effective_date": "2026-03-01",
    },
    "td_vehicle_fuel_type_2025_12.xls": {
        "url": "https://www.td.gov.hk/filemanager/en/content_5378/table44.xls",
        "role": "Transport Department December 2025 registered/licensed vehicles by fuel type.",
        "effective_date": "2025-12-31",
    },
}

ZONE_GROUPS = {
    "hong_kong_island": {"zones": "1|2|3|4", "day": (16.0, 24.0, 26.0), "night": (14.0, 19.0, 20.0)},
    "kowloon_urban": {
        "zones": "5|6|7|8|9|10|11|12|13",
        "day": (14.0, 20.0, 24.0),
        "night": (12.0, 16.0, 19.0),
    },
    "new_territories_lantau": {
        "zones": "14|15|16|17|18|19|20|21|22|23|24|25|26",
        "day": (10.0, 16.0, 21.0),
        "night": (8.0, 14.0, 17.0),
    },
}
SCENARIOS = ("low", "base", "high")
SCENARIO_INDEX = {"low": 0, "base": 1, "high": 2}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-project-root", type=Path, default=DEFAULT_INPUT_PROJECT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--refresh-sources", action="store_true")
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_directory(path: Path) -> str:
    digest = hashlib.sha256()
    for child in sorted(item for item in path.rglob("*") if item.is_file()):
        relative = child.relative_to(path).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        with child.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def download(url: str, path: Path) -> None:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/126.0 Safari/537.36"
            )
        },
    )
    context = ssl.create_default_context()
    with urllib.request.urlopen(request, timeout=90, context=context) as response:
        with path.open("wb") as handle:
            shutil.copyfileobj(response, handle)


def collect_sources(output_dir: Path, refresh: bool) -> list[dict[str, object]]:
    snapshot_dir = output_dir / "source_snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, object]] = []
    for filename, metadata in SOURCES.items():
        path = snapshot_dir / filename
        if refresh or not path.exists():
            download(str(metadata["url"]), path)
        if path.stat().st_size == 0:
            raise ValueError(f"Downloaded source is empty: {path}")
        records.append(
            {
                "source_id": path.stem,
                "source_url": metadata["url"],
                "source_file": path.relative_to(output_dir).as_posix(),
                "file_sha256": sha256_file(path),
                "file_size_bytes": path.stat().st_size,
                "retrieval_date": SNAPSHOT_DATE,
                "effective_date": metadata["effective_date"],
                "role": metadata["role"],
                "publisher": publisher_for(str(metadata["url"])),
            }
        )
    return records


def publisher_for(url: str) -> str:
    if "consumer.org.hk" in url:
        return "Hong Kong Consumer Council"
    if "emsd.gov.hk" in url:
        return "Electrical and Mechanical Services Department"
    if "housingauthority.gov.hk" in url or "hkha.gov.hk" in url:
        return "Hong Kong Housing Authority"
    if "info.gov.hk" in url:
        return "Hong Kong SAR Government"
    return "Transport Department"


def source_record(records: list[dict[str, object]], filename: str) -> dict[str, object]:
    suffix = f"/{filename}"
    return next(row for row in records if str(row["source_file"]).endswith(suffix))


def read_fleet_shares(table_path: Path) -> dict[str, float]:
    """Read private-car licensed counts from TD table 4.4.

    The bilingual legacy workbook has merged cells and presentation rows, so
    tokens are located rather than relying on a fixed row number.
    """
    raw = pd.read_excel(table_path, header=None, dtype=object)
    rows = raw.astype(str).apply(lambda row: " | ".join(row.tolist()), axis=1)
    candidates = rows[rows.str.contains("Private Cars", case=False, na=False)]
    if candidates.empty:
        raise ValueError("Could not locate the Private Cars row in TD table 4.4")
    row = raw.loc[candidates.index[0]]
    numeric = []
    for value in row.tolist():
        try:
            number = float(str(value).replace(",", "").replace(" ", ""))
        except ValueError:
            continue
        if number >= 0:
            numeric.append(number)
    if len(numeric) < 6:
        raise ValueError(f"Unexpected TD table 4.4 private-car row: {row.tolist()}")
    # Table layout is registered/licensed pairs for petrol, diesel, electric,
    # LPG, hydrogen, others, and total. Take licensed members of the final 14.
    values = numeric[-14:]
    licensed = {
        "petrol": values[1],
        "diesel": values[3],
        "electric": values[5],
        "lpg": values[7],
        "hydrogen": values[9],
        "others": values[11],
        "total": values[13],
    }
    if licensed["total"] <= 0:
        raise ValueError(f"Invalid licensed private-car total: {licensed}")
    if abs(sum(licensed[key] for key in licensed if key != "total") - licensed["total"]) > 1:
        raise ValueError(f"TD private-car fuel-type counts do not conserve: {licensed}")
    return {
        "combustion_proxy_share": (
            licensed["petrol"]
            + licensed["diesel"]
            + licensed["lpg"]
            + licensed["hydrogen"]
            + licensed["others"]
        )
        / licensed["total"],
        "electric_share": licensed["electric"] / licensed["total"],
        **{f"licensed_{key}": value for key, value in licensed.items()},
    }


def build_energy_rules(
    records: list[dict[str, object]], output_dir: Path
) -> tuple[pd.DataFrame, dict[str, float]]:
    snapshot_dir = output_dir / "source_snapshots"
    shares = read_fleet_shares(snapshot_dir / "td_vehicle_fuel_type_2025_12.xls")
    oil = source_record(records, "consumer_oil_price.html")
    energy = source_record(records, "government_private_car_energy_consumption.html")
    tariff = source_record(records, "government_electricity_tariff_2026.html")
    fleet = source_record(records, "td_vehicle_fuel_type_2025_12.xls")

    # Consumer Council 2026-07-28 10:47 snapshot:
    # low=min standard-petrol walk-in price; base=median walk-in price;
    # high=max listed standard-petrol pump price.
    petrol_prices = {"low": 22.67, "base": 25.67, "high": 32.67}
    # Government-announced 2026 average net tariffs: CLP=1.406 and HKE=1.633
    # HKD/kWh. Base is weighted by 2.9m and 0.6m customers stated in 2025.
    electricity_prices = {
        "low": 1.406,
        "base": (1.406 * 2.9 + 1.633 * 0.6) / 3.5,
        "high": 1.633,
    }
    # The government reply cites EMSD at 11.6 L/100km for the dominant
    # 1501-2500cc petrol class and 0.2 kWh/km for the most common e-PC.
    # Low/high are explicit +/-20% consumption sensitivity assumptions.
    petrol_consumption = {"low": 9.28, "base": 11.6, "high": 13.92}
    electric_consumption = {"low": 16.0, "base": 20.0, "high": 24.0}

    files = "|".join(
        str(item["source_file"]) for item in (oil, energy, tariff, fleet)
    )
    hashes = "|".join(str(item["file_sha256"]) for item in (oil, energy, tariff, fleet))
    urls = "|".join(str(item["source_url"]) for item in (oil, energy, tariff, fleet))
    rows = []
    for scenario in SCENARIOS:
        energy_hkd_km = (
            shares["combustion_proxy_share"]
            * petrol_prices[scenario]
            * petrol_consumption[scenario]
            / 100.0
            + shares["electric_share"]
            * electricity_prices[scenario]
            * electric_consumption[scenario]
            / 100.0
        )
        rows.append(
            {
                "scenario": scenario,
                "vehicle_powertrain": "representative_hk_private_car_fleet_average",
                "petrol_price_hkd_per_litre": petrol_prices[scenario],
                "electricity_price_hkd_per_kwh": electricity_prices[scenario],
                "fuel_consumption_l_per_100km": petrol_consumption[scenario],
                "electricity_consumption_kwh_per_100km": electric_consumption[scenario],
                "combustion_proxy_share": shares["combustion_proxy_share"],
                "electric_share": shares["electric_share"],
                "energy_cost_hkd_per_km": energy_hkd_km,
                "effective_date": "2026-07-28",
                "source_url": urls,
                "source_file": files,
                "file_sha256": hashes,
                "cost_quality": "official_sources_representative_fleet_proxy",
                "assumption": (
                    "Current MATSim vehicles have no powertrain. TD licensed-fleet shares "
                    "are applied as a representative average; diesel/LPG/other non-electric "
                    "private cars use the petrol cost proxy. No per-vehicle powertrain is fabricated."
                ),
            }
        )
    frame = pd.DataFrame(rows)
    return frame, shares


def canonical_toll_id(name: str) -> str:
    base = name.replace(" (Backup Toll Point)", "")
    aliases = {
        "Cross Harbour Tunnel": "cross_harbour_tunnel",
        "Eastern Harbour Crossing": "eastern_harbour_crossing",
        "Western Harbour Crossing": "western_harbour_crossing",
        "Tai Lam Tunnel": "tai_lam_tunnel",
        "Aberdeen Tunnel": "aberdeen_tunnel",
        "Lion Rock Tunnel": "lion_rock_tunnel",
        "Shing Mun Tunnels": "shing_mun_tunnels",
        "Tate's Cairn Tunnel": "tates_cairn_tunnel",
        "Tsing Sha Control Area (Eagle's Nest Tunnel and Sha Tin Heights Tunnel)": (
            "tsing_sha_control_area"
        ),
    }
    return aliases[base]


def seconds(value: object) -> int:
    parts = str(value).split(":")
    return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(float(parts[2]))


def build_toll_rules(
    input_project: Path,
    records: list[dict[str, object]],
) -> tuple[pd.DataFrame, dict[str, object]]:
    gdb = input_project / "data/transit/hongkong/RdNet_IRNP.gdb"
    if not gdb.exists():
        raise FileNotFoundError(gdb)
    gdb_hash = sha256_directory(gdb)
    toll_web = source_record(records, "td_toll_rates.html")
    harbour_web = source_record(records, "td_harbour_tvt.html")
    tai_lam_web = source_record(records, "td_tai_lam_tvt.html")

    flat = gpd.read_file(gdb, layer="TUN_BRIDGE_TOLL", engine="pyogrio").drop(
        columns="geometry", errors="ignore"
    )
    flat = flat.loc[flat["VEHICLE_CLASS_DESCRIPTION"].eq("PC")].copy()
    tv = gpd.read_file(gdb, layer="TUN_BRIDGE_TV_TOLL", engine="pyogrio").drop(
        columns="geometry", errors="ignore"
    )
    tv = tv.loc[tv["VEHICLE_CLASS_DESCRIPTION"].eq("PC")].copy()
    tv_rows_before_backup_deduplication = len(tv)

    rows: list[dict[str, object]] = []
    for _, row in flat.iterrows():
        rows.append(
            {
                "toll_facility_id": canonical_toll_id(str(row["TUNNEL_BRIDGE_NAME"])),
                "toll_facility_name": row["TUNNEL_BRIDGE_NAME"],
                "vehicle_class": "private_car",
                "rule_type": "flat",
                "day_of_week_code": "ALL",
                "start_time_s": 0,
                "end_time_s": 86399,
                "toll_hkd": float(row["CONCESSION_TOLL"]),
                "feature_ids": f"{int(row['FEATURE_ID_1'])}|{int(row['FEATURE_ID_2'])}",
                "effective_date": pd.Timestamp(row["EFFECTIVE_DATE"]).date().isoformat(),
                "hketoll": True,
                "source_url": toll_web["source_url"],
                "source_file": (
                    f"{gdb.as_posix()}|{toll_web['source_file']}"
                ),
                "file_sha256": f"{gdb_hash}|{toll_web['file_sha256']}",
                "cost_quality": "official_machine_readable_private_car_rule",
            }
        )

    tv["toll_facility_id"] = tv["TUNNEL_BRIDGE_NAME"].map(
        lambda value: canonical_toll_id(str(value))
    )
    feature_union = (
        tv.groupby("toll_facility_id")[["FEATURE_ID_1", "FEATURE_ID_2"]]
        .agg(lambda series: sorted({int(value) for value in series.dropna()}))
        .apply(lambda row: sorted(set(row["FEATURE_ID_1"]) | set(row["FEATURE_ID_2"])), axis=1)
        .to_dict()
    )
    # Drop backup-point duplicate price schedules after retaining its feature ID.
    tv = tv.loc[~tv["TUNNEL_BRIDGE_NAME"].str.contains("Backup Toll Point", na=False)]
    for _, row in tv.iterrows():
        facility_id = str(row["toll_facility_id"])
        web = tai_lam_web if facility_id == "tai_lam_tunnel" else harbour_web
        rows.append(
            {
                "toll_facility_id": facility_id,
                "toll_facility_name": row["TUNNEL_BRIDGE_NAME"],
                "vehicle_class": "private_car",
                "rule_type": "time_varying",
                "day_of_week_code": row["DAY_OF_WEEK"],
                "start_time_s": seconds(row["START_TIME"]),
                "end_time_s": seconds(row["END_TIME"]),
                "toll_hkd": float(row["GAZETTED_TOLL"]),
                "feature_ids": "|".join(str(value) for value in feature_union[facility_id]),
                "effective_date": pd.Timestamp(row["EFFECTIVE_DATE"]).date().isoformat(),
                "hketoll": True,
                "source_url": web["source_url"],
                "source_file": f"{gdb.as_posix()}|{web['source_file']}",
                "file_sha256": f"{gdb_hash}|{web['file_sha256']}",
                "cost_quality": "official_machine_readable_private_car_rule",
            }
        )
    frame = pd.DataFrame(rows).sort_values(
        ["toll_facility_id", "day_of_week_code", "start_time_s"]
    )
    metadata = {
        "source_path": gdb.as_posix(),
        "directory_sha256_method": (
            "SHA256 over sorted relative file names and bytes, with each UTF-8 "
            "relative name prefixed by its 8-byte big-endian length."
        ),
        "directory_sha256": gdb_hash,
        "flat_private_car_rows": int(len(flat)),
        "time_varying_private_car_rows_before_backup_deduplication": int(
            tv_rows_before_backup_deduplication
        ),
        "canonical_facilities": int(frame["toll_facility_id"].nunique()),
    }
    return frame, metadata


def build_parking_rules(records: list[dict[str, object]]) -> pd.DataFrame:
    government_parks = source_record(records, "td_government_car_parks.html")
    meters = source_record(records, "td_parking_meters.html")
    parking_pdf = source_record(records, "td_parking_fees_2026.pdf")
    housing_pdf = source_record(records, "housing_authority_carpark_fees_2026.pdf")
    sources = (government_parks, meters, parking_pdf, housing_pdf)
    files = "|".join(str(item["source_file"]) for item in sources)
    hashes = "|".join(str(item["file_sha256"]) for item in sources)
    urls = "|".join(str(item["source_url"]) for item in sources)

    rows = []
    for zone_group, zone_rule in ZONE_GROUPS.items():
        for scenario in SCENARIOS:
            index = SCENARIO_INDEX[scenario]
            day_rate = float(zone_rule["day"][index])
            night_rate = float(zone_rule["night"][index])
            work_pass = {
                "hong_kong_island": (0.0, 210.0, 260.0),
                "kowloon_urban": (0.0, 160.0, 240.0),
                "new_territories_lantau": (0.0, 110.0, 210.0),
            }[zone_group][index]
            work_pass_base = {
                "hong_kong_island": 210.0,
                "kowloon_urban": 160.0,
                "new_territories_lantau": 110.0,
            }[zone_group]
            for activity_group in (
                "home",
                "work",
                "education",
                "shopping",
                "leisure",
                "medical_personal_business",
                "visitor_accommodation",
                "border",
                "other",
            ):
                if activity_group == "home":
                    method = "home_temporary_cost_zero_fixed_parking_separate"
                    resolved = True
                    hourly_day = hourly_night = daily_cap = 0.0
                elif activity_group == "work" and scenario == "low":
                    method = "monthly_subscription_marginal_zero_fixed_cost_separate"
                    resolved = True
                    hourly_day = hourly_night = daily_cap = 0.0
                elif activity_group == "work" and scenario == "base":
                    method = "representative_day_pass"
                    resolved = True
                    hourly_day = hourly_night = 0.0
                    daily_cap = work_pass
                elif activity_group == "work":
                    method = "hourly_or_part_capped_at_ten_hours"
                    resolved = True
                    hourly_day, hourly_night = day_rate, night_rate
                    daily_cap = work_pass
                elif activity_group == "visitor_accommodation":
                    method = "representative_night_pass"
                    resolved = True
                    hourly_day = hourly_night = 0.0
                    daily_cap = {"low": 60.0, "base": 80.0, "high": 150.0}[scenario]
                elif activity_group in {"border", "other"}:
                    method = "unresolved_no_supported_destination_parking_type"
                    resolved = False
                    hourly_day = hourly_night = daily_cap = float("nan")
                else:
                    method = "hourly_or_part_by_arrival_clock"
                    resolved = True
                    hourly_day, hourly_night = day_rate, night_rate
                    daily_cap = {
                        "low": 110.0,
                        "base": 210.0,
                        "high": 260.0,
                    }[scenario]
                rows.append(
                    {
                        "scenario": scenario,
                        "zone_group": zone_group,
                        "tcs_zones": zone_rule["zones"],
                        "activity_group": activity_group,
                        "pricing_method": method,
                        "hourly_day_hkd": hourly_day,
                        "hourly_night_hkd": hourly_night,
                        "daily_cap_hkd": daily_cap,
                        "minimum_charge_hkd": (
                            work_pass_base
                            if activity_group == "work" and scenario == "high"
                            else 0.0
                        ),
                        "monthly_rate_hkd": (
                            0.0
                            if not (activity_group == "work" and scenario == "low")
                            else {
                                "hong_kong_island": 4850.0,
                                "kowloon_urban": 3310.0,
                                "new_territories_lantau": 2340.0,
                            }[zone_group]
                        ),
                        "marginal_leg_cost_resolved": resolved,
                        "billing_increment_s": 3600,
                        "day_period_start_s": 7 * 3600,
                        "day_period_end_s": 23 * 3600,
                        "effective_date": "2026-03-01",
                        "source_url": urls,
                        "source_file": files,
                        "file_sha256": hashes,
                        "cost_quality": "official_rate_bounded_zone_activity_proxy",
                        "assumption": (
                            "Destination facility is not an observed car park. Official public "
                            "rates bound a TCS-zone/activity/duration proxy; border and other "
                            "destinations remain unresolved."
                        ),
                    }
                )
    return pd.DataFrame(rows)


def build_fixed_cost_parameters(records: list[dict[str, object]]) -> list[dict[str, object]]:
    licence = source_record(records, "td_vehicle_licence_fees_2026.pdf")
    housing = source_record(records, "housing_authority_carpark_fees_2026.pdf")
    government = source_record(records, "td_government_car_parks.html")
    rows = []
    values = {
        "low": (5074.0, 1614.0, 0.0),
        "base": (7498.0, 2614.0, 3310.0),
        "high": (9929.0, 5114.0, 4850.0),
    }
    for scenario, (combustion_licence, electric_licence, monthly_parking) in values.items():
        rows.append(
            {
                "scenario": scenario,
                "combustion_annual_licence_hkd": combustion_licence,
                "electric_annual_licence_hkd": electric_licence,
                "residential_monthly_parking_hkd": monthly_parking,
                "source_url": "|".join(
                    str(item["source_url"]) for item in (licence, housing, government)
                ),
                "source_file": "|".join(
                    str(item["source_file"]) for item in (licence, housing, government)
                ),
                "file_sha256": "|".join(
                    str(item["file_sha256"]) for item in (licence, housing, government)
                ),
                "effective_date": "2026-03-01",
                "exclusions": "depreciation|finance|insurance|maintenance",
                "cost_quality": "partial_fixed_cost_official_licence_and_parking_proxy",
            }
        )
    return rows


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    records = collect_sources(args.output_dir, args.refresh_sources)
    energy, fleet = build_energy_rules(records, args.output_dir)
    toll, toll_metadata = build_toll_rules(args.input_project_root, records)
    parking = build_parking_rules(records)
    fixed = build_fixed_cost_parameters(records)

    energy.to_csv(
        args.output_dir / "car_energy_cost_parameters.csv",
        index=False,
        encoding="utf-8",
    )
    toll.to_csv(args.output_dir / "car_toll_rules.csv", index=False, encoding="utf-8")
    parking.to_csv(
        args.output_dir / "car_parking_cost_rules.csv",
        index=False,
        encoding="utf-8",
    )
    manifest = {
        "model": "Hong Kong private car offline cost model v1",
        "generated_date": date.today().isoformat(),
        "source_snapshot_date": SNAPSHOT_DATE,
        "currency": "HKD",
        "sources": records,
        "machine_readable_toll_source": toll_metadata,
        "licensed_private_car_fleet": fleet,
        "fixed_vehicle_ownership_cost_parameters": fixed,
        "source_policy": (
            "Official Hong Kong government or Consumer Council sources are pinned. "
            "Proxy assumptions are explicit and do not create per-vehicle powertrains."
        ),
    }
    (args.output_dir / "car_cost_source_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output_dir": args.output_dir.as_posix(),
                "source_snapshots": len(records),
                "energy_scenarios": len(energy),
                "toll_rule_rows": len(toll),
                "parking_rule_rows": len(parking),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
