#!/usr/bin/env python
"""Collect AMap mobile metro arrival/headway observations via Android ADB.

This is a small, auditable helper for gap-filling metro headway data when the
public AMap Web Service does not return a usable `timedesc`.

It does *not* call private AMap APIs. It only:

1. opens/searches the AMap Android app using intents or manual navigation;
2. captures a screenshot for provenance;
3. dumps the visible Android UI hierarchy via `uiautomator`;
4. parses visible text such as "开往 万寿", "下一班8分钟", "首06:00 末22:30".

Because AMap pages differ across versions and phones, this script is designed
as semi-automatic: if opening/searching fails, run with --manual and navigate
on the phone yourself before each capture.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from urllib.parse import quote


DEFAULT_TARGETS = [
    {
        "station_name": "潘墩",
        "line_name": "地铁6号线",
        "direction_to": "万寿",
        "query": "潘墩(地铁站)",
        "notes": "6号线缺少 Web timedesc；截图示例显示下一班约 8 分钟。",
    },
    {
        "station_name": "万寿",
        "line_name": "地铁6号线",
        "direction_to": "潘墩",
        "query": "万寿(地铁站)",
        "notes": "6号线反方向缺少 Web timedesc。",
    },
    {
        "station_name": "福州火车站",
        "line_name": "滨海快线",
        "direction_to": "文岭",
        "query": "福州火车站(地铁站)",
        "notes": "滨海快线缺少 Web timedesc。",
    },
    {
        "station_name": "文岭",
        "line_name": "滨海快线",
        "direction_to": "福州火车站",
        "query": "文岭(地铁站)",
        "notes": "滨海快线反方向缺少 Web timedesc。",
    },
]


OBSERVATION_FIELDS = [
    "observation_id",
    "captured_at",
    "device_serial",
    "station_name",
    "line_name",
    "direction_to",
    "query",
    "open_method",
    "screenshot_path",
    "ui_xml_path",
    "ui_text_path",
    "current_train_status",
    "next_train_minutes",
    "estimated_headway_minutes",
    "first_train_time",
    "last_train_time",
    "parsed_line_name",
    "parsed_direction_to",
    "raw_text_compact",
    "parse_confidence",
    "needs_manual_review",
    "notes",
]


def run_adb(adb: str, args: list[str], *, serial: str | None = None, timeout: int = 30, binary: bool = False):
    cmd = [adb]
    if serial:
        cmd += ["-s", serial]
    cmd += args
    result = subprocess.run(cmd, capture_output=True, timeout=timeout)
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="ignore")
        stdout = result.stdout.decode("utf-8", errors="ignore")
        raise RuntimeError(f"ADB command failed: {' '.join(cmd)}\nSTDOUT={stdout}\nSTDERR={stderr}")
    return result.stdout if binary else result.stdout.decode("utf-8", errors="ignore")


def list_devices(adb: str) -> list[str]:
    text = run_adb(adb, ["devices"])
    serials = []
    for line in text.splitlines()[1:]:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            serials.append(parts[0])
    return serials


def adb_shell(adb: str, shell_args: list[str], *, serial: str | None = None, timeout: int = 30) -> str:
    return run_adb(adb, ["shell", *shell_args], serial=serial, timeout=timeout)


def capture_screenshot(adb: str, path: Path, *, serial: str | None = None) -> None:
    data = run_adb(adb, ["exec-out", "screencap", "-p"], serial=serial, timeout=30, binary=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def dump_ui_xml(adb: str, path: Path, *, serial: str | None = None) -> str:
    adb_shell(adb, ["uiautomator", "dump", "/sdcard/window.xml"], serial=serial, timeout=30)
    xml_text = run_adb(adb, ["exec-out", "cat", "/sdcard/window.xml"], serial=serial, timeout=30)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(xml_text, encoding="utf-8")
    return xml_text


def extract_texts_from_ui_xml(xml_text: str) -> list[str]:
    texts: list[str] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return texts
    for node in root.iter("node"):
        for attr in ("text", "content-desc"):
            value = (node.attrib.get(attr) or "").strip()
            if value and value not in texts:
                texts.append(value)
    return texts


def compact_text(texts: list[str]) -> str:
    return " | ".join(t.strip() for t in texts if t and t.strip())


def parse_time_fragment(text: str, label: str) -> str:
    # Examples: 首06:00, 首 06:00, 末22:30, 末 22:30
    pattern = rf"{label}\s*([0-2]?\d[:：]?[0-5]\d)"
    m = re.search(pattern, text)
    if not m:
        return ""
    raw = m.group(1).replace("：", ":")
    if ":" not in raw and len(raw) in {3, 4}:
        raw = raw[:-2] + ":" + raw[-2:]
    return raw


def parse_visible_metro_info(texts: list[str], target: dict[str, str]) -> dict[str, Any]:
    text = compact_text(texts)
    joined = "\n".join(texts)

    current_status = ""
    if "即将进站" in text:
        current_status = "即将进站"
    elif "终点站" in text:
        current_status = "终点站"
    elif "已进站" in text:
        current_status = "已进站"

    next_minutes = ""
    patterns = [
        r"下一班\s*([0-9]{1,3})\s*分钟",
        r"下[一1]班\s*([0-9]{1,3})\s*分",
        r"([0-9]{1,3})\s*分钟\s*(?:后|到达|进站)",
    ]
    for pattern in patterns:
        m = re.search(pattern, text)
        if m:
            next_minutes = m.group(1)
            break

    first_time = parse_time_fragment(text, "首")
    last_time = parse_time_fragment(text, "末")

    line_name = ""
    m = re.search(r"(地铁\s*[0-9一二三四五六七八九十]+号线|滨海快线)", text)
    if m:
        line_name = re.sub(r"\s+", "", m.group(1))

    direction_to = ""
    for pattern in [r"开往\s*([^\s|，,。]+)", r"往\s*([^\s|，,。]+)"]:
        m = re.search(pattern, joined)
        if m:
            direction_to = m.group(1)
            break

    score = 0
    if next_minutes:
        score += 2
    if current_status:
        score += 1
    if first_time or last_time:
        score += 1
    if line_name:
        score += 1
    if target.get("direction_to") and target["direction_to"] in text:
        score += 1
    confidence = "high" if score >= 4 else "medium" if score >= 2 else "low"

    return {
        "current_train_status": current_status,
        "next_train_minutes": next_minutes,
        "estimated_headway_minutes": next_minutes,
        "first_train_time": first_time,
        "last_train_time": last_time,
        "parsed_line_name": line_name,
        "parsed_direction_to": direction_to,
        "raw_text_compact": text,
        "parse_confidence": confidence,
        "needs_manual_review": "false" if confidence in {"high", "medium"} and next_minutes else "true",
    }


def load_targets(path: Path | None) -> list[dict[str, str]]:
    if not path:
        return list(DEFAULT_TARGETS)
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return [dict(row) for row in csv.DictReader(f)]


def write_default_targets(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["station_name", "line_name", "direction_to", "query", "notes"]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(DEFAULT_TARGETS)


def append_observations(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists() and path.stat().st_size > 0
    with path.open("a", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OBSERVATION_FIELDS)
        if not exists:
            writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in OBSERVATION_FIELDS})


def quote_uri_value(value: str) -> str:
    return quote(value, safe="")


def open_amap_for_target(
    adb: str,
    target: dict[str, str],
    *,
    serial: str | None,
    method: str,
    wait_seconds: float,
) -> str:
    query = target.get("query") or f"{target.get('station_name', '')}(地铁站)"
    if method == "none":
        return "manual_none"
    if method == "monkey":
        adb_shell(adb, ["monkey", "-p", "com.autonavi.minimap", "-c", "android.intent.category.LAUNCHER", "1"], serial=serial)
        time.sleep(wait_seconds)
        return "monkey"

    # AMap mobile URI support varies by app version. These intents are tried in
    # descending preference. If they fail silently, the script still captures
    # the current page, so --manual remains the reliable fallback.
    encoded_query = quote_uri_value(query)
    candidates = []
    if method in {"auto", "poi"}:
        candidates.append(f"androidamap://poi?sourceApplication=matsim-fuzhou&keywords={encoded_query}&dev=0")
        candidates.append(f"amapuri://poi/search?sourceApplication=matsim-fuzhou&query={encoded_query}&dev=0")
    if method in {"auto", "geo"}:
        candidates.append(f"geo:0,0?q={encoded_query}")

    last_error = ""
    for uri in candidates:
        try:
            adb_shell(
                adb,
                ["am", "start", "-a", "android.intent.action.VIEW", "-d", uri],
                serial=serial,
                timeout=20,
            )
            time.sleep(wait_seconds)
            return f"intent:{uri}"
        except Exception as exc:
            last_error = str(exc)
            continue
    raise RuntimeError(f"Could not open AMap/search intent for query={query!r}. Last error: {last_error}")


def maybe_prompt(message: str, enabled: bool) -> None:
    if enabled:
        input(message)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", default=shutil.which("adb") or "adb")
    parser.add_argument("--serial", help="ADB device serial. If omitted, the first connected device is used.")
    parser.add_argument("--targets", type=Path, help="CSV with station_name,line_name,direction_to,query,notes.")
    parser.add_argument(
        "--write-default-targets",
        type=Path,
        help="Write a starter target CSV for missing Fuzhou metro lines and exit.",
    )
    parser.add_argument("--output-dir", type=Path, default=Path("data/transit/fuzhou_metro_amap_mobile_observations"))
    parser.add_argument("--observations-csv", type=Path, help="CSV to append observations to.")
    parser.add_argument(
        "--open-method",
        choices=["auto", "poi", "geo", "monkey", "none"],
        default="auto",
        help="How to open/search AMap before capture. Use none for fully manual navigation.",
    )
    parser.add_argument("--wait-seconds", type=float, default=8.0)
    parser.add_argument(
        "--manual",
        action="store_true",
        help="Pause before each capture so you can manually open the exact station detail page.",
    )
    parser.add_argument("--repeat", type=int, default=1, help="Repeat captures per target.")
    parser.add_argument("--interval-seconds", type=float, default=60.0, help="Interval between repeats.")
    args = parser.parse_args()

    if args.write_default_targets:
        write_default_targets(args.write_default_targets)
        print(f"wrote {args.write_default_targets}")
        return

    adb = args.adb
    if not shutil.which(adb) and not Path(adb).exists():
        print(
            "ADB was not found. Install Android Platform Tools and add adb.exe to PATH, "
            "or pass --adb C:\\path\\to\\adb.exe.",
            file=sys.stderr,
        )
        sys.exit(2)

    serial = args.serial
    devices = list_devices(adb)
    if not serial:
        if not devices:
            print("No authorized Android device found. Enable USB debugging and run `adb devices`.", file=sys.stderr)
            sys.exit(2)
        serial = devices[0]
    elif serial not in devices:
        print(f"Device {serial!r} not in authorized adb devices: {devices}", file=sys.stderr)
        sys.exit(2)

    targets = load_targets(args.targets)
    output_dir = args.output_dir
    shots_dir = output_dir / "screenshots"
    xml_dir = output_dir / "ui_xml"
    text_dir = output_dir / "ui_text"
    observations_csv = args.observations_csv or output_dir / "amap_mobile_metro_arrival_observations.csv"

    rows = []
    for target_index, target in enumerate(targets, start=1):
        for repeat_index in range(1, args.repeat + 1):
            station = target.get("station_name") or target.get("query") or f"target_{target_index}"
            print(f"[{target_index}/{len(targets)} repeat {repeat_index}/{args.repeat}] target={station}")

            open_method_used = ""
            if not args.manual:
                try:
                    open_method_used = open_amap_for_target(
                        adb,
                        target,
                        serial=serial,
                        method=args.open_method,
                        wait_seconds=args.wait_seconds,
                    )
                except Exception as exc:
                    open_method_used = f"open_failed:{exc}"
                    print(open_method_used, file=sys.stderr)

            maybe_prompt(
                "Please confirm the AMap station detail page is visible on the phone, "
                "then press Enter to capture...",
                args.manual or open_method_used.startswith("open_failed"),
            )

            captured_at = dt.datetime.now().isoformat(timespec="seconds")
            obs_id = f"amap_mobile_{captured_at.replace(':','').replace('-','')}_{uuid.uuid4().hex[:8]}"
            safe_name = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff_-]+", "_", station)
            base = f"{captured_at.replace(':','').replace('-','')}_{safe_name}_{repeat_index}"
            screenshot_path = shots_dir / f"{base}.png"
            xml_path = xml_dir / f"{base}.xml"
            text_path = text_dir / f"{base}.txt"

            capture_screenshot(adb, screenshot_path, serial=serial)
            xml_text = dump_ui_xml(adb, xml_path, serial=serial)
            texts = extract_texts_from_ui_xml(xml_text)
            text_path.parent.mkdir(parents=True, exist_ok=True)
            text_path.write_text("\n".join(texts), encoding="utf-8")

            parsed = parse_visible_metro_info(texts, target)
            row = {
                "observation_id": obs_id,
                "captured_at": captured_at,
                "device_serial": serial,
                "station_name": target.get("station_name", ""),
                "line_name": target.get("line_name", ""),
                "direction_to": target.get("direction_to", ""),
                "query": target.get("query", ""),
                "open_method": open_method_used or "manual",
                "screenshot_path": str(screenshot_path),
                "ui_xml_path": str(xml_path),
                "ui_text_path": str(text_path),
                "notes": target.get("notes", ""),
                **parsed,
            }
            rows.append(row)
            append_observations(observations_csv, [row])
            print(json.dumps({k: row.get(k) for k in OBSERVATION_FIELDS if k not in {"raw_text_compact"}}, ensure_ascii=False, indent=2))

            if repeat_index < args.repeat:
                time.sleep(args.interval_seconds)

    summary = {
        "device_serial": serial,
        "targets": len(targets),
        "observations": len(rows),
        "observations_csv": str(observations_csv),
        "output_dir": str(output_dir),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "amap_mobile_observation_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
