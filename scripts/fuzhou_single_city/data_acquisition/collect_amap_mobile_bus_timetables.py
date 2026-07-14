#!/usr/bin/env python
"""Collect AMap mobile bus timetables through ADB + UIAutomator XML.

The script reads AMap app UI text directly with ``uiautomator dump``. It does
not use OCR. It is designed for the bus timetable information that the public
AMap Web Service often does not expose:

- query routes with a Fuzhou prefix, e.g. ``福州公交1路`` instead of ``1路``;
- collect both visible directions in the mobile timetable panel;
- expand normal "全天时刻表" time sections;
- preserve irregular textual timetable rules, e.g. ``06:10-09:00 首站发车约20分钟/趟``.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_LINES = PROJECT_ROOT / "data" / "transit" / "fuzhou_bus_amap_stopid_lineid" / "amap_bus_lines_full.csv"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "transit" / "fuzhou_bus_amap_mobile_timetables"
AMAP_PACKAGE = "com.autonavi.minimap"

TIME_RE = re.compile(r"^\d{2}:\d{2}$")
PERIOD_RE = re.compile(r"^(\d{2}:\d{2})[-–](\d{2}:\d{2})$")
# AMap route labels are not limited to "xx路": examples include 夜班2号线,
# 地铁接驳27号专线, 20路夜间区间车, 高峰快线1路, 马尾快线2号线, etc.
LINE_NAME_RE = re.compile(
    r"^(?:"
    r"[A-Za-z]?\d+[A-Za-z]?路(?:夜间区间车|区间车|快线|支线)?"
    r"|城巴\d+路"
    r"|夜班\d+号线"
    r"|地铁接驳\d+号专线"
    r"|高峰快线\d+路"
    r"|马尾快线\d+号线"
    r"|通勤快线\d+路"
    r"|旅游专线\d*号?"
    r"|.*(?:专线|号线|区间车|夜间区间车|快线|支线)"
    r")$"
)
HEADWAY_RE = re.compile(r"约?\s*(\d+)\s*分钟\s*/?\s*趟")
PERIOD_IN_TEXT_RE = re.compile(r"(\d{2}:\d{2})[-–](\d{2}:\d{2})")


@dataclass
class UiNode:
    text: str
    desc: str
    rid: str
    cls: str
    bounds: str
    x1: int
    y1: int
    x2: int
    y2: int

    @property
    def label(self) -> str:
        return self.text or self.desc

    @property
    def cx(self) -> int:
        return (self.x1 + self.x2) // 2

    @property
    def cy(self) -> int:
        return (self.y1 + self.y2) // 2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", default="adb")
    parser.add_argument("--input-lines", type=Path, default=DEFAULT_INPUT_LINES)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--line-query", action="append", default=[], help="Line query to test, e.g. 1路 or K1路. Repeatable.")
    parser.add_argument("--max-lines", type=int, default=0, help="Use first N unique line names from input when --line-query is absent.")
    parser.add_argument("--current-only", action="store_true", help="Extract timetable from the current phone page without navigation.")
    parser.add_argument("--max-scrolls", type=int, default=5)
    parser.add_argument("--sleep", type=float, default=1.2)
    parser.add_argument("--save-screenshots", action="store_true")
    parser.add_argument("--force-stop-between-lines", action="store_true", default=True)
    parser.add_argument("--collect-both-directions", action="store_true", default=True)
    parser.add_argument("--flush-each-line", action="store_true", default=True, help="Write CSV/JSON outputs after every processed line.")
    parser.add_argument("--resume", action="store_true", help="Load existing output CSVs and skip lines already completed with status=ok.")
    parser.add_argument(
        "--capture-only",
        action="store_true",
        help="Drive the phone and save XML snapshots/manifests only; skip heavy timetable parsing until --parse-captures-only.",
    )
    parser.add_argument(
        "--parse-captures-only",
        action="store_true",
        help="Parse previously captured XML manifests in --output-dir without touching the phone.",
    )
    parser.add_argument(
        "--search-entry",
        choices=["manual", "uri", "auto"],
        default="auto",
        help="How to enter the line search. auto tries URI first, then manual input when possible.",
    )
    return parser.parse_args()


def run_adb(args: argparse.Namespace, parts: list[str], timeout: int = 30, check: bool = False) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        [args.adb, *parts],
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(f"adb {' '.join(parts)} failed: {proc.stderr.strip() or proc.stdout.strip()}")
    return proc


def ensure_device(args: argparse.Namespace) -> str:
    proc = run_adb(args, ["devices", "-l"], timeout=20)
    lines = [line.strip() for line in proc.stdout.splitlines() if line.strip() and not line.startswith("List of")]
    devices = [line for line in lines if "\tdevice" in line or " device " in line]
    if not devices:
        raise RuntimeError(f"No authorized adb device found. adb devices output:\n{proc.stdout}\n{proc.stderr}")
    return devices[0]


def parse_bounds(bounds: str) -> tuple[int, int, int, int]:
    nums = [int(x) for x in re.findall(r"\d+", bounds or "")]
    if len(nums) != 4:
        return 0, 0, 0, 0
    return nums[0], nums[1], nums[2], nums[3]


def dump_ui(args: argparse.Namespace, local_path: Path, timeout: int = 60) -> list[UiNode]:
    local_path.parent.mkdir(parents=True, exist_ok=True)
    remote = "/sdcard/amap_mobile_timetable_dump.xml"
    proc = run_adb(args, ["shell", "uiautomator", "dump", remote], timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip())
    run_adb(args, ["pull", remote, str(local_path)], timeout=timeout, check=True)
    return parse_ui_xml(local_path)


def parse_ui_xml(local_path: Path) -> list[UiNode]:
    root = ET.parse(local_path).getroot()
    nodes: list[UiNode] = []
    for node in root.iter("node"):
        text = node.attrib.get("text", "")
        desc = node.attrib.get("content-desc", "")
        if not text and not desc:
            continue
        x1, y1, x2, y2 = parse_bounds(node.attrib.get("bounds", ""))
        nodes.append(
            UiNode(
                text=text,
                desc=desc,
                rid=node.attrib.get("resource-id", ""),
                cls=node.attrib.get("class", ""),
                bounds=node.attrib.get("bounds", ""),
                x1=x1,
                y1=y1,
                x2=x2,
                y2=y2,
            )
        )
    nodes.sort(key=lambda n: (n.y1, n.x1, n.y2, n.x2))
    return nodes


def tap(args: argparse.Namespace, x: int, y: int, sleep: float | None = None) -> None:
    run_adb(args, ["shell", "input", "tap", str(x), str(y)], timeout=10)
    time.sleep(args.sleep if sleep is None else sleep)


def swipe(args: argparse.Namespace, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 700) -> None:
    run_adb(args, ["shell", "input", "swipe", str(x1), str(y1), str(x2), str(y2), str(duration_ms)], timeout=20)
    time.sleep(args.sleep)


def keyevent(args: argparse.Namespace, code: str | int, sleep: float | None = None) -> None:
    run_adb(args, ["shell", "input", "keyevent", str(code)], timeout=10)
    time.sleep(args.sleep if sleep is None else sleep)


def set_clipboard_and_paste(args: argparse.Namespace, text: str) -> None:
    proc = run_adb(args, ["shell", "cmd", "clipboard", "set", "text", text], timeout=10)
    output = f"{proc.stdout}\n{proc.stderr}"
    if proc.returncode != 0 or "No shell command implementation" in output:
        raise RuntimeError(
            "This Android ROM does not expose `cmd clipboard`; Chinese text cannot be pasted "
            "through adb clipboard. Use --search-entry uri, or install an ADB keyboard input bridge."
        )
    time.sleep(0.3)
    keyevent(args, 279, sleep=0.6)


def find_node(nodes: list[UiNode], predicate) -> UiNode | None:
    for node in nodes:
        if predicate(node):
            return node
    return None


def clean_label(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", str(text or ""))
    text = text.replace("\u200b", "").strip()
    return re.sub(r"\s+", "", text)


def base_line_name(query: str) -> str:
    q = clean_label(query)
    q = re.sub(r"^福州公交", "", q)
    q = re.sub(r"[（(].*", "", q)
    if re.fullmatch(r"[A-Za-z]?\d+[A-Za-z]?", q) or re.fullmatch(r"城巴\d+", q):
        q = f"{q}路"
    return q


def build_search_phrase(query: str) -> tuple[str, str, list[str]]:
    line = base_line_name(query)
    # Use the complete crawled route name directly, e.g.
    # "309路(雁头路东--尤溪洲(东)停车场)". Adding "福州公交" caused AMap to
    # over-generalize some numeric routes, e.g. matching 福清309路.
    phrase = clean_label(query)
    return phrase, line, [line, clean_label(query), phrase]


def is_route_label(label: str) -> bool:
    label = clean_label(label)
    if not label:
        return False
    if LINE_NAME_RE.match(label):
        return True
    return any(
        token in label
        for token in ["专线", "号线", "区间车", "夜间区间车", "快线", "支线", "接驳"]
    ) and not any(
        token in label
        for token in ["公交站", "地铁站", "火车站", "广场", "总站", "枢纽站"]
    )


def clear_text_field(args: argparse.Namespace, presses: int = 40) -> None:
    keyevent(args, 123, sleep=0.1)
    for _ in range(presses):
        run_adb(args, ["shell", "input", "keyevent", "67"], timeout=5)
    time.sleep(0.3)


def enter_search_query(args: argparse.Namespace, query: str) -> tuple[str, str, list[str]]:
    phrase, line, labels = build_search_phrase(query)
    clear_text_field(args)
    set_clipboard_and_paste(args, phrase)
    return phrase, line, labels


def open_keyword_search_uri(args: argparse.Namespace, query: str) -> tuple[str, str]:
    """Open AMap search with a fully-qualified Fuzhou query.

    AMap's documented `androidamap://poi?...&keywords=...` and Android's
    generic `geo:0,0?q=...` both open the app search page without typing into
    the custom search field. We use a quoted remote-shell command so `&` does
    not get interpreted by `/system/bin/sh`.
    """
    phrase, line, _ = build_search_phrase(query)
    encoded = quote(phrase, safe="")
    uri = f"geo:0,0?q={encoded}"
    run_adb(args, ["shell", f"am force-stop {AMAP_PACKAGE}; am start -a android.intent.action.VIEW -p {AMAP_PACKAGE} -d '{uri}'"], timeout=30, check=True)
    time.sleep(5.0)
    return phrase, line


def focus_visible_search_input(args: argparse.Namespace, out_dir: Path) -> None:
    nodes = dump_ui(args, out_dir / "search_input_focus.xml")
    input_node = find_node(nodes, lambda n: "请输入内容" in n.label or (180 <= n.x1 <= 260 and 150 <= n.y1 <= 280))
    if input_node:
        tap(args, input_node.cx, input_node.cy, sleep=0.5)


def tap_search_button(args: argparse.Namespace, out_dir: Path) -> None:
    nodes = dump_ui(args, out_dir / "search_before_submit.xml")
    btn = find_node(nodes, lambda n: clean_label(n.label) == "搜索" and n.x1 > 850 and n.y1 < 520)
    if btn:
        tap(args, btn.cx, btn.cy, sleep=3.0)
    else:
        keyevent(args, 66, sleep=3.0)


def launch_amap_home(args: argparse.Namespace, out_dir: Path) -> list[UiNode]:
    if args.force_stop_between_lines:
        run_adb(args, ["shell", "input", "keyevent", "3"], timeout=10)
        time.sleep(0.5)
        run_adb(args, ["shell", "am", "force-stop", AMAP_PACKAGE], timeout=10)
        time.sleep(1.0)
    run_adb(args, ["shell", "monkey", "-p", AMAP_PACKAGE, "-c", "android.intent.category.LAUNCHER", "1"], timeout=20)
    time.sleep(5.0)
    nodes: list[UiNode] = []
    for attempt in range(6):
        nodes = dump_ui(args, out_dir / f"home_attempt_{attempt}.xml")
        if find_node(nodes, lambda n: "maphome_searchbar_bg" in n.rid or "搜索" in n.label or "查找地点" in n.label):
            return nodes
        keyevent(args, 4, sleep=1.0)
    return nodes


def open_line_schedule(args: argparse.Namespace, query: str, out_dir: Path) -> tuple[bool, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    if args.search_entry in {"uri", "auto"}:
        try:
            search_phrase, expected_line = open_keyword_search_uri(args, query)
            ok, message = open_schedule_from_visible_results(args, expected_line, out_dir, search_phrase)
            if ok or args.search_entry == "uri":
                return ok, message
        except Exception as exc:  # noqa: BLE001
            if args.search_entry == "uri":
                return False, f"uri_search_failed_for_query={query}: {exc}"

    nodes = launch_amap_home(args, out_dir)
    search = find_node(nodes, lambda n: "maphome_searchbar_bg" in n.rid or "搜索" in n.label or "查找地点" in n.label)
    if not search:
        return False, "search_bar_not_found"
    tap(args, search.cx, search.cy, sleep=1.0)
    focus_visible_search_input(args, out_dir)
    search_phrase, expected_line, _ = enter_search_query(args, query)
    tap_search_button(args, out_dir)

    for attempt in range(7):
        nodes = dump_ui(args, out_dir / f"search_result_{attempt}.xml")
        candidates = []
        for n in nodes:
            label = clean_label(n.label)
            if n.y1 <= 150 or n.y2 >= 2600:
                continue
            if expected_line and expected_line in label:
                candidates.append(n)
        if candidates:
            target = sorted(candidates, key=lambda n: (n.y1, n.x1))[0]
            tap(args, target.cx, target.cy, sleep=4.0)
            nodes_after_tap = dump_ui(args, out_dir / f"search_result_after_tap_{attempt}.xml")
            if any("请输入内容" in n.label for n in nodes_after_tap):
                tap_search_button(args, out_dir)
            break
        time.sleep(1.0)

    for attempt in range(8):
        nodes = dump_ui(args, out_dir / f"line_detail_{attempt}.xml")
        schedule_nodes = [n for n in nodes if "发车时刻表" in n.text]
        if schedule_nodes:
            target = sorted(schedule_nodes, key=lambda n: n.y1, reverse=True)[0]
            tap(args, target.cx, target.cy, sleep=2.0)
            return True, f"opened_schedule;search_phrase={search_phrase}"
        line_candidates = [n for n in nodes if expected_line in clean_label(n.label) and n.y1 > 150]
        if line_candidates:
            target = sorted(line_candidates, key=lambda n: (n.y1, n.x1))[0]
            tap(args, target.cx, target.cy, sleep=3.0)
            continue
        keyevent(args, 66, sleep=2.0)
    return False, f"schedule_button_not_found_for_query={query};search_phrase={search_phrase}"


def open_schedule_from_visible_results(args: argparse.Namespace, expected_line: str, out_dir: Path, search_phrase: str) -> tuple[bool, str]:
    """Try to reach a line schedule from the current AMap result page.

    This covers URI-opened result pages and manual search result pages. Some
    AMap versions return bus-stop POI cards first; for those we tap visible
    line chips and then look for the line schedule button. If a route cannot be
    opened from the POI cards, the caller may fall back to manual input.
    """
    for attempt in range(8):
        nodes = dump_ui(args, out_dir / f"visible_result_{attempt}.xml")
        if dismiss_optional_popups(args, nodes):
            continue
        schedule_nodes = [n for n in nodes if "发车时刻表" in n.text]
        if schedule_nodes:
            target = sorted(schedule_nodes, key=lambda n: n.y1, reverse=True)[0]
            tap(args, target.cx, target.cy, sleep=2.0)
            return True, f"opened_schedule;search_phrase={search_phrase};entry=visible_result"
        route_result_nodes = route_result_candidates(nodes, expected_line, search_phrase)
        if route_result_nodes:
            target = sorted(route_result_nodes, key=lambda n: (n.y1, n.x1))[0]
            tap(args, target.cx, target.cy, sleep=3.0)
            continue
        clicked_from_stop, stop_message = try_click_line_direction_from_bus_stop_card(
            args,
            nodes,
            expected_line,
            out_dir,
            attempt,
        )
        if clicked_from_stop:
            continue
        if stop_message == "target_line_not_found_in_bus_stop_card":
            return False, f"target_line_not_found_in_bus_stop_card_after_scroll;search_phrase={search_phrase};expected_line={expected_line}"
        exact_line_nodes = [
            n
            for n in nodes
            if clean_label(n.label) == expected_line
            and 650 < n.y1 < 2550
        ]
        if exact_line_nodes:
            # Prefer a standalone route result/chip over text in the top bar.
            target = sorted(exact_line_nodes, key=lambda n: (n.y1, n.x1))[0]
            tap(args, target.cx, target.cy, sleep=3.0)
            continue
        fuzzy_line_nodes = [
            n
            for n in nodes
            if expected_line in clean_label(n.label)
            and 650 < n.y1 < 2550
            and "公交站" not in clean_label(n.label)
        ]
        if fuzzy_line_nodes:
            target = sorted(fuzzy_line_nodes, key=lambda n: (n.y1, n.x1))[0]
            tap(args, target.cx, target.cy, sleep=3.0)
            continue
        time.sleep(1.0)
    return False, f"schedule_button_not_found_from_visible_results;search_phrase={search_phrase}"


def route_result_candidates(nodes: list[UiNode], expected_line: str, search_phrase: str) -> list[UiNode]:
    """Prefer visible route result cards before falling back to bus-stop cards."""
    candidates: list[UiNode] = []
    full_query = clean_label(search_phrase)
    base = clean_label(expected_line)
    for node in nodes:
        label = clean_label(node.label)
        if not label or not (450 < node.y1 < 2550):
            continue
        if label == full_query:
            candidates.append(node)
            continue
        if base and label == base:
            candidates.append(node)
            continue
        if base and label.startswith(f"{base}("):
            candidates.append(node)
            continue
        if full_query and full_query in label and base and base in label:
            candidates.append(node)
            continue
    return candidates


def dismiss_optional_popups(args: argparse.Namespace, nodes: list[UiNode]) -> bool:
    for label in ["稍后再说", "我知道了", "取消"]:
        node = find_node(nodes, lambda n, label=label: clean_label(n.label) == label)
        if node:
            tap(args, node.cx, node.cy, sleep=1.0)
            return True
    return False


def has_bus_stop_card_context(nodes: list[UiNode]) -> bool:
    labels = [clean_label(n.label) for n in nodes if clean_label(n.label)]
    return any(
        ("途经线路" in label)
        or ("公交站" in label)
        or ("上车站" in label)
        or ("下车站" in label)
        for label in labels
    )


def try_click_line_direction_from_bus_stop_card(
    args: argparse.Namespace,
    nodes: list[UiNode],
    expected_line: str,
    out_dir: Path,
    attempt: int,
    *,
    max_card_scrolls: int = 2,
) -> tuple[bool, str]:
    """Find a target route inside a bus-stop POI card with bounded scrolling.

    Some searches open a bus-stop card first. The target route may be hidden
    below the visible area under "途经线路". We therefore scan the current card,
    scroll the card a small number of times, then give up quickly instead of
    getting stuck on a stop that does not serve the requested line.
    """
    current_nodes = nodes
    if not has_bus_stop_card_context(current_nodes):
        return False, "not_bus_stop_card"
    for card_scroll in range(max_card_scrolls + 1):
        if click_line_direction_from_bus_stop_card(args, current_nodes, expected_line):
            return True, f"clicked_bus_stop_card_scroll_{card_scroll}"
        if card_scroll >= max_card_scrolls:
            return False, "target_line_not_found_in_bus_stop_card"
        swipe(args, 640, 2440, 640, 1340, duration_ms=550)
        current_nodes = dump_ui(args, out_dir / f"visible_result_{attempt}_bus_stop_scroll_{card_scroll + 1}.xml")
    return False, "target_line_not_found_in_bus_stop_card"


def click_line_direction_from_bus_stop_card(args: argparse.Namespace, nodes: list[UiNode], expected_line: str) -> bool:
    """Handle the AMap fallback where a line query returns bus-stop cards.

    Some queries, e.g. "福州公交K1路", open a bus stop detail page instead of a
    line page. The route can still be opened by tapping one of the direction
    rows directly below the target line under "途经线路".
    """
    if not any(clean_label(n.label) == "途经线路" for n in nodes):
        return False
    target_lines = [
        n
        for n in nodes
        if clean_label(n.label) == expected_line
        and n.y1 > 1200
    ]
    if not target_lines:
        return False
    line_node = sorted(target_lines, key=lambda n: (n.y1, n.x1))[0]
    next_line_y = 2800
    for node in nodes:
        label = clean_label(node.label)
        if node.y1 > line_node.y2 + 80 and is_route_label(label):
            next_line_y = min(next_line_y, node.y1)
    direction_rows = [
        n
        for n in nodes
        if clean_label(n.label).startswith("开往")
        and line_node.y2 < n.y1 < next_line_y
    ]
    if not direction_rows:
        return False
    # The direction label itself is sometimes not clickable. Tapping the middle
    # of the whole direction row is more reliable.
    row = sorted(direction_rows, key=lambda n: n.y1)[0]
    tap(args, 650, row.cy, sleep=3.0)
    return True


def node_texts(nodes: list[UiNode]) -> list[str]:
    return [n.text for n in nodes if n.text]


def normalize_time(value: str) -> str:
    value = str(value)
    if ":" in value:
        return value
    if len(value) == 4 and value.isdigit():
        return f"{value[:2]}:{value[2:]}"
    return value


def first_line_name(texts: list[str], target_query: str) -> str:
    target = base_line_name(target_query)
    for text in texts:
        label = clean_label(text)
        if label == target or is_route_label(label):
            return label
    return target


def parse_direction_from_nodes(nodes: list[UiNode]) -> tuple[str, str]:
    texts = node_texts(nodes)
    if "共2个方向" in texts:
        idx = texts.index("共2个方向")
        stop_candidates = [
            clean_label(t)
            for t in texts[idx + 1 : idx + 10]
            if clean_label(t)
            and clean_label(t) not in {"换向"}
            and not TIME_RE.match(clean_label(t))
            and not PERIOD_RE.match(clean_label(t))
            and "时刻" not in clean_label(t)
            and "最近班次" not in clean_label(t)
        ]
        if len(stop_candidates) >= 2:
            return stop_candidates[0], stop_candidates[1]
    tab_nodes = [n for n in nodes if 430 <= n.y1 <= 720 and clean_label(n.text) and "→" not in n.text]
    labels = [clean_label(n.text) for n in tab_nodes if len(clean_label(n.text)) >= 2]
    if len(labels) >= 2:
        return labels[0], labels[1]
    return "", ""


def parse_header(target_query: str, nodes: list[UiNode]) -> dict[str, Any]:
    texts = node_texts(nodes)
    direction_from, direction_to = parse_direction_from_nodes(nodes)
    header: dict[str, Any] = {
        "target_query": target_query,
        "observed_line": first_line_name(texts, target_query),
        "direction_from": direction_from,
        "direction_to": direction_to,
        "service_start": "",
        "service_end": "",
        "fare": "",
        "latest_departure_text": "",
        "note": "",
    }
    for text in texts:
        label = clean_label(text)
        if "首末班车" in label:
            times = re.findall(r"\d{2}:?\d{2}", label)
            if len(times) >= 2:
                header["service_start"] = normalize_time(times[0])
                header["service_end"] = normalize_time(times[1])
        if label.startswith("票价信息") or label.startswith("票价"):
            header["fare"] = text
        if "仅供参考" in label:
            header["note"] = text
        if ("班次预计" in label) or ("预计" in label and "发车" in label):
            header["latest_departure_text"] = text
    return header


def raw_rows_for_nodes(target_query: str, nodes: list[UiNode], scroll_index: int, direction_index: int, direction_label: str) -> list[dict[str, Any]]:
    return [
        {
            "target_query": target_query,
            "direction_index": direction_index,
            "direction_tab_label": direction_label,
            "scroll_index": scroll_index,
            "text": n.text,
            "content_desc": n.desc,
            "resource_id": n.rid,
            "class": n.cls,
            "bounds": n.bounds,
            "x1": n.x1,
            "y1": n.y1,
            "x2": n.x2,
            "y2": n.y2,
        }
        for n in nodes
        if n.text or n.desc
    ]


def parse_time_rows(target_query: str, nodes: list[UiNode], scroll_index: int, header: dict[str, Any], direction_index: int, direction_label: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    current_period = ""
    current_label = ""
    for node in nodes:
        text = node.text.strip()
        if PERIOD_RE.match(text):
            current_period = text
            current_label = ""
            continue
        if text in {"早高峰", "晚高峰", "平峰", "低峰"}:
            current_label = text
            continue
        if TIME_RE.match(text) and current_period:
            rows.append(
                {
                    "target_query": target_query,
                    "direction_index": direction_index,
                    "direction_tab_label": direction_label,
                    "scroll_index": scroll_index,
                    "observed_line": header.get("observed_line", ""),
                    "direction_from": header.get("direction_from", ""),
                    "direction_to": header.get("direction_to", ""),
                    "period": current_period,
                    "period_label": current_label,
                    "departure_time": text,
                    "bounds": node.bounds,
                    "y1": node.y1,
                    "x1": node.x1,
                }
            )
    return rows


def rule_row(
    target_query: str,
    header: dict[str, Any],
    direction_index: int,
    direction_label: str,
    scroll_index: int,
    day_type: str,
    rule_type: str,
    text: str,
    node: UiNode,
    *,
    period_start: str = "",
    period_end: str = "",
    departure_time: str = "",
    headway_minutes: str = "",
) -> dict[str, Any]:
    return {
        "target_query": target_query,
        "direction_index": direction_index,
        "direction_tab_label": direction_label,
        "scroll_index": scroll_index,
        "observed_line": header.get("observed_line", ""),
        "direction_from": header.get("direction_from", ""),
        "direction_to": header.get("direction_to", ""),
        "day_type": day_type,
        "rule_type": rule_type,
        "period_start": period_start,
        "period_end": period_end,
        "departure_time": departure_time,
        "headway_minutes": headway_minutes,
        "text": text,
        "bounds": node.bounds,
        "x1": node.x1,
        "y1": node.y1,
    }


def parse_rule_rows(target_query: str, nodes: list[UiNode], scroll_index: int, header: dict[str, Any], direction_index: int, direction_label: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    current_day = ""
    current_rule = ""
    texts = [(clean_label(n.text), n) for n in nodes if clean_label(n.text)]
    for i, (text, node) in enumerate(texts):
        if text in {"工作日", "周一至周五", "周六", "周日", "节假日", "法定节假日"}:
            current_day = text
            continue
        if text.startswith("定点发车"):
            current_rule = "fixed_departure"
            times = [m.group(0) for m in re.finditer(r"\d{2}:\d{2}", text)]
            if not times:
                for next_text, _ in texts[i + 1 : i + 8]:
                    if next_text in {"规则发车", "工作日", "周六", "周日", "节假日"} or next_text.startswith("规则发车"):
                        break
                    times.extend(m.group(0) for m in re.finditer(r"\d{2}:\d{2}", next_text))
            for departure_time in sorted(set(times)):
                rows.append(rule_row(target_query, header, direction_index, direction_label, scroll_index, current_day, current_rule, text, node, departure_time=departure_time))
            continue
        if text.startswith("规则发车"):
            current_rule = "regular_headway"
            continue
        if current_rule == "regular_headway":
            period_match = PERIOD_IN_TEXT_RE.search(text)
            headway_match = HEADWAY_RE.search(text)
            if period_match or headway_match:
                rows.append(
                    rule_row(
                        target_query,
                        header,
                        direction_index,
                        direction_label,
                        scroll_index,
                        current_day,
                        "regular_headway",
                        text,
                        node,
                        period_start=period_match.group(1) if period_match else "",
                        period_end=period_match.group(2) if period_match else "",
                        headway_minutes=headway_match.group(1) if headway_match else "",
                    )
                )
                continue
        if any(k in text for k in ["上车站", "票价信息", "首末班车"]) or ("发车" in text and "分钟/趟" in text):
            rows.append(rule_row(target_query, header, direction_index, direction_label, scroll_index, current_day, "raw_text", text, node))
    return rows


def visible_text_fingerprint(nodes: list[UiNode]) -> tuple[str, ...]:
    ignored = {"刷新", "关注", "返回", "更多", "公交闹钟", "上车提醒", "开始导航", "下车提醒"}
    labels = []
    for node in nodes:
        text = clean_label(node.text or node.desc)
        if not text or text in ignored:
            continue
        if text.startswith("第") and "屏" in text:
            continue
        labels.append(text)
    return tuple(labels)


def fingerprint_similarity(a: tuple[str, ...], b: tuple[str, ...]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    sa, sb = set(a), set(b)
    return len(sa & sb) / max(1, len(sa | sb))


def period_sections(nodes: list[UiNode]) -> list[dict[str, Any]]:
    periods = [node for node in nodes if PERIOD_RE.match(node.text.strip())]
    sections = []
    for idx, node in enumerate(periods):
        next_y = periods[idx + 1].y1 if idx + 1 < len(periods) else 2800
        time_count = sum(1 for other in nodes if TIME_RE.match(other.text.strip()) and node.y2 < other.y1 < next_y)
        label = ""
        for other in nodes:
            if other.y1 >= node.y1 - 20 and other.y2 <= node.y2 + 20 and other.text in {"早高峰", "晚高峰", "平峰", "低峰"}:
                label = other.text
                break
        sections.append({"period": node.text.strip(), "label": label, "node": node, "time_count": time_count, "expanded": time_count > 0})
    return sections


def expand_visible_periods_fast(
    args: argparse.Namespace,
    line_dir: Path,
    prefix: str,
    expanded_periods: set[str],
    max_taps: int = 5,
) -> tuple[list[UiNode], str]:
    """Fast-expand all collapsed timetable sections visible in the viewport.

    AMap's XML does not expose the chevron state reliably. So we do not infer
    expanded/collapsed from nearby time nodes. Instead, for each direction, each
    period is tapped at most once. Visible periods are tapped bottom-to-top so
    the bottom-most chevrons, especially "20:00-24:00", are not pushed out of
    the sheet by an upper section expanding first.
    """
    actions: list[str] = []
    last_nodes: list[UiNode] = []
    tapped: set[tuple[str, int]] = set()
    for attempt in range(max_taps):
        nodes = dump_ui(args, line_dir / f"{prefix}_expand_{attempt:02d}.xml")
        last_nodes = nodes
        candidates = [
            sec
            for sec in period_sections(nodes)
            if sec["period"] not in expanded_periods
            and 650 < sec["node"].cy < 2700
            and (sec["period"], sec["node"].cy) not in tapped
        ]
        if not candidates:
            return nodes, ";".join(actions) if actions else "no_collapsed_period"
        sec = sorted(candidates, key=lambda item: item["node"].cy, reverse=True)[0]
        tapped.add((sec["period"], sec["node"].cy))
        expanded_periods.add(sec["period"])
        actions.append(f"expanded:{sec['period']}")
        tap(args, 1160, min(sec["node"].cy, 2630), sleep=0.65)
    return last_nodes, ";".join(actions) if actions else "max_taps_no_action"


def collect_current_schedule(
    args: argparse.Namespace,
    query: str,
    line_dir: Path,
    *,
    direction_index: int = 1,
    direction_label: str = "",
    expand_policy: str = "always",
) -> dict[str, Any]:
    line_dir.mkdir(parents=True, exist_ok=True)
    all_raw: list[dict[str, Any]] = []
    all_times: list[dict[str, Any]] = []
    all_rules: list[dict[str, Any]] = []
    headers: list[dict[str, Any]] = []
    snapshot_rows: list[dict[str, Any]] = []
    expanded_periods: set[str] = set()
    last_fingerprint: tuple[str, ...] | None = None
    stable_seen = 0

    for scroll_index in range(args.max_scrolls + 1):
        prefix = f"dir_{direction_index}_scroll_{scroll_index:02d}"
        pre_xml_path = line_dir / f"dir_{direction_index}_pre_{scroll_index:02d}.xml"
        pre_nodes = dump_ui(args, pre_xml_path)
        pre_header = parse_header(query, pre_nodes)
        pre_header["direction_index"] = direction_index
        pre_header["direction_tab_label"] = direction_label
        if "→" in direction_label:
            left, right = direction_label.split("→", 1)
            pre_header["direction_from"] = left
            pre_header["direction_to"] = right
        pre_time_rows = parse_time_rows(query, pre_nodes, scroll_index * 1000, pre_header, direction_index, direction_label)

        sections = period_sections(pre_nodes)
        no_period_sections = not sections
        if no_period_sections:
            expand_action = "no_period_sections_single_dump"
            nodes = pre_nodes
            snapshot_paths = [pre_xml_path]
        elif expand_policy == "if_no_visible_times" and pre_time_rows:
            expand_action = "visible_times_no_expand"
            nodes = pre_nodes
            snapshot_paths = [pre_xml_path]
        else:
            nodes, expand_action = expand_visible_periods_fast(
                args,
                line_dir,
                prefix=prefix,
                expanded_periods=expanded_periods,
            )
            xml_path = line_dir / f"dir_{direction_index}_dump_{scroll_index:02d}.xml"
            nodes = dump_ui(args, xml_path)
            # Fast mode: parse only the final dump after expansion to reduce XML
            # parsing and duplicated raw rows. The pre dump is kept on disk for
            # diagnostics but not parsed unless no expansion was needed.
            snapshot_paths = [xml_path]
        if args.save_screenshots:
            png_path = line_dir / f"dir_{direction_index}_screen_{scroll_index:02d}.png"
            with png_path.open("wb") as fh:
                subprocess.run([args.adb, "exec-out", "screencap", "-p"], stdout=fh, stderr=subprocess.PIPE)

        for snapshot_index, snapshot_path in enumerate(snapshot_paths):
            snapshot_rows.append(
                {
                    "snapshot_file": snapshot_path.name,
                    "scroll_index": scroll_index,
                    "snapshot_index": snapshot_index,
                    "direction_index": direction_index,
                    "direction_tab_label": direction_label,
                    "expand_action": expand_action,
                }
            )

        if args.capture_only:
            header = parse_header(query, nodes)
            header["expand_action"] = expand_action
            header["snapshot_file"] = snapshot_paths[-1].name if snapshot_paths else ""
            header["direction_index"] = direction_index
            header["direction_tab_label"] = direction_label
            if "→" in direction_label:
                left, right = direction_label.split("→", 1)
                header["direction_from"] = left
                header["direction_to"] = right
            headers.append(header)
            if scroll_index >= args.max_scrolls:
                break
            fingerprint = visible_text_fingerprint(nodes)
            if last_fingerprint is not None and fingerprint_similarity(last_fingerprint, fingerprint) >= 0.98:
                stable_seen += 1
            else:
                stable_seen = 0
            last_fingerprint = fingerprint
            if stable_seen >= 2:
                break
            if no_period_sections:
                break
            swipe(args, 640, 2520, 640, 1320, duration_ms=700)
            continue

        for snapshot_index, snapshot_path in enumerate(snapshot_paths):
            try:
                snapshot_nodes = parse_ui_xml(snapshot_path)
            except Exception:
                continue
            header = parse_header(query, snapshot_nodes)
            header["expand_action"] = expand_action
            header["snapshot_file"] = snapshot_path.name
            header["direction_index"] = direction_index
            header["direction_tab_label"] = direction_label
            if "→" in direction_label:
                left, right = direction_label.split("→", 1)
                header["direction_from"] = left
                header["direction_to"] = right
            headers.append(header)
            effective_scroll_index = scroll_index * 100 + snapshot_index
            all_raw.extend(raw_rows_for_nodes(query, snapshot_nodes, effective_scroll_index, direction_index, direction_label))
            all_times.extend(parse_time_rows(query, snapshot_nodes, effective_scroll_index, header, direction_index, direction_label))
            all_rules.extend(parse_rule_rows(query, snapshot_nodes, effective_scroll_index, header, direction_index, direction_label))

        if scroll_index >= args.max_scrolls:
            break
        fingerprint = visible_text_fingerprint(nodes)
        if last_fingerprint is not None and fingerprint_similarity(last_fingerprint, fingerprint) >= 0.98:
            stable_seen += 1
        else:
            stable_seen = 0
        last_fingerprint = fingerprint
        if stable_seen >= 2:
            break
        if no_period_sections:
            break
        swipe(args, 640, 2520, 640, 1320, duration_ms=700)

    dedup_times = {}
    for row in all_times:
        key = (
            row.get("direction_index", ""),
            row.get("direction_from", ""),
            row.get("direction_to", ""),
            row.get("period", ""),
            row.get("departure_time", ""),
        )
        dedup_times[key] = row

    dedup_rules = {}
    for row in all_rules:
        key = (
            row.get("direction_index", ""),
            row.get("day_type", ""),
            row.get("rule_type", ""),
            row.get("period_start", ""),
            row.get("period_end", ""),
            row.get("departure_time", ""),
            row.get("headway_minutes", ""),
            row.get("text", ""),
        )
        dedup_rules[key] = row

    best_header = next((h for h in headers if h.get("observed_line") or h.get("service_start")), headers[0] if headers else {})
    return {
        "header": best_header,
        "raw_rows": all_raw,
        "time_rows": list(dedup_times.values()),
        "rule_rows": list(dedup_rules.values()),
        "snapshot_rows": snapshot_rows,
        "scrolls": len(headers),
    }


def scroll_sheet_to_top(args: argparse.Namespace) -> None:
    for _ in range(5):
        swipe(args, 640, 1100, 640, 2450, duration_ms=550)


def direction_tabs_from_current_page(args: argparse.Namespace, line_dir: Path) -> list[dict[str, Any]]:
    nodes = dump_ui(args, line_dir / "direction_tabs.xml")
    texts = node_texts(nodes)
    if "共2个方向" not in texts:
        return [{"direction_index": 1, "label": "current", "x": 320, "y": 590}]
    labels = []
    idx = texts.index("共2个方向")
    for t in texts[idx + 1 : idx + 8]:
        label = clean_label(t)
        if label and label not in {"换向"} and not is_route_label(label):
            labels.append(label)
    left_label = "→".join(labels[:2]) if len(labels) >= 2 else "direction_1"
    right_label = "→".join(labels[2:4]) if len(labels) >= 4 else "direction_2"
    return [
        {"direction_index": 1, "label": left_label, "x": 300, "y": 590},
        {"direction_index": 2, "label": right_label, "x": 880, "y": 590},
    ]


def collect_all_directions(args: argparse.Namespace, query: str, line_dir: Path) -> dict[str, Any]:
    all_headers: list[dict[str, Any]] = []
    all_times: list[dict[str, Any]] = []
    all_rules: list[dict[str, Any]] = []
    all_raw: list[dict[str, Any]] = []
    all_snapshots: list[dict[str, Any]] = []
    total_scrolls = 0

    scroll_sheet_to_top(args)
    tabs = direction_tabs_from_current_page(args, line_dir)
    if not args.collect_both_directions:
        tabs = tabs[:1]

    for tab in tabs:
        scroll_sheet_to_top(args)
        tap(args, int(tab["x"]), int(tab["y"]), sleep=1.4)
        result = collect_current_schedule(
            args,
            query,
            line_dir,
            direction_index=int(tab["direction_index"]),
            direction_label=str(tab["label"]),
            expand_policy="always" if int(tab["direction_index"]) == 1 else "if_no_visible_times",
        )
        all_headers.append(result["header"])
        all_times.extend(result["time_rows"])
        all_rules.extend(result["rule_rows"])
        all_raw.extend(result["raw_rows"])
        all_snapshots.extend(result.get("snapshot_rows", []))
        total_scrolls += result["scrolls"]

    best_header = all_headers[0] if all_headers else {}
    best_header["directions_collected"] = len(tabs)
    return {
        "header": best_header,
        "headers": all_headers,
        "time_rows": all_times,
        "rule_rows": all_rules,
        "raw_rows": all_raw,
        "snapshot_rows": all_snapshots,
        "scrolls": total_scrolls,
    }


def line_queries_from_input(path: Path, max_lines: int) -> list[dict[str, str]]:
    df = pd.read_csv(path, encoding="utf-8-sig")
    rows = []
    seen_queries: set[str] = set()
    for _, row in df.iterrows():
        line_name = str(row.get("line_name") or "")
        query = line_name.strip()
        if not query or query in seen_queries:
            continue
        seen_queries.add(query)
        rows.append(
            {
                "query": query,
                "target_line_id": str(row.get("line_id") or ""),
                "target_line_name": line_name,
                "target_start_stop": str(row.get("start_stop") or ""),
                "target_end_stop": str(row.get("end_stop") or ""),
            }
        )
    if max_lines:
        rows = rows[:max_lines]
    return rows


def time_to_minutes(value: str) -> int | None:
    if not isinstance(value, str) or not TIME_RE.match(value):
        return None
    hour, minute = value.split(":")
    return int(hour) * 60 + int(minute)


def minutes_to_time(value: int | None) -> str:
    if value is None:
        return ""
    value = int(value) % (24 * 60)
    return f"{value // 60:02d}:{value % 60:02d}"


def median_int(values: list[int]) -> str:
    if not values:
        return ""
    vals = sorted(values)
    mid = len(vals) // 2
    if len(vals) % 2:
        return str(vals[mid])
    return f"{(vals[mid - 1] + vals[mid]) / 2:.1f}".rstrip("0").rstrip(".")


def mode_int(values: list[int]) -> str:
    if not values:
        return ""
    counts: dict[int, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    best = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0]
    return str(best[0])


def period_bounds(period: str) -> tuple[str, str]:
    match = PERIOD_RE.match(str(period or ""))
    if not match:
        return "", ""
    return match.group(1), match.group(2)


def regularize_departure_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert exact departure times into interval-rule summaries.

    The original departure table is still preserved. This derived table is what
    downstream transit modelling usually wants: per line/direction/period,
    first/last departure, headway statistics, and the exact sequence for audit.
    """
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for row in rows:
        key = (
            row.get("target_line_id", ""),
            row.get("target_line_name", ""),
            row.get("target_query", ""),
            row.get("observed_line", ""),
            row.get("direction_index", ""),
            row.get("direction_tab_label", ""),
            row.get("direction_from", ""),
            row.get("direction_to", ""),
            row.get("period", ""),
            row.get("period_label", ""),
        )
        groups.setdefault(key, []).append(row)

    regularized: list[dict[str, Any]] = []
    for key, group_rows in groups.items():
        times = sorted({m for m in (time_to_minutes(str(r.get("departure_time", ""))) for r in group_rows) if m is not None})
        if not times:
            continue
        intervals = [b - a for a, b in zip(times, times[1:]) if b > a]
        period_start, period_end = period_bounds(str(key[8]))
        median_headway = median_int(intervals)
        min_headway = str(min(intervals)) if intervals else ""
        max_headway = str(max(intervals)) if intervals else ""
        mean_headway = f"{sum(intervals) / len(intervals):.1f}".rstrip("0").rstrip(".") if intervals else ""
        mode_headway = mode_int(intervals)
        if intervals:
            if min_headway == max_headway:
                rule_text = f"{period_start}-{period_end} 约{median_headway}分钟/趟"
            else:
                rule_text = f"{period_start}-{period_end} 约{median_headway}分钟/趟，范围{min_headway}-{max_headway}分钟"
        else:
            rule_text = f"{period_start}-{period_end} 定点发车 {minutes_to_time(times[0])}"
        regularized.append(
            {
                "target_line_id": key[0],
                "target_line_name": key[1],
                "target_query": key[2],
                "observed_line": key[3],
                "direction_index": key[4],
                "direction_tab_label": key[5],
                "direction_from": key[6],
                "direction_to": key[7],
                "period": key[8],
                "period_start": period_start,
                "period_end": period_end,
                "period_label": key[9],
                "rule_source": "departure_sequence",
                "departure_count": len(times),
                "first_departure": minutes_to_time(times[0]),
                "last_departure": minutes_to_time(times[-1]),
                "interval_count": len(intervals),
                "headway_min_minutes": min_headway,
                "headway_max_minutes": max_headway,
                "headway_mean_minutes": mean_headway,
                "headway_median_minutes": median_headway,
                "headway_mode_minutes": mode_headway,
                "departures_csv": ";".join(minutes_to_time(t) for t in times),
                "intervals_minutes_csv": ";".join(str(v) for v in intervals),
                "regularized_rule_text": rule_text,
            }
        )
    regularized.sort(
        key=lambda r: (
            str(r.get("target_query", "")),
            int(r.get("direction_index") or 0),
            time_to_minutes(str(r.get("period_start", "00:00"))) or 0,
        )
    )
    return regularized


