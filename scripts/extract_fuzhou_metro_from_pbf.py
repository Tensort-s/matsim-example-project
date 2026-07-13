#!/usr/bin/env python
"""Extract Fuzhou Metro stations and line geometries from a local OSM PBF.

The output is intentionally simple GeoJSON so it can be inspected in QGIS and
used as the geometric basis for a later synthetic MATSim transit schedule.

Default input is the Geofabrik Fujian PBF already stored in this project.
Geometries are written in EPSG:4326 (lon/lat), matching OSM.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import osmium
from shapely.geometry import LineString, MultiLineString, Point, mapping, shape
from shapely.ops import unary_union


METRO_TERMS = (
    "福州地铁",
    "福州市轨道交通",
    "Fuzhou Metro",
    "Fuzhou Subway",
    "滨海快线",
    "Binhai Express",
    "F1",
)

ROUTE_VALUES = {"subway", "light_rail"}
RAILWAY_VALUES = {"subway", "light_rail"}


def tags_to_dict(tags: Any) -> dict[str, str]:
    return {str(k): str(v) for k, v in tags}


def tags_blob(tags: dict[str, str]) -> str:
    keys = (
        "name",
        "name:zh",
        "name:en",
        "network",
        "network:zh",
        "network:en",
        "operator",
        "operator:zh",
        "operator:en",
        "description",
        "ref",
    )
    return " ".join(tags.get(k, "") for k in keys)


def looks_fuzhou_metro(tags: dict[str, str]) -> bool:
    blob = tags_blob(tags)
    if any(term.lower() in blob.lower() for term in METRO_TERMS):
        return True
    if tags.get("station") == "subway":
        return True
    if tags.get("subway") in {"yes", "station"}:
        return True
    return False


def looks_metro_route(tags: dict[str, str]) -> bool:
    route = tags.get("route")
    route_master = tags.get("route_master")
    if route in ROUTE_VALUES or route_master in ROUTE_VALUES:
        if looks_fuzhou_metro(tags):
            return True
        # Some route relations are cleanly tagged as subway but have no network
        # name. Keep them for later boundary/name validation.
        return True
    return False


def looks_station(tags: dict[str, str]) -> bool:
    railway = tags.get("railway")
    public_transport = tags.get("public_transport")
    if looks_fuzhou_metro(tags):
        return railway in {"station", "halt", "stop", "subway_entrance"} or public_transport in {
            "station",
            "stop_position",
            "platform",
        }
    if tags.get("station") == "subway":
        return True
    return False


def looks_metro_way(tags: dict[str, str]) -> bool:
    railway = tags.get("railway")
    if railway in RAILWAY_VALUES:
        return True
    if looks_fuzhou_metro(tags) and railway in {"rail", "construction"}:
        return True
    return False


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


class RouteRelationCollector(osmium.SimpleHandler):
    def __init__(self):
        super().__init__()
        self.routes: dict[int, dict[str, Any]] = {}
        self.route_masters: dict[int, dict[str, Any]] = {}
        self.member_way_ids: set[int] = set()

    def relation(self, r):
        tags = tags_to_dict(r.tags)
        if not looks_metro_route(tags):
            return
        members = []
        for m in r.members:
            members.append({"type": m.type, "ref": int(m.ref), "role": m.role})
            if m.type == "w":
                self.member_way_ids.add(int(m.ref))
        record = {"id": int(r.id), "tags": tags, "members": members}
        if tags.get("type") == "route_master" or tags.get("route_master"):
            self.route_masters[int(r.id)] = record
        else:
            self.routes[int(r.id)] = record


class MetroGeometryCollector(osmium.SimpleHandler):
    def __init__(self, relation_way_ids: set[int], boundary=None):
        super().__init__()
        self.relation_way_ids = relation_way_ids
        self.boundary = boundary
        self.stations: list[dict[str, Any]] = []
        self.ways: dict[int, dict[str, Any]] = {}
        self.way_errors: Counter[str] = Counter()

    def _inside_or_intersects(self, geom) -> bool:
        if self.boundary is None:
            return True
        try:
            return geom.intersects(self.boundary)
        except Exception:
            return False

    def node(self, n):
        tags = tags_to_dict(n.tags)
        if not looks_station(tags):
            return
        try:
            pt = Point(float(n.location.lon), float(n.location.lat))
        except Exception:
            return
        if not self._inside_or_intersects(pt):
            return
        self.stations.append(
            {
                "type": "Feature",
                "geometry": mapping(pt),
                "properties": {
                    "osm_type": "node",
                    "osm_id": int(n.id),
                    **tags,
                },
            }
        )

    def way(self, w):
        tags = tags_to_dict(w.tags)
        if int(w.id) not in self.relation_way_ids and not looks_metro_way(tags):
            return
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
        if not self._inside_or_intersects(line):
            return
        source = "route_member" if int(w.id) in self.relation_way_ids else "railway_tag"
        self.ways[int(w.id)] = {
            "type": "Feature",
            "geometry": mapping(line),
            "properties": {
                "osm_type": "way",
                "osm_id": int(w.id),
                "source": source,
                **tags,
            },
        }


def feature_collection(features: list[dict[str, Any]]) -> dict[str, Any]:
    return {"type": "FeatureCollection", "features": features}


def write_geojson(path: Path, features: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(feature_collection(features), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def build_station_group_features(station_features: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for feat in station_features:
        props = feat["properties"]
        name = props.get("name") or props.get("name:zh") or props.get("name:en")
        if name:
            grouped[name].append(feat)

    group_features = []
    for name, feats in sorted(grouped.items()):
        points = [shape(feat["geometry"]) for feat in feats]
        preferred = [
            feat
            for feat in feats
            if feat["properties"].get("railway") == "station"
            or feat["properties"].get("public_transport") == "station"
        ]
        if preferred:
            point = shape(preferred[0]["geometry"])
        else:
            xs = [pt.x for pt in points]
            ys = [pt.y for pt in points]
            point = Point(sum(xs) / len(xs), sum(ys) / len(ys))
        osm_ids = [feat["properties"].get("osm_id") for feat in feats]
        railways = sorted({feat["properties"].get("railway", "") for feat in feats if feat["properties"].get("railway")})
        public_transport = sorted(
            {
                feat["properties"].get("public_transport", "")
                for feat in feats
                if feat["properties"].get("public_transport")
            }
        )
        group_features.append(
            {
                "type": "Feature",
                "geometry": mapping(point),
                "properties": {
                    "name": name,
                    "raw_feature_count": len(feats),
                    "osm_ids": ",".join(str(x) for x in osm_ids if x is not None),
                    "railway_values": ",".join(railways),
                    "public_transport_values": ",".join(public_transport),
                },
            }
        )
    return group_features


def build_route_relation_features(
    routes: dict[int, dict[str, Any]],
    ways: dict[int, dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[int, dict[str, int]]]:
    features = []
    diagnostics: dict[int, dict[str, int]] = {}
    for rid, route in sorted(routes.items()):
        line_geoms = []
        total_way_members = 0
        matched_way_members = 0
        for member in route["members"]:
            if member["type"] != "w":
                continue
            total_way_members += 1
            feat = ways.get(member["ref"])
            if not feat:
                continue
            matched_way_members += 1
            line_geoms.append(shape(feat["geometry"]))
        if not line_geoms:
            diagnostics[rid] = {
                "total_way_members": total_way_members,
                "matched_way_members": matched_way_members,
            }
            continue
        geom = MultiLineString([list(g.coords) for g in line_geoms])
        features.append(
            {
                "type": "Feature",
                "geometry": mapping(geom),
                "properties": {
                    "osm_type": "relation",
                    "osm_id": rid,
                    **route["tags"],
                    "total_way_members": total_way_members,
                    "matched_way_members": matched_way_members,
                },
            }
        )
        diagnostics[rid] = {
            "total_way_members": total_way_members,
            "matched_way_members": matched_way_members,
        }
    return features, diagnostics


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--pbf",
        default="data/osm/fuzhou_city_23/fujian-latest.osm.pbf",
        help="Input OSM PBF.",
    )
    parser.add_argument(
        "--boundary",
        default="data/osm/fuzhou_city_23/fuzhou_city_23_boundary.geojson",
        help="Optional GeoJSON boundary used to spatially filter features.",
    )
    parser.add_argument(
        "--output-dir",
        default="data/transit/fuzhou_metro",
        help="Output directory.",
    )
    args = parser.parse_args()

    pbf = Path(args.pbf)
    boundary_path = Path(args.boundary) if args.boundary else None
    output_dir = Path(args.output_dir)
    if not pbf.exists():
        raise FileNotFoundError(pbf)

    boundary = load_boundary(boundary_path)

    relation_collector = RouteRelationCollector()
    relation_collector.apply_file(str(pbf))

    geometry_collector = MetroGeometryCollector(relation_collector.member_way_ids, boundary)
    geometry_collector.apply_file(str(pbf), locations=True)

    station_features = geometry_collector.stations
    station_group_features = build_station_group_features(station_features)
    way_features = list(geometry_collector.ways.values())
    route_features, route_diag = build_route_relation_features(
        relation_collector.routes,
        geometry_collector.ways,
    )

    write_geojson(output_dir / "fuzhou_metro_stations.geojson", station_features)
    write_geojson(output_dir / "fuzhou_metro_station_groups.geojson", station_group_features)
    write_geojson(output_dir / "fuzhou_metro_line_ways.geojson", way_features)
    write_geojson(output_dir / "fuzhou_metro_route_relations.geojson", route_features)

    station_names = Counter(
        feat["properties"].get("name") or feat["properties"].get("name:zh") or ""
        for feat in station_features
    )
    route_names = [
        {
            "osm_id": feat["properties"].get("osm_id"),
            "name": feat["properties"].get("name"),
            "ref": feat["properties"].get("ref"),
            "network": feat["properties"].get("network"),
            "operator": feat["properties"].get("operator"),
            "matched_way_members": feat["properties"].get("matched_way_members"),
            "total_way_members": feat["properties"].get("total_way_members"),
        }
        for feat in route_features
    ]
    way_sources = Counter(feat["properties"].get("source", "") for feat in way_features)
    railway_tags = Counter(feat["properties"].get("railway", "") for feat in way_features)

    summary = {
        "input_pbf": str(pbf),
        "boundary": str(boundary_path) if boundary_path else None,
        "output_dir": str(output_dir),
        "route_relations_found": len(relation_collector.routes),
        "route_masters_found": len(relation_collector.route_masters),
        "relation_member_way_ids": len(relation_collector.member_way_ids),
        "station_features": len(station_features),
        "station_group_features": len(station_group_features),
        "unique_station_names": len([k for k in station_names if k]),
        "line_way_features": len(way_features),
        "route_relation_features": len(route_features),
        "way_sources": dict(way_sources),
        "railway_tags": dict(railway_tags),
        "way_errors": dict(geometry_collector.way_errors),
        "route_member_match_diagnostics": route_diag,
        "routes": route_names,
        "station_name_counts": dict(station_names),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "fuzhou_metro_extraction_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
