#!/usr/bin/env python3
"""Build the run8-baseline Hong Kong all-expressed 96-bin TOD signal proxy."""

from __future__ import annotations

import argparse
from pathlib import Path

from build_hong_kong_traffic_signal_tod_proxy_top100 import REPO_ROOT, build


DEFAULT_STAGE1 = REPO_ROOT / (
    "data/transit/hongkong/processed/"
    "hong_kong_traffic_signals_2026_v3_tpdm_proxy_stage1_road_hotspot_v1_candidate8"
)
DEFAULT_NETWORK = REPO_ROOT / (
    "data/transit/hongkong/processed/"
    "hong_kong_road_hotspot_v1_materialized_candidate8/network.xml.gz"
)
DEFAULT_OUTPUT = REPO_ROOT / (
    "data/transit/hongkong/processed/"
    "hong_kong_traffic_signals_2026_v3_tod_proxy_all_expressed_road_hotspot_v1_candidate9"
)
DEFAULT_STAGE_OVERRIDES = REPO_ROOT / "cities/hongkong/traffic_signal_priority_junction_overrides_v1.csv"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage1-dir", type=Path, default=DEFAULT_STAGE1)
    parser.add_argument("--network", type=Path, default=DEFAULT_NETWORK)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--stage-overrides", type=Path, default=DEFAULT_STAGE_OVERRIDES)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.selection_scope = "all_expressed"
    args.junction_count = 1
    summary = build(args)
    print(
        f"Built {summary['junction_count']:,} systems and "
        f"{summary['plan_count']:,} fixed 15-minute plans in {args.output_dir}"
    )


if __name__ == "__main__":
    main()
