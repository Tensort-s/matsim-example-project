#!/usr/bin/env python3
"""Validate the Stage 8D bundle contract without building or contacting a server."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from types import ModuleType


REPO_ROOT = Path(__file__).resolve().parents[3]
PREPARER_PATH = Path(__file__).with_name(
    "prepare_hong_kong_matsim_server_bundle.py"
)
DATA_ROOT = Path(r"F:\Matsim\matsim-example-project\data")
RELEASE_ROOT = "/mnt/DiskM/by/stage8d_contract_validation_not_deployed"


def load_preparer() -> ModuleType:
    spec = importlib.util.spec_from_file_location("stage8d_preparer", PREPARER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {PREPARER_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parameter_values(root: ET.Element) -> dict[tuple[str, str], str]:
    values: dict[tuple[str, str], str] = {}
    for module in root.findall("./module"):
        module_name = module.attrib["name"]
        for param in module.findall("./param"):
            values[(module_name, param.attrib["name"])] = param.attrib["value"]
    return values


def config_differences(source: Path, generated: Path) -> set[tuple[str, str]]:
    before = parameter_values(ET.parse(source).getroot())
    after = parameter_values(ET.parse(generated).getroot())
    if set(before) != set(after):
        raise AssertionError("Server adaptation added or removed config parameters")
    return {key for key in before if before[key] != after[key]}


def main() -> None:
    preparer = load_preparer()
    sources = preparer.current_input_sources(DATA_ROOT)
    hashes = preparer.verify_current_inputs(sources)
    config_source = sources[
        "config/config_hong_kong_5pct_v2_activity_modechoice_50it.xml"
    ]
    path_keys = {
        ("network", "inputNetworkFile"),
        ("plans", "inputPlansFile"),
        ("facilities", "inputFacilitiesFile"),
        ("vehicles", "vehiclesFile"),
        ("transit", "transitScheduleFile"),
        ("transit", "vehiclesFile"),
        ("controller", "outputDirectory"),
    }
    smoke_extra = {
        ("controller", "lastIteration"),
        ("controller", "writeEventsInterval"),
        ("controller", "writePlansInterval"),
    }
    with tempfile.TemporaryDirectory(prefix="hk-stage8d-contract-") as directory:
        temporary = Path(directory)
        formal = temporary / "formal.xml"
        smoke = temporary / "smoke.xml"
        preparer.write_server_config(
            config_source,
            formal,
            RELEASE_ROOT,
            "plans_routed_5pct_v2.xml.gz",
            "formal_50it_v1",
            50,
        )
        preparer.write_server_config(
            config_source,
            smoke,
            RELEASE_ROOT,
            "plans_smoke_0p1.xml.gz",
            "smoke_qsim_v1",
            0,
        )
        formal_differences = config_differences(config_source, formal)
        smoke_differences = config_differences(config_source, smoke)
        incomplete_jar = temporary / "old-server.jar"
        with zipfile.ZipFile(incomplete_jar, "w") as archive:
            archive.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\n")
        try:
            preparer.verify_fat_jar(incomplete_jar)
        except ValueError:
            incomplete_jar_rejected = True
        else:
            incomplete_jar_rejected = False
    if not incomplete_jar_rejected:
        raise AssertionError("An old/incomplete server JAR was accepted")
    if formal_differences != path_keys:
        raise AssertionError(
            f"Unexpected formal config differences: {formal_differences}"
        )
    if smoke_differences != path_keys | smoke_extra:
        raise AssertionError(
            f"Unexpected smoke config differences: {smoke_differences}"
        )

    active_defaults = "\n".join(
        [
            preparer.SCENARIO_RELATIVE.as_posix(),
            preparer.SUPPLY_RELATIVE.as_posix(),
            preparer.CONFIG_NAME,
            *preparer.EXPECTED_INPUT_SHA256,
        ]
    )
    stale_defaults = [
        fragment
        for fragment in preparer.STALE_ACTIVE_INPUT_FRAGMENTS
        if fragment in active_defaults
    ]
    if stale_defaults:
        raise AssertionError(f"Stale active defaults remain: {stale_defaults}")

    stale_sources = dict(sources)
    stale_sources["input/plans_routed_5pct_v2.xml.gz"] = (
        DATA_ROOT
        / "matsim_agents/hongkong/typical_weekday_5pct_v1/"
        "plans_routed_5pct.xml.gz"
    )
    try:
        preparer.verify_current_inputs(stale_sources)
    except (FileNotFoundError, ValueError):
        stale_input_rejected = True
    else:
        stale_input_rejected = False
    if not stale_input_rejected:
        raise AssertionError("A stale v1 input path was accepted")

    result = {
        "status": "passed",
        "locked_input_hashes": hashes,
        "locked_input_count": len(hashes),
        "formal_config_changed_parameters": sorted(
            ".".join(key) for key in formal_differences
        ),
        "smoke_config_changed_parameters": sorted(
            ".".join(key) for key in smoke_differences
        ),
        "formal_replanning_or_qsim_change": False,
        "stale_active_defaults": stale_defaults,
        "stale_v1_input_rejected": stale_input_rejected,
        "incomplete_server_jar_rejected": incomplete_jar_rejected,
        "server_access_performed": False,
        "bundle_built": False,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
