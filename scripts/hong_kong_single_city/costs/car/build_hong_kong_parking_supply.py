#!/usr/bin/env python3
"""Build a unified, non-adopted Hong Kong private-car parking supply candidate."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import shutil
import ssl
import urllib.request
from datetime import date
from pathlib import Path

import geopandas as gpd
import pandas as pd
from lxml import etree
from shapely.geometry import LineString, Point


REPO_ROOT = Path(__file__).resolve().parents[4]
CANONICAL_ROOT = Path(r"F:\Matsim\matsim-example-project")
SNAPSHOT_DATE = "2026-08-12"
OUTPUT_DIR = (
    REPO_ROOT / "data/transport_costs/hongkong/parking_supply_2026_v1"
)
SOURCES = {
    "data_gov_hk_metered_parking_resource.html": {
        "url": "https://data.gov.hk/en-data/dataset/hk-td-msd_1-metered-parking-spaces-data/resource/40ff6aca-cb3f-4b17-8910-7bc967ec18f6",
        "publisher": "Hong Kong Government Data One-stop",
        "role": "Official catalogue and metadata page for the metered-space dataset.",
    },
    "metered_parking_spaces.csv": {
        "url": "https://resource.data.one.gov.hk/td/psiparkingspaces/spaceinfo/parkingspaces.csv",
        "publisher": "Hong Kong Transport Department",
        "role": "Static metered parking-space locations, vehicle class and tariffs.",
    },
    "metered_parking_occupancy.csv": {
        "url": "https://resource.data.one.gov.hk/td/psiparkingspaces/occupancystatus/occupancystatus.csv",
        "publisher": "Hong Kong Transport Department",
        "role": "Current meter feed coverage only; snapshot vacancy is not static capacity.",
    },
    "carpark_info.json": {
        "url": "https://api.data.gov.hk/v1/carpark-info-vacancy?data=info&lang=en_US",
        "publisher": "Hong Kong Government Data One-stop",
        "role": "Off-street car-park identity, location, capacity and structured tariffs.",
    },
    "data_gov_hk_carpark_info_resource.html": {
        "url": "https://data.gov.hk/en-data/dataset/hk-dpo-datagovhk1-carpark-info-vacancy/resource/01752c62-a6b6-4ddc-bf2d-25efccadc143",
        "publisher": "Hong Kong Government Data One-stop",
        "role": "Official catalogue and metadata page for the car-park information API.",
    },
    "carpark_vacancy.json": {
        "url": "https://api.data.gov.hk/v1/carpark-info-vacancy?data=vacancy&vehicleTypes=privateCar&lang=en_US",
        "publisher": "Hong Kong Government Data One-stop",
        "role": "Current off-street availability-feed coverage only; values are not static capacity.",
    },
    "td_government_car_parks.html": {
        "url": "https://www.td.gov.hk/en/transport_in_hong_kong/parking/carparks/gov_car_parks_managed_by_td/index.html?print=1",
        "publisher": "Hong Kong Transport Department",
        "role": "Official capacities and tariffs for TD-managed government car parks.",
    },
    "metered_parking_spaces_data_spec.pdf": {
        "url": "https://www.td.gov.hk/datagovhk_td/metered-parking-spaces-data/resources/en/dataspec/metered_parking_spaces_data_dataspec.pdf",
        "publisher": "Hong Kong Transport Department",
        "role": "Meter field and code definitions.",
    },
    "parking_vacancy_data_spec.pdf": {
        "url": "https://resource.data.one.gov.hk/opendata/carpark/Parking_Vacancy_Data_Specification.pdf",
        "publisher": "Hong Kong Government Data One-stop",
        "role": "Car-park information and vacancy API field definitions.",
    },
}

EXPLICIT_NON_PRIVATE_CARPARK_IDS = {
    "tdc31p1",   # Wong Tai Sin: coach/goods vehicle only on the TD table.
    "tdc294p1",  # So Uk Phase 1: motorcycle and medium/heavy goods only.
    "tdstt141",  # Hoi Yu Street: goods vehicles and light buses only.
}

# The official meter specification defines these as charging periods. They are
# not treated as evidence that parking is prohibited outside the period.
METER_PERIODS = {
    "A": [("MON|TUE|WED|THU|FRI|SAT", True, "08:00", "24:00")],
    "B": [("MON|TUE|WED|THU|FRI|SAT", True, "08:00", "20:00")],
    "D": [
        ("MON|TUE|WED|THU|FRI|SAT", False, "08:00", "24:00"),
        ("SUN|PH", False, "10:00", "22:00"),
    ],
    "E": [("MON|TUE|WED|THU|FRI|SAT|SUN|PH", False, "07:00", "20:00")],
    "F": [("MON|TUE|WED|THU|FRI|SAT|SUN|PH", False, "08:00", "21:00")],
    "G": [("MON|TUE|WED|THU|FRI|SAT|SUN|PH", False, "07:00", "19:00")],
    "H": [("MON|TUE|WED|THU|FRI|SAT|SUN|PH", False, "08:00", "20:00")],
    "J": [("MON|TUE|WED|THU|FRI|SAT|SUN|PH", False, "08:00", "24:00")],
    "N": [("MON|TUE|WED|THU|FRI|SAT|SUN|PH", False, "19:00", "24:00")],
    "P": [("MON|TUE|WED|THU|FRI|SAT", True, "08:00", "20:00")],
    "Q": [
        ("MON|TUE|WED|THU|FRI|SAT", True, "08:00", "20:00"),
        ("SUN|PH", False, "10:00", "22:00"),
    ],
    "S": [
        ("MON|TUE|WED|THU|FRI", True, "17:00", "24:00"),
        ("SAT", True, "08:00", "24:00"),
        ("SUN|PH", False, "10:00", "22:00"),
    ],
    "T": [
        ("MON|TUE|WED|THU|FRI", True, "17:30", "24:00"),
        ("SAT", True, "08:00", "24:00"),
        ("SUN|PH", False, "10:00", "22:00"),
    ],
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--snapshot-date", default=SNAPSHOT_DATE)
    parser.add_argument("--refresh-sources", action="store_true")
    parser.add_argument("--input-project-root", type=Path, default=CANONICAL_ROOT)
    parser.add_argument(
        "--network",
        type=Path,
        default=REPO_ROOT / "data/transit/hongkong/processed/"
        "matsim_road_pt_school_bus_supply_2026_v6_adoption_ready/network.xml.gz",
    )
    return parser.parse_args()


def compact(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(url: str, path: Path) -> None:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 HongKongMATSimParkingSupply/1.0"},
    )
    context = ssl.create_default_context()
    temporary = path.with_suffix(path.suffix + ".download")
    with urllib.request.urlopen(request, timeout=120, context=context) as response:
        with temporary.open("wb") as handle:
            shutil.copyfileobj(response, handle)
    if temporary.stat().st_size == 0:
        raise ValueError(f"Empty download: {url}")
    temporary.replace(path)


def collect_sources(output_dir: Path, snapshot_date: str, refresh: bool) -> Path:
    snapshot_dir = output_dir / "source_snapshots" / snapshot_date
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    manifest = []
    for filename, metadata in SOURCES.items():
        path = snapshot_dir / filename
        if refresh or not path.exists():
            download(str(metadata["url"]), path)
        if not path.exists() or path.stat().st_size == 0:
            raise FileNotFoundError(path)
        manifest.append(
            {
                "source_file": path.relative_to(output_dir).as_posix(),
                "source_url": metadata["url"],
                "publisher": metadata["publisher"],
                "retrieval_date": snapshot_date,
                "sha256": sha256_file(path),
                "role": metadata["role"],
            }
        )
    pd.DataFrame(manifest).to_csv(
        output_dir / "SOURCE_MANIFEST.csv", index=False, encoding="utf-8", lineterminator="\n"
    )
    return snapshot_dir


def clean_text(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def numeric(value: object) -> float | None:
    if value is None or isinstance(value, (dict, list)):
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", str(value).replace(",", ""))
    return float(match.group()) if match else None


def td_government_charge_rules(header: str, value: str) -> list[dict[str, object]]:
    """Parse the bounded TD table forms while retaining each original value."""
    rules: list[dict[str, object]] = []
    header_period = re.search(r"(\d{2}:\d{2})\s*-\s*(\d{2}:\d{2})", header)
    if re.fullmatch(r"\d+(?:\.\d+)?", value) and header_period:
        return [
            {
                "source": "td_government_car_parks_page",
                "type": "hourly",
                "period_start": header_period.group(1),
                "period_end": header_period.group(2),
                "price_hkd": float(value),
            }
        ]
    pattern = re.compile(
        r"(?P<price>\d+(?:\.\d+)?)\s*\("
        r"(?P<kind>Day|Night)\s+Park\s+"
        r"(?P<start>\d{2}:\d{2})\s*-\s*(?P<end>\d{2}:\d{2})"
        r"(?P<qualifier>[^)]*)\)",
        re.IGNORECASE,
    )
    for match in pattern.finditer(value):
        qualifier = clean_text(match.group("qualifier")).lstrip(",").strip()
        rules.append(
            {
                "source": "td_government_car_parks_page",
                "type": f"{match.group('kind').lower()}_park_pass",
                "period_start": match.group("start"),
                "period_end": match.group("end"),
                "eligibility_text": qualifier,
                "price_hkd": float(match.group("price")),
                "raw": value,
            }
        )
    return rules


def meter_rules(group: pd.DataFrame) -> list[dict[str, object]]:
    rules: list[dict[str, object]] = []
    fields = ["OperatingPeriod", "TimeUnit", "PaymentUnit", "LPP"]
    for row in group[fields].drop_duplicates().itertuples(index=False):
        code = re.sub(r"^\d+", "", clean_text(row.OperatingPeriod)).upper()
        if code not in METER_PERIODS:
            raise ValueError(f"Unknown meter operating-period code: {row.OperatingPeriod}")
        unit = float(row.TimeUnit)
        payment = float(row.PaymentUnit)
        for weekdays, exclude_ph, start, end in METER_PERIODS[code]:
            rules.append(
                {
                    "source": "td_meter_static",
                    "operating_period_code": clean_text(row.OperatingPeriod),
                    "weekdays": weekdays,
                    "exclude_public_holiday": exclude_ph,
                    "period_start": start,
                    "period_end": end,
                    "billing_increment_min": unit,
                    "price_per_increment_hkd": payment,
                    "equivalent_hourly_rate_hkd": round(payment * 60 / unit, 6),
                    "maximum_stay_min": int(row.LPP),
                }
            )
    return rules


def build_meters(snapshot_dir: Path, snapshot_date: str) -> tuple[pd.DataFrame, dict[str, int]]:
    source = snapshot_dir / "metered_parking_spaces.csv"
    source_date = source.read_text(encoding="utf-8-sig").splitlines()[0].strip()
    raw = pd.read_csv(source, skiprows=2, dtype=str)
    raw["PoleIdNumber"] = pd.to_numeric(raw["PoleId"], errors="coerce")
    raw["Latitude"] = pd.to_numeric(raw["Latitude"], errors="coerce")
    raw["Longitude"] = pd.to_numeric(raw["Longitude"], errors="coerce")
    raw["LPP"] = pd.to_numeric(raw["LPP"], errors="raise")
    raw["TimeUnit"] = pd.to_numeric(raw["TimeUnit"], errors="raise")
    raw["PaymentUnit"] = pd.to_numeric(raw["PaymentUnit"], errors="raise")
    testing = raw["PoleIdNumber"].gt(90000).fillna(False)
    private = raw.loc[
        raw["VehicleType"].eq("A") & ~testing & raw["PoleIdNumber"].notna()
    ].copy()
    occupancy = pd.read_csv(snapshot_dir / "metered_parking_occupancy.csv", dtype=str)
    covered_spaces = set(occupancy["ParkingSpaceId"].dropna().astype(str))
    rows = []
    for pole_id, group in private.groupby("PoleIdNumber", sort=True):
        rules = meter_rules(group)
        rates = [float(item["equivalent_hourly_rate_hkd"]) for item in rules]
        spaces = sorted(set(group["ParkingSpaceId"].dropna().astype(str)))
        covered = sum(space in covered_spaces for space in spaces)
        street = " | ".join(sorted(set(filter(None, map(clean_text, group["Street"])))))
        section = " | ".join(sorted(set(filter(None, map(clean_text, group["SectionOfStreet"])))))
        rows.append(
            {
                "parking_supply_id": f"hk_meter_pole_{int(pole_id)}",
                "facility_type": "metered_on_street_pole",
                "source_record_id": str(int(pole_id)),
                "name_en": f"Meter pole {int(pole_id)} - {street}",
                "address_en": " - ".join(filter(None, [street, section])),
                "region_en": clean_text(group["Region"].iloc[0]),
                "district_en": clean_text(group["District"].iloc[0]),
                "subdistrict_en": clean_text(group["SubDistrict"].iloc[0]),
                "latitude": group["Latitude"].mean(),
                "longitude": group["Longitude"].mean(),
                "private_car_capacity": len(spaces),
                "capacity_status": "official_space_count_static_uncommissioned_risk",
                "capacity_source": "td_meter_space_rows",
                "capacity_includes_ev_and_disabled": "not_applicable",
                "ev_spaces": "",
                "disabled_spaces": "",
                "unloading_spaces": "",
                "opening_status_snapshot": "not_provided",
                "opening_rules_json": "",
                "pricing_status": "structured_meter_rate",
                "hourly_rate_min_hkd": min(rates),
                "hourly_rate_max_hkd": max(rates),
                "maximum_stay_min": int(group["LPP"].max()),
                "pricing_rules_json": compact(rules),
                "pricing_evidence_text": "",
                "payment_methods": "meter_payment_channels_not_in_static_file",
                "height_limit_m": "",
                "facility_features": "",
                "meter_space_ids": "|".join(spaces),
                "meter_operating_period_codes": "|".join(sorted(set(group["OperatingPeriod"]))),
                "availability_feed_status": (
                    "space_level_feed_complete" if covered == len(spaces)
                    else "space_level_feed_partial" if covered else "no_current_space_feed"
                ),
                "availability_reference_id": "|".join(space for space in spaces if space in covered_spaces),
                "source_provider": "Hong Kong Transport Department",
                "source_url": SOURCES["metered_parking_spaces.csv"]["url"],
                "source_modified_date": source_date,
                "source_snapshot_date": snapshot_date,
                "private_car_service_evidence": "official_vehicle_type_A",
                "limitations": "PoleId>90000 testing records excluded; static file may still include meters awaiting commissioning.",
            }
        )
    frame = pd.DataFrame(rows)
    stats = {
        "meter_raw_space_rows": int(len(raw)),
        "meter_test_rows_excluded": int(testing.sum()),
        "meter_private_car_space_rows": int(len(private)),
        "meter_private_car_unique_spaces": int(private["ParkingSpaceId"].nunique()),
        "meter_poles": int(len(frame)),
    }
    if int(frame["private_car_capacity"].sum()) != stats["meter_private_car_unique_spaces"]:
        raise ValueError("Meter capacity does not conserve distinct private-car spaces")
    return frame, stats


def td_government_records(snapshot_dir: Path) -> dict[str, dict[str, object]]:
    tables = pd.read_html(snapshot_dir / "td_government_car_parks.html")
    records: dict[str, dict[str, object]] = {}
    for table in tables[:2]:
        name_col = next(col for col in table if str(col).strip() == "Name")
        address_col = next(col for col in table if str(col).startswith("Address / Location"))
        capacity_col = next(col for col in table if "parking spaces for private cars" in str(col))
        quarterly_col = next(col for col in table if "quarterly parking service of private cars" in str(col))
        hourly_cols = [col for col in table if "Hourly charge for private cars" in str(col)]
        for name, group in table.groupby(name_col, sort=False):
            name = clean_text(name)
            hourly_rules = []
            evidence = []
            for col in hourly_cols:
                header = clean_text(col)
                for value in dict.fromkeys(clean_text(v) for v in group[col]):
                    if not value:
                        continue
                    evidence.append(f"{header}: {value}")
                    hourly_rules.extend(td_government_charge_rules(header, value))
            quarterly = clean_text(group[quarterly_col].iloc[0])
            if quarterly:
                evidence.append(f"quarterly_private_car_hkd: {quarterly}")
                quarterly_price = numeric(quarterly)
                hourly_rules.append(
                    {
                        "source": "td_government_car_parks_page",
                        "type": "quarterly_parking",
                        "price_hkd": quarterly_price,
                        "raw": quarterly,
                    }
                )
            records[name.casefold()] = {
                "name": name,
                "address": clean_text(group[address_col].iloc[0]),
                "capacity": int(float(group[capacity_col].iloc[0])),
                "hourly_rules": hourly_rules,
                "evidence": " | ".join(evidence),
            }
    return records


def vacancy_coverage(snapshot_dir: Path) -> dict[str, str]:
    rows = json.loads((snapshot_dir / "carpark_vacancy.json").read_text(encoding="utf-8"))["results"]
    result = {}
    labels = {"A": "actual_count_feed", "B": "binary_availability_feed", "C": "closed_feed_state"}
    for row in rows:
        states = row.get("privateCar") or []
        types = sorted({clean_text(item.get("vacancy_type")) for item in states if item})
        result[str(row["park_Id"])] = "|".join(labels.get(value, f"unknown_type_{value}") for value in types)
    return result


def height_and_text(row: dict[str, object]) -> tuple[float | str, str]:
    heights = []
    remarks = []
    for item in row.get("heightLimits") or []:
        height = numeric(item.get("height"))
        if height and height > 0:
            heights.append(height)
        if clean_text(item.get("remark")):
            remarks.append(clean_text(item.get("remark")))
    return (min(heights) if heights else "", " | ".join(remarks))


def hourly_rates(rules: list[dict[str, object]]) -> list[float]:
    rates = []
    for rule in rules:
        rate = numeric(rule.get("price"))
        if rate is None:
            continue
        rates.append(rate * 2 if clean_text(rule.get("type")).lower() == "half-hourly" else rate)
    return rates


def build_offstreet(snapshot_dir: Path, snapshot_date: str) -> tuple[pd.DataFrame, dict[str, int]]:
    info = json.loads((snapshot_dir / "carpark_info.json").read_text(encoding="utf-8"))["results"]
    vacancy = vacancy_coverage(snapshot_dir)
    government = td_government_records(snapshot_dir)
    rows = []
    excluded_non_private = 0
    supplemented = set()
    for source in info:
        park_id = str(source["park_Id"])
        latitude = numeric(source.get("latitude"))
        longitude = numeric(source.get("longitude"))
        if latitude is None or longitude is None:
            continue
        private = source.get("privateCar") if isinstance(source.get("privateCar"), dict) else None
        height, remarks = height_and_text(source)
        govt = government.get(clean_text(source.get("name")).casefold())
        explicit_heavy_only = park_id in EXPLICIT_NON_PRIVATE_CARPARK_IDS
        if explicit_heavy_only:
            excluded_non_private += 1
            continue
        structured_rules = []
        if private:
            for key in ("hourlyCharges", "dayNightParks", "monthlyCharges"):
                for item in private.get(key) or []:
                    structured_rules.append({"source": "carpark_info_api", "category": key, **item})
        rates = hourly_rates(private.get("hourlyCharges") or []) if private else []
        capacity = private.get("space") if private else None
        capacity_status = "official_structured_private_car_capacity" if capacity is not None else "unknown_not_zero"
        capacity_source = "carpark_info_api" if capacity is not None else ""
        source_urls = [SOURCES["carpark_info.json"]["url"]]
        evidence = remarks
        if govt:
            supplemented.add(clean_text(source.get("name")).casefold())
            capacity = govt["capacity"]
            capacity_status = "official_td_managed_car_park_capacity"
            capacity_source = "td_government_car_parks_page"
            structured_rules = [*structured_rules, *govt["hourly_rules"]]
            rates.extend(
                float(item["price_hkd"])
                for item in govt["hourly_rules"]
                if item["type"] == "hourly"
            )
            evidence = " | ".join(filter(None, [remarks, govt["evidence"]]))
            source_urls.append(SOURCES["td_government_car_parks.html"]["url"])
        if private:
            service_evidence = "structured_privateCar_object"
        elif govt:
            service_evidence = "td_government_private_car_table"
        elif re.search(r"(?i)private car|ev cars?|general parking", remarks):
            service_evidence = "official_free_text_private_car_reference"
        else:
            service_evidence = "official_carpark_catalog_vehicle_class_unspecified"
        address = source.get("address") or {}
        rows.append(
            {
                "parking_supply_id": f"hk_offstreet_{park_id}",
                "facility_type": clean_text(source.get("carpark_Type")) or "off_street_unspecified",
                "source_record_id": park_id,
                "name_en": clean_text(source.get("name")),
                "address_en": clean_text(source.get("displayAddress")) or clean_text(source.get("address")),
                "region_en": clean_text(address.get("region")) if isinstance(address, dict) else "",
                "district_en": clean_text(source.get("district")) or (clean_text(address.get("dcDistrict")) if isinstance(address, dict) else ""),
                "subdistrict_en": clean_text(address.get("subDistrict")) if isinstance(address, dict) else "",
                "latitude": latitude,
                "longitude": longitude,
                "private_car_capacity": "" if capacity is None else int(capacity),
                "capacity_status": capacity_status,
                "capacity_source": capacity_source,
                "capacity_includes_ev_and_disabled": "true" if capacity is not None else "unknown",
                "ev_spaces": private.get("spaceEV", "") if private else "",
                "disabled_spaces": private.get("spaceDIS", "") if private else "",
                "unloading_spaces": private.get("spaceUNL", "") if private else "",
                "opening_status_snapshot": clean_text(source.get("opening_status")) or "not_provided",
                "opening_rules_json": compact(source.get("openingHours") or []),
                "pricing_status": "structured_offstreet_rates" if structured_rules else "unparsed_or_not_provided",
                "hourly_rate_min_hkd": min(rates) if rates else "",
                "hourly_rate_max_hkd": max(rates) if rates else "",
                "maximum_stay_min": "",
                "pricing_rules_json": compact(structured_rules) if structured_rules else "",
                "pricing_evidence_text": evidence,
                "payment_methods": "|".join(map(clean_text, source.get("paymentMethods") or [])),
                "height_limit_m": height,
                "facility_features": "|".join(map(clean_text, source.get("facilities") or [])),
                "meter_space_ids": "",
                "meter_operating_period_codes": "",
                "availability_feed_status": vacancy.get(park_id, "no_current_private_car_feed"),
                "availability_reference_id": park_id if park_id in vacancy else "",
                "source_provider": "Hong Kong Government Data One-stop" + ("|Hong Kong Transport Department" if govt else ""),
                "source_url": "|".join(source_urls),
                "source_modified_date": clean_text(source.get("modifiedDate")) + ("|2026-06-30" if govt else ""),
                "source_snapshot_date": snapshot_date,
                "private_car_service_evidence": service_evidence,
                "limitations": "Current OPEN/CLOSED and vacancy are observations, not permanent supply eligibility. Blank capacity means unknown, not zero.",
            }
        )
    missing_government = sorted(set(government) - supplemented)
    if missing_government:
        raise ValueError(f"TD government car parks did not match API records: {missing_government}")
    frame = pd.DataFrame(rows)
    return frame, {
        "carpark_api_records": len(info),
        "carpark_explicit_non_private_excluded": excluded_non_private,
        "offstreet_facilities": len(frame),
        "offstreet_structured_private_car_records": sum(isinstance(row.get("privateCar"), dict) for row in info),
        "td_government_private_car_records_supplemented": len(supplemented),
        "offstreet_unknown_capacity": int(frame["private_car_capacity"].eq("").sum()),
    }


def assign_tcs(frame: pd.DataFrame, input_root: Path) -> pd.DataFrame:
    regions_path = input_root / "data/worldcommuting_od/hongkong/custom_features/hong_kong_fixed_link_grid/CityAndRegionSplit/hong_kong_fixed_link_grid/regions.shp"
    households_path = input_root / "data/matsim_agents/hongkong/synthetic_households_tcs2022/synthetic_households.parquet"
    households = pd.read_parquet(households_path, columns=["grid_id", "tcs_zone"])
    modal = (
        households.loc[households["tcs_zone"].between(1, 26)]
        .groupby(["grid_id", "tcs_zone"], as_index=False).size()
        .sort_values(["grid_id", "size", "tcs_zone"], ascending=[True, False, True])
        .drop_duplicates("grid_id")
    )
    lookup = dict(zip(modal["grid_id"].astype(int), modal["tcs_zone"].astype(int)))
    regions = gpd.read_file(regions_path)[["grid_id", "geometry"]]
    regions["tcs_zone"] = regions["grid_id"].astype(int).map(lookup)
    points = gpd.GeoDataFrame(
        frame[["parking_supply_id"]].copy(),
        geometry=gpd.points_from_xy(frame["longitude"], frame["latitude"]),
        crs="EPSG:4326",
    ).to_crs("EPSG:32650")
    joined = gpd.sjoin(points, regions[["grid_id", "tcs_zone", "geometry"]], how="left", predicate="within")
    joined = joined.sort_values(["parking_supply_id", "grid_id"], na_position="last").drop_duplicates("parking_supply_id")
    zone = joined.set_index("parking_supply_id")["tcs_zone"]
    frame["x_epsg32650"] = points.geometry.x.to_numpy()
    frame["y_epsg32650"] = points.geometry.y.to_numpy()
    frame["tcs_zone"] = frame["parking_supply_id"].map(zone).fillna(-1).astype(int)
    return frame


def car_link_frame(network_path: Path) -> gpd.GeoDataFrame:
    nodes: dict[str, tuple[float, float]] = {}
    links = []
    opener = gzip.open if network_path.suffix == ".gz" else open
    with opener(network_path, "rb") as handle:
        for _, element in etree.iterparse(handle, events=("end",), tag=("node", "link")):
            if element.tag == "node":
                nodes[element.get("id")] = (float(element.get("x")), float(element.get("y")))
            else:
                modes = set(filter(None, clean_text(element.get("modes")).split(",")))
                if "car" in modes:
                    start = nodes.get(element.get("from"))
                    end = nodes.get(element.get("to"))
                    if start and end and start != end:
                        links.append(
                            {
                                "nearest_car_link_id": element.get("id"),
                                "nearest_car_link_freespeed_kmh": round(float(element.get("freespeed")) * 3.6, 3),
                                "geometry": LineString([start, end]),
                            }
                        )
            element.clear()
    if not links:
        raise ValueError("No Car links in network")
    return gpd.GeoDataFrame(links, geometry="geometry", crs="EPSG:32650")


def assign_nearest_car_link(frame: pd.DataFrame, network_path: Path) -> pd.DataFrame:
    points = gpd.GeoDataFrame(
        frame[["parking_supply_id"]].copy(),
        geometry=[Point(x, y) for x, y in zip(frame["x_epsg32650"], frame["y_epsg32650"])],
        crs="EPSG:32650",
    )
    joined = gpd.sjoin_nearest(points, car_link_frame(network_path), how="left", distance_col="nearest_car_link_distance_m")
    joined = joined.sort_values(["parking_supply_id", "nearest_car_link_distance_m", "nearest_car_link_id"]).drop_duplicates("parking_supply_id")
    lookup = joined.set_index("parking_supply_id")
    for column in ("nearest_car_link_id", "nearest_car_link_freespeed_kmh", "nearest_car_link_distance_m"):
        frame[column] = frame["parking_supply_id"].map(lookup[column])
    frame["routing_link_status"] = "audit_candidate_only_entrance_and_direction_unverified"
    frame.loc[frame["nearest_car_link_distance_m"].gt(100), "routing_link_status"] = "distant_audit_candidate_over_100m_entrance_and_direction_unverified"
    return frame


def validate(frame: pd.DataFrame) -> None:
    if frame.empty or frame["parking_supply_id"].duplicated().any():
        raise ValueError("Parking supply must be non-empty with unique IDs")
    if not frame["latitude"].between(22.1, 22.7).all() or not frame["longitude"].between(113.8, 114.6).all():
        raise ValueError("Parking coordinates outside Hong Kong validation bounds")
    capacity = pd.to_numeric(frame["private_car_capacity"], errors="coerce")
    if capacity.dropna().lt(0).any():
        raise ValueError("Negative private-car capacity")
    if frame["source_url"].eq("").any():
        raise ValueError("Missing source URL")


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    snapshot_dir = collect_sources(args.output_dir, args.snapshot_date, args.refresh_sources)
    meters, meter_stats = build_meters(snapshot_dir, args.snapshot_date)
    offstreet, offstreet_stats = build_offstreet(snapshot_dir, args.snapshot_date)
    frame = pd.concat([offstreet, meters], ignore_index=True, sort=False)
    frame = assign_tcs(frame, args.input_project_root)
    frame = assign_nearest_car_link(frame, args.network)
    frame["routing_adoption_status"] = "not_adopted_requires_entrance_direction_validation"
    frame["runtime_parking_cost_status"] = "not_adopted_existing_tcs_activity_duration_proxy_remains_active"
    frame = frame.sort_values(["facility_type", "parking_supply_id"]).reset_index(drop=True)
    validate(frame)
    output = args.output_dir / "hong_kong_parking_supply.csv"
    frame.to_csv(output, index=False, encoding="utf-8", lineterminator="\n")
    summary = {
        "scenario": "hong_kong_parking_supply_2026_v1",
        "status": "candidate_not_runtime_adopted",
        "snapshot_date": args.snapshot_date,
        "output": output.relative_to(REPO_ROOT).as_posix(),
        "rows": len(frame),
        "facility_type_counts": frame["facility_type"].value_counts().sort_index().to_dict(),
        "known_private_car_capacity": int(pd.to_numeric(frame["private_car_capacity"], errors="coerce").sum()),
        "tcs_zone_assigned": int(frame["tcs_zone"].between(1, 26).sum()),
        "tcs_zone_unresolved": int(frame["tcs_zone"].eq(-1).sum()),
        "nearest_car_link_within_100m": int(frame["nearest_car_link_distance_m"].le(100).sum()),
        "pricing_status_counts": frame["pricing_status"].value_counts().sort_index().to_dict(),
        **meter_stats,
        **offstreet_stats,
        "runtime_boundary": "No MATSim config, facility, route, scoring or traffic-signal input is changed.",
    }
    (args.output_dir / "build_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
