#!/usr/bin/env python3
"""Fix abnormal bus routes/waits and calibrate metro generalized speed to 40 km/h."""

from __future__ import annotations

import argparse
import copy
import csv
import gzip
import json
import math
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from calibrate_fuzhou_bus_priority_speed_and_transfers import (  # noqa: E402
    find_monotonic_route_indices,
    format_time_s,
    parse_time_s,
    recalibrate_bus_route_profiles,
    route_and_stop_modes,
    safe_float,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "data/transit/fuzhou_transit_matsim_integrated_20260709_bus_priority_speedcal_transfer300_carcap5"
DEFAULT_OUTPUT = ROOT / "data/transit/fuzhou_transit_matsim_integrated_20260709_bus_priority_transferwait_metro40"
BUS_STOPS = ROOT / "data/transit/fuzhou_bus_amap_stop_line_final_20260709/bus_lines/amap_bus_stops_by_line_full.csv"
SPECIAL = re.compile(r"专线|通勤|通学|高峰|旅游|空港|夜|区间|定制|快线")


def args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT)
    p.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    p.add_argument("--metro-speed-factor", type=float, default=1.35)
    p.add_argument("--metro-headway-factor", type=float, default=0.75)
    p.add_argument("--regular-bus-max-headway-min", type=float, default=20.0)
    return p.parse_args()


def read_gz(path: Path) -> ET.ElementTree:
    with gzip.open(path, "rb") as f:
        return ET.parse(f)


def write_gz(path: Path, root: ET.Element, doctype: str) -> None:
    ET.indent(root, space="  ")
    with gzip.open(path, "wt", encoding="utf-8", newline="\n") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write(f'<!DOCTYPE {doctype} SYSTEM "http://www.matsim.org/files/dtd/{doctype}_v2.dtd">\n')
        ET.ElementTree(root).write(f, encoding="unicode", xml_declaration=False)


def write_vehicle_gz(path: Path, root: ET.Element) -> None:
    """VehicleDefinitions v2 uses an XML schema/namespace, not the legacy DTD."""
    ET.register_namespace("", "http://www.matsim.org/files/dtd")
    ET.register_namespace("xsi", "http://www.w3.org/2001/XMLSchema-instance")
    ET.indent(root, space="  ")
    with gzip.open(path, "wt", encoding="utf-8", newline="\n") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        ET.ElementTree(root).write(f, encoding="unicode", xml_declaration=False)


def line_names() -> dict[str, str]:
    out: dict[str, str] = {}
    with BUS_STOPS.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            out.setdefault("bus_line_" + row["line_id"], row["line_name"])
    return out


def facilities(schedule: ET.Element) -> dict[str, str]:
    return {x.get("id", ""): x.get("linkRefId", "") for x in schedule.find("transitStops").findall("stopFacility")}


def trim_bus_routes(schedule: ET.Element, facility_links: dict[str, str]) -> list[dict]:
    rows = []
    for line in schedule.findall("transitLine"):
        for route in line.findall("transitRoute"):
            if (route.findtext("transportMode") or "").strip() != "bus":
                continue
            route_el, profile = route.find("route"), route.find("routeProfile")
            refs = [x.get("refId", "") for x in route_el.findall("link")]
            stops = [x.get("refId", "") for x in profile.findall("stop")]
            idx, warnings = find_monotonic_route_indices(refs, stops, facility_links)
            first, last = idx[0], idx[-1]
            trimmed = refs[first:last + 1]
            if trimmed and (first > 0 or last < len(refs) - 1):
                for x in list(route_el):
                    route_el.remove(x)
                for ref in trimmed:
                    ET.SubElement(route_el, "link", {"refId": ref})
            rows.append({"line_id": line.get("id", ""), "route_id": route.get("id", ""),
                         "links_before": len(refs), "links_after": len(trimmed),
                         "removed_prefix": first, "removed_suffix": len(refs)-1-last,
                         "index_warnings": len(warnings)})
    return rows


def scale_metro(schedule: ET.Element, network_links: dict[str, ET.Element], factor: float) -> list[dict]:
    metro_refs: set[str] = set()
    rows = []
    for line in schedule.findall("transitLine"):
        for route in line.findall("transitRoute"):
            if (route.findtext("transportMode") or "").strip() != "metro":
                continue
            metro_refs.update(x.get("refId", "") for x in route.find("route").findall("link"))
            stops = route.find("routeProfile").findall("stop")
            old_terminal = parse_time_s(stops[-1].get("arrivalOffset"))
            previous_old_departure = 0.0
            previous_new_departure = 0.0
            for i, stop in enumerate(stops):
                old_arrival = parse_time_s(stop.get("arrivalOffset"))
                old_departure = parse_time_s(stop.get("departureOffset"))
                if i == 0:
                    new_arrival = new_departure = 0.0
                else:
                    run = max(1.0, old_arrival - previous_old_departure)
                    new_arrival = previous_new_departure + run / factor
                    dwell = 0.0 if i == len(stops)-1 else max(0.0, old_departure-old_arrival)
                    new_departure = new_arrival + dwell
                stop.set("arrivalOffset", format_time_s(new_arrival))
                stop.set("departureOffset", format_time_s(new_departure))
                previous_old_departure, previous_new_departure = old_departure, new_departure
            rows.append({"line_id": line.get("id", ""), "route_id": route.get("id", ""),
                         "old_terminal_s": old_terminal, "new_terminal_s": new_arrival,
                         "running_speed_factor": factor})
    for ref in metro_refs:
        link = network_links.get(ref)
        if link is not None:
            link.set("freespeed", f"{safe_float(link.get('freespeed')) * factor:.6f}")
    return rows


