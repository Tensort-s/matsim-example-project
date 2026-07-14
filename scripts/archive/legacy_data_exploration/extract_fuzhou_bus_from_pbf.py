#!/usr/bin/env python
"""Extract Fuzhou bus routes and stops from a local OSM PBF.

Inputs are expected to be local Geofabrik/OSM PBF data and the current
Greenspace Fuzhou boundary. Outputs are WGS84 GeoJSON/CSV inspection layers.

This script extracts:
- route=bus relations that intersect the Fuzhou boundary;
- bus route member way geometries;
- bus stop / platform / stop_position nodes inside the boundary;
- bus stop nodes referenced by selected route relations.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import osmium
from shapely.geometry import LineString, MultiLineString, Point, mapping, shape
from shapely.ops import unary_union


def tags_to_dict(tags: Any) -> dict[str, str]:
    return {str(k): str(v) for k, v in tags}


def load_boundary(path: Path | None):
    if not path or not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    geoms = []
    if data.get("type") == "FeatureCollection":
        for feat in data.get("features", []):
            if feat.get("geometry"):
                geoms.append(shape(feat["geometry"]))
    elif data.get("type") == "Feature":
        geoms.append(shape(data["geometry"]))
    else:
        geoms.append(shape(data))
    return unary_union(geoms) if geoms else None


def inside_or_intersects(geom, boundary) -> bool:
    if boundary is None:
        return True
    try:
        return geom.intersects(boundary)
    except Exception:
        return False


def is_bus_route(tags: dict[str, str]) -> bool:
    return tags.get("type") == "route" and tags.get("route") == "bus"


def is_bus_route_master(tags: dict[str, str]) -> bool:
    return tags.get("type") == "route_master" and tags.get("route_master") == "bus"


def looks_bus_stop(tags: dict[str, str]) -> bool:
    if tags.get("highway") == "bus_stop":
        return True
    if tags.get("public_transport") in {"platform", "stop_position", "station"} and (
        tags.get("bus") == "yes" or tags.get("route_ref") or tags.get("highway") == "bus_stop"
    ):
        return True
    if tags.get("amenity") == "bus_station":
        return True
    return False


class BusRelationCollector(osmium.SimpleHandler):
    def __init__(self):
        super().__init__()
        self.routes: dict[int, dict[str, Any]] = {}
        self.route_masters: dict[int, dict[str, Any]] = {}
        self.member_way_ids: set[int] = set()
        self.member_node_ids: set[int] = set()

    def relation(self, r):
        tags = tags_to_dict(r.tags)
        if not (is_bus_route(tags) or is_bus_route_master(tags)):
            return
        members = []
        for m in r.members:
            members.append({"type": m.type, "ref": int(m.ref), "role": m.role})
            if m.type == "w":
                self.member_way_ids.add(int(m.ref))
            elif m.type == "n":
                self.member_node_ids.add(int(m.ref))
        record = {"id": int(r.id), "tags": tags, "members": members}
        if is_bus_route_master(tags):
            self.route_masters[int(r.id)] = record
        else:
            self.routes[int(r.id)] = record


class BusGeometryCollector(osmium.SimpleHandler):
    def __init__(self, relation_way_ids: set[int], relation_node_ids: set[int], boundary=None):
        super().__init__()
        self.relation_way_ids = relation_way_ids
        self.relation_node_ids = relation_node_ids
        self.boundary = boundary
        self.ways: dict[int, dict[str, Any]] = {}
        self.bus_stop_nodes: dict[int, dict[str, Any]] = {}
        self.member_nodes: dict[int, dict[str, Any]] = {}
        self.way_errors: Counter[str] = Counter()

    def node(self, n):
        tags = tags_to_dict(n.tags)
        is_member = int(n.id) in self.relation_node_ids
        is_stop = looks_bus_stop(tags)
        if not is_member and not is_stop:
            return
        try:
            pt = Point(float(n.location.lon), float(n.location.lat))
        except Exception:
            return
        if not inside_or_intersects(pt, self.boundary):
            return
        feature = {
            "type": "Feature",
            "geometry": mapping(pt),
            "properties": {
                "osm_type": "node",
                "osm_id": int(n.id),
                "is_relation_member": is_member,
                "is_bus_stop_tagged": is_stop,
                **tags,
            },
        }
        if is_stop:
            self.bus_stop_nodes[int(n.id)] = feature
        if is_member:
            self.member_nodes[int(n.id)] = feature

    def way(self, w):
        if int(w.id) not in self.relation_way_ids:
            return
        tags = tags_to_dict(w.tags)
        coords = []
        try:
            for node in w.nodes:
                if not node.location.valid():
                    continue
                coords.append((float(node.location.lon), float(node.location.lat)))
        except Exception as exc:
            self.way_errors[type(exc).__name__] += 1
            return
        if len(coords) < 2:
            self.way_errors["too_few_coords"] += 1
            return
        line = LineString(coords)
        # Keep member ways even if they are just outside; route-level filtering
        # will decide whether a relation intersects the boundary.
        self.ways[int(w.id)] = {
            "type": "Feature",
            "geometry": mapping(line),
            "properties": {
                "osm_type": "way",
                "osm_id": int(w.id),
                **tags,
            },
        }


def feature_collection(features: list[dict[str, Any]]) -> dict[str, Any]:
    return {"type": "FeatureCollection", "features": features}


def write_geojson(path: Path, features: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(feature_collection(features), ensure_ascii=False, indent=2), encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8-sig")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def route_display_name(tags: dict[str, str]) -> str:
    return tags.get("name") or tags.get("ref") or tags.get("from", "") + "->" + tags.get("to", "")


def build_route_features(
    routes: dict[int, dict[str, Any]],
    ways: dict[int, dict[str, Any]],
    member_nodes: dict[int, dict[str, Any]],
    boundary,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[int, dict[str, int]]]:
    route_features: list[dict[str, Any]] = []
    stop_member_features: list[dict[str, Any]] = []
    diagnostics: dict[int, dict[str, int]] = {}

    for rid, route in sorted(routes.items()):
        line_geoms = []
        member_stop_nodes = []
        total_way_members = 0
        matched_way_members = 0
        total_node_members = 0
        matched_node_members = 0
        for m in route["members"]:
            if m["type"] == "w":
                total_way_members += 1
                feat = ways.get(m["ref"])
                if feat:
                    matched_way_members += 1
                    line_geoms.append(shape(feat["geometry"]))
            elif m["type"] == "n":
                total_node_members += 1
                feat = member_nodes.get(m["ref"])
                if feat:
                    matched_node_members += 1
                    member_stop_nodes.append((m, feat))

        intersects = False
        if line_geoms:
            try:
                intersects = MultiLineString([list(g.coords) for g in line_geoms]).intersects(boundary) if boundary else True
            except Exception:
                intersects = any(inside_or_intersects(g, boundary) for g in line_geoms)
        if not intersects and member_stop_nodes:
            intersects = any(inside_or_intersects(shape(feat["geometry"]), boundary) for _, feat in member_stop_nodes)
        if not intersects:
            continue

        tags = route["tags"]
        if line_geoms:
            geom = MultiLineString([list(g.coords) for g in line_geoms])
            route_features.append(
                {
                    "type": "Feature",
                    "geometry": mapping(geom),
                    "properties": {
                        "osm_type": "relation",
                        "osm_id": rid,
                        "route_name": route_display_name(tags),
                        "ref": tags.get("ref", ""),
                        "name": tags.get("name", ""),
                        "from": tags.get("from", ""),
                        "to": tags.get("to", ""),
                        "operator": tags.get("operator", ""),
                        "network": tags.get("network", ""),
                        "total_way_members": total_way_members,
                        "matched_way_members": matched_way_members,
                        "total_node_members": total_node_members,
                        "matched_node_members": matched_node_members,
                    },
                }
            )

        for member, feat in member_stop_nodes:
            props = dict(feat["properties"])
            props.update(
                {
                    "route_relation_id": rid,
                    "route_name": route_display_name(tags),
                    "route_ref": tags.get("ref", ""),
                    "route_from": tags.get("from", ""),
                    "route_to": tags.get("to", ""),
                    "member_role": member.get("role", ""),
                }
            )
            stop_member_features.append({"type": "Feature", "geometry": feat["geometry"], "properties": props})

        diagnostics[rid] = {
            "total_way_members": total_way_members,
            "matched_way_members": matched_way_members,
            "total_node_members": total_node_members,
            "matched_node_members": matched_node_members,
        }

    return route_features, stop_member_features, diagnostics


def rows_from_features(features: list[dict[str, Any]], property_keys: list[str]) -> list[dict[str, Any]]:
    rows = []
    for feat in features:
        geom = shape(feat["geometry"])
        props = feat.get("properties", {})
        row = {k: props.get(k, "") for k in property_keys}
        if geom.geom_type == "Point":
            row["lon"] = geom.x
            row["lat"] = geom.y
        rows.append(row)
    return rows


def plot_boundary(ax, boundary):
    if boundary is None:
        return
    geoms = boundary.geoms if boundary.geom_type == "MultiPolygon" else [boundary]
    for geom in geoms:
        x, y = geom.exterior.xy
        ax.plot(x, y, color="#555555", linewidth=0.7, alpha=0.5)


def plot_lines(ax, features, color="#1f77b4", alpha=0.25, linewidth=0.45):
    for feat in features:
        geom = shape(feat["geometry"])
        geoms = geom.geoms if geom.geom_type == "MultiLineString" else [geom]
        for g in geoms:
            if g.geom_type != "LineString":
                continue
            x, y = g.xy
            ax.plot(x, y, color=color, alpha=alpha, linewidth=linewidth)


def plot_preview(output_dir: Path, boundary, route_features, stop_features):
    fig, ax = plt.subplots(figsize=(12, 12))
    plot_boundary(ax, boundary)
    plot_lines(ax, route_features)
    xs, ys = [], []
    for feat in stop_features:
        pt = shape(feat["geometry"])
        if pt.geom_type == "Point":
            xs.append(pt.x)
            ys.append(pt.y)
    ax.scatter(xs, ys, s=5, color="#111111", alpha=0.55, linewidths=0)
    ax.set_title(f"Fuzhou bus from local OSM PBF: {len(route_features)} route relations, {len(stop_features)} stops")
    ax.set_xlabel("Longitude (WGS84)")
    ax.set_ylabel("Latitude (WGS84)")
    ax.set_aspect("equal", adjustable="box")
    ax.grid(alpha=0.2)
    fig.tight_layout()
    fig.savefig(output_dir / "fuzhou_bus_osm_preview.png", dpi=220)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(11, 10))
    if xs:
        hb = ax.hexbin(xs, ys, gridsize=60, mincnt=1, cmap="magma")
        fig.colorbar(hb, ax=ax, label="Stop count")
    plot_boundary(ax, boundary)
    ax.set_title(f"Fuzhou OSM bus stop density: {len(stop_features)} stop nodes")
    ax.set_xlabel("Longitude (WGS84)")
    ax.set_ylabel("Latitude (WGS84)")
    ax.set_aspect("equal", adjustable="box")
    ax.grid(alpha=0.15)
    fig.tight_layout()
    fig.savefig(output_dir / "fuzhou_bus_osm_stop_density.png", dpi=220)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pbf", default="data/osm/fuzhou_city_23/fujian-latest.osm.pbf")
    parser.add_argument("--boundary", default="data/osm/fuzhou_city_23/fuzhou_city_23_boundary.geojson")
    parser.add_argument("--output-dir", default="data/transit/fuzhou_bus_osm")
    args = parser.parse_args()

    pbf = Path(args.pbf)
    boundary_path = Path(args.boundary) if args.boundary else None
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if not pbf.exists():
        raise FileNotFoundError(pbf)
    boundary = load_boundary(boundary_path)

    relation_collector = BusRelationCollector()
    relation_collector.apply_file(str(pbf))

    geometry_collector = BusGeometryCollector(
        relation_collector.member_way_ids,
        relation_collector.member_node_ids,
        boundary,
    )
    geometry_collector.apply_file(str(pbf), locations=True)

    route_features, route_stop_member_features, route_diag = build_route_features(
        relation_collector.routes,
        geometry_collector.ways,
        geometry_collector.member_nodes,
        boundary,
    )

    # Use tagged stops inside boundary, plus route member stops inside boundary.
    bus_stop_features_by_id: dict[int, dict[str, Any]] = {}
    for source in (geometry_collector.bus_stop_nodes, geometry_collector.member_nodes):
        for osm_id, feat in source.items():
            if inside_or_intersects(shape(feat["geometry"]), boundary):
                bus_stop_features_by_id[osm_id] = feat
    bus_stop_features = list(bus_stop_features_by_id.values())

    member_way_features = [
        feat
        for feat in geometry_collector.ways.values()
        if inside_or_intersects(shape(feat["geometry"]), boundary)
    ]

    write_geojson(output_dir / "fuzhou_bus_osm_route_relations.geojson", route_features)
    write_geojson(output_dir / "fuzhou_bus_osm_member_ways.geojson", member_way_features)
    write_geojson(output_dir / "fuzhou_bus_osm_stops.geojson", bus_stop_features)
    write_geojson(output_dir / "fuzhou_bus_osm_route_stop_members.geojson", route_stop_member_features)

    stop_keys = [
        "osm_id",
        "name",
        "highway",
        "public_transport",
        "bus",
        "route_ref",
        "operator",
        "network",
        "is_relation_member",
        "is_bus_stop_tagged",
    ]
    write_csv(output_dir / "fuzhou_bus_osm_stops.csv", rows_from_features(bus_stop_features, stop_keys))
    route_rows = [feat["properties"] for feat in route_features]
    write_csv(output_dir / "fuzhou_bus_osm_route_relations.csv", route_rows)

    route_names = Counter((feat["properties"].get("route_name") or "") for feat in route_features)
    stop_tag_counter = Counter((feat["properties"].get("highway") or feat["properties"].get("public_transport") or "") for feat in bus_stop_features)
    summary = {
        "input_pbf": str(pbf),
        "boundary": str(boundary_path) if boundary_path else None,
        "output_dir": str(output_dir),
        "bus_route_relations_in_pbf": len(relation_collector.routes),
        "bus_route_masters_in_pbf": len(relation_collector.route_masters),
        "bus_relation_member_way_ids": len(relation_collector.member_way_ids),
        "bus_relation_member_node_ids": len(relation_collector.member_node_ids),
        "selected_route_relations_intersecting_boundary": len(route_features),
        "member_way_features_inside_boundary": len(member_way_features),
        "bus_stop_features_inside_boundary": len(bus_stop_features),
        "route_stop_member_features_inside_boundary": len(route_stop_member_features),
        "way_errors": dict(geometry_collector.way_errors),
        "stop_tag_counter": dict(stop_tag_counter),
        "top_route_names": route_names.most_common(30),
        "route_member_match_diagnostics": route_diag,
    }
    (output_dir / "fuzhou_bus_osm_extraction_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    plot_preview(output_dir, boundary, route_features, bus_stop_features)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
