#!/usr/bin/env python3
"""Download the official Hong Kong Traffic Aids traffic-light layers.

The files are monthly Transport Department source data.  This downloader does
not use content hashes as a workflow gate: an existing non-empty file is kept
unless ``--overwrite`` is requested.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import shutil
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT = (
    REPO_ROOT / "data/transit/hongkong/raw/traffic_signals_2026"
)
BASE_URL = "https://static.data.gov.hk/td/traffic-aids-drawings-v2"
RESOURCES = {
    "DTAD_TRAFFIC_LIGHT_PT.gml": f"{BASE_URL}/DTAD_TRAFFIC_LIGHT_PT.gml",
    "DTAD_TRAFFIC_LIGHT_LINE.gml": f"{BASE_URL}/DTAD_TRAFFIC_LIGHT_LINE.gml",
    "DTAD_TRAFFIC_LIGHT_FILLED.gml": f"{BASE_URL}/DTAD_TRAFFIC_LIGHT_FILLED.gml",
    "tadrawings_dataspec.zip": (
        f"{BASE_URL}/dataspec/tadrawings_dataspec.zip"
    ),
}


def download(url: str, target: Path, overwrite: bool) -> str:
    if target.exists() and target.stat().st_size > 0 and not overwrite:
        return "kept"
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".download")
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Hong-Kong-MATSim-traffic-signal-data-builder/1.0"},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        with temporary.open("wb") as handle:
            shutil.copyfileobj(response, handle)
    if temporary.stat().st_size == 0:
        raise RuntimeError(f"Downloaded an empty file: {url}")
    temporary.replace(target)
    return "downloaded"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_source_manifest(output_dir: Path) -> None:
    """Record source provenance; hashes are not used as workflow gates."""
    recorded_at = datetime.now(timezone.utc).isoformat()
    with (output_dir / "SOURCE_MANIFEST.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "filename",
                "source_url",
                "size_bytes",
                "sha256_provenance_only",
                "recorded_at_utc",
            ],
            lineterminator="\n",
        )
        writer.writeheader()
        for filename, url in RESOURCES.items():
            path = output_dir / filename
            writer.writerow(
                {
                    "filename": filename,
                    "source_url": url,
                    "size_bytes": path.stat().st_size,
                    "sha256_provenance_only": file_sha256(path),
                    "recorded_at_utc": recorded_at,
                }
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    for filename, url in RESOURCES.items():
        target = args.output_dir / filename
        status = download(url, target, args.overwrite)
        print(f"{status}: {target} ({target.stat().st_size:,} bytes)")
    write_source_manifest(args.output_dir)
    print(f"provenance manifest: {args.output_dir / 'SOURCE_MANIFEST.csv'}")

    archive = args.output_dir / "tadrawings_dataspec.zip"
    specification_dir = args.output_dir / "dataspec"
    if args.overwrite or not specification_dir.exists():
        specification_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive) as source:
            source.extractall(specification_dir)
        print(f"extracted: {specification_dir}")


if __name__ == "__main__":
    main()
