from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt


PROJECT_ROOT = Path(__file__).resolve().parents[3]
TRANSIT_ROOT = PROJECT_ROOT / "data/transit/hongkong"
DEFAULT_FREQUENCY = Path(r"D:\Program Files\mtr_average_train_frequency_long.csv")
DEFAULT_MTR_STOPS = TRANSIT_ROOT / "MTR/mtr_lines_and_stations.csv"
DEFAULT_LRT_STOPS = TRANSIT_ROOT / "MTR/light_rail_routes_and_stops.csv"
DEFAULT_AMAP_LINES = TRANSIT_ROOT / "AMap_Supplements/normalized/amap_lines.csv"
DEFAULT_SNAPSHOTS = [
    TRANSIT_ROOT / "API_Supplements/realtime_snapshots/20260720T102416Z",
    TRANSIT_ROOT / "API_Supplements/realtime_snapshots/20260722T034716Z",
]
DEFAULT_OUTPUT = (
    TRANSIT_ROOT / "processed/mtr_lrt_approximate_timetable_2026_weekday"
)

PERIOD_WINDOWS = {
    "weekday_morning_peak": [(7 * 3600, 9 * 3600 + 30 * 60)],
    "weekday_evening_peak": [(17 * 3600, 20 * 3600)],
    "weekday_non_peak": [
        (0, 7 * 3600),
        (9 * 3600 + 30 * 60, 17 * 3600),
        (20 * 3600, 30 * 3600),
    ],
}

MTR_LINE_NAMES = {
    "AEL": ("Airport Express", "机场快线"),
    "DRL": ("Disneyland Resort Line", "迪士尼线"),
    "EAL": ("East Rail Line", "东铁线"),
    "ISL": ("Island Line", "港岛线"),
    "KTL": ("Kwun Tong Line", "观塘线"),
    "SIL": ("South Island Line", "南港岛线"),
    "TCL": ("Tung Chung Line", "东涌线"),
    "TKL": ("Tseung Kwan O Line", "将军澳线"),
    "TML": ("Tuen Ma Line", "屯马线"),
    "TWL": ("Tsuen Wan Line", "荃湾线"),
}