def departures(route: ET.Element) -> list[ET.Element]:
    el = route.find("departures")
    return [] if el is None else el.findall("departure")


def vehicle_index(root: ET.Element) -> tuple[dict[str, ET.Element], dict[str, ET.Element]]:
    types = {x.get("id", ""): x for x in root.findall("{*}vehicleType")}
    vehicles = {x.get("id", ""): x for x in root.findall("{*}vehicle")}
    return types, vehicles


def regularize_departures(schedule: ET.Element, vehicles_root: ET.Element, names: dict[str, str],
                          bus_max_s: float, metro_factor: float) -> list[dict]:
    _, vehicles = vehicle_index(vehicles_root)
    rows = []
    for line in schedule.findall("transitLine"):
        line_id = line.get("id", "")
        name = names.get(line_id, "")
        for route in line.findall("transitRoute"):
            mode = (route.findtext("transportMode") or "").strip()
            old = departures(route)
            if len(old) < 2 or mode not in {"bus", "metro"}:
                continue
            times = sorted(parse_time_s(x.get("departureTime")) for x in old)
            gaps = [b-a for a,b in zip(times,times[1:]) if b>a]
            old_med = sorted(gaps)[len(gaps)//2] if gaps else math.inf
            special = bool(SPECIAL.search(name))
            if mode == "metro":
                new_headway = max(120.0, old_med * metro_factor)
            elif special or old_med <= bus_max_s:
                rows.append({"line_id": line_id, "line_name": name, "mode": mode,
                             "old_departures": len(old), "new_departures": len(old),
                             "old_median_headway_min": round(old_med/60,2), "action": "kept_special" if special else "kept"})
                continue
            else:
                new_headway = bus_max_s
            new_times=[]; t=times[0]
            while t <= times[-1]+0.1:
                new_times.append(t); t += new_headway
            if new_times[-1] < times[-1]-60:
                new_times.append(times[-1])
            dep_el=route.find("departures"); template_vehicle=vehicles[old[0].get("vehicleRefId","")]
            for x in list(dep_el): dep_el.remove(x)
            for i,t in enumerate(new_times,1):
                dep_id=f"optdep_{route.get('id','route')}_{i:04d}"; veh_id=f"optveh_{route.get('id','route')}_{i:04d}"
                ET.SubElement(dep_el,"departure",{"id":dep_id,"departureTime":format_time_s(t),"vehicleRefId":veh_id})
                v=copy.deepcopy(template_vehicle); v.set("id",veh_id); vehicles_root.append(v)
            rows.append({"line_id":line_id,"line_name":name,"mode":mode,"old_departures":len(old),
                         "new_departures":len(new_times),"old_median_headway_min":round(old_med/60,2),
                         "new_headway_min":round(new_headway/60,2),"action":"densified"})
    return rows


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows: return
    fields=[]
    for row in rows:
        for key in row:
            if key not in fields: fields.append(key)
    with path.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)


def main() -> None:
    a=args(); a.output_dir.mkdir(parents=True,exist_ok=True)
    net=read_gz(a.input_dir/"network_with_car_busprio_metro.xml.gz"); sched=read_gz(a.input_dir/"transitSchedule.xml.gz")
    veh=read_gz(a.input_dir/"transitVehicles.xml.gz")
    links={x.get("id",""):x for x in net.getroot().find("links").findall("link")}
    frefs=facilities(sched.getroot())
    trim=trim_bus_routes(sched.getroot(),frefs)
    timing,warnings=recalibrate_bus_route_profiles(sched.getroot(),links,frefs,20.0)
    metro=scale_metro(sched.getroot(),links,a.metro_speed_factor)
    headways=regularize_departures(sched.getroot(),veh.getroot(),line_names(),a.regular_bus_max_headway_min*60,a.metro_headway_factor)
    write_gz(a.output_dir/"network_with_car_busprio_metro.xml.gz",net.getroot(),"network")
    write_gz(a.output_dir/"transitSchedule.xml.gz",sched.getroot(),"transitSchedule")
    write_vehicle_gz(a.output_dir/"transitVehicles.xml.gz",veh.getroot())
    write_csv(a.output_dir/"bus_route_trim_qa.csv",trim); write_csv(a.output_dir/"bus_route_timing_qa.csv",timing)
    write_csv(a.output_dir/"headway_optimization_qa.csv",headways); write_csv(a.output_dir/"metro40_calibration_qa.csv",metro)
    summary={"bus_routes_trimmed":sum(r["links_before"]!=r["links_after"] for r in trim),
             "bus_links_removed":sum(r["links_before"]-r["links_after"] for r in trim),
             "bus_routes_with_index_warnings":sum(r["index_warnings"]>0 for r in trim),
             "regular_bus_routes_densified":sum(r["mode"]=="bus" and r["action"]=="densified" for r in headways),
             "metro_routes":len(metro),"metro_speed_factor":a.metro_speed_factor,
             "metro_headway_factor":a.metro_headway_factor,"profile_warnings":warnings,
             "target_metric":"metro in-vehicle plus waiting speed approximately 40 km/h; verify after simulation"}
    (a.output_dir/"transit_wait_metro40_summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__ == "__main__": main()