def regularize_text_rule_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    regularized: list[dict[str, Any]] = []
    for row in rows:
        if row.get("rule_type") not in {"regular_headway", "fixed_departure"}:
            continue
        regularized.append(
            {
                "target_line_id": row.get("target_line_id", ""),
                "target_line_name": row.get("target_line_name", ""),
                "target_query": row.get("target_query", ""),
                "observed_line": row.get("observed_line", ""),
                "direction_index": row.get("direction_index", ""),
                "direction_tab_label": row.get("direction_tab_label", ""),
                "direction_from": row.get("direction_from", ""),
                "direction_to": row.get("direction_to", ""),
                "period": "",
                "period_start": row.get("period_start", ""),
                "period_end": row.get("period_end", ""),
                "period_label": row.get("day_type", ""),
                "rule_source": f"text_{row.get('rule_type', '')}",
                "departure_count": 1 if row.get("departure_time") else "",
                "first_departure": row.get("departure_time", ""),
                "last_departure": row.get("departure_time", ""),
                "interval_count": "",
                "headway_min_minutes": row.get("headway_minutes", ""),
                "headway_max_minutes": row.get("headway_minutes", ""),
                "headway_mean_minutes": row.get("headway_minutes", ""),
                "headway_median_minutes": row.get("headway_minutes", ""),
                "headway_mode_minutes": row.get("headway_minutes", ""),
                "departures_csv": row.get("departure_time", ""),
                "intervals_minutes_csv": "",
                "regularized_rule_text": row.get("text", ""),
            }
        )
    return regularized