TERMINAL_ALIASES = {
    "AWE": "博览馆",
    "HOK": "香港",
    "DIS": "迪士尼",
    "SUN": "欣澳",
    "LOW": "罗湖",
    "ADM": "金钟",
    "LMC": "落马洲",
    "CHW": "柴湾",
    "KET": "坚尼地城",
    "TIK": "调景岭",
    "HOM": "何文田",
    "WHA": "黄埔",
    "WKS": "乌溪沙",
    "TUM": "屯门",
    "TUC": "东涌",
    "TSY": "青衣",
    "POA": "宝琳",
    "NOP": "北角",
    "LHP": "康城",
    "CEN": "中环",
    "TSW": "荃湾",
    "SOH": "海怡半岛",
    "SAS": "三圣",
    "SHL": "兆康",
    "FEP": "屯门码头",
    "TNK": "田景",
    "YLL": "元朗",
    "TSL": "天水围",
    "TWI": "天荣",
    "YAO": "友爱",
    "TYA": "天逸",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build an inferred typical-weekday MTR/LRT origin-departure timetable."
    )
    parser.add_argument("--frequency-table", type=Path, default=DEFAULT_FREQUENCY)
    parser.add_argument("--mtr-stops", type=Path, default=DEFAULT_MTR_STOPS)
    parser.add_argument("--lrt-stops", type=Path, default=DEFAULT_LRT_STOPS)
    parser.add_argument("--amap-lines", type=Path, default=DEFAULT_AMAP_LINES)
    parser.add_argument(
        "--snapshot-dir",
        action="append",
        type=Path,
        dest="snapshot_dirs",
        help="Snapshot directory containing MTR and LRT JSONL files; repeat twice.",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def normalize_id(value: Any) -> str:
    text = str(value).strip()
    return re.sub(r"\.0$", "", text)


def normalize_name(value: Any) -> str:
    text = str(value).strip().lower()
    text = re.sub(r"\([^)]*\)", "", text)
    text = text.replace("总站", "").replace("總站", "")
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", text)


def parse_hhmm(value: Any) -> int:
    text = str(value).strip()
    if not text or text in {"[]", "nan", "None"}:
        raise ValueError(f"Missing service time: {value!r}")
    digits = re.sub(r"\D", "", text)
    if len(digits) != 4:
        raise ValueError(f"Expected HHMM service time, got {value!r}")
    hour, minute = int(digits[:2]), int(digits[2:])
    if hour > 29 or minute > 59:
        raise ValueError(f"Invalid service time: {value!r}")
    return hour * 3600 + minute * 60


def format_time(seconds: int | float) -> str:
    value = int(round(seconds))
    hour, remainder = divmod(value, 3600)
    minute, second = divmod(remainder, 60)
    return f"{hour:02d}:{minute:02d}:{second:02d}"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_sha256_manifest(output_dir: Path) -> Path:
    manifest_path = output_dir / "SHA256SUMS.txt"
    rows = []
    for path in sorted(output_dir.rglob("*")):
        if not path.is_file() or path == manifest_path:
            continue
        relative = path.relative_to(output_dir).as_posix()
        rows.append(f"{file_sha256(path)}  {relative}")
    manifest_path.write_text("\n".join(rows) + "\n", encoding="ascii")
    return manifest_path


def make_pattern(
    mode: str,
    line_code: str,
    direction: str,
    stops: pd.DataFrame,
    frequency_section: str,
    strategy: str = "direct",
    common_section: str = "",
    full_section: str = "",
    amap_parent_origin: str = "",
    amap_parent_destination: str = "",
) -> dict[str, Any]:
    stop_code_col = "Station Code" if mode == "mtr" else "Stop Code"
    stop_id_col = "Station ID" if mode == "mtr" else "Stop ID"
    frame = stops.reset_index(drop=True).copy()
    stop_codes = frame[stop_code_col].map(normalize_id)
    frame = frame.loc[stop_codes.ne(stop_codes.shift())].reset_index(drop=True)
    origin = frame.iloc[0]
    destination = frame.iloc[-1]
    route_id = f"{mode}_{line_code}_{direction}"
    return {
        "route_variant_id": route_id,
        "mode": mode,
        "line_code": str(line_code),
        "direction": str(direction),
        "line_name": MTR_LINE_NAMES[line_code][0] if mode == "mtr" else f"Light Rail {line_code}",
        "frequency_line_name": MTR_LINE_NAMES[line_code][0] if mode == "mtr" else "Light Rail",
        "frequency_section": frequency_section,
        "frequency_strategy": strategy,
        "common_section": common_section,
        "full_section": full_section,
        "origin_code": normalize_id(origin[stop_code_col]),
        "destination_code": normalize_id(destination[stop_code_col]),
        "origin_stop_id": normalize_id(origin[stop_id_col]),
        "destination_stop_id": normalize_id(destination[stop_id_col]),
        "origin_name_en": str(origin["English Name"]),
        "destination_name_en": str(destination["English Name"]),
        "origin_name_zh": str(origin["Chinese Name"]),
        "destination_name_zh": str(destination["Chinese Name"]),
        "stop_count": int(len(frame)),
        "amap_parent_origin": amap_parent_origin or normalize_id(origin[stop_code_col]),
        "amap_parent_destination": amap_parent_destination or normalize_id(destination[stop_code_col]),
        "stops": frame,
    }


def build_route_patterns(
    mtr_stops: pd.DataFrame, lrt_stops: pd.DataFrame
) -> list[dict[str, Any]]:
    patterns: list[dict[str, Any]] = []
    full_sections = {
        "AEL": "全线",
        "DRL": "全线",
        "ISL": "全线",
        "SIL": "全线",
        "TML": "全线",
        "TWL": "全线",
    }
    for (line_code, direction), group in mtr_stops.groupby(
        ["Line Code", "Direction"], sort=False
    ):
        line_code = str(line_code)
        direction = str(direction)
        group = group.sort_values("Sequence")
        destination = normalize_id(group.iloc[-1]["Station Code"])
        if line_code in full_sections:
            section = full_sections[line_code]
        elif line_code == "EAL":
            section = (
                "Admiralty-Lok Ma Chau"
                if "LMC" in direction or destination == "LMC"
                else "Admiralty-Lo Wu"
            )
        elif line_code == "KTL":
            section = "Ho Man Tin-Whampoa"
        elif line_code == "TCL":
            section = "Hong Kong-Tung Chung"
        elif line_code == "TKL":
            section = (
                "Tiu Keng Leng-LOHAS Park"
                if direction.startswith("TKS-")
                else "North Point-Po Lam"
            )
        else:
            raise ValueError(f"Unhandled MTR line: {line_code}")
        parent_origin = ""
        parent_destination = ""
        if line_code == "TKL" and direction == "TKS-DT":
            parent_origin, parent_destination = "LHP", "NOP"
        elif line_code == "TKL" and direction == "TKS-UT":
            parent_origin, parent_destination = "NOP", "LHP"
        patterns.append(
            make_pattern(
                "mtr",
                line_code,
                direction,
                group,
                section,
                amap_parent_origin=parent_origin,
                amap_parent_destination=parent_destination,
            )
        )

    def mtr_group(line: str, direction: str) -> pd.DataFrame:
        return mtr_stops.loc[
            mtr_stops["Line Code"].astype(str).eq(line)
            & mtr_stops["Direction"].astype(str).eq(direction)
        ].sort_values("Sequence")

    # Common-section short turns preserve the higher common-section service rate.
    ktl_dt = mtr_group("KTL", "DT")
    ktl_ut = mtr_group("KTL", "UT")
    patterns.append(
        make_pattern(
            "mtr",
            "KTL",
            "SHORT-DT",
            ktl_dt.loc[ktl_dt["Sequence"].le(16)],
            "derived_additional",
            "supplemental",
            "Tiu Keng Leng-Ho Man Tin",
            "Ho Man Tin-Whampoa",
            "TIK",
            "WHA",
        )
    )
    patterns.append(
        make_pattern(
            "mtr",
            "KTL",
            "SHORT-UT",
            ktl_ut.loc[ktl_ut["Station Code"].astype(str).ne("WHA")],
            "derived_additional",
            "supplemental",
            "Tiu Keng Leng-Ho Man Tin",
            "Ho Man Tin-Whampoa",
            "WHA",
            "TIK",
        )
    )
    tcl_dt = mtr_group("TCL", "DT")
    tcl_ut = mtr_group("TCL", "UT")
    patterns.append(
        make_pattern(
            "mtr",
            "TCL",
            "SHORT-DT",
            tcl_dt.loc[tcl_dt["Station Code"].astype(str).ne("TUC")],
            "derived_additional",
            "supplemental",
            "Hong Kong-Tsing Yi",
            "Hong Kong-Tung Chung",
            "TUC",
            "HOK",
        )
    )
    patterns.append(
        make_pattern(
            "mtr",
            "TCL",
            "SHORT-UT",
            tcl_ut.loc[tcl_ut["Sequence"].le(3)],
            "derived_additional",
            "supplemental",
            "Hong Kong-Tsing Yi",
            "Hong Kong-Tung Chung",
            "HOK",
            "TUC",
        )
    )

    # Build the missing North Point-LOHAS Park through-service route from the
    # common TKL section and the LOHAS branch.
    tkl_dt = mtr_group("TKL", "DT")
    tkl_ut = mtr_group("TKL", "UT")
    shuttle_dt = mtr_group("TKL", "TKS-DT")
    shuttle_ut = mtr_group("TKL", "TKS-UT")
    lhp_to_nop = pd.concat(
        [shuttle_dt, tkl_dt.loc[tkl_dt["Station Code"].isin(["YAT", "QUB", "NOP"])]],
        ignore_index=True,
    )
    lhp_to_nop["Sequence"] = np.arange(1, len(lhp_to_nop) + 1)
    nop_to_lhp = pd.concat(
        [tkl_ut.loc[tkl_ut["Station Code"].isin(["NOP", "QUB", "YAT"])], shuttle_ut],
        ignore_index=True,
    ).drop_duplicates("Station Code", keep="first")
    nop_to_lhp["Sequence"] = np.arange(1, len(nop_to_lhp) + 1)
    patterns.append(
        make_pattern("mtr", "TKL", "LHP-DT", lhp_to_nop, "North Point-LOHAS Park")
    )
    patterns.append(
        make_pattern("mtr", "TKL", "LHP-UT", nop_to_lhp, "North Point-LOHAS Park")
    )

    for line_code in lrt_stops["Line Code"].astype(str).drop_duplicates():
        line_rows = lrt_stops.loc[lrt_stops["Line Code"].astype(str).eq(line_code)]
        if line_code in {"705", "706"}:
            first = line_rows.loc[line_rows["Direction"].astype(str).eq("1")].sort_values("Sequence")
            second = line_rows.loc[line_rows["Direction"].astype(str).eq("2")].sort_values("Sequence")
            loop = pd.concat([first, second.iloc[1:]], ignore_index=True)
            loop["Sequence"] = np.arange(1, len(loop) + 1)
            patterns.append(
                make_pattern("lrt", line_code, "LOOP", loop, f"Route {line_code}")
            )
        else:
            for direction, group in line_rows.groupby("Direction", sort=False):
                patterns.append(
                    make_pattern(
                        "lrt",
                        line_code,
                        normalize_id(direction),
                        group.sort_values("Sequence"),
                        f"Route {line_code}",
                    )
                )
    return patterns


def attach_service_windows(
    patterns: list[dict[str, Any]], amap_lines: pd.DataFrame
) -> None:
    amap_lines = amap_lines.copy()
    amap_lines["start_norm"] = amap_lines["start_stop"].map(normalize_name)
    amap_lines["end_norm"] = amap_lines["end_stop"].map(normalize_name)
    for pattern in patterns:
        origin_code = pattern["amap_parent_origin"]
        destination_code = pattern["amap_parent_destination"]
        origin_alias = TERMINAL_ALIASES[origin_code]
        destination_alias = TERMINAL_ALIASES[destination_code]
        if pattern["mode"] == "mtr":
            token = MTR_LINE_NAMES[pattern["line_code"]][1]
            candidates = amap_lines.loc[
                amap_lines["mode"].eq("mtr")
                & amap_lines["line_name"].str.contains(token, regex=False, na=False)
                & amap_lines["start_norm"].eq(normalize_name(origin_alias))
                & amap_lines["end_norm"].eq(normalize_name(destination_alias))
            ]
        else:
            token_pattern = rf"(?:轻铁|轻便铁路){re.escape(pattern['line_code'])}线"
            candidates = amap_lines.loc[
                amap_lines["mode"].eq("lrt")
                & amap_lines["line_name"].str.contains(token_pattern, regex=True, na=False)
            ]
            if pattern["direction"] != "LOOP":
                candidates = candidates.loc[
                    candidates["start_norm"].eq(normalize_name(origin_alias))
                    & candidates["end_norm"].eq(normalize_name(destination_alias))
                ]
        if len(candidates) != 1:
            raise ValueError(
                f"Expected one AMap service window for {pattern['route_variant_id']}, "
                f"found {len(candidates)}"
            )
        row = candidates.iloc[0]
        start_s = parse_hhmm(row["start_time"])
        end_s = parse_hhmm(row["end_time"])
        if end_s <= start_s:
            end_s += 24 * 3600
        pattern.update(
            {
                "amap_line_id": normalize_id(row["amap_line_id"]),
                "service_start_s": start_s,
                "service_end_s": end_s,
                "service_start": format_time(start_s),
                "service_end": format_time(end_s),
            }
        )


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def classify_period(seconds: int) -> str:
    value = seconds % (24 * 3600)
    if 7 * 3600 <= value < 9 * 3600 + 30 * 60:
        return "weekday_morning_peak"
    if 17 * 3600 <= value < 20 * 3600:
        return "weekday_evening_peak"
    return "weekday_non_peak"


def extract_snapshot_observations(
    patterns: list[dict[str, Any]], snapshot_dirs: list[Path]
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for snapshot_dir in snapshot_dirs:
        mtr_rows = read_jsonl(snapshot_dir / "mtr_next_train.jsonl")
        lrt_rows = read_jsonl(snapshot_dir / "light_rail_next_train.jsonl")
        mtr_index = {
            (str(row["request_parameters"]["line"]), str(row["request_parameters"]["sta"])): row
            for row in mtr_rows
        }
        lrt_index = {
            normalize_id(row["request_parameters"]["station_id"]): row for row in lrt_rows
        }
        first_response = mtr_rows[0]["response"]
        local_text = first_response.get("sys_time") or first_response.get("curr_time")
        local_time = datetime.strptime(local_text, "%Y-%m-%d %H:%M:%S")
        snapshot_period = classify_period(
            local_time.hour * 3600 + local_time.minute * 60 + local_time.second
        )
        for pattern in patterns:
            waits: list[float] = []
            absolute_times: list[int] = []
            if pattern["frequency_strategy"] == "supplemental":
                # An intermediate short-turn terminal also sees through trains,
                # so next-train data cannot identify short-turn departures.
                pass
            elif pattern["mode"] == "mtr":
                record = mtr_index.get((pattern["line_code"], pattern["origin_code"]))
                if record:
                    for data in (record["response"].get("data") or {}).values():
                        for direction in ("UP", "DOWN"):
                            for train in data.get(direction) or []:
                                if (
                                    str(train.get("dest")) == pattern["destination_code"]
                                    and str(train.get("valid")) == "Y"
                                ):
                                    try:
                                        waits.append(float(train["ttnt"]))
                                        parsed = datetime.strptime(train["time"], "%Y-%m-%d %H:%M:%S")
                                        absolute_times.append(
                                            parsed.hour * 3600 + parsed.minute * 60 + parsed.second
                                        )
                                    except (KeyError, TypeError, ValueError):
                                        pass
            else:
                record = lrt_index.get(pattern["origin_stop_id"])
                expected_destination = (
                    "tsw circular"
                    if pattern["direction"] == "LOOP"
                    else normalize_name(pattern["destination_name_en"])
                )
                if record:
                    system_text = record["response"].get("system_time") or local_text
                    base_time = datetime.strptime(system_text, "%Y-%m-%d %H:%M:%S")
                    base_s = base_time.hour * 3600 + base_time.minute * 60 + base_time.second
                    for platform in record["response"].get("platform_list") or []:
                        for train in platform.get("route_list") or []:
                            destination = normalize_name(train.get("dest_en", ""))
                            if str(train.get("route_no")) != pattern["line_code"]:
                                continue
                            if destination != normalize_name(expected_destination):
                                continue
                            text = str(train.get("time_en", ""))
                            match = re.search(r"(\d+)\s*mins?", text, flags=re.I)
                            wait = float(match.group(1)) if match else (0.0 if "depart" in text.lower() else math.nan)
                            if math.isfinite(wait):
                                waits.append(wait)
                                absolute_times.append(int(base_s + wait * 60))
            unique_times = sorted(set(absolute_times))
            gaps = np.diff(unique_times) / 60.0 if len(unique_times) >= 2 else np.array([])
            rows.append(
                {
                    "snapshot_id": snapshot_dir.name,
                    "captured_local": local_text,
                    "period_code": snapshot_period,
                    "route_variant_id": pattern["route_variant_id"],
                    "mode": pattern["mode"],
                    "line_code": pattern["line_code"],
                    "direction": pattern["direction"],
                    "origin_code": pattern["origin_code"],
                    "destination_code": pattern["destination_code"],
                    "prediction_count": len(unique_times),
                    "predicted_times": "|".join(format_time(value) for value in unique_times),
                    "observed_gap_count": len(gaps),
                    "observed_headway_minutes": round(float(np.median(gaps)), 3) if len(gaps) else np.nan,
                    "first_prediction_seconds": unique_times[0] if unique_times else np.nan,
                    "first_prediction_time": format_time(unique_times[0]) if unique_times else "",
                }
            )
    return pd.DataFrame(rows)


def published_row(
    frequencies: pd.DataFrame, line_name: str, section: str, period: str
) -> pd.Series | None:
    rows = frequencies.loc[
        frequencies["line_name"].eq(line_name)
        & frequencies["service_section"].eq(section)
        & frequencies["period_code"].eq(period)
    ]
    if len(rows) == 0:
        return None
    if len(rows) != 1:
        raise ValueError(f"Duplicate frequency row: {line_name} / {section} / {period}")
    return rows.iloc[0]


def direct_headway(
    source: pd.Series | None, observed: float | None
) -> tuple[float | None, str]:
    if source is None:
        return (observed, "snapshot_only") if observed is not None else (None, "missing")
    minimum = pd.to_numeric(pd.Series([source.get("min_headway_minutes")]), errors="coerce").iloc[0]
    maximum = pd.to_numeric(pd.Series([source.get("max_headway_minutes")]), errors="coerce").iloc[0]
    value_type = str(source.get("value_type", ""))
    if value_type == "not_listed" or not math.isfinite(float(minimum)):
        return (observed, "snapshot_fills_not_listed") if observed is not None else (None, "not_listed")
    minimum, maximum = float(minimum), float(maximum)
    if value_type == "single" or abs(maximum - minimum) < 1e-9:
        return minimum, "published_single"
    if value_type == "dual_value":
        options = [
            value
            for value in (
                pd.to_numeric(pd.Series([source.get("option_1_minutes")]), errors="coerce").iloc[0],
                pd.to_numeric(pd.Series([source.get("option_2_minutes")]), errors="coerce").iloc[0],
            )
            if math.isfinite(float(value))
        ]
        if observed is not None and options:
            return float(min(options, key=lambda value: abs(float(value) - observed))), "published_dual_nearest_snapshot"
        return float(np.mean(options or [minimum, maximum])), "published_dual_mean"
    if observed is not None:
        selected = float(np.clip(observed, minimum, maximum))
        method = "snapshot_within_published_range" if minimum <= observed <= maximum else "snapshot_clipped_to_published_range"
        return selected, method
    return (minimum + maximum) / 2.0, "published_range_midpoint"


def build_service_periods(
    patterns: list[dict[str, Any]], frequencies: pd.DataFrame, observations: pd.DataFrame
) -> pd.DataFrame:
    periods: list[dict[str, Any]] = []
    pattern_by_id = {pattern["route_variant_id"]: pattern for pattern in patterns}
    direct_cache: dict[tuple[str, str, str, str], tuple[float | None, str, pd.Series | None, float | None]] = {}

    def observation_for(route_id: str, period: str) -> float | None:
        frame = observations.loc[
            observations["route_variant_id"].eq(route_id)
            & observations["period_code"].eq(period)
            & observations["observed_headway_minutes"].notna()
        ]
        return float(frame["observed_headway_minutes"].median()) if len(frame) else None

    def select_direct(pattern: dict[str, Any], section: str, period: str) -> tuple[float | None, str, pd.Series | None, float | None]:
        frequency_line_name = pattern["frequency_line_name"]
        key = (pattern["route_variant_id"], frequency_line_name, section, period)
        if key not in direct_cache:
            source = published_row(frequencies, frequency_line_name, section, period)
            observed = observation_for(pattern["route_variant_id"], period)
            selected, method = direct_headway(source, observed)
            direct_cache[key] = selected, method, source, observed
        return direct_cache[key]

    for pattern in patterns:
        for period in PERIOD_WINDOWS:
            if pattern["frequency_strategy"] == "direct":
                selected, method, source, observed = select_direct(
                    pattern, pattern["frequency_section"], period
                )
                # Direct North Point-LOHAS service is peak-only when the source
                # table does not list an off-peak value.
                if (
                    pattern["line_code"] == "TKL"
                    and pattern["frequency_section"] == "North Point-LOHAS Park"
                    and period == "weekday_non_peak"
                    and source is not None
                    and source.get("value_type") == "not_listed"
                ):
                    selected, method = None, "not_operated_direct_off_peak"
                # The LOHAS shuttle is retained in peak periods using its
                # published non-peak midpoint when no period-specific value exists.
                if (
                    selected is None
                    and pattern["line_code"] == "TKL"
                    and pattern["frequency_section"] == "Tiu Keng Leng-LOHAS Park"
                ):
                    proxy = published_row(
                        frequencies,
                        pattern["frequency_line_name"],
                        pattern["frequency_section"],
                        "weekday_non_peak",
                    )
                    selected, _ = direct_headway(proxy, observed)
                    method = "lohas_shuttle_nonpeak_proxy"
            else:
                common_source = published_row(
                    frequencies,
                    pattern["frequency_line_name"],
                    pattern["common_section"],
                    period,
                )
                full_source = published_row(
                    frequencies,
                    pattern["frequency_line_name"],
                    pattern["full_section"],
                    period,
                )
                common_h, _, _, _ = select_direct(pattern, pattern["common_section"], period)
                full_h, _, _, _ = select_direct(pattern, pattern["full_section"], period)
                observed = observation_for(pattern["route_variant_id"], period)
                source = common_source
                if common_h and full_h and 1 / common_h > 1 / full_h + 1e-9:
                    derived = 1 / (1 / common_h - 1 / full_h)
                    if observed is not None and 0.5 * derived <= observed <= 1.5 * derived:
                        selected, method = observed, "snapshot_supported_supplemental"
                    else:
                        selected, method = derived, "derived_common_minus_full_rate"
                else:
                    selected, method = None, "no_supplemental_service_required"
            periods.append(
                {
                    "route_variant_id": pattern["route_variant_id"],
                    "mode": pattern["mode"],
                    "line_code": pattern["line_code"],
                    "direction": pattern["direction"],
                    "line_name": pattern["line_name"],
                    "service_section": pattern["frequency_section"],
                    "period_code": period,
                    "published_headway_raw_minutes": "" if source is None else source.get("headway_raw_minutes", ""),
                    "published_min_headway_minutes": np.nan if source is None else source.get("min_headway_minutes"),
                    "published_max_headway_minutes": np.nan if source is None else source.get("max_headway_minutes"),
                    "snapshot_observed_headway_minutes": observed,
                    "selected_headway_minutes": selected,
                    "selection_method": method,
                    "frequency_source_url": "" if source is None else source.get("source_url", ""),
                }
            )
    return pd.DataFrame(periods)


def balance_branch_common_sections(
    periods: pd.DataFrame, frequencies: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    balanced = periods.copy()
    audit_rows: list[dict[str, Any]] = []
    groups = [
        (
            "East Rail Line",
            "Admiralty-Sheung Shui",
            [
                ["mtr_EAL_DT", "mtr_EAL_LMC-DT"],
                ["mtr_EAL_UT", "mtr_EAL_LMC-UT"],
            ],
        ),
        (
            "Tseung Kwan O Line",
            "North Point-Tseung Kwan O",
            [
                ["mtr_TKL_DT", "mtr_TKL_LHP-DT"],
                ["mtr_TKL_UT", "mtr_TKL_LHP-UT"],
            ],
        ),
    ]
    for line_name, common_section, direction_groups in groups:
        for period in PERIOD_WINDOWS:
            common_source = published_row(frequencies, line_name, common_section, period)
            if common_source is None or str(common_source.get("value_type")) == "not_listed":
                continue
            for route_ids in direction_groups:
                indexes = [
                    balanced.index[
                        balanced["route_variant_id"].eq(route_id)
                        & balanced["period_code"].eq(period)
                    ][0]
                    for route_id in route_ids
                ]
                selected = pd.to_numeric(
                    balanced.loc[indexes, "selected_headway_minutes"], errors="coerce"
                ).to_numpy(dtype=float)
                if not np.isfinite(selected).all():
                    continue
                observed = pd.to_numeric(
                    balanced.loc[indexes, "snapshot_observed_headway_minutes"],
                    errors="coerce",
                ).to_numpy(dtype=float)
                observed_common = (
                    float(1.0 / np.sum(1.0 / observed))
                    if np.isfinite(observed).all()
                    else None
                )
                target, target_method = direct_headway(common_source, observed_common)
                if target is None:
                    continue
                before = float(1.0 / np.sum(1.0 / selected))
                candidate_axes: list[np.ndarray] = []
                for index, seed in zip(indexes, selected, strict=True):
                    minimum = pd.to_numeric(
                        pd.Series([balanced.at[index, "published_min_headway_minutes"]]),
                        errors="coerce",
                    ).iloc[0]
                    maximum = pd.to_numeric(
                        pd.Series([balanced.at[index, "published_max_headway_minutes"]]),
                        errors="coerce",
                    ).iloc[0]
                    if not math.isfinite(float(minimum)) or not math.isfinite(float(maximum)):
                        minimum = maximum = seed
                    points = max(2, min(301, int(round((float(maximum) - float(minimum)) / 0.025)) + 1))
                    candidate_axes.append(
                        np.array([float(minimum)])
                        if abs(float(maximum) - float(minimum)) < 1e-9
                        else np.linspace(float(minimum), float(maximum), points)
                    )
                first, second = np.meshgrid(candidate_axes[0], candidate_axes[1], indexing="ij")
                effective = 1.0 / (1.0 / first + 1.0 / second)
                scale = np.maximum(selected, 1.0)
                objective = (
                    250.0 * np.square(effective - float(target))
                    + np.square((first - selected[0]) / scale[0])
                    + np.square((second - selected[1]) / scale[1])
                )
                best = np.unravel_index(int(np.argmin(objective)), objective.shape)
                adjusted = [float(first[best]), float(second[best])]
                after = float(effective[best])
                for index, value in zip(indexes, adjusted, strict=True):
                    balanced.at[index, "pre_common_balance_headway_minutes"] = balanced.at[
                        index, "selected_headway_minutes"
                    ]
                    balanced.at[index, "selected_headway_minutes"] = value
                    balanced.at[index, "selection_method"] = (
                        str(balanced.at[index, "selection_method"])
                        + "+common_section_balanced"
                    )
                    balanced.at[index, "common_section_target_headway_minutes"] = float(target)
                audit_rows.append(
                    {
                        "line_name": line_name,
                        "common_section": common_section,
                        "period_code": period,
                        "route_variant_ids": "|".join(route_ids),
                        "branch_headways_before": "|".join(f"{value:.3f}" for value in selected),
                        "branch_headways_after": "|".join(f"{value:.3f}" for value in adjusted),
                        "effective_common_headway_before": before,
                        "effective_common_headway_after": after,
                        "target_common_headway": float(target),
                        "target_method": target_method,
                        "published_common_min": common_source.get("min_headway_minutes"),
                        "published_common_max": common_source.get("max_headway_minutes"),
                        "absolute_target_error": abs(after - float(target)),
                    }
                )
    return balanced, pd.DataFrame(audit_rows)


def period_at(seconds: int) -> str:
    return classify_period(seconds)


def generate_departures(
    patterns: list[dict[str, Any]], periods: pd.DataFrame, observations: pd.DataFrame
) -> pd.DataFrame:
    result: list[dict[str, Any]] = []
    period_index = periods.set_index(["route_variant_id", "period_code"])
    for pattern in patterns:
        route_id = pattern["route_variant_id"]
        start, end = pattern["service_start_s"], pattern["service_end_s"]
        departures: dict[int, dict[str, Any]] = {}
        for period, windows in PERIOD_WINDOWS.items():
            row = period_index.loc[(route_id, period)]
            headway = pd.to_numeric(pd.Series([row["selected_headway_minutes"]]), errors="coerce").iloc[0]
            if not math.isfinite(float(headway)) or float(headway) <= 0:
                continue
            step = max(30, int(round(float(headway) * 60)))
            obs = observations.loc[
                observations["route_variant_id"].eq(route_id)
                & observations["period_code"].eq(period)
                & observations["first_prediction_seconds"].notna()
            ]
            anchor = int(round(float(obs.iloc[-1]["first_prediction_seconds"]))) if len(obs) else None
            for window_start, window_end in windows:
                lo, hi = max(start, window_start), min(end + 1, window_end)
                if lo >= hi:
                    continue
                phase = anchor if anchor is not None else lo
                first = phase + math.ceil((lo - phase) / step) * step
                for departure in range(first, hi, step):
                    departures[departure] = {
                        "period_code": period,
                        "selected_headway_minutes": float(headway),
                        "phase_source": "snapshot_first_prediction" if anchor is not None else "period_boundary",
                        "selection_method": row["selection_method"],
                    }
        for anchor_s, anchor_type in ((start, "first_service_anchor"), (end, "last_service_anchor")):
            period = period_at(anchor_s)
            row = period_index.loc[(route_id, period)]
            headway = pd.to_numeric(pd.Series([row["selected_headway_minutes"]]), errors="coerce").iloc[0]
            if math.isfinite(float(headway)):
                departures[anchor_s] = {
                    "period_code": period,
                    "selected_headway_minutes": float(headway),
                    "phase_source": anchor_type,
                    "selection_method": row["selection_method"],
                }
        for sequence, departure_s in enumerate(sorted(departures), start=1):
            metadata = departures[departure_s]
            result.append(
                {
                    "departure_id": f"{route_id}_{sequence:04d}",
                    "route_variant_id": route_id,
                    "mode": pattern["mode"],
                    "line_code": pattern["line_code"],
                    "direction": pattern["direction"],
                    "origin_code": pattern["origin_code"],
                    "destination_code": pattern["destination_code"],
                    "origin_name_en": pattern["origin_name_en"],
                    "destination_name_en": pattern["destination_name_en"],
                    "departure_sequence": sequence,
                    "departure_seconds": departure_s,
                    "departure_time": format_time(departure_s),
                    **metadata,
                }
            )
    return pd.DataFrame(result)


def build_route_frames(patterns: list[dict[str, Any]]) -> tuple[pd.DataFrame, pd.DataFrame]:
    routes: list[dict[str, Any]] = []
    stops: list[dict[str, Any]] = []
    for pattern in patterns:
        routes.append({key: value for key, value in pattern.items() if key != "stops"})
        frame = pattern["stops"]
        stop_code_col = "Station Code" if pattern["mode"] == "mtr" else "Stop Code"
        stop_id_col = "Station ID" if pattern["mode"] == "mtr" else "Stop ID"
        for sequence, (_, row) in enumerate(frame.iterrows(), start=1):
            stops.append(
                {
                    "route_variant_id": pattern["route_variant_id"],
                    "mode": pattern["mode"],
                    "line_code": pattern["line_code"],
                    "direction": pattern["direction"],
                    "stop_sequence": sequence,
                    "stop_code": normalize_id(row[stop_code_col]),
                    "stop_id": normalize_id(row[stop_id_col]),
                    "stop_name_en": row["English Name"],
                    "stop_name_zh": row["Chinese Name"],
                }
            )
    return pd.DataFrame(routes), pd.DataFrame(stops)


def validate_snapshots(
    departures: pd.DataFrame, observations: pd.DataFrame
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for observation in observations.itertuples(index=False):
        if not observation.predicted_times:
            continue
        candidates = departures.loc[
            departures["route_variant_id"].eq(observation.route_variant_id),
            "departure_seconds",
        ].to_numpy(dtype=float)
        if len(candidates) == 0:
            continue
        for predicted in str(observation.predicted_times).split("|"):
            parts = [int(value) for value in predicted.split(":")]
            seconds = parts[0] * 3600 + parts[1] * 60 + parts[2]
            nearest = float(candidates[np.argmin(np.abs(candidates - seconds))])
            rows.append(
                {
                    "snapshot_id": observation.snapshot_id,
                    "period_code": observation.period_code,
                    "route_variant_id": observation.route_variant_id,
                    "mode": observation.mode,
                    "line_code": observation.line_code,
                    "direction": observation.direction,
                    "observed_origin_prediction": predicted,
                    "nearest_generated_departure": format_time(nearest),
                    "absolute_error_minutes": abs(nearest - seconds) / 60.0,
                }
            )
    return pd.DataFrame(rows)


def plot_headway_qa(periods: pd.DataFrame, output_path: Path) -> None:
    selected = periods.loc[
        periods["period_code"].isin(["weekday_non_peak", "weekday_evening_peak"])
        & periods["selected_headway_minutes"].notna()
    ].copy()
    selected["label"] = selected["mode"].str.upper() + " " + selected["line_code"]
    fig, axes = plt.subplots(1, 2, figsize=(15, 7), dpi=200)
    for ax, period, title in zip(
        axes,
        ["weekday_non_peak", "weekday_evening_peak"],
        ["Weekday non-peak (11:47 snapshot)", "Weekday evening peak (18:24 snapshot)"],
        strict=True,
    ):
        frame = selected.loc[selected["period_code"].eq(period)].sort_values(
            ["mode", "line_code", "direction"]
        )
        x = np.arange(len(frame))
        minimum = pd.to_numeric(frame["published_min_headway_minutes"], errors="coerce")
        maximum = pd.to_numeric(frame["published_max_headway_minutes"], errors="coerce")
        midpoint = (minimum + maximum) / 2
        yerr = np.vstack([(midpoint - minimum).fillna(0), (maximum - midpoint).fillna(0)])
        ax.errorbar(x, midpoint, yerr=yerr, fmt="none", ecolor="#aeb5bb", capsize=2, linewidth=1)
        ax.scatter(x, frame["selected_headway_minutes"], s=20, color="#16817a", label="Selected")
        observed = frame["snapshot_observed_headway_minutes"].notna()
        ax.scatter(
            x[observed],
            frame.loc[observed, "snapshot_observed_headway_minutes"],
            s=22,
            marker="x",
            color="#a51c4b",
            label="Snapshot observed",
        )
        ax.set_title(title)
        ax.set_ylabel("Headway (minutes)")
        ax.set_xticks(x, frame["label"], rotation=90, fontsize=6)
        ax.grid(axis="y", linewidth=0.45, color="#d7dce0")
        ax.spines[["top", "right", "left"]].set_visible(False)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=2, frameon=False)
    fig.suptitle("Hong Kong inferred MTR and Light Rail headways", fontsize=14)
    fig.tight_layout(rect=(0, 0.05, 1, 0.96))
    fig.savefig(output_path, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def main() -> int:
    args = parse_args()
    snapshot_dirs = args.snapshot_dirs or DEFAULT_SNAPSHOTS
    required = [args.frequency_table, args.mtr_stops, args.lrt_stops, args.amap_lines]
    for snapshot in snapshot_dirs:
        required.extend([snapshot / "mtr_next_train.jsonl", snapshot / "light_rail_next_train.jsonl"])
    for path in required:
        if not path.exists():
            raise FileNotFoundError(path)
    if len(snapshot_dirs) != 2:
        raise ValueError("Exactly two independent snapshot directories are required")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    inputs_dir = args.output_dir / "inputs"
    inputs_dir.mkdir(exist_ok=True)
    shutil.copy2(args.frequency_table, inputs_dir / args.frequency_table.name)

    frequencies = pd.read_csv(args.frequency_table)
    mtr_stops = pd.read_csv(args.mtr_stops, low_memory=False)
    lrt_stops = pd.read_csv(args.lrt_stops, low_memory=False)
    amap_lines = pd.read_csv(args.amap_lines, dtype=str, keep_default_na=False)
    patterns = build_route_patterns(mtr_stops, lrt_stops)
    attach_service_windows(patterns, amap_lines)
    observations = extract_snapshot_observations(patterns, snapshot_dirs)
    periods = build_service_periods(patterns, frequencies, observations)
    periods, common_section_audit = balance_branch_common_sections(periods, frequencies)
    departures = generate_departures(patterns, periods, observations)
    routes, route_stops = build_route_frames(patterns)
    validation = validate_snapshots(departures, observations)

    routes.to_csv(args.output_dir / "approximate_route_patterns.csv", index=False, encoding="utf-8-sig")
    route_stops.to_csv(args.output_dir / "approximate_route_stops.csv", index=False, encoding="utf-8-sig")
    periods.to_csv(args.output_dir / "approximate_service_periods.csv", index=False, encoding="utf-8-sig")
    common_section_audit.to_csv(
        args.output_dir / "common_section_frequency_validation.csv",
        index=False,
        encoding="utf-8-sig",
    )
    departures.to_csv(args.output_dir / "approximate_origin_departures.csv", index=False, encoding="utf-8-sig")
    observations.to_csv(args.output_dir / "snapshot_observed_headways.csv", index=False, encoding="utf-8-sig")
    validation.to_csv(args.output_dir / "snapshot_timetable_validation.csv", index=False, encoding="utf-8-sig")
    preview = args.output_dir / "approximate_headway_qa.png"
    plot_headway_qa(periods, preview)

    if routes["route_variant_id"].duplicated().any():
        raise ValueError("Duplicate route_variant_id")
    if departures["departure_id"].duplicated().any():
        raise ValueError("Duplicate departure_id")
    if not departures["departure_seconds"].ge(0).all():
        raise ValueError("Negative departure time")
    route_counts = departures.groupby("route_variant_id").size()
    if not set(route_counts.index).issubset(set(routes["route_variant_id"])):
        raise ValueError("Departure references unknown route")

    active_periods = periods[periods["selected_headway_minutes"].notna()]
    direct_periods = active_periods[
        active_periods["selection_method"] != "derived_common_minus_full_rate"
    ]
    direct_bounded = direct_periods[
        direct_periods["published_min_headway_minutes"].notna()
        & direct_periods["published_max_headway_minutes"].notna()
    ]
    direct_bound_violations = direct_bounded[
        (direct_bounded["selected_headway_minutes"] < direct_bounded["published_min_headway_minutes"])
        | (direct_bounded["selected_headway_minutes"] > direct_bounded["published_max_headway_minutes"])
    ]
    if len(direct_bound_violations):
        raise ValueError("Directly constrained headway falls outside its published range")

    summary = {
        "scope": "inferred typical-weekday origin-departure timetable; not an observed full timetable",
        "service_period_windows": {
            key: [[format_time(start), format_time(end)] for start, end in value]
            for key, value in PERIOD_WINDOWS.items()
        },
        "source_frequency_table": str(args.frequency_table),
        "source_frequency_sha256": file_sha256(args.frequency_table),
        "snapshot_dirs": [str(path) for path in snapshot_dirs],
        "snapshot_sha256": {
            path.name: {
                "mtr": file_sha256(path / "mtr_next_train.jsonl"),
                "lrt": file_sha256(path / "light_rail_next_train.jsonl"),
            }
            for path in snapshot_dirs
        },
        "route_patterns": int(len(routes)),
        "route_patterns_by_mode": routes.groupby("mode").size().astype(int).to_dict(),
        "route_stop_rows": int(len(route_stops)),
        "service_period_rows": int(len(periods)),
        "service_periods_with_selected_headway": int(periods["selected_headway_minutes"].notna().sum()),
        "directly_constrained_active_periods": int(len(direct_periods)),
        "derived_supplemental_active_periods": int(
            (active_periods["selection_method"] == "derived_common_minus_full_rate").sum()
        ),
        "direct_published_bound_violations": int(len(direct_bound_violations)),
        "common_section_validation_rows": int(len(common_section_audit)),
        "common_section_max_target_error_minutes": (
            float(common_section_audit["absolute_target_error"].max())
            if len(common_section_audit)
            else None
        ),
        "origin_departures": int(len(departures)),
        "origin_departures_by_mode": departures.groupby("mode").size().astype(int).to_dict(),
        "earliest_departure": format_time(departures["departure_seconds"].min()),
        "latest_departure": format_time(departures["departure_seconds"].max()),
        "snapshot_observation_rows": int(len(observations)),
        "snapshot_rows_with_headway": int(observations["observed_headway_minutes"].notna().sum()),
        "snapshot_validation_rows": int(len(validation)),
        "snapshot_nearest_departure_mae_minutes": (
            float(validation["absolute_error_minutes"].mean()) if len(validation) else None
        ),
        "snapshot_nearest_departure_p95_minutes": (
            float(validation["absolute_error_minutes"].quantile(0.95)) if len(validation) else None
        ),
        "snapshot_nearest_departure_max_minutes": (
            float(validation["absolute_error_minutes"].max()) if len(validation) else None
        ),
        "assumptions": [
            "The 2026-07-22 11:47 snapshot selects weekday non-peak headways within published ranges.",
            "The 2026-07-20 18:24 snapshot selects weekday evening-peak headways within published ranges.",
            "Morning-peak ranges use their midpoint because no morning snapshot is available.",
            "KTL and TCL common-section short turns are derived by subtracting full-route frequency from common-section frequency.",
            "North Point-LOHAS Park through service is peak-only when the source table does not list an off-peak frequency.",
            "The Tiu Keng Leng-LOHAS Park shuttle uses its non-peak published range as a peak proxy where the table is not listed.",
            "This output contains origin departures and ordered route stops, not inferred station arrival/departure offsets.",
        ],
    }
    (args.output_dir / "approximate_timetable_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    write_sha256_manifest(args.output_dir)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
