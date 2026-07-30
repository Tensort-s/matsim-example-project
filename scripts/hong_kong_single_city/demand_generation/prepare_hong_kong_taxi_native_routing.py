#!/usr/bin/env python3
"""Create versioned Hong Kong Taxi plans/config for native Taxi routing.

The input Taxi plans are never overwritten. Every Taxi leg keeps mode=taxi,
changes routingMode from ride to taxi, and copies the six Taxi metadata values
to the trip's origin main activity. MATSim PlanRouter uses those activity
attributes as trip attributes, allowing the native Taxi routing module to copy
them back to its newly routed Taxi leg.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

from lxml import etree as ET


TAXI_ATTRIBUTES = (
    "hkTaxiFareBaselineHkd",
    "hkTaxiType",
    "hkTaxiFareScope",
    "hkTaxiFareModelVersion",
    "hkTaxiClassificationSource",
    "hkTaxiMainTripIndex",
)
EXPECTED_CLASSES = {
    "hkTaxiFareBaselineHkd": "java.lang.Double",
    "hkTaxiType": "java.lang.String",
    "hkTaxiFareScope": "java.lang.String",
    "hkTaxiFareModelVersion": "java.lang.String",
    "hkTaxiClassificationSource": "java.lang.String",
    "hkTaxiMainTripIndex": "java.lang.Integer",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-plans", type=Path, required=True)
    parser.add_argument("--base-config", type=Path, required=True)
    parser.add_argument("--output-plans", type=Path, required=True)
    parser.add_argument("--output-config", type=Path, required=True)
    parser.add_argument("--validation-json", type=Path, required=True)
    parser.add_argument(
        "--runtime-plans-path",
        required=True,
        help="Plans path written into the versioned MATSim config.",
    )
    parser.add_argument("--expected-taxi-count", type=int, default=37_286)
    return parser.parse_args()


def fail(message: str) -> None:
    raise RuntimeError(message)


def local_name(element: ET._Element) -> str:
    return ET.QName(element).localname


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def direct_children(
    element: ET._Element, name: str
) -> list[ET._Element]:
    return [child for child in element if local_name(child) == name]


def named_attributes(element: ET._Element) -> dict[str, ET._Element]:
    blocks = direct_children(element, "attributes")
    if len(blocks) > 1:
        fail(f"Multiple direct attributes blocks on {local_name(element)}")
    if not blocks:
        return {}
    result: dict[str, ET._Element] = {}
    for attribute in direct_children(blocks[0], "attribute"):
        name = attribute.get("name", "")
        if not name or name in result:
            fail(f"Missing or duplicate named attribute: {name!r}")
        result[name] = attribute
    return result


def ensure_attributes_block(element: ET._Element) -> ET._Element:
    blocks = direct_children(element, "attributes")
    if len(blocks) > 1:
        fail(f"Multiple direct attributes blocks on {local_name(element)}")
    if blocks:
        return blocks[0]
    block = ET.Element("attributes")
    element.insert(0, block)
    return block


def activity_signature(activity: ET._Element) -> str:
    fields = (
        activity.get("type", ""),
        activity.get("x", ""),
        activity.get("y", ""),
        activity.get("link", ""),
        activity.get("facility", ""),
    )
    return "\x1f".join(fields)


def selected_plan(person: ET._Element) -> ET._Element:
    plans = direct_children(person, "plan")
    selected = [plan for plan in plans if plan.get("selected") == "yes"]
    if len(selected) == 1:
        return selected[0]
    if len(plans) == 1:
        return plans[0]
    fail(
        f"Selected plan is not unique for person {person.get('id', '')}: "
        f"{len(selected)} selected / {len(plans)} total"
    )


def taxi_trips(
    person: ET._Element,
) -> list[tuple[int, ET._Element, ET._Element, ET._Element]]:
    plan = selected_plan(person)
    main_origin: ET._Element | None = None
    pending: list[ET._Element] = []
    main_trip_index = 0
    result: list[
        tuple[int, ET._Element, ET._Element, ET._Element]
    ] = []
    for element in plan:
        name = local_name(element)
        if name == "leg":
            pending.append(element)
            continue
        if name != "activity":
            continue
        if element.get("type", "").endswith(" interaction"):
            continue
        if main_origin is None:
            main_origin = element
            continue
        taxi_legs = [
            leg for leg in pending if leg.get("mode", "") == "taxi"
        ]
        if taxi_legs:
            if len(taxi_legs) != 1 or len(pending) != 1:
                fail(
                    "Taxi trip must contain exactly one Taxi leg and no "
                    f"stage legs: person={person.get('id', '')}, "
                    f"main_trip_index={main_trip_index}"
                )
            result.append(
                (main_trip_index, main_origin, taxi_legs[0], element)
            )
        main_origin = element
        pending = []
        main_trip_index += 1
    return result


def fingerprint_taxi_trip(
    person_id: str,
    main_trip_index: int,
    origin: ET._Element,
    destination: ET._Element,
) -> bytes:
    return (
        f"{person_id}\x1e{main_trip_index}\x1e"
        f"{activity_signature(origin)}\x1e"
        f"{activity_signature(destination)}\n"
    ).encode("utf-8")


def mutate_person(
    person: ET._Element,
    od_hasher: Any,
    routing_before: Counter[str],
) -> int:
    count = 0
    person_id = person.get("id", "")
    for main_index, origin, leg, destination in taxi_trips(person):
        leg_attributes = named_attributes(leg)
        missing = set(TAXI_ATTRIBUTES) - set(leg_attributes)
        if missing:
            fail(
                f"Taxi leg metadata missing for {person_id}/{main_index}: "
                f"{sorted(missing)}"
            )
        routing = leg_attributes.get("routingMode")
        if routing is None:
            fail(
                f"Taxi routingMode missing for {person_id}/{main_index}"
            )
        routing_value = (routing.text or "").strip()
        routing_before[routing_value] += 1
        if routing_value not in {"ride", "taxi"}:
            fail(
                f"Unexpected Taxi routingMode={routing_value!r} for "
                f"{person_id}/{main_index}"
            )
        routing.set("class", "java.lang.String")
        routing.text = "taxi"

        origin_named = named_attributes(origin)
        conflicts = set(TAXI_ATTRIBUTES) & set(origin_named)
        if conflicts:
            fail(
                f"Origin activity already has Taxi trip attributes for "
                f"{person_id}/{main_index}: {sorted(conflicts)}"
            )
        block = ensure_attributes_block(origin)
        for name in TAXI_ATTRIBUTES:
            source = leg_attributes[name]
            expected_class = EXPECTED_CLASSES[name]
            if source.get("class") != expected_class:
                fail(
                    f"Taxi attribute class mismatch for {person_id}/"
                    f"{main_index}/{name}: {source.get('class')!r}"
                )
            clone = ET.SubElement(
                block,
                "attribute",
                name=name,
                **{"class": expected_class},
            )
            clone.text = source.text

        od_hasher.update(
            fingerprint_taxi_trip(
                person_id, main_index, origin, destination
            )
        )
        count += 1
    return count


def source_doctype(path: Path) -> str:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        prefix = handle.read(2048)
    match = re.search(r"<!DOCTYPE\s+[^>]+>", prefix)
    if not match:
        fail("Source plans DOCTYPE was not found")
    return match.group(0)


def clear_top_level(element: ET._Element) -> None:
    parent = element.getparent()
    element.clear()
    if parent is not None:
        while element.getprevious() is not None:
            del parent[0]


def transform_plans(
    source: Path, output: Path
) -> dict[str, Any]:
    routing_before: Counter[str] = Counter()
    od_hasher = hashlib.sha256()
    taxi_count = 0
    with gzip.open(source, "rb") as source_gzip:
        context = ET.iterparse(
            source_gzip, events=("start", "end"), huge_tree=True
        )
        event, root = next(context)
        if event != "start" or local_name(root) != "population":
            fail("Population root start event was not found")
        with output.open("wb") as output_raw:
            with gzip.GzipFile(
                fileobj=output_raw,
                mode="wb",
                compresslevel=6,
                mtime=0,
            ) as output_gzip:
                with ET.xmlfile(output_gzip, encoding="utf-8") as writer:
                    writer.write_declaration()
                    writer.write_doctype(source_doctype(source))
                    with writer.element(root.tag, root.attrib):
                        for event, element in context:
                            if (
                                event != "end"
                                or element.getparent() is not root
                            ):
                                continue
                            if local_name(element) == "person":
                                taxi_count += mutate_person(
                                    element, od_hasher, routing_before
                                )
                            writer.write(element)
                            clear_top_level(element)
    return {
        "taxi_count": taxi_count,
        "taxi_routing_mode_counts_before": dict(
            sorted(routing_before.items())
        ),
        "taxi_od_fingerprint_sha256": od_hasher.hexdigest(),
    }


def audit_plans(path: Path) -> dict[str, Any]:
    taxi_count = 0
    mode_counts: Counter[str] = Counter()
    routing_counts: Counter[str] = Counter()
    trip_attribute_sets = 0
    od_hasher = hashlib.sha256()
    with gzip.open(path, "rb") as handle:
        context = ET.iterparse(handle, events=("end",), huge_tree=True)
        for _, person in context:
            if local_name(person) != "person":
                continue
            person_id = person.get("id", "")
            for main_index, origin, leg, destination in taxi_trips(person):
                taxi_count += 1
                leg_named = named_attributes(leg)
                routing = leg_named.get("routingMode")
                routing_counts[
                    "<missing>"
                    if routing is None
                    else (routing.text or "").strip()
                ] += 1
                if set(TAXI_ATTRIBUTES).issubset(
                    named_attributes(origin)
                ):
                    trip_attribute_sets += 1
                od_hasher.update(
                    fingerprint_taxi_trip(
                        person_id, main_index, origin, destination
                    )
                )
            plan = selected_plan(person)
            for leg in direct_children(plan, "leg"):
                mode_counts[leg.get("mode", "")] += 1
            clear_top_level(person)
    return {
        "taxi_count": taxi_count,
        "mode_counts": dict(sorted(mode_counts.items())),
        "taxi_routing_mode_counts": dict(
            sorted(routing_counts.items())
        ),
        "taxi_trip_attribute_sets": trip_attribute_sets,
        "taxi_od_fingerprint_sha256": od_hasher.hexdigest(),
    }


def transform_config(
    source: Path, output: Path, runtime_plans_path: str
) -> dict[str, Any]:
    parser = ET.XMLParser(remove_blank_text=False)
    tree = ET.parse(str(source), parser)
    root = tree.getroot()
    plans_modules = [
        module
        for module in direct_children(root, "module")
        if module.get("name") == "plans"
    ]
    if len(plans_modules) != 1:
        fail(f"Expected one plans module, found {len(plans_modules)}")
    plans_params = [
        param
        for param in direct_children(plans_modules[0], "param")
        if param.get("name") == "inputPlansFile"
    ]
    if len(plans_params) != 1:
        fail(
            "Expected one plans/inputPlansFile parameter, found "
            f"{len(plans_params)}"
        )
    old_plans_path = plans_params[0].get("value", "")
    plans_params[0].set("value", runtime_plans_path)
    tree.write(
        str(output),
        encoding="utf-8",
        xml_declaration=True,
        doctype=tree.docinfo.doctype or None,
        pretty_print=False,
    )

    qsim_main_modes: list[str] = []
    routing_network_modes: list[str] = []
    module_names: list[str] = []
    for module in direct_children(root, "module"):
        name = module.get("name", "")
        module_names.append(name)
        for param in direct_children(module, "param"):
            if name == "qsim" and param.get("name") == "mainMode":
                qsim_main_modes.extend(
                    part.strip()
                    for part in param.get("value", "").split(",")
                    if part.strip()
                )
            if (
                name == "routing"
                and param.get("name") == "networkModes"
            ):
                routing_network_modes.extend(
                    part.strip()
                    for part in param.get("value", "").split(",")
                    if part.strip()
                )
    forbidden_modules = [
        name
        for name in module_names
        if any(
            token in name.lower()
            for token in ("dvrp", "fleet", "multimodetaxi")
        )
    ]
    return {
        "old_plans_path": old_plans_path,
        "new_plans_path": runtime_plans_path,
        "qsim_main_modes": qsim_main_modes,
        "routing_network_modes": routing_network_modes,
        "forbidden_modules": forbidden_modules,
    }


def main() -> None:
    args = parse_args()
    input_plans = args.input_plans.resolve()
    base_config = args.base_config.resolve()
    outputs = [
        args.output_plans.resolve(),
        args.output_config.resolve(),
        args.validation_json.resolve(),
    ]
    for source in (input_plans, base_config):
        if not source.is_file():
            fail(f"Input file does not exist: {source}")
    if len(set(outputs)) != len(outputs):
        fail("Output paths must be distinct")
    for output in outputs:
        if output.exists():
            fail(f"Output already exists: {output}")
        output.parent.mkdir(parents=True, exist_ok=True)

    temporary: list[Path] = []
    try:
        for output in outputs[:2]:
            handle = tempfile.NamedTemporaryFile(
                prefix=output.name + ".",
                suffix=".tmp",
                dir=output.parent,
                delete=False,
            )
            handle.close()
            temporary.append(Path(handle.name))
        transformed = transform_plans(input_plans, temporary[0])
        audited = audit_plans(temporary[0])
        config_audit = transform_config(
            base_config, temporary[1], args.runtime_plans_path
        )
        checks = {
            "taxi_count_exact": (
                transformed["taxi_count"]
                == audited["taxi_count"]
                == args.expected_taxi_count
            ),
            "taxi_od_unchanged": (
                transformed["taxi_od_fingerprint_sha256"]
                == audited["taxi_od_fingerprint_sha256"]
            ),
            "output_mode_taxi_exact": (
                audited["mode_counts"].get("taxi", 0)
                == args.expected_taxi_count
            ),
            "output_routing_mode_taxi_exact": (
                audited["taxi_routing_mode_counts"]
                == {"taxi": args.expected_taxi_count}
            ),
            "taxi_trip_attributes_complete": (
                audited["taxi_trip_attribute_sets"]
                == args.expected_taxi_count
            ),
            "taxi_not_qsim_main_mode": (
                "taxi" not in config_audit["qsim_main_modes"]
            ),
            "taxi_not_network_mode": (
                "taxi" not in config_audit["routing_network_modes"]
            ),
            "no_dvrp_or_fleet_config": (
                not config_audit["forbidden_modules"]
            ),
            "runtime_plans_path_exact": (
                config_audit["new_plans_path"]
                == args.runtime_plans_path
            ),
        }
        if not all(checks.values()):
            fail(
                "Native Taxi conversion validation failed: "
                + ", ".join(
                    name for name, passed in checks.items() if not passed
                )
            )
        temporary[0].replace(outputs[0])
        temporary[1].replace(outputs[1])
        temporary.clear()
        validation = {
            "audit": "hong_kong_taxi_native_routing_v1",
            "status": "validated",
            "all_checks_passed": True,
            "checks": checks,
            "input_plans": {
                "path": input_plans.as_posix(),
                "sha256": sha256(input_plans),
            },
            "output_plans": {
                "path": outputs[0].as_posix(),
                "sha256": sha256(outputs[0]),
            },
            "base_config": {
                "path": base_config.as_posix(),
                "sha256": sha256(base_config),
            },
            "output_config": {
                "path": outputs[1].as_posix(),
                "sha256": sha256(outputs[1]),
            },
            "transformation": transformed,
            "output_audit": audited,
            "config_audit": config_audit,
        }
        with outputs[2].open(
            "w", encoding="utf-8", newline="\n"
        ) as handle:
            json.dump(validation, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        print(json.dumps(validation, ensure_ascii=False, indent=2))
    finally:
        for path in temporary:
            if path.exists():
                path.unlink()


if __name__ == "__main__":
    main()
