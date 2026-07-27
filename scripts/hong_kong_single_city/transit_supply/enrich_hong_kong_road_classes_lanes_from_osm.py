#!/usr/bin/env python3
"""Build OSM-supported Hong Kong RdNet road-class and lane candidates.

The workflow is deliberately non-destructive: it writes an auditable candidate
layer and validation tables, but never edits MATSim network capacity, lanes, or
road classes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import osmium
import pandas as pd
from shapely.geometry import LineString
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
)
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler


DEFAULT_PROJECT_ROOT = Path(r"F:\Matsim\matsim-example-project")
MOTOR_HIGHWAYS = {
    "motorway",
    "motorway_link",
    "trunk",
    "trunk_link",
    "primary",
    "primary_link",
    "secondary",
    "secondary_link",
    "tertiary",
    "tertiary_link",
    "unclassified",
    "residential",
    "living_street",
    "service",
}
MODEL_CLASSES = ("EX", "UT", "PD", "DD", "LD")
PROTECTED_CLASS_SOURCES = {"atc_direct", "st_code_corridor"}
LOW_CONFIDENCE_CLASS_SOURCES = {
    "speed_fallback",
    "route_number_fallback",
    "default_fallback",
}
CLASS_COLORS = {
    "EX": "#d1495b",
    "UT": "#f28e2b",
    "PD": "#edc948",
    "DD": "#59a14f",
    "LD": "#4e79a7",
    "RT": "#9c755f",
    "RR": "#79706e",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=DEFAULT_PROJECT_ROOT)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--search-distance-m", type=float, default=30.0)
    parser.add_argument("--accept-distance-m", type=float, default=20.0)
    parser.add_argument("--accept-bearing-deg", type=float, default=35.0)
    parser.add_argument("--auto-probability", type=float, default=0.80)
    parser.add_argument("--auto-margin", type=float, default=0.25)
    parser.add_argument(
        "--reuse-matches",
        action="store_true",
        help="Reuse existing OSM parquet, sample matches, and route crosswalk.",
    )
    parser.add_argument("--skip-plots", action="store_true")
    return parser.parse_args()


def safe_text(value: Any) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    return str(value).strip()


def safe_float(value: Any, default: float = math.nan) -> float:
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default


def parse_integer(value: Any) -> int | None:
    match = re.fullmatch(r"\s*(\d+)\s*", safe_text(value))
    if not match:
        return None
    result = int(match.group(1))
    return result if 0 < result <= 12 else None


def parse_speed(value: Any) -> float:
    match = re.search(r"(\d+(?:\.\d+)?)", safe_text(value))
    return safe_float(match.group(1)) if match else math.nan


def normalize_name(value: Any) -> str:
    text = safe_text(value).upper()
    text = re.sub(
        r"\b(?:ROAD|RD|STREET|ST|AVENUE|AVE|HIGHWAY|HWY|EXPRESSWAY|"
        r"FLYOVER|BRIDGE|TUNNEL)\b",
        " ",
        text,
    )
    return re.sub(r"[^A-Z0-9]+", " ", text).strip()


def name_similarity(left: Any, right: Any) -> float:
    a, b = normalize_name(left), normalize_name(right)
    if not a or not b or a == "99" or b == "99":
        return math.nan
    if a in b or b in a:
        return min(len(a), len(b)) / max(len(a), len(b))
    return SequenceMatcher(None, a, b).ratio()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def line_bearing(line: Any, point: Any) -> float:
    try:
        position = line.project(point)
        start = line.interpolate(max(0.0, position - 8.0))
        end = line.interpolate(min(line.length, position + 8.0))
        return math.degrees(math.atan2(end.y - start.y, end.x - start.x)) % 360.0
    except Exception:
        return math.nan


def full_angle_difference(left: float, right: float) -> float:
    return abs((left - right + 180.0) % 360.0 - 180.0)


def undirected_angle_difference(left: float, right: float) -> float:
    difference = full_angle_difference(left, right)
    return min(difference, 180.0 - difference)


def is_oneway(highway: str, value: Any) -> bool:
    return highway in {"motorway", "motorway_link"} or safe_text(value).lower() in {
        "yes",
        "1",
        "true",
        "-1",
    }


def effective_osm_flow_bearing(
    geometry_bearing: float,
    highway: str,
    oneway: Any,
) -> float:
    if safe_text(oneway) == "-1":
        return (geometry_bearing + 180.0) % 360.0
    return geometry_bearing


class OSMRoadHandler(osmium.SimpleHandler):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[dict[str, Any]] = []

    def way(self, way: osmium.osm.Way) -> None:
        highway = way.tags.get("highway")
        if highway not in MOTOR_HIGHWAYS:
            return
        try:
            coordinates = [(node.lon, node.lat) for node in way.nodes]
        except osmium.InvalidLocationError:
            return
        if len(coordinates) < 2:
            return
        self.rows.append(
            {
                "osm_way_id": int(way.id),
                "highway": highway,
                "name": way.tags.get("name"),
                "name_en": way.tags.get("name:en"),
                "ref": way.tags.get("ref"),
                "lanes": way.tags.get("lanes"),
                "lanes_forward": way.tags.get("lanes:forward"),
                "lanes_backward": way.tags.get("lanes:backward"),
                "lanes_both_ways": way.tags.get("lanes:both_ways"),
                "oneway": way.tags.get("oneway"),
                "maxspeed": way.tags.get("maxspeed"),
                "junction": way.tags.get("junction"),
                "bridge": way.tags.get("bridge"),
                "tunnel": way.tags.get("tunnel"),
                "layer": way.tags.get("layer"),
                "service": way.tags.get("service"),
                "access": way.tags.get("access"),
                "motor_vehicle": way.tags.get("motor_vehicle"),
                "geometry": LineString(coordinates),
            }
        )


def load_osm_roads(path: Path) -> gpd.GeoDataFrame:
    handler = OSMRoadHandler()
    handler.apply_file(str(path), locations=True)
    roads = gpd.GeoDataFrame(handler.rows, geometry="geometry", crs="EPSG:4326")
    roads = roads.to_crs("EPSG:2326").reset_index(drop=True)
    roads["length_m"] = roads.geometry.length
    roads["osm_name_for_match"] = roads["name_en"].fillna(roads["name"])
    roads["osm_maxspeed_kmh"] = roads["maxspeed"].map(parse_speed)
    roads["osm_is_link"] = roads["highway"].str.endswith("_link")
    roads["osm_is_oneway"] = [
        is_oneway(highway, oneway)
        for highway, oneway in zip(
            roads["highway"], roads["oneway"], strict=True
        )
    ]
    return roads


def load_rdnet(
    road_gdb: Path,
    calibration_dir: Path,
) -> tuple[gpd.GeoDataFrame, pd.DataFrame]:
    roads = gpd.read_file(road_gdb, layer="CENTERLINE").to_crs("EPSG:2326")
    roads["route_id"] = pd.to_numeric(roads["ROUTE_ID"], errors="raise").astype(int)
    roads = roads.drop_duplicates("route_id").copy()
    attributes = pd.read_csv(
        calibration_dir / "road_route_direction_attributes.csv"
    )
    route_attributes = (
        attributes.sort_values(["route_id", "direction"])
        .drop_duplicates("route_id")
        [
            [
                "route_id",
                "road_type",
                "road_type_source",
                "legal_speed_kmh",
                "permlanes",
                "lane_source",
            ]
        ]
    )
    roads = roads.merge(route_attributes, on="route_id", how="inner")
    roads["route_num_present"] = roads["ROUTE_NUM"].map(safe_text).ne("")
    roads["street_name"] = roads["STREET_ENAME"].map(safe_text)
    roads["st_code"] = pd.to_numeric(roads["ST_CODE"], errors="coerce")
    roads["travel_direction"] = pd.to_numeric(
        roads["TRAVEL_DIRECTION"], errors="raise"
    ).astype(int)
    return roads, attributes


def select_osm_candidate(
    point: Any,
    rdnet_bearing: float,
    rdnet_name: str,
    travel_direction: int,
    osm: gpd.GeoDataFrame,
    candidate_indices: list[int],
    search_distance_m: float,
) -> dict[str, Any] | None:
    ranked: list[tuple[float, dict[str, Any]]] = []
    for index in candidate_indices:
        row = osm.iloc[int(index)]
        distance = float(point.distance(row.geometry))
        if distance > search_distance_m:
            continue
        osm_bearing = line_bearing(row.geometry, point)
        bearing_difference = undirected_angle_difference(
            rdnet_bearing, osm_bearing
        )
        similarity = name_similarity(rdnet_name, row.osm_name_for_match)
        one_way = bool(row.osm_is_oneway)
        direction_difference = math.nan
        direction_penalty = 0.0
        if one_way and travel_direction == 3:
            flow_bearing = effective_osm_flow_bearing(
                osm_bearing, row.highway, row.oneway
            )
            direction_difference = full_angle_difference(
                rdnet_bearing, flow_bearing
            )
            if direction_difference > 45.0:
                direction_penalty = 35.0
        elif one_way and travel_direction == 1:
            direction_penalty = 12.0
        name_penalty = (
            8.0 * (1.0 - similarity) if math.isfinite(similarity) else 0.0
        )
        score = (
            distance
            + 0.35 * bearing_difference
            + direction_penalty
            + name_penalty
        )
        ranked.append(
            (
                score,
                {
                    "osm_index": int(index),
                    "osm_way_id": int(row.osm_way_id),
                    "osm_highway": row.highway,
                    "osm_name": safe_text(row.osm_name_for_match),
                    "osm_geometry_bearing": osm_bearing,
                    "rdnet_geometry_bearing": rdnet_bearing,
                    "distance_m": distance,
                    "bearing_difference_deg": bearing_difference,
                    "direction_difference_deg": direction_difference,
                    "name_similarity": similarity,
                    "match_score": score,
                    "same_digitized_direction": (
                        full_angle_difference(rdnet_bearing, osm_bearing) <= 90.0
                    ),
                    "direction_compatible": (
                        not one_way
                        or travel_direction != 3
                        or direction_difference <= 45.0
                    ),
                },
            )
        )
    return min(ranked, key=lambda value: value[0])[1] if ranked else None


def build_sample_matches(
    rdnet: gpd.GeoDataFrame,
    osm: gpd.GeoDataFrame,
    search_distance_m: float,
    accept_distance_m: float,
    accept_bearing_deg: float,
) -> pd.DataFrame:
    spatial_index = osm.sindex
    rows: list[dict[str, Any]] = []
    for road in rdnet.itertuples():
        for fraction in (0.20, 0.50, 0.80):
            point = road.geometry.interpolate(fraction, normalized=True)
            bearing = line_bearing(road.geometry, point)
            candidate_indices = list(
                spatial_index.query(
                    point.buffer(search_distance_m), predicate="intersects"
                )
            )
            selected = select_osm_candidate(
                point,
                bearing,
                road.street_name,
                int(road.travel_direction),
                osm,
                candidate_indices,
                search_distance_m,
            )
            record: dict[str, Any] = {
                "route_id": int(road.route_id),
                "sample_fraction": fraction,
            }
            if selected is None:
                record["sample_match_status"] = "no_candidate"
            else:
                record.update(selected)
                record["sample_match_status"] = (
                    "accepted"
                    if selected["distance_m"] <= accept_distance_m
                    and selected["bearing_difference_deg"]
                    <= accept_bearing_deg
                    and selected["direction_compatible"]
                    else "rejected"
                )
            rows.append(record)
    return pd.DataFrame(rows)


def lane_values_for_sample(
    sample: pd.Series,
    osm_row: pd.Series,
    travel_direction: int,
) -> tuple[float, float, str]:
    total = parse_integer(osm_row["lanes"])
    forward = parse_integer(osm_row["lanes_forward"])
    backward = parse_integer(osm_row["lanes_backward"])
    one_way = bool(osm_row["osm_is_oneway"])
    same_direction = bool(sample["same_digitized_direction"])

    if one_way:
        value = forward or total
        if travel_direction == 3 and value is not None and 1 <= value <= 8:
            return float(value), math.nan, "oneway_explicit_or_implicit"
        return math.nan, math.nan, "oneway_cross_section_conflict"

    if forward is not None and backward is not None:
        if same_direction:
            return (
                float(forward),
                float(backward),
                "directional_tags_available",
            )
        return float(backward), float(forward), "directional_tags_available"

    if total is not None and total % 2 == 0 and 2 <= total <= 12:
        value = float(total // 2)
        return value, value, "even_total_split"

    return math.nan, math.nan, "two_way_ambiguous_or_missing"


def stable_lane_value(values: list[float]) -> tuple[float, float]:
    valid = [float(value) for value in values if math.isfinite(float(value))]
    if len(valid) < 2 or max(valid) - min(valid) > 1.0:
        return math.nan, 0.0
    rounded = [int(round(value)) for value in valid]
    mode, count = Counter(rounded).most_common(1)[0]
    return float(mode), count / len(valid)


def aggregate_route_matches(
    rdnet: gpd.GeoDataFrame,
    osm: gpd.GeoDataFrame,
    samples: pd.DataFrame,
) -> pd.DataFrame:
    road_lookup = rdnet.set_index("route_id")
    rows: list[dict[str, Any]] = []
    for route_id, frame in samples.groupby("route_id"):
        road = road_lookup.loc[int(route_id)]
        accepted = frame.loc[frame["sample_match_status"].eq("accepted")].copy()
        if accepted.empty:
            rows.append(
                {
                    "route_id": int(route_id),
                    "matched_samples": 0,
                    "spatial_match": False,
                    "match_status": "no_reliable_osm_match",
                }
            )
            continue
        counts = Counter(accepted["osm_highway"])
        highway, highway_count = counts.most_common(1)[0]
        selected = accepted.loc[accepted["osm_highway"].eq(highway)].copy()
        class_agreement = highway_count / len(accepted)
        spatial_match = (
            len(accepted) >= 2
            and class_agreement >= 2.0 / 3.0
            and selected["distance_m"].median() <= 15.0
            and selected["bearing_difference_deg"].median() <= 30.0
        )
        osm_indices = selected["osm_index"].dropna().astype(int).tolist()
        osm_subset = osm.iloc[osm_indices].copy()
        representative = osm_subset.iloc[0]
        lane_f_values: list[float] = []
        lane_r_values: list[float] = []
        lane_bases: list[str] = []
        for _, sample in selected.iterrows():
            osm_row = osm.iloc[int(sample["osm_index"])]
            lane_f, lane_r, basis = lane_values_for_sample(
                sample, osm_row, int(road.travel_direction)
            )
            lane_f_values.append(lane_f)
            lane_r_values.append(lane_r)
            lane_bases.append(basis)
        lane_f, lane_f_consensus = stable_lane_value(lane_f_values)
        lane_r, lane_r_consensus = stable_lane_value(lane_r_values)
        valid_lane_bases = [
            basis
            for basis, value in zip(lane_bases, lane_f_values, strict=True)
            if math.isfinite(value)
        ]
        lane_basis = (
            Counter(valid_lane_bases).most_common(1)[0][0]
            if valid_lane_bases
            else Counter(lane_bases).most_common(1)[0][0]
        )
        speed_values = osm_subset["osm_maxspeed_kmh"].dropna()
        rows.append(
            {
                "route_id": int(route_id),
                "matched_samples": int(len(accepted)),
                "matching_highway_samples": int(len(selected)),
                "osm_class_agreement": float(class_agreement),
                "spatial_match": bool(spatial_match),
                "match_status": (
                    "matched" if spatial_match else "insufficient_consensus"
                ),
                "osm_way_ids": ",".join(
                    map(
                        str,
                        sorted(selected["osm_way_id"].dropna().astype(int).unique()),
                    )
                ),
                "osm_highway": highway,
                "osm_name": safe_text(representative.osm_name_for_match),
                "osm_ref": safe_text(representative.ref),
                "osm_is_link": bool(highway.endswith("_link")),
                "osm_is_oneway": bool(
                    osm_subset["osm_is_oneway"].mode().iloc[0]
                ),
                "osm_maxspeed_kmh": (
                    float(speed_values.median())
                    if not speed_values.empty
                    else math.nan
                ),
                "match_distance_m": float(selected["distance_m"].median()),
                "bearing_difference_deg": float(
                    selected["bearing_difference_deg"].median()
                ),
                "name_similarity": (
                    float(selected["name_similarity"].dropna().median())
                    if selected["name_similarity"].notna().any()
                    else math.nan
                ),
                "osm_lanes_f": lane_f,
                "osm_lanes_r": lane_r,
                "osm_lane_basis": lane_basis,
                "osm_lane_consensus": float(
                    max(lane_f_consensus, lane_r_consensus)
                ),
            }
        )
    return pd.DataFrame(rows)


def build_class_training_data(
    project_root: Path,
    calibration_dir: Path,
    route_features: pd.DataFrame,
) -> pd.DataFrame:
    annual = pd.read_csv(
        calibration_dir / "annual_atc_station_summary_2019_2024.csv"
    )
    annual = (
        annual.loc[annual["year"].eq(2024), ["station_no", "road_type"]]
        .dropna(subset=["road_type"])
        .drop_duplicates("station_no")
    )
    atc_matches = pd.read_csv(
        calibration_dir / "atc_station_route_crosswalk.csv"
    )
    anchors = annual.merge(
        atc_matches[["station_no", "route_id", "match_status"]],
        on="station_no",
        how="inner",
    )
    anchors = anchors.loc[anchors["match_status"].eq("matched")]
    labels = (
        anchors.groupby("route_id")["road_type"]
        .agg(lambda values: Counter(values).most_common(1)[0][0])
        .rename("target_road_type")
        .reset_index()
    )
    return route_features.merge(labels, on="route_id", how="inner")


def model_feature_columns() -> tuple[list[str], list[str]]:
    categorical = ["osm_highway", "osm_is_oneway", "travel_direction"]
    numeric = [
        "legal_speed_kmh",
        "route_num_present",
        "osm_maxspeed_kmh",
        "osm_lanes_f",
        "osm_lanes_r",
        "name_similarity",
    ]
    return categorical, numeric


def prepare_model_frame(frame: pd.DataFrame) -> pd.DataFrame:
    categorical, numeric = model_feature_columns()
    result = frame[categorical + numeric].copy()
    for column in categorical:
        result[column] = (
            result[column].astype("string").fillna("missing").astype(str)
        )
    for column in numeric:
        values = pd.to_numeric(result[column], errors="coerce")
        result[column] = values.fillna(values.median() if values.notna().any() else 0.0)
    return result


def make_model() -> Pipeline:
    categorical, numeric = model_feature_columns()
    processor = ColumnTransformer(
        [
            (
                "categorical",
                OneHotEncoder(handle_unknown="ignore"),
                categorical,
            ),
            ("numeric", StandardScaler(), numeric),
        ]
    )
    return Pipeline(
        [
            ("features", processor),
            (
                "classifier",
                LogisticRegression(
                    max_iter=3000,
                    class_weight="balanced",
                    C=1.0,
                ),
            ),
        ]
    )


def cross_validate_class_model(
    training: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    training = training.loc[
        training["spatial_match"].fillna(False)
        & training["target_road_type"].isin(MODEL_CLASSES)
    ].copy()
    training["cv_group"] = training["st_code"].fillna(training["route_id"])
    splitter = GroupKFold(n_splits=5)
    probabilities = np.zeros((len(training), len(MODEL_CLASSES)), dtype=float)
    predictions = np.empty(len(training), dtype=object)
    folds = np.zeros(len(training), dtype=int)
    features = prepare_model_frame(training)
    labels = training["target_road_type"].to_numpy()
    groups = training["cv_group"].to_numpy()
    for fold, (train_index, test_index) in enumerate(
        splitter.split(features, labels, groups), start=1
    ):
        model = make_model()
        model.fit(features.iloc[train_index], labels[train_index])
        fold_probability = model.predict_proba(features.iloc[test_index])
        fold_classes = model.named_steps["classifier"].classes_
        for column, label in enumerate(fold_classes):
            probabilities[test_index, MODEL_CLASSES.index(label)] = fold_probability[
                :, column
            ]
        predictions[test_index] = model.predict(features.iloc[test_index])
        folds[test_index] = fold
    validation = training[
        [
            "route_id",
            "st_code",
            "osm_highway",
            "target_road_type",
        ]
    ].copy()
    validation["fold"] = folds
    validation["predicted_road_type"] = predictions
    for index, label in enumerate(MODEL_CLASSES):
        validation[f"prob_{label}"] = probabilities[:, index]
    metrics = {
        "records": len(validation),
        "groups": int(training["cv_group"].nunique()),
        "accuracy": float(accuracy_score(labels, predictions)),
        "balanced_accuracy": float(
            balanced_accuracy_score(labels, predictions)
        ),
        "macro_f1": float(f1_score(labels, predictions, average="macro")),
        "weighted_f1": float(
            f1_score(labels, predictions, average="weighted")
        ),
        "classification_report": classification_report(
            labels,
            predictions,
            labels=list(MODEL_CLASSES),
            output_dict=True,
            zero_division=0,
        ),
        "confusion_matrix_labels": list(MODEL_CLASSES),
        "confusion_matrix": confusion_matrix(
            labels, predictions, labels=list(MODEL_CLASSES)
        ).tolist(),
    }
    return validation, metrics


def predict_road_classes(
    route_features: pd.DataFrame,
    training: pd.DataFrame,
) -> pd.DataFrame:
    train = training.loc[
        training["spatial_match"].fillna(False)
        & training["target_road_type"].isin(MODEL_CLASSES)
    ].copy()
    model = make_model()
    model.fit(prepare_model_frame(train), train["target_road_type"])
    result = route_features.copy()
    matched = result["spatial_match"].fillna(False)
    probabilities = model.predict_proba(prepare_model_frame(result.loc[matched]))
    classes = model.named_steps["classifier"].classes_
    for label in MODEL_CLASSES:
        result[f"prob_{label}"] = math.nan
    result.loc[matched, "model_road_type"] = model.predict(
        prepare_model_frame(result.loc[matched])
    )
    for column, label in enumerate(classes):
        result.loc[matched, f"prob_{label}"] = probabilities[:, column]
    probability_columns = [f"prob_{label}" for label in MODEL_CLASSES]
    result["model_probability"] = result[probability_columns].max(axis=1)
    sorted_probability = np.sort(
        result[probability_columns].fillna(0.0).to_numpy(), axis=1
    )
    result["model_probability_margin"] = (
        sorted_probability[:, -1] - sorted_probability[:, -2]
    )
    return result


def assign_road_type_candidates(
    predicted: pd.DataFrame,
    probability_threshold: float,
    margin_threshold: float,
) -> pd.DataFrame:
    result = predicted.copy()
    result["candidate_road_type"] = result["road_type"]
    result["candidate_road_type_source"] = "current_preserved"
    result["road_type_adoption_status"] = "preserve_current"
    osm_is_link = (
        result["osm_is_link"].astype("boolean").fillna(False).astype(bool)
    )
    model_ready = (
        result["road_type_source"].isin(LOW_CONFIDENCE_CLASS_SOURCES)
        & result["spatial_match"].fillna(False)
        & ~osm_is_link
        & result["model_probability"].ge(probability_threshold)
        & result["model_probability_margin"].ge(margin_threshold)
    )
    result.loc[model_ready, "candidate_road_type"] = result.loc[
        model_ready, "model_road_type"
    ]
    result.loc[
        model_ready, "candidate_road_type_source"
    ] = "osm_atc_probability_model"
    result.loc[model_ready, "road_type_adoption_status"] = np.where(
        result.loc[model_ready, "candidate_road_type"].eq(
            result.loc[model_ready, "road_type"]
        ),
        "osm_confirmed_current",
        "candidate_change",
    )

    # Link ways inherit an established class from non-link routes sharing the
    # same street code. They are never independently classified from *_link.
    parent_pool = result.loc[
        ~osm_is_link
        & (
            result["road_type_source"].isin(PROTECTED_CLASS_SOURCES)
            | model_ready
        )
        & result["st_code"].notna()
    ].copy()
    parent_pool["parent_type"] = np.where(
        parent_pool["road_type_source"].isin(PROTECTED_CLASS_SOURCES),
        parent_pool["road_type"],
        parent_pool["candidate_road_type"],
    )
    parent_map = (
        parent_pool.groupby("st_code")["parent_type"]
        .agg(
            lambda values: (
                Counter(values).most_common(1)[0][0]
                if Counter(values).most_common(1)[0][1] / len(values) >= 0.75
                else ""
            )
        )
        .to_dict()
    )
    link_ready = (
        result["road_type_source"].isin(LOW_CONFIDENCE_CLASS_SOURCES)
        & osm_is_link
        & result["st_code"].map(parent_map).fillna("").ne("")
    )
    result.loc[link_ready, "candidate_road_type"] = result.loc[
        link_ready, "st_code"
    ].map(parent_map)
    result.loc[
        link_ready, "candidate_road_type_source"
    ] = "osm_link_inherited_from_st_code_parent"
    result.loc[link_ready, "road_type_adoption_status"] = np.where(
        result.loc[link_ready, "candidate_road_type"].eq(
            result.loc[link_ready, "road_type"]
        ),
        "osm_confirmed_current",
        "candidate_change",
    )

    protected_conflict = (
        result["road_type_source"].isin(PROTECTED_CLASS_SOURCES)
        & result["model_probability"].ge(probability_threshold)
        & result["model_probability_margin"].ge(margin_threshold)
        & result["model_road_type"].ne(result["road_type"])
    )
    result.loc[
        protected_conflict, "road_type_adoption_status"
    ] = "protected_official_osm_conflict"
    unresolved_link = (
        result["road_type_source"].isin(LOW_CONFIDENCE_CLASS_SOURCES)
        & osm_is_link
        & ~link_ready
    )
    result.loc[
        unresolved_link, "road_type_adoption_status"
    ] = "link_without_reliable_parent"
    return result


def assign_lane_candidates(
    direction_attributes: pd.DataFrame,
    routes: pd.DataFrame,
) -> pd.DataFrame:
    columns = [
        "route_id",
        "osm_lanes_f",
        "osm_lanes_r",
        "osm_lane_basis",
        "osm_lane_consensus",
        "spatial_match",
        "match_distance_m",
        "bearing_difference_deg",
        "osm_way_ids",
    ]
    result = direction_attributes.merge(
        routes[columns], on="route_id", how="left"
    )
    result["osm_directional_lanes"] = np.where(
        result["direction"].eq("f"),
        result["osm_lanes_f"],
        result["osm_lanes_r"],
    )
    result["candidate_permlanes"] = result["permlanes"]
    result["candidate_lane_source"] = "current_preserved"
    result["lane_adoption_status"] = "no_usable_osm_lane"
    usable = (
        result["spatial_match"].fillna(False)
        & result["osm_directional_lanes"].notna()
        & result["osm_lane_consensus"].ge(2.0 / 3.0)
    )
    result.loc[usable, "lane_adoption_status"] = "osm_candidate_evaluated"
    protected_detector = result["lane_source"].str.startswith(
        "detector_modal", na=False
    )
    result.loc[
        usable & protected_detector, "lane_adoption_status"
    ] = "detector_lane_preserved"
    difference = (
        result["osm_directional_lanes"] - result["permlanes"]
    ).abs()
    detailed_atc_conflict = (
        result["lane_source"].str.contains("atc_direction_peak", na=False)
        & difference.gt(1.0)
    )
    vc_conflict = (
        result["lane_source"].str.contains("vc_adjustment", na=False)
        & result["osm_directional_lanes"].lt(result["permlanes"])
    )
    conflict = usable & (detailed_atc_conflict | vc_conflict)
    result.loc[conflict, "lane_adoption_status"] = "manual_lane_conflict"
    extreme_change = usable & difference.ge(3.0)
    result.loc[
        extreme_change & ~protected_detector, "lane_adoption_status"
    ] = "manual_extreme_lane_change"
    auto = usable & ~protected_detector & ~conflict & ~extreme_change
    result.loc[auto, "candidate_permlanes"] = result.loc[
        auto, "osm_directional_lanes"
    ].round().astype(int)
    result.loc[auto, "candidate_lane_source"] = np.where(
        result.loc[auto, "osm_lane_basis"].eq("directional_tags_available"),
        "osm_directional_lanes",
        np.where(
            result.loc[auto, "osm_lane_basis"].eq(
                "oneway_explicit_or_implicit"
            ),
            "osm_oneway_lanes",
            "osm_even_total_split",
        ),
    )
    result.loc[auto, "lane_adoption_status"] = np.where(
        result.loc[auto, "candidate_permlanes"].eq(
            result.loc[auto, "permlanes"]
        ),
        "osm_confirmed_current",
        "candidate_change",
    )
    result["lane_change"] = result["candidate_permlanes"] - result["permlanes"]
    return result


def validate_lanes_with_detectors(
    project_root: Path,
    calibration_dir: Path,
    lanes: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    detector_stats = pd.read_csv(
        calibration_dir / "traffic_detector_lane_capacity_estimates.csv"
    )
    detector_stats = detector_stats.loc[
        detector_stats["lane_count_reliable"].astype(str).str.lower().eq("true"),
        ["detector_id", "modal_lanes"],
    ]
    matches = pd.read_csv(
        calibration_dir / "traffic_detector_route_crosswalk.csv"
    )
    validation = (
        detector_stats.merge(
            matches[
                [
                    "AID_ID_Number",
                    "route_id",
                    "matched_direction",
                    "match_distance_m",
                    "match_status",
                ]
            ].rename(columns={"AID_ID_Number": "detector_id"}),
            on="detector_id",
            how="left",
        )
        .merge(
            lanes[
                [
                    "route_id",
                    "direction",
                    "osm_directional_lanes",
                    "osm_lane_basis",
                    "candidate_permlanes",
                    "lane_adoption_status",
                ]
            ],
            left_on=["route_id", "matched_direction"],
            right_on=["route_id", "direction"],
            how="left",
        )
    )
    validation["osm_minus_detector"] = (
        validation["osm_directional_lanes"] - validation["modal_lanes"]
    )
    usable = validation["osm_directional_lanes"].notna()
    values = validation.loc[usable, "osm_minus_detector"]
    summary = {
        "reliable_detectors": len(validation),
        "usable_osm_lane_matches": int(usable.sum()),
        "exact_matches": int(values.eq(0).sum()),
        "exact_share": float(values.eq(0).mean()) if len(values) else math.nan,
        "within_one_lane_share": (
            float(values.abs().le(1).mean()) if len(values) else math.nan
        ),
        "osm_higher": int(values.gt(0).sum()),
        "osm_lower": int(values.lt(0).sum()),
    }
    return validation, summary


def build_manual_review(
    roads: pd.DataFrame,
    lanes: pd.DataFrame,
) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    road_issues = roads.loc[
        roads["road_type_adoption_status"].isin(
            {
                "protected_official_osm_conflict",
                "link_without_reliable_parent",
            }
        )
        | (
            roads["road_type_source"].isin(LOW_CONFIDENCE_CLASS_SOURCES)
            & roads["spatial_match"].fillna(False)
            & roads["model_road_type"].ne(roads["road_type"])
            & roads["road_type_adoption_status"].ne("candidate_change")
        )
    ]
    for row in road_issues.itertuples():
        if row.road_type_adoption_status in {
            "protected_official_osm_conflict",
            "link_without_reliable_parent",
        }:
            issue = row.road_type_adoption_status
        elif row.road_type_adoption_status == "osm_confirmed_current":
            issue = "link_parent_model_disagreement"
        else:
            issue = "low_confidence_class_disagreement"
        records.append(
            {
                "entity_type": "route",
                "route_id": row.route_id,
                "direction": "",
                "issue": issue,
                "current_value": row.road_type,
                "candidate_value": row.model_road_type,
                "evidence": (
                    f"osm={row.osm_highway}; probability={row.model_probability:.3f}; "
                    f"margin={row.model_probability_margin:.3f}; "
                    f"distance={row.match_distance_m:.1f}"
                ),
            }
        )
    lane_issues = lanes.loc[
        lanes["lane_adoption_status"].isin(
            {"manual_lane_conflict", "manual_extreme_lane_change"}
        )
    ]
    for row in lane_issues.itertuples():
        records.append(
            {
                "entity_type": "route_direction",
                "route_id": row.route_id,
                "direction": row.direction,
                "issue": row.lane_adoption_status,
                "current_value": row.permlanes,
                "candidate_value": row.osm_directional_lanes,
                "evidence": (
                    f"current_source={row.lane_source}; osm_basis={row.osm_lane_basis}; "
                    f"consensus={row.osm_lane_consensus:.3f}"
                ),
            }
        )
    return pd.DataFrame(records)


def write_qa_plots(
    roads_geo: gpd.GeoDataFrame,
    road_candidates: pd.DataFrame,
    lane_candidates: pd.DataFrame,
    lane_validation: pd.DataFrame,
    output_dir: Path,
) -> None:
    class_changes = road_candidates.loc[
        road_candidates["road_type_adoption_status"].eq("candidate_change")
    ]
    lane_changes = lane_candidates.loc[
        lane_candidates["lane_adoption_status"].eq("candidate_change")
    ]
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    road_candidates["road_type_source"].value_counts().plot.bar(
        ax=axes[0, 0], color="#4e79a7"
    )
    axes[0, 0].set_title("Current road-class evidence")
    axes[0, 0].set_ylabel("RdNet routes")
    axes[0, 0].tick_params(axis="x", rotation=25)
    class_changes["candidate_road_type"].value_counts().reindex(
        MODEL_CLASSES
    ).fillna(0).plot.bar(
        ax=axes[0, 1],
        color=[CLASS_COLORS[label] for label in MODEL_CLASSES],
    )
    axes[0, 1].set_title("Automatic class-change candidates")
    axes[0, 1].set_ylabel("RdNet routes")
    axes[0, 1].tick_params(axis="x", rotation=0)
    lane_changes["lane_change"].value_counts().sort_index().plot.bar(
        ax=axes[1, 0], color="#59a14f"
    )
    axes[1, 0].set_title("Automatic lane-change candidates")
    axes[1, 0].set_xlabel("Candidate lanes minus current lanes")
    axes[1, 0].set_ylabel("Route-directions")
    detector_delta = lane_validation["osm_minus_detector"].dropna()
    axes[1, 1].hist(
        detector_delta,
        bins=np.arange(-5.5, 5.6, 1),
        color="#f28e2b",
        edgecolor="white",
    )
    axes[1, 1].set_title("OSM lanes minus detector lanes")
    axes[1, 1].set_xlabel("Lane difference")
    axes[1, 1].set_ylabel("Reliable detectors")
    fig.suptitle("Hong Kong OSM road-class and lane enrichment QA")
    fig.tight_layout()
    fig.savefig(output_dir / "osm_class_lane_enrichment_qa.png", dpi=180)
    plt.close(fig)

    geometry = roads_geo[["route_id", "geometry"]].copy()
    class_geo = geometry.merge(
        class_changes[["route_id", "candidate_road_type"]],
        on="route_id",
        how="inner",
    )
    lane_route = (
        lane_changes.groupby("route_id", as_index=False)["lane_change"]
        .agg(lambda values: values.iloc[np.argmax(np.abs(values.to_numpy()))])
    )
    lane_geo = geometry.merge(lane_route, on="route_id", how="inner")
    fig, axes = plt.subplots(1, 2, figsize=(15, 7))
    roads_geo.plot(ax=axes[0], color="#d9d9d9", linewidth=0.15)
    for road_type in MODEL_CLASSES:
        subset = class_geo.loc[
            class_geo["candidate_road_type"].eq(road_type)
        ]
        if not subset.empty:
            subset.plot(
                ax=axes[0],
                color=CLASS_COLORS[road_type],
                linewidth=0.8,
                label=road_type,
            )
    axes[0].set_title("Automatic road-class candidates")
    axes[0].legend()
    axes[0].set_axis_off()
    roads_geo.plot(ax=axes[1], color="#d9d9d9", linewidth=0.15)
    if not lane_geo.empty:
        lane_geo.plot(
            ax=axes[1],
            column="lane_change",
            cmap="coolwarm",
            linewidth=0.9,
            legend=True,
            vmin=-3,
            vmax=3,
        )
    axes[1].set_title("Automatic directional-lane candidates")
    axes[1].set_axis_off()
    fig.tight_layout()
    fig.savefig(output_dir / "osm_class_lane_candidate_maps.png", dpi=180)
    plt.close(fig)


def json_default(value: Any) -> Any:
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return None if not math.isfinite(float(value)) else float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    raise TypeError(f"Cannot serialize {type(value)}")


def threshold_validation_metrics(
    validation: pd.DataFrame,
    probability_threshold: float,
    margin_threshold: float,
) -> dict[str, Any]:
    probability_columns = [f"prob_{label}" for label in MODEL_CLASSES]
    values = validation[probability_columns].to_numpy()
    maximum = values.max(axis=1)
    ordered = np.sort(values, axis=1)
    margin = ordered[:, -1] - ordered[:, -2]
    selected = validation.loc[
        (maximum >= probability_threshold) & (margin >= margin_threshold)
    ].copy()
    selected["correct"] = selected["predicted_road_type"].eq(
        selected["target_road_type"]
    )
    by_prediction = (
        selected.groupby("predicted_road_type")["correct"]
        .agg(["size", "mean"])
        .rename(columns={"size": "records", "mean": "precision"})
        .to_dict("index")
    )
    return {
        "probability_threshold": probability_threshold,
        "margin_threshold": margin_threshold,
        "records": len(selected),
        "coverage": len(selected) / len(validation) if len(validation) else 0.0,
        "accuracy": float(selected["correct"].mean())
        if len(selected)
        else math.nan,
        "by_predicted_class": by_prediction,
    }


def main() -> None:
    args = parse_args()
    project_root = args.project_root.resolve()
    transit_root = project_root / "data" / "transit" / "hongkong"
    calibration_dir = (
        transit_root / "processed" / "road_speed_capacity_2026_v1"
    )
    pbf = (
        project_root
        / "data"
        / "osm"
        / "hongkong"
        / "fixed_link_boundary"
        / "hong-kong-latest.osm.pbf"
    )
    road_gdb = transit_root / "RdNet_IRNP.gdb"
    output_dir = (
        args.output_dir.resolve()
        if args.output_dir
        else transit_root
        / "processed"
        / "road_osm_class_lane_enrichment_2026_v1"
    )
    required = [
        pbf,
        road_gdb,
        calibration_dir / "road_route_direction_attributes.csv",
        calibration_dir / "annual_atc_station_summary_2019_2024.csv",
        calibration_dir / "atc_station_route_crosswalk.csv",
        calibration_dir / "traffic_detector_lane_capacity_estimates.csv",
        calibration_dir / "traffic_detector_route_crosswalk.csv",
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise SystemExit(f"Missing required inputs: {missing}")
    output_dir.mkdir(parents=True, exist_ok=True)

    rdnet, direction_attributes = load_rdnet(road_gdb, calibration_dir)
    cached_osm = output_dir / "osm_motor_road_tags.parquet"
    cached_samples = output_dir / "osm_rdnet_sample_matches.csv"
    cached_crosswalk = output_dir / "osm_rdnet_crosswalk.csv"
    if (
        args.reuse_matches
        and cached_osm.exists()
        and cached_samples.exists()
        and cached_crosswalk.exists()
    ):
        osm = gpd.read_parquet(cached_osm)
        samples = pd.read_csv(cached_samples, low_memory=False)
        crosswalk = pd.read_csv(cached_crosswalk, low_memory=False)
    else:
        osm = load_osm_roads(pbf)
        samples = build_sample_matches(
            rdnet,
            osm,
            args.search_distance_m,
            args.accept_distance_m,
            args.accept_bearing_deg,
        )
        crosswalk = aggregate_route_matches(rdnet, osm, samples)
    route_features = rdnet.drop(columns="geometry").merge(
        crosswalk, on="route_id", how="left"
    )
    training = build_class_training_data(
        project_root, calibration_dir, route_features
    )
    class_validation, class_metrics = cross_validate_class_model(training)
    class_metrics["automatic_threshold_validation"] = (
        threshold_validation_metrics(
            class_validation, args.auto_probability, args.auto_margin
        )
    )
    predicted = predict_road_classes(route_features, training)
    road_candidates = assign_road_type_candidates(
        predicted, args.auto_probability, args.auto_margin
    )
    lane_candidates = assign_lane_candidates(
        direction_attributes, road_candidates
    )
    lane_validation, lane_metrics = validate_lanes_with_detectors(
        project_root, calibration_dir, lane_candidates
    )
    manual_review = build_manual_review(road_candidates, lane_candidates)
    default_upgrades = road_candidates.loc[
        road_candidates["road_type_source"].eq("default_fallback")
        & road_candidates["road_type_adoption_status"].eq("candidate_change")
    ].copy()

    osm.to_parquet(output_dir / "osm_motor_road_tags.parquet", index=False)
    samples.to_csv(output_dir / "osm_rdnet_sample_matches.csv", index=False)
    crosswalk.to_csv(output_dir / "osm_rdnet_crosswalk.csv", index=False)
    road_candidates.to_csv(output_dir / "road_type_candidates.csv", index=False)
    lane_candidates.to_csv(output_dir / "lane_count_candidates.csv", index=False)
    default_upgrades.to_csv(
        output_dir / "default_ld_upgrade_candidates.csv", index=False
    )
    class_validation.to_csv(
        output_dir / "osm_atc_class_validation.csv", index=False
    )
    lane_validation.to_csv(
        output_dir / "osm_detector_lane_validation.csv", index=False
    )
    manual_review.to_csv(output_dir / "manual_review.csv", index=False)
    combined_geo = rdnet[
        [
            "route_id",
            "STREET_ENAME",
            "ST_CODE",
            "TRAVEL_DIRECTION",
            "geometry",
        ]
    ].merge(
        road_candidates[
            [
                "route_id",
                "road_type",
                "candidate_road_type",
                "road_type_adoption_status",
                "osm_highway",
                "model_probability",
            ]
        ],
        on="route_id",
        how="left",
    )
    combined_geo.to_parquet(
        output_dir / "road_class_lane_candidates.parquet", index=False
    )
    if not args.skip_plots:
        write_qa_plots(
            rdnet,
            road_candidates,
            lane_candidates,
            lane_validation,
            output_dir,
        )

    matched = road_candidates["spatial_match"].fillna(False)
    usable_lanes = lane_candidates["osm_directional_lanes"].notna()
    summary = {
        "purpose": "Candidate enrichment only; no MATSim network or capacity was modified.",
        "inputs": {
            "osm_pbf": str(pbf),
            "osm_pbf_sha256": sha256(pbf),
            "rdnet_gdb": str(road_gdb),
            "road_calibration_dir": str(calibration_dir),
        },
        "parameters": {
            "search_distance_m": args.search_distance_m,
            "accept_distance_m": args.accept_distance_m,
            "accept_bearing_deg": args.accept_bearing_deg,
            "auto_probability": args.auto_probability,
            "auto_margin": args.auto_margin,
            "protected_class_sources": sorted(PROTECTED_CLASS_SOURCES),
        },
        "counts": {
            "osm_motor_ways": len(osm),
            "rdnet_routes": len(rdnet),
            "rdnet_route_directions": len(direction_attributes),
            "spatially_matched_routes": int(matched.sum()),
            "spatial_match_share": float(matched.mean()),
            "route_directions_with_usable_osm_lanes": int(
                usable_lanes.sum()
            ),
            "automatic_road_class_changes": int(
                road_candidates["road_type_adoption_status"]
                .eq("candidate_change")
                .sum()
            ),
            "default_ld_changes": len(default_upgrades),
            "automatic_lane_changes": int(
                lane_candidates["lane_adoption_status"]
                .eq("candidate_change")
                .sum()
            ),
            "manual_review_records": len(manual_review),
        },
        "road_class_cv": class_metrics,
        "detector_lane_validation": lane_metrics,
        "road_type_adoption_status": road_candidates[
            "road_type_adoption_status"
        ].value_counts().to_dict(),
        "lane_adoption_status": lane_candidates[
            "lane_adoption_status"
        ].value_counts().to_dict(),
        "road_class_change_matrix": pd.crosstab(
            road_candidates.loc[
                road_candidates["road_type_adoption_status"].eq(
                    "candidate_change"
                ),
                "road_type",
            ],
            road_candidates.loc[
                road_candidates["road_type_adoption_status"].eq(
                    "candidate_change"
                ),
                "candidate_road_type",
            ],
        ).to_dict(),
        "limitations": [
            "OSM road classes are community-maintained and are not official Hong Kong functional classes.",
            "RT and RR are not inferred by the probability model.",
            "Two-way odd total lane counts without directional tags are not used.",
            "OSM link ways require a reliable ST_CODE parent and are not independently classified.",
            "Capacity is intentionally outside this workflow.",
        ],
    }
    with (output_dir / "enrichment_summary.json").open(
        "w", encoding="utf-8"
    ) as stream:
        json.dump(
            summary,
            stream,
            ensure_ascii=True,
            indent=2,
            default=json_default,
        )
    print(
        json.dumps(
            {
                "output_dir": str(output_dir),
                "counts": summary["counts"],
                "road_class_cv": {
                    key: class_metrics[key]
                    for key in (
                        "records",
                        "accuracy",
                        "balanced_accuracy",
                        "macro_f1",
                    )
                },
                "detector_lane_validation": lane_metrics,
            },
            indent=2,
            default=json_default,
        )
    )


if __name__ == "__main__":
    main()