def build_regularized_rules(departure_rows: list[dict[str, Any]], text_rule_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return regularize_departure_rows(departure_rows) + regularize_text_rule_rows(text_rule_rows)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({k for row in rows for k in row})
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def read_csv_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def write_all_outputs(
    output_dir: Path,
    device: str,
    targets: list[dict[str, str]],
    all_headers: list[dict[str, Any]],
    all_times: list[dict[str, Any]],
    all_rules: list[dict[str, Any]],
    all_raw: list[dict[str, Any]],
    summary_rows: list[dict[str, Any]],
) -> None:
    write_csv(output_dir / "amap_mobile_timetable_headers.csv", all_headers)
    write_csv(output_dir / "amap_mobile_timetable_departures.csv", all_times)
    write_csv(output_dir / "amap_mobile_timetable_rules.csv", all_rules)
    regularized_rules = build_regularized_rules(all_times, all_rules)
    write_csv(output_dir / "amap_mobile_timetable_regularized_rules.csv", regularized_rules)
    write_csv(output_dir / "amap_mobile_timetable_raw_text.csv", all_raw)
    summary = {
        "device": device,
        "target_count": len(targets),
        "processed_count": len({str(row.get("query", "")) for row in summary_rows if row.get("query")}),
        "success_count": sum(1 for row in summary_rows if row.get("status") == "ok"),
        "failure_count": sum(1 for row in summary_rows if row.get("status") and row.get("status") != "ok"),
        "departure_rows": len(all_times),
        "rule_rows": len(all_rules),
        "regularized_rule_rows": len(regularized_rules),
        "output_dir": str(output_dir),
        "outputs": [
            "amap_mobile_timetable_headers.csv",
            "amap_mobile_timetable_departures.csv",
            "amap_mobile_timetable_rules.csv",
            "amap_mobile_timetable_regularized_rules.csv",
            "amap_mobile_timetable_raw_text.csv",
            "amap_mobile_timetable_summary.json",
        ],
    }
    (output_dir / "amap_mobile_timetable_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def write_capture_manifest(line_dir: Path, target: dict[str, Any], status: str, message: str, result: dict[str, Any] | None) -> None:
    line_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "target": target,
        "status": status,
        "message": message,
        "scrolls": int((result or {}).get("scrolls") or 0),
        "directions_collected": int(((result or {}).get("header") or {}).get("directions_collected") or 0),
        "headers": (result or {}).get("headers", []),
        "snapshots": (result or {}).get("snapshot_rows", []),
    }
    (line_dir / "capture_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def read_capture_manifests(output_dir: Path) -> list[dict[str, Any]]:
    manifests: list[dict[str, Any]] = []
    for path in sorted(output_dir.glob("*/capture_manifest.json")):
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
            item["_line_dir"] = str(path.parent)
            manifests.append(item)
        except Exception as exc:  # noqa: BLE001
            manifests.append(
                {
                    "_line_dir": str(path.parent),
                    "target": {"query": path.parent.name},
                    "status": "manifest_read_failed",
                    "message": str(exc),
                    "headers": [],
                    "snapshots": [],
                }
            )
    return manifests


def dedupe_departure_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    dedup: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in rows:
        key = (
            row.get("target_line_id", ""),
            row.get("target_line_name", ""),
            row.get("target_query", ""),
            row.get("direction_index", ""),
            row.get("direction_from", ""),
            row.get("direction_to", ""),
            row.get("period", ""),
            row.get("departure_time", ""),
        )
        dedup[key] = row
    return list(dedup.values())


def dedupe_rule_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    dedup: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in rows:
        key = (
            row.get("target_line_id", ""),
            row.get("target_line_name", ""),
            row.get("target_query", ""),
            row.get("direction_index", ""),
            row.get("day_type", ""),
            row.get("rule_type", ""),
            row.get("period_start", ""),
            row.get("period_end", ""),
            row.get("departure_time", ""),
            row.get("headway_minutes", ""),
            row.get("text", ""),
        )
        dedup[key] = row
    return list(dedup.values())


def enrich_direction_from_label(header: dict[str, Any], direction_label: str) -> None:
    header["direction_tab_label"] = direction_label
    if "→" in direction_label:
        left, right = direction_label.split("→", 1)
        header["direction_from"] = left
        header["direction_to"] = right


def parse_captured_outputs(output_dir: Path, device: str = "offline") -> None:
    manifests = read_capture_manifests(output_dir)
    if not manifests:
        raise RuntimeError(f"No capture_manifest.json files found under {output_dir}")

    all_headers: list[dict[str, Any]] = []
    all_times: list[dict[str, Any]] = []
    all_rules: list[dict[str, Any]] = []
    all_raw: list[dict[str, Any]] = []
    summary_rows: list[dict[str, Any]] = []
    targets: list[dict[str, str]] = []

    for manifest in manifests:
        target = manifest.get("target") or {}
        target = {str(k): v for k, v in target.items()}
        query = str(target.get("query") or target.get("target_line_name") or "")
        targets.append(target)
        line_dir = Path(str(manifest.get("_line_dir") or output_dir))
        status = str(manifest.get("status") or "")
        message = str(manifest.get("message") or "")

        if status != "ok":
            row = {
                **target,
                "status": status or "failed",
                "message": message,
                "scrolls": manifest.get("scrolls", 0),
                "departure_count": 0,
                "rule_count": 0,
            }
            all_headers.append(row)
            summary_rows.append(row)
            continue

        snapshot_groups: dict[tuple[int, str], list[dict[str, Any]]] = {}
        for snap in manifest.get("snapshots", []):
            direction_index = int(snap.get("direction_index") or 1)
            direction_label = str(snap.get("direction_tab_label") or "")
            snapshot_groups.setdefault((direction_index, direction_label), []).append(snap)

        direction_headers: list[dict[str, Any]] = []
        line_times: list[dict[str, Any]] = []
        line_rules: list[dict[str, Any]] = []
        line_raw: list[dict[str, Any]] = []

        for (direction_index, direction_label), snaps in sorted(snapshot_groups.items(), key=lambda kv: kv[0][0]):
            candidate_headers: list[dict[str, Any]] = []
            direction_times: list[dict[str, Any]] = []
            direction_rules: list[dict[str, Any]] = []
            for snap in snaps:
                snapshot_file = str(snap.get("snapshot_file") or "")
                snapshot_path = line_dir / snapshot_file
                if not snapshot_file or not snapshot_path.exists():
                    continue
                try:
                    nodes = parse_ui_xml(snapshot_path)
                except Exception:
                    continue
                scroll_index = int(snap.get("scroll_index") or 0) * 100 + int(snap.get("snapshot_index") or 0)
                header = parse_header(query, nodes)
                header["expand_action"] = snap.get("expand_action", "")
                header["snapshot_file"] = snapshot_file
                header["direction_index"] = direction_index
                enrich_direction_from_label(header, direction_label)
                candidate_headers.append(header)
                line_raw.extend(raw_rows_for_nodes(query, nodes, scroll_index, direction_index, direction_label))
                direction_times.extend(parse_time_rows(query, nodes, scroll_index, header, direction_index, direction_label))
                direction_rules.extend(parse_rule_rows(query, nodes, scroll_index, header, direction_index, direction_label))

            direction_times = dedupe_departure_rows([{**target, **row} for row in direction_times])
            direction_rules = dedupe_rule_rows([{**target, **row} for row in direction_rules])
            best_header = next(
                (h for h in candidate_headers if h.get("observed_line") or h.get("service_start")),
                candidate_headers[0] if candidate_headers else {},
            )
            if best_header:
                best_header = {**target, **best_header}
                best_header["status"] = status
                best_header["message"] = message
                best_header["scrolls"] = manifest.get("scrolls", 0)
                best_header["departure_count"] = len(direction_times)
                best_header["rule_count"] = len(direction_rules)
                direction_headers.append(best_header)
            line_times.extend(direction_times)
            line_rules.extend(direction_rules)

        for h in direction_headers:
            h["directions_collected"] = len(direction_headers)
        all_headers.extend(direction_headers or [{**target, "status": status, "message": message, "scrolls": manifest.get("scrolls", 0)}])
        all_times.extend(dedupe_departure_rows(line_times))
        all_rules.extend(dedupe_rule_rows(line_rules))
        all_raw.extend({**target, **row} for row in line_raw)
        summary_rows.append(
            {
                **target,
                "status": status,
                "message": message,
                "scrolls": manifest.get("scrolls", 0),
                "directions_collected": len(direction_headers),
                "departure_count": len(dedupe_departure_rows(line_times)),
                "rule_count": len(dedupe_rule_rows(line_rules)),
            }
        )

    write_all_outputs(
        output_dir,
        device,
        targets,
        all_headers,
        dedupe_departure_rows(all_times),
        dedupe_rule_rows(all_rules),
        all_raw,
        summary_rows,
    )


def safe_name(text: str) -> str:
    return re.sub(r"[\\/:*?\"<>|\s]+", "_", text)[:40] or "line"


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    if args.parse_captures_only:
        parse_captured_outputs(args.output_dir, device="offline")
        summary = json.loads((args.output_dir / "amap_mobile_timetable_summary.json").read_text(encoding="utf-8"))
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    device = ensure_device(args)
    print(f"ADB device: {device}")

    if args.line_query:
        targets = [{"query": q, "target_line_id": "", "target_line_name": q, "target_start_stop": "", "target_end_stop": ""} for q in args.line_query]
    elif args.current_only:
        targets = [{"query": "current", "target_line_id": "", "target_line_name": "current", "target_start_stop": "", "target_end_stop": ""}]
    else:
        targets = line_queries_from_input(args.input_lines, args.max_lines)
        if not targets:
            raise RuntimeError("No targets found. Provide --line-query or a valid --input-lines CSV.")

    if args.resume:
        if args.capture_only:
            all_headers = []
            all_times = []
            all_rules = []
            all_raw = []
            summary_rows = []
            completed_queries = set()
            for manifest in read_capture_manifests(args.output_dir):
                target = manifest.get("target") or {}
                query = str(target.get("query") or "")
                status = str(manifest.get("status") or "")
                if query and status:
                    summary_rows.append(
                        {
                            **target,
                            "status": status,
                            "message": manifest.get("message", ""),
                            "scrolls": manifest.get("scrolls", 0),
                            "departure_count": 0,
                            "rule_count": 0,
                        }
                    )
                if query and status == "ok":
                    completed_queries.add(query)
            print(f"Resume capture-only mode: loaded_manifests={len(summary_rows)}, completed_queries={len(completed_queries)}")
        else:
            all_headers = read_csv_rows(args.output_dir / "amap_mobile_timetable_headers.csv")
            all_times = read_csv_rows(args.output_dir / "amap_mobile_timetable_departures.csv")
            all_rules = read_csv_rows(args.output_dir / "amap_mobile_timetable_rules.csv")
            all_raw = read_csv_rows(args.output_dir / "amap_mobile_timetable_raw_text.csv")
            summary_rows = []
            for row in all_headers:
                if row.get("query") and row.get("status"):
                    summary_rows.append(
                        {
                            "query": row.get("query", ""),
                            "status": row.get("status", ""),
                            "message": row.get("message", ""),
                            "departure_count": row.get("departure_count", ""),
                            "rule_count": row.get("rule_count", ""),
                        }
                    )
            completed_queries = {str(row.get("query", "")) for row in all_headers if row.get("status") == "ok"}
            print(f"Resume mode: loaded headers={len(all_headers)}, departures={len(all_times)}, completed_queries={len(completed_queries)}")
    else:
        all_headers: list[dict[str, Any]] = []
        all_times: list[dict[str, Any]] = []
        all_rules: list[dict[str, Any]] = []
        all_raw: list[dict[str, Any]] = []
        summary_rows: list[dict[str, Any]] = []
        completed_queries: set[str] = set()

    for idx, target in enumerate(targets, start=1):
        query = target["query"]
        if args.resume and query in completed_queries:
            print(f"[{idx}/{len(targets)}] {query}: skipped_existing_ok")
            continue
        line_dir = args.output_dir / f"{idx:04d}_{safe_name(query)}"
        status = "ok"
        message = ""
        try:
            if not args.current_only:
                ok, message = open_line_schedule(args, query, line_dir)
                if not ok:
                    status = "navigation_failed"
                    raise RuntimeError(message)
            result = collect_all_directions(args, query, line_dir)
            if args.capture_only:
                write_capture_manifest(line_dir, target, status, message, result)
            for h in result["headers"] or [result["header"]]:
                header = {**target, **h}
                header["status"] = status
                header["message"] = message
                header["scrolls"] = result["scrolls"]
                header["departure_count"] = len([r for r in result["time_rows"] if r.get("direction_index") == h.get("direction_index")])
                header["rule_count"] = len([r for r in result["rule_rows"] if r.get("direction_index") == h.get("direction_index")])
                all_headers.append(header)
            all_times.extend({**target, **row} for row in result["time_rows"])
            all_rules.extend({**target, **row} for row in result["rule_rows"])
            all_raw.extend({**target, **row} for row in result["raw_rows"])
            summary = {
                **target,
                "status": status,
                "message": message,
                "scrolls": result["scrolls"],
                "directions_collected": result["header"].get("directions_collected", 1),
                "departure_count": len(result["time_rows"]),
                "rule_count": len(result["rule_rows"]),
            }
            summary_rows.append(summary)
            print(
                f"[{idx}/{len(targets)}] {query}: {status}, "
                f"directions={summary['directions_collected']}, departures={summary['departure_count']}, "
                f"rules={summary['rule_count']}, scrolls={summary['scrolls']}"
            )
            if args.flush_each_line:
                if args.capture_only:
                    capture_summary = {
                        "device": device,
                        "target_count": len(targets),
                        "processed_count": len(summary_rows),
                        "success_count": sum(1 for row in summary_rows if row.get("status") == "ok"),
                        "failure_count": sum(1 for row in summary_rows if row.get("status") and row.get("status") != "ok"),
                        "mode": "capture_only",
                        "output_dir": str(args.output_dir),
                    }
                    (args.output_dir / "amap_mobile_timetable_capture_summary.json").write_text(
                        json.dumps(capture_summary, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                else:
                    write_all_outputs(args.output_dir, device, targets, all_headers, all_times, all_rules, all_raw, summary_rows)
        except Exception as exc:  # noqa: BLE001
            status = "failed" if status == "ok" else status
            row = {**target, "status": status, "message": str(exc), "scrolls": 0, "departure_count": 0, "rule_count": 0}
            if args.capture_only:
                write_capture_manifest(line_dir, target, status, str(exc), None)
            all_headers.append(row)
            summary_rows.append(row)
            print(f"[{idx}/{len(targets)}] {query}: {status}: {exc}")
            if args.flush_each_line:
                if args.capture_only:
                    capture_summary = {
                        "device": device,
                        "target_count": len(targets),
                        "processed_count": len(summary_rows),
                        "success_count": sum(1 for item in summary_rows if item.get("status") == "ok"),
                        "failure_count": sum(1 for item in summary_rows if item.get("status") and item.get("status") != "ok"),
                        "mode": "capture_only",
                        "output_dir": str(args.output_dir),
                    }
                    (args.output_dir / "amap_mobile_timetable_capture_summary.json").write_text(
                        json.dumps(capture_summary, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                else:
                    write_all_outputs(args.output_dir, device, targets, all_headers, all_times, all_rules, all_raw, summary_rows)

    if args.capture_only:
        capture_summary = {
            "device": device,
            "target_count": len(targets),
            "processed_count": len(summary_rows),
            "success_count": sum(1 for row in summary_rows if row.get("status") == "ok"),
            "failure_count": sum(1 for row in summary_rows if row.get("status") and row.get("status") != "ok"),
            "mode": "capture_only",
            "output_dir": str(args.output_dir),
        }
        (args.output_dir / "amap_mobile_timetable_capture_summary.json").write_text(
            json.dumps(capture_summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(json.dumps(capture_summary, ensure_ascii=False, indent=2))
    else:
        write_all_outputs(args.output_dir, device, targets, all_headers, all_times, all_rules, all_raw, summary_rows)
        summary = json.loads((args.output_dir / "amap_mobile_timetable_summary.json").read_text(encoding="utf-8"))
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
