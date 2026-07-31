#!/usr/bin/env python3
"""Prepare an append-only Hong Kong MATSim server deployment bundle."""

from __future__ import annotations

import argparse
import base64
import binascii
import csv
import gzip
import hashlib
import heapq
import json
import os
import shlex
import shutil
import stat
import subprocess
import sys
import tarfile
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATA_ROOT = Path(r"F:\Matsim\matsim-example-project\data")
SCENARIO_RELATIVE = Path(
    "matsim_agents/hongkong/typical_weekday_5pct_v2_activity_modechoice"
)
SUPPLY_RELATIVE = Path(
    "transit/hongkong/processed/"
    "matsim_road_pt_supply_2026_hybrid_capacity_"
    "mixed_bus_pcu005_ferry_core_v1_cap010"
)
CONFIG_NAME = "config_hong_kong_5pct_v2_activity_modechoice_50it.xml"
SERVER_BUILD_COMMAND = "./mvnw -DskipTests package"
MATSIM_VERSION = "2026.0"
SOURCE_SNAPSHOT_SCHEMA = "hong_kong_exact_git_tree_source_snapshot_v1"
EXPECTED_INPUT_SHA256 = {
    "config/config_hong_kong_5pct_v2_activity_modechoice_50it.xml":
        "75f9c8e82b6fee4141d3544c931309ca23abce76fe6d170c840acb007e1b115c",
    "input/plans_routed_5pct_v2.xml.gz":
        "c73ee48e792e7aebd55b7a2691664ae7f3f4f27d307aef2a6bf58263b3aaafea",
    "input/facilities_5pct_v2.xml.gz":
        "74775533a7022b248d37197dbc94d27f239239aca386df75c7a391cc277ef10e",
    "input/privateVehicles_5pct.xml.gz":
        "5a48b2afe404afaa6864a465c527277605a276e54cd879d3971261186938c994",
    "input/network.xml.gz":
        "dfc696442913a6d16a1ca1be7e5a332ec5762012190ed43a38f05493905ddc95",
    "input/transitSchedule_5pct.xml.gz":
        "eb92e6c7b3c2746313be92b8c88d51bc645d1db3c6605d1f4b472f27c9896aed",
    "input/transitVehicles_10pct.xml.gz":
        "16a6b89f77d3827ded06641869bf4e4c5168fb718356c1fe04e9f9249fdd7429",
}
STALE_ACTIVE_INPUT_FRAGMENTS = (
    "typical_weekday_5pct_v1",
    "matsim_road_pt_supply_2026_hybrid_capacity_mixed_bus_pcu005_v1",
    "transitVehicles_5pct.xml.gz",
    "config_hong_kong_5pct_50it.xml",
)
REQUIRED_RUNTIME_CLASSES = (
    "org/matsim/project/hongkong/taxi/"
    "HongKongTaxiFareScoringComponentFactory.class",
    "org/matsim/project/hongkong/pt/"
    "HongKongPtFareScoringComponentFactory.class",
    "org/matsim/project/hongkong/car/"
    "HongKongCarEnergyScoringComponentFactory.class",
    "org/matsim/project/hongkong/car/"
    "HongKongCarTollScoringComponentFactory.class",
    "org/matsim/project/hongkong/car/"
    "HongKongCarParkingScoringComponentFactory.class",
    "org/matsim/project/hongkong/car/"
    "HongKongCarMarginalCostScoringComponentFactory.class",
    "org/matsim/project/hongkong/scoring/"
    "HongKongMultimodalScoringFunctionFactory.class",
)
SMOKE_PERSON_COUNT = 7_716


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_full_sha(value: str, label: str) -> str:
    if len(value) != 40 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise ValueError(f"{label} must be a full lowercase Git SHA")
    return value


def validate_sha256(value: str, label: str) -> str:
    if len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise ValueError(f"{label} must be a lowercase SHA256")
    return value


def git_object_sha1(object_type: str, payload: bytes) -> str:
    digest = hashlib.sha1(usedforsecurity=False)
    digest.update(f"{object_type} {len(payload)}\0".encode("ascii"))
    digest.update(payload)
    return digest.hexdigest()


def validate_git_commit_object(
    source_commit_sha: str,
    commit_object_base64: str,
) -> tuple[bytes, str]:
    validate_full_sha(source_commit_sha, "Source commit")
    try:
        payload = base64.b64decode(commit_object_base64, validate=True)
    except (binascii.Error, ValueError, TypeError) as error:
        raise ValueError("Invalid base64 Git commit object") from error
    if git_object_sha1("commit", payload) != source_commit_sha:
        raise ValueError("Git commit object does not match the supplied exact SHA")
    tree_headers = [
        line[5:].decode("ascii")
        for line in payload.splitlines()
        if line.startswith(b"tree ")
    ]
    if len(tree_headers) != 1:
        raise ValueError("Git commit object must contain exactly one tree header")
    tree_sha = validate_full_sha(tree_headers[0], "Commit tree")
    return payload, tree_sha


def read_git_commit_object(source_commit_sha: str) -> tuple[bytes, str]:
    validate_full_sha(source_commit_sha, "Source commit")
    payload = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "cat-file", "commit", source_commit_sha],
        check=True,
        capture_output=True,
    ).stdout
    encoded = base64.b64encode(payload).decode("ascii")
    validated_payload, tree_sha = validate_git_commit_object(
        source_commit_sha, encoded
    )
    if validated_payload != payload:
        raise ValueError("Git commit object round-trip mismatch")
    return payload, tree_sha


def verify_repository_clean() -> None:
    status = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "status", "--porcelain=v1"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    if status:
        raise ValueError("Repository must be clean before source preparation")


def verify_repository_identity(source_commit_sha: str) -> None:
    validate_full_sha(source_commit_sha, "Source commit")
    head = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if head != source_commit_sha:
        raise ValueError(
            f"Repository HEAD mismatch: expected {source_commit_sha}, got {head}"
        )
    verify_repository_clean()


def git_blob_hashes(handle: Any, size: int) -> tuple[str, str]:
    git_digest = hashlib.sha1(usedforsecurity=False)
    git_digest.update(f"blob {size}\0".encode("ascii"))
    sha256_digest = hashlib.sha256()
    observed = 0
    for block in iter(lambda: handle.read(1024 * 1024), b""):
        observed += len(block)
        git_digest.update(block)
        sha256_digest.update(block)
    if observed != size:
        raise ValueError(f"Expected {size} bytes, read {observed}")
    return git_digest.hexdigest(), sha256_digest.hexdigest()


def canonical_inventory_sha256(entries: list[dict[str, Any]]) -> str:
    fields = [
        {
            "path": entry["path"],
            "mode": entry["mode"],
            "git_blob_sha1": entry["git_blob_sha1"],
            "size_bytes": entry["size_bytes"],
            "sha256": entry["sha256"],
        }
        for entry in entries
    ]
    payload = json.dumps(
        fields,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def canonical_git_blob_inventory_sha256(entries: list[dict[str, Any]]) -> str:
    fields = [
        {
            "path": entry["path"],
            "mode": entry["mode"],
            "git_blob_sha1": entry["git_blob_sha1"],
            "size_bytes": entry["size_bytes"],
        }
        for entry in entries
    ]
    payload = json.dumps(
        fields,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def validate_snapshot_path(value: str) -> str:
    path = Path(value)
    if (
        not value
        or "\\" in value
        or path.is_absolute()
        or value.startswith("/")
        or any(part in ("", ".", "..") for part in value.split("/"))
    ):
        raise ValueError(f"Unsafe snapshot path: {value!r}")
    return value


def require_outside_repository_output(path: Path) -> None:
    resolved = path.resolve()
    try:
        resolved.relative_to(REPO_ROOT.resolve())
    except ValueError:
        return
    raise ValueError(f"Source snapshot output must be outside the worktree: {path}")


def compute_git_tree_sha1(entries: list[dict[str, Any]]) -> str:
    root: dict[str, Any] = {}
    for entry in entries:
        path = validate_snapshot_path(entry["path"])
        mode = entry["mode"]
        if mode not in ("100644", "100755"):
            raise ValueError(f"Unsupported Git mode for {path}: {mode}")
        blob_sha = validate_full_sha(entry["git_blob_sha1"], "Git blob")
        node = root
        parts = path.split("/")
        for part in parts[:-1]:
            child = node.setdefault(part, {})
            if not isinstance(child, dict):
                raise ValueError(f"File/directory collision at {path}")
            node = child
        name = parts[-1]
        if name in node:
            raise ValueError(f"Duplicate snapshot path: {path}")
        node[name] = (mode, blob_sha)

    def hash_tree(node: dict[str, Any]) -> str:
        children: list[tuple[bytes, str, bytes]] = []
        for name, value in node.items():
            encoded_name = name.encode("utf-8")
            if isinstance(value, dict):
                mode = "40000"
                object_sha = hash_tree(value)
                sort_key = encoded_name + b"/"
            else:
                mode, object_sha = value
                sort_key = encoded_name
            record = (
                mode.encode("ascii")
                + b" "
                + encoded_name
                + b"\0"
                + bytes.fromhex(object_sha)
            )
            children.append((sort_key, name, record))
        content = b"".join(record for _, _, record in sorted(children))
        digest = hashlib.sha1(usedforsecurity=False)
        digest.update(f"tree {len(content)}\0".encode("ascii"))
        digest.update(content)
        return digest.hexdigest()

    return hash_tree(root)


def read_git_tree_entries(source_commit_sha: str) -> tuple[str, list[dict[str, Any]]]:
    validate_full_sha(source_commit_sha, "Source commit")
    tree_sha = subprocess.run(
        [
            "git",
            "-C",
            str(REPO_ROOT),
            "rev-parse",
            f"{source_commit_sha}^{{tree}}",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    output = subprocess.run(
        [
            "git",
            "-C",
            str(REPO_ROOT),
            "ls-tree",
            "-r",
            "-l",
            "-z",
            "--full-tree",
            source_commit_sha,
        ],
        check=True,
        capture_output=True,
    ).stdout
    entries: list[dict[str, Any]] = []
    for record in output.split(b"\0"):
        if not record:
            continue
        metadata, path_bytes = record.split(b"\t", 1)
        mode, object_type, object_sha, size = metadata.split(maxsplit=3)
        path = path_bytes.decode("utf-8")
        if object_type != b"blob" or mode not in (b"100644", b"100755"):
            raise ValueError(f"Unsupported Git tree entry: {record!r}")
        entries.append(
            {
                "path": validate_snapshot_path(path),
                "mode": mode.decode("ascii"),
                "git_blob_sha1": object_sha.decode("ascii"),
                "size_bytes": int(size),
            }
        )
    if compute_git_tree_sha1(entries) != tree_sha:
        raise ValueError("Git tree inventory does not reconstruct its tree SHA")
    return tree_sha, entries


def inspect_snapshot_archive(
    archive_path: Path,
    expected_entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    expected = {entry["path"]: entry for entry in expected_entries}
    observed: list[dict[str, Any]] = []
    with tarfile.open(archive_path, "r:*") as archive:
        members = archive.getmembers()
        for member in members:
            path = validate_snapshot_path(member.name.rstrip("/"))
            if member.isdir():
                continue
            if not member.isfile():
                raise ValueError(f"Snapshot contains non-file member: {member.name}")
            entry = expected.get(path)
            if entry is None:
                raise ValueError(f"Snapshot contains unexpected file: {path}")
            if member.size != entry["size_bytes"]:
                raise ValueError(f"Snapshot size mismatch for {path}")
            expected_executable = entry["mode"] == "100755"
            if bool(member.mode & 0o111) != expected_executable:
                raise ValueError(f"Snapshot executable mode mismatch for {path}")
            handle = archive.extractfile(member)
            if handle is None:
                raise ValueError(f"Cannot read snapshot member: {path}")
            blob_sha, content_sha = git_blob_hashes(handle, member.size)
            if blob_sha != entry["git_blob_sha1"]:
                raise ValueError(f"Snapshot Git blob mismatch for {path}")
            observed.append(
                {
                    **entry,
                    "sha256": content_sha,
                }
            )
    if set(expected) != {entry["path"] for entry in observed}:
        missing = sorted(set(expected) - {entry["path"] for entry in observed})
        raise ValueError(f"Snapshot is missing tracked files: {missing[:5]}")
    return sorted(observed, key=lambda entry: entry["path"])


def create_source_snapshot(
    source_commit_sha: str,
    snapshot_path: Path,
    snapshot_manifest: Path,
) -> dict[str, Any]:
    validate_full_sha(source_commit_sha, "Source commit")
    verify_repository_clean()
    snapshot_path = snapshot_path.resolve()
    snapshot_manifest = snapshot_manifest.resolve()
    require_outside_repository_output(snapshot_path)
    require_outside_repository_output(snapshot_manifest)
    assert_new_path(snapshot_path)
    assert_new_path(snapshot_manifest)
    commit_payload, commit_tree_sha = read_git_commit_object(source_commit_sha)
    tree_sha, git_entries = read_git_tree_entries(source_commit_sha)
    if tree_sha != commit_tree_sha:
        raise ValueError("Git commit object and tree inventory disagree")
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(REPO_ROOT),
            "-c",
            "core.autocrlf=false",
            "-c",
            "core.eol=lf",
            "archive",
            "--format=tar",
            f"--output={snapshot_path}",
            source_commit_sha,
        ],
        check=True,
    )
    entries = inspect_snapshot_archive(snapshot_path, git_entries)
    manifest = {
        "schema_version": SOURCE_SNAPSHOT_SCHEMA,
        "source_commit_sha": source_commit_sha,
        "source_commit_object_base64":
            base64.b64encode(commit_payload).decode("ascii"),
        "source_tree_sha": tree_sha,
        "source_archive_format": "git_archive_tar",
        "source_archive_sha256": sha256_file(snapshot_path),
        "source_archive_size_bytes": snapshot_path.stat().st_size,
        "tracked_file_count": len(entries),
        "git_blob_inventory_sha256":
            canonical_git_blob_inventory_sha256(entries),
        "inventory_sha256": canonical_inventory_sha256(entries),
        "entries": entries,
        "git_metadata_included": False,
    }
    write_new_text(
        snapshot_manifest,
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
    )
    return {
        "source_commit_sha": source_commit_sha,
        "source_tree_sha": tree_sha,
        "snapshot_path": str(snapshot_path),
        "snapshot_sha256": manifest["source_archive_sha256"],
        "snapshot_manifest": str(snapshot_manifest),
        "snapshot_manifest_sha256": sha256_file(snapshot_manifest),
        "tracked_file_count": len(entries),
    }


def load_and_validate_snapshot_manifest(
    source_commit_sha: str,
    snapshot_path: Path,
    snapshot_manifest: Path,
    snapshot_manifest_sha256: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    validate_full_sha(source_commit_sha, "Source commit")
    validate_sha256(snapshot_manifest_sha256, "Snapshot manifest SHA256")
    if sha256_file(snapshot_manifest) != snapshot_manifest_sha256:
        raise ValueError("Snapshot manifest SHA256 mismatch")
    manifest = json.loads(snapshot_manifest.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != SOURCE_SNAPSHOT_SCHEMA:
        raise ValueError("Unsupported source snapshot manifest schema")
    if manifest.get("source_archive_format") != "git_archive_tar":
        raise ValueError("Source snapshot must be a Git archive tar")
    if manifest.get("source_commit_sha") != source_commit_sha:
        raise ValueError("Snapshot manifest source commit mismatch")
    commit_object_base64 = manifest.get("source_commit_object_base64")
    if not isinstance(commit_object_base64, str):
        raise ValueError("Snapshot manifest Git commit object is missing")
    _, commit_tree_sha = validate_git_commit_object(
        source_commit_sha, commit_object_base64
    )
    if manifest.get("source_tree_sha") != commit_tree_sha:
        raise ValueError("Snapshot manifest tree differs from its Git commit object")
    if manifest.get("git_metadata_included") is not False:
        raise ValueError("Source snapshot must not contain Git metadata")
    entries = manifest.get("entries")
    if not isinstance(entries, list) or not entries:
        raise ValueError("Snapshot manifest entries are missing")
    required_entry_fields = {
        "path",
        "mode",
        "git_blob_sha1",
        "size_bytes",
        "sha256",
    }
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != required_entry_fields:
            raise ValueError("Snapshot manifest entry schema mismatch")
        if not isinstance(entry["size_bytes"], int) or entry["size_bytes"] < 0:
            raise ValueError("Snapshot manifest entry size is invalid")
        validate_sha256(entry["sha256"], "Snapshot file SHA256")
    if manifest.get("tracked_file_count") != len(entries):
        raise ValueError("Snapshot manifest file count mismatch")
    if entries != sorted(entries, key=lambda entry: entry["path"]):
        raise ValueError("Snapshot manifest entries must be path-sorted")
    if canonical_inventory_sha256(entries) != manifest.get("inventory_sha256"):
        raise ValueError("Snapshot manifest inventory SHA256 mismatch")
    git_blob_inventory_sha256 = canonical_git_blob_inventory_sha256(entries)
    if git_blob_inventory_sha256 != manifest.get("git_blob_inventory_sha256"):
        raise ValueError("Snapshot manifest Git blob inventory SHA256 mismatch")
    if compute_git_tree_sha1(entries) != commit_tree_sha:
        raise ValueError("Snapshot entries do not reconstruct the commit tree")
    if snapshot_path.stat().st_size != manifest.get("source_archive_size_bytes"):
        raise ValueError("Snapshot archive size mismatch")
    if sha256_file(snapshot_path) != manifest.get("source_archive_sha256"):
        raise ValueError("Snapshot archive SHA256 mismatch")
    observed = inspect_snapshot_archive(snapshot_path, entries)
    if observed != entries:
        raise ValueError("Snapshot archive content differs from its manifest")
    return manifest, entries


def verify_extracted_snapshot(
    source_root: Path,
    entries: list[dict[str, Any]],
) -> None:
    if not source_root.is_dir():
        raise FileNotFoundError(source_root)
    if (source_root / ".git").exists():
        raise ValueError("Snapshot source root must not contain Git metadata")
    expected = {entry["path"]: entry for entry in entries}
    observed_paths: set[str] = set()
    for path in source_root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(source_root).as_posix()
        if relative == "target" or relative.startswith("target/"):
            continue
        relative = validate_snapshot_path(relative)
        entry = expected.get(relative)
        if entry is None:
            raise ValueError(f"Unexpected extracted source file: {relative}")
        with path.open("rb") as handle:
            blob_sha, content_sha = git_blob_hashes(
                handle, path.stat().st_size
            )
        if path.stat().st_size != entry["size_bytes"]:
            raise ValueError(f"Extracted source size mismatch for {relative}")
        if blob_sha != entry["git_blob_sha1"]:
            raise ValueError(f"Extracted source Git blob mismatch for {relative}")
        if content_sha != entry["sha256"]:
            raise ValueError(f"Extracted source SHA256 mismatch for {relative}")
        if os.name != "nt":
            executable = bool(stat.S_IMODE(path.stat().st_mode) & 0o111)
            if executable != (entry["mode"] == "100755"):
                raise ValueError(
                    f"Extracted source executable mode mismatch for {relative}"
                )
        observed_paths.add(relative)
    if set(expected) != observed_paths:
        missing = sorted(set(expected) - observed_paths)
        raise ValueError(f"Extracted source is missing files: {missing[:5]}")


def verify_source_snapshot(
    source_commit_sha: str,
    source_root: Path,
    snapshot_path: Path,
    snapshot_manifest: Path,
    snapshot_manifest_sha256: str,
) -> dict[str, Any]:
    summary, entries = verify_source_snapshot_archive(
        source_commit_sha,
        snapshot_path=snapshot_path,
        snapshot_manifest=snapshot_manifest,
        snapshot_manifest_sha256=snapshot_manifest_sha256,
    )
    verify_extracted_snapshot(source_root, entries)
    return {**summary, "extracted_source_verified": True}


def verify_source_snapshot_archive(
    source_commit_sha: str,
    snapshot_path: Path,
    snapshot_manifest: Path,
    snapshot_manifest_sha256: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    manifest, entries = load_and_validate_snapshot_manifest(
        source_commit_sha,
        snapshot_path,
        snapshot_manifest,
        snapshot_manifest_sha256,
    )
    return (
        {
            "source_identity_mode": "exact_git_tree_snapshot",
            "source_commit_sha": source_commit_sha,
            "source_tree_sha": manifest["source_tree_sha"],
            "source_commit_object_verified": True,
            "snapshot_sha256": manifest["source_archive_sha256"],
            "snapshot_manifest_sha256": snapshot_manifest_sha256,
            "tracked_file_count": len(entries),
            "git_metadata_present": False,
            "source_archive_verified": True,
        },
        entries,
    )


def verify_source_identity(args: argparse.Namespace) -> dict[str, Any]:
    if args.source_identity_mode == "git":
        verify_repository_identity(args.source_commit_sha)
        tree_sha, entries = read_git_tree_entries(args.source_commit_sha)
        return {
            "source_identity_mode": "exact_clean_git_checkout",
            "source_commit_sha": args.source_commit_sha,
            "source_tree_sha": tree_sha,
            "tracked_file_count": len(entries),
        }
    required = {
        "source_snapshot": args.source_snapshot,
        "source_snapshot_manifest": args.source_snapshot_manifest,
        "source_snapshot_manifest_sha256":
            args.source_snapshot_manifest_sha256,
    }
    missing = [name for name, value in required.items() if value is None]
    if missing:
        raise ValueError(f"Snapshot identity arguments missing: {missing}")
    return verify_source_snapshot(
        args.source_commit_sha,
        args.source_root,
        args.source_snapshot,
        args.source_snapshot_manifest,
        args.source_snapshot_manifest_sha256,
    )


def current_input_sources(data_root: Path) -> dict[str, Path]:
    scenario = data_root / SCENARIO_RELATIVE
    supply = data_root / SUPPLY_RELATIVE
    return {
        "config/config_hong_kong_5pct_v2_activity_modechoice_50it.xml":
            scenario / CONFIG_NAME,
        "input/network.xml.gz": supply / "network.xml.gz",
        "input/transitSchedule_5pct.xml.gz":
            supply / "transitSchedule_5pct.xml.gz",
        "input/transitVehicles_10pct.xml.gz":
            supply / "transitVehicles_10pct.xml.gz",
        "input/plans_routed_5pct_v2.xml.gz":
            scenario / "plans_routed_5pct_v2.xml.gz",
        "input/facilities_5pct_v2.xml.gz":
            scenario / "facilities_5pct_v2.xml.gz",
        "input/privateVehicles_5pct.xml.gz":
            scenario / "privateVehicles_5pct.xml.gz",
    }


def verify_current_inputs(sources: dict[str, Path]) -> dict[str, str]:
    if set(sources) != set(EXPECTED_INPUT_SHA256):
        raise ValueError("Current input inventory differs from the Stage 8D lock")
    actual: dict[str, str] = {}
    for relative, source in sources.items():
        if not source.is_file():
            raise FileNotFoundError(source)
        normalized = source.as_posix()
        stale = [
            fragment
            for fragment in STALE_ACTIVE_INPUT_FRAGMENTS
            if fragment in normalized
        ]
        if stale:
            raise ValueError(
                f"Stale v1/pre-Ferry input is prohibited: {source}: {stale}"
            )
        digest = sha256_file(source)
        expected = EXPECTED_INPUT_SHA256[relative]
        if digest != expected:
            raise ValueError(
                f"Locked input checksum mismatch for {relative}: "
                f"expected {expected}, got {digest}"
            )
        actual[relative] = digest
    return actual


def verify_fat_jar(path: Path) -> tuple[str, list[str]]:
    if not path.is_file():
        raise FileNotFoundError(path)
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
    missing = [name for name in REQUIRED_RUNTIME_CLASSES if name not in names]
    if missing:
        raise ValueError(
            "Fat JAR is missing Stage 8C Taxi/PT/Car runtime classes: "
            + ", ".join(missing)
        )
    return sha256_file(path), list(REQUIRED_RUNTIME_CLASSES)


def assert_new_path(path: Path) -> None:
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite existing path: {path}")


def copy_new(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(source)
    assert_new_path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def write_new_text(path: Path, text: str, executable: bool = False) -> None:
    assert_new_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    if executable:
        path.chmod(0o750)


def select_smoke_person_ids(plans_path: Path, count: int) -> set[str]:
    heap: list[tuple[int, str]] = []
    with gzip.open(plans_path, "rb") as handle:
        for _, element in ET.iterparse(handle, events=("end",)):
            if element.tag != "person":
                continue
            person_id = element.attrib["id"]
            score = int.from_bytes(
                hashlib.sha256(person_id.encode("utf-8")).digest(),
                "big",
            )
            item = (-score, person_id)
            if len(heap) < count:
                heapq.heappush(heap, item)
            elif item > heap[0]:
                heapq.heapreplace(heap, item)
            element.clear()
    if len(heap) != count:
        raise ValueError(f"Requested {count} people, found only {len(heap)}")
    return {person_id for _, person_id in heap}


def write_smoke_plans(
    input_path: Path,
    output_path: Path,
    selected_ids: set[str],
) -> int:
    assert_new_path(output_path)
    written = 0
    with gzip.open(input_path, "rb") as source, gzip.open(
        output_path, "wt", encoding="utf-8", newline="\n"
    ) as destination:
        destination.write('<?xml version="1.0" encoding="utf-8"?>\n')
        destination.write(
            '<!DOCTYPE population SYSTEM '
            '"http://www.matsim.org/files/dtd/population_v6.dtd">\n\n'
        )
        destination.write("<population>\n")
        destination.write(
            '\t<attributes>\n'
            '\t\t<attribute name="coordinateReferenceSystem" '
            'class="java.lang.String">EPSG:32650</attribute>\n'
            '\t</attributes>\n'
        )
        for _, element in ET.iterparse(source, events=("end",)):
            if element.tag != "person":
                continue
            if element.attrib["id"] in selected_ids:
                destination.write(ET.tostring(element, encoding="unicode"))
                destination.write("\n")
                written += 1
            element.clear()
        destination.write("</population>\n")
    if written != len(selected_ids):
        raise ValueError(f"Expected {len(selected_ids)} people, wrote {written}")
    with gzip.open(output_path, "rb") as handle:
        root = ET.parse(handle).getroot()
    if len(root.findall("./person")) != written:
        raise ValueError("Smoke plans XML verification failed")
    return written


def set_param(module: ET.Element, name: str, value: str) -> None:
    for param in module.findall("./param"):
        if param.attrib.get("name") == name:
            param.set("value", value)
            return
    ET.SubElement(module, "param", {"name": name, "value": value})


def get_module(root: ET.Element, name: str) -> ET.Element:
    for module in root.findall("./module"):
        if module.attrib.get("name") == name:
            return module
    return ET.SubElement(root, "module", {"name": name})


def write_server_config(
    template: Path,
    output: Path,
    release_root: str,
    plans_name: str,
    output_name: str,
    last_iteration: int,
) -> None:
    root = ET.parse(template).getroot()
    paths = {
        ("network", "inputNetworkFile"): "input/network.xml.gz",
        ("plans", "inputPlansFile"): f"input/{plans_name}",
        ("facilities", "inputFacilitiesFile"):
            "input/facilities_5pct_v2.xml.gz",
        ("vehicles", "vehiclesFile"): "input/privateVehicles_5pct.xml.gz",
        ("transit", "transitScheduleFile"): "input/transitSchedule_5pct.xml.gz",
        ("transit", "vehiclesFile"): "input/transitVehicles_10pct.xml.gz",
    }
    for (module_name, param_name), relative in paths.items():
        set_param(
            get_module(root, module_name),
            param_name,
            f"{release_root}/{relative}",
        )
    controller = get_module(root, "controller")
    set_param(controller, "firstIteration", "0")
    set_param(controller, "lastIteration", str(last_iteration))
    set_param(
        controller,
        "outputDirectory",
        f"{release_root}/runs/{output_name}/output",
    )
    set_param(controller, "overwriteFiles", "failIfDirectoryExists")
    interval = "1" if last_iteration <= 1 else "10"
    set_param(controller, "writeEventsInterval", interval)
    set_param(controller, "writePlansInterval", interval)
    set_param(controller, "writeSnapshotsInterval", "0")

    assert_new_path(output)
    with output.open("wt", encoding="utf-8", newline="\n") as handle:
        handle.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        handle.write(
            '<!DOCTYPE config SYSTEM '
            '"http://www.matsim.org/files/dtd/config_v2.dtd">\n'
        )
        handle.write(ET.tostring(root, encoding="unicode"))
        handle.write("\n")


def worker_script(release_root: str, config_name: str) -> str:
    return f"""#!/usr/bin/env bash
set -euo pipefail
ROOT={release_root!r}
case "$(readlink -m "$ROOT")" in
  /mnt/DiskM/by/*) ;;
  *) printf '%s\\n' "Unsafe ROOT: $ROOT" >&2; exit 90 ;;
esac
export HOME="$ROOT/home"
export TMPDIR="$ROOT/tmp"
export XDG_CACHE_HOME="$ROOT/home/.cache"
export JAVA_HOME="$ROOT/runtime/jdk-25"
export PATH="$JAVA_HOME/bin:/usr/bin:/bin"
export JAVA_TOOL_OPTIONS="-Djava.io.tmpdir=$ROOT/tmp -Djava.util.prefs.userRoot=$ROOT/home/.java"
set +e
/usr/bin/time -v "$JAVA_HOME/bin/java" -Xms16g -Xmx96g \\
  -cp "$ROOT/app/matsim-example-project-0.0.1-SNAPSHOT.jar" \\
  org.matsim.project.RunHongKong5Pct \\
  "$ROOT/config/{config_name}" unused --simulate
rc=$?
set -e
set -o noclobber
printf '%s\\n' "$rc" > "$JOB_DIR/exit_code.txt"
exit "$rc"
"""


def launcher_script(release_root: str, job_name: str, worker_name: str) -> str:
    return f"""#!/usr/bin/env bash
set -euo pipefail
set -o noclobber
ROOT={release_root!r}
case "$(readlink -m "$ROOT")" in
  /mnt/DiskM/by/*) ;;
  *) printf '%s\\n' "Unsafe ROOT: $ROOT" >&2; exit 90 ;;
esac
JOB_DIR="$ROOT/runs/{job_name}"
test ! -e "$JOB_DIR"
mkdir "$JOB_DIR"
export JOB_DIR
LOG="$JOB_DIR/stdout_stderr.log"
PID_FILE="$JOB_DIR/pid.txt"
test ! -e "$LOG"
test ! -e "$PID_FILE"
nohup "$ROOT/scripts/{worker_name}" > "$LOG" 2>&1 &
pid=$!
printf '%s\\n' "$pid" > "$PID_FILE"
printf 'started pid=%s job=%s\\n' "$pid" "$JOB_DIR"
"""


def status_script(release_root: str, job_name: str) -> str:
    return f"""#!/usr/bin/env bash
set -euo pipefail
ROOT={release_root!r}
JOB_DIR="$ROOT/runs/{job_name}"
case "$(readlink -m "$JOB_DIR")" in
  /mnt/DiskM/by/*) ;;
  *) printf '%s\\n' "Unsafe JOB_DIR: $JOB_DIR" >&2; exit 90 ;;
esac
if test -f "$JOB_DIR/exit_code.txt"; then
  printf 'completed exit_code='
  cat "$JOB_DIR/exit_code.txt"
elif test -f "$JOB_DIR/pid.txt"; then
  pid="$(cat "$JOB_DIR/pid.txt")"
  if kill -0 "$pid" 2>/dev/null; then
    printf 'running pid=%s\\n' "$pid"
  else
    printf 'process_not_running_without_exit_code pid=%s\\n' "$pid"
  fi
else
  printf 'not_started\\n'
fi
if test -f "$JOB_DIR/stdout_stderr.log"; then
  tail -30 "$JOB_DIR/stdout_stderr.log"
fi
"""


def validate_release_root(value: str) -> str:
    normalized = value.rstrip("/")
    if not normalized.startswith("/mnt/DiskM/by/"):
        raise ValueError("Release root must be below /mnt/DiskM/by")
    return normalized


def build_bundle(args: argparse.Namespace) -> dict[str, Any]:
    source_identity = verify_source_identity(args)
    release_root = validate_release_root(args.release_root)
    assert_new_path(args.staging_dir)
    assert_new_path(args.bundle_path)
    assert_new_path(args.deployment_manifest)
    if args.build_command != SERVER_BUILD_COMMAND:
        raise ValueError(
            f"Server build command must be exact: {SERVER_BUILD_COMMAND}"
        )
    if args.matsim_version != MATSIM_VERSION:
        raise ValueError(
            f"MATSim version must be {MATSIM_VERSION}, got {args.matsim_version}"
        )
    if not args.java_version.startswith("25"):
        raise ValueError("The server build must use Linux JDK 25")
    jar_hash, runtime_classes = verify_fat_jar(args.fat_jar)
    if not args.jdk_archive.is_file():
        raise FileNotFoundError(args.jdk_archive)
    jdk_hash = sha256_file(args.jdk_archive)
    if jdk_hash != args.jdk_sha256:
        raise ValueError(f"JDK checksum mismatch: {jdk_hash}")
    current_sources = current_input_sources(args.data_root)
    input_hashes = verify_current_inputs(current_sources)
    args.staging_dir.mkdir(parents=True)
    for relative in (
        "app",
        "archives",
        "config",
        "home",
        "input",
        "logs",
        "manifests",
        "runtime/jdk-25",
        "runs",
        "scripts",
        "tmp",
    ):
        (args.staging_dir / relative).mkdir(parents=True, exist_ok=False)

    scenario = args.data_root / SCENARIO_RELATIVE
    sources = {
        "app/matsim-example-project-0.0.1-SNAPSHOT.jar": args.fat_jar,
        "archives/OpenJDK25U-jdk_x64_linux_hotspot_25.0.3_9.tar.gz": args.jdk_archive,
        **{
            relative: source
            for relative, source in current_sources.items()
            if not relative.startswith("config/")
        },
    }
    for relative, source in sources.items():
        copy_new(source, args.staging_dir / relative)

    formal_plans = args.staging_dir / "input/plans_routed_5pct_v2.xml.gz"
    selected = select_smoke_person_ids(formal_plans, SMOKE_PERSON_COUNT)
    smoke_count = write_smoke_plans(
        formal_plans,
        args.staging_dir / "input/plans_smoke_0p1.xml.gz",
        selected,
    )
    write_server_config(
        scenario / CONFIG_NAME,
        args.staging_dir / "config/config_smoke_qsim.xml",
        release_root,
        "plans_smoke_0p1.xml.gz",
        "smoke_qsim_v1",
        0,
    )
    write_server_config(
        scenario / CONFIG_NAME,
        args.staging_dir / "config/config_formal_50it.xml",
        release_root,
        "plans_routed_5pct_v2.xml.gz",
        "formal_50it_v1",
        50,
    )

    scripts = {
        "scripts/smoke_worker.sh": worker_script(
            release_root, "config_smoke_qsim.xml"
        ),
        "scripts/formal_worker.sh": worker_script(
            release_root, "config_formal_50it.xml"
        ),
        "scripts/run_smoke.sh": launcher_script(
            release_root, "smoke_qsim_v1", "smoke_worker.sh"
        ),
        "scripts/run_formal_50it.sh": launcher_script(
            release_root, "formal_50it_v1", "formal_worker.sh"
        ),
        "scripts/status_smoke.sh": status_script(
            release_root, "smoke_qsim_v1"
        ),
        "scripts/status_formal_50it.sh": status_script(
            release_root, "formal_50it_v1"
        ),
    }
    for relative, content in scripts.items():
        write_new_text(args.staging_dir / relative, content, executable=True)

    source_rows: list[dict[str, Any]] = []
    for path in sorted(args.staging_dir.rglob("*")):
        if not path.is_file() or "manifests" in path.parts:
            continue
        relative = path.relative_to(args.staging_dir).as_posix()
        source = str(sources.get(relative, "generated"))
        source_rows.append(
            {
                "relative_path": relative,
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
                "source": source,
            }
        )
    manifest_path = args.staging_dir / "manifests/SOURCE_MANIFEST.csv"
    with manifest_path.open("x", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(source_rows[0]))
        writer.writeheader()
        writer.writerows(source_rows)

    metadata = {
        "source_commit_sha": args.source_commit_sha,
        "source_identity": source_identity,
        "release_root": release_root,
        "fat_jar_sha256": jar_hash,
        "required_runtime_classes": runtime_classes,
        "build_command": args.build_command,
        "prepare_command": shlex.join([sys.executable, *sys.argv]),
        "java_version": args.java_version,
        "maven_version": args.maven_version,
        "matsim_version": args.matsim_version,
        "locked_input_sha256": input_hashes,
        "locked_config_template": str(
            current_sources[
                "config/config_hong_kong_5pct_v2_activity_modechoice_50it.xml"
            ]
        ),
        "smoke_person_count": smoke_count,
        "formal_person_count": 385_820,
        "flow_capacity_factor": 0.1,
        "storage_capacity_factor": 0.1,
        "bus_pcu": 0.125,
        "gmb_pcu": 0.075,
        "transit_departures": 159_967,
        "formal_iterations": 50,
        "formal_output_interval": 10,
        "formal_run_started_by_deployment": False,
        "jdk_sha256": jdk_hash,
        "append_only_remote_policy": True,
        "stale_v1_or_pre_ferry_input_allowed": False,
    }
    write_new_text(
        args.staging_dir / "manifests/DEPLOYMENT_METADATA.json",
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
    )
    checksums = []
    for path in sorted(args.staging_dir.rglob("*")):
        if path.is_file() and path.name != "SHA256SUMS.txt":
            checksums.append(
                f"{sha256_file(path)}  {path.relative_to(args.staging_dir).as_posix()}"
            )
    write_new_text(
        args.staging_dir / "manifests/SHA256SUMS.txt",
        "\n".join(checksums) + "\n",
    )

    def normalize_tar_permissions(info: tarfile.TarInfo) -> tarfile.TarInfo:
        if info.isdir():
            info.mode = 0o750
        elif info.name.startswith("scripts/") and info.name.endswith(".sh"):
            info.mode = 0o750
        else:
            info.mode = 0o640
        return info

    with tarfile.open(args.bundle_path, "x") as archive:
        for child in sorted(args.staging_dir.iterdir()):
            archive.add(
                child,
                arcname=child.name,
                recursive=True,
                filter=normalize_tar_permissions,
            )
    bundle_summary = {
        **metadata,
        "staging_dir": str(args.staging_dir),
        "bundle_path": str(args.bundle_path),
        "bundle_size_bytes": args.bundle_path.stat().st_size,
        "bundle_sha256": sha256_file(args.bundle_path),
        "release_file_count": sum(
            path.is_file() for path in args.staging_dir.rglob("*")
        ),
    }
    deployment_manifest = {
        "schema_version":
            "hong_kong_exact_sha_server_bundle_deployment_manifest_v1",
        "status": "prepared_not_uploaded_not_run",
        "prepared_at_utc": datetime.now(timezone.utc).isoformat(),
        **bundle_summary,
        "deployment_manifest_path": str(args.deployment_manifest),
        "server_upload_performed": False,
        "server_run_performed": False,
    }
    write_new_text(
        args.deployment_manifest,
        json.dumps(deployment_manifest, ensure_ascii=False, indent=2) + "\n",
    )
    print(json.dumps(bundle_summary, ensure_ascii=False, indent=2))
    return bundle_summary


def add_bundle_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--source-commit-sha", required=True)
    parser.add_argument(
        "--source-identity-mode",
        choices=("git", "snapshot"),
        default="git",
    )
    parser.add_argument("--source-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--source-snapshot", type=Path)
    parser.add_argument("--source-snapshot-manifest", type=Path)
    parser.add_argument("--source-snapshot-manifest-sha256")
    parser.add_argument("--fat-jar", type=Path, required=True)
    parser.add_argument("--jdk-archive", type=Path, required=True)
    parser.add_argument(
        "--jdk-sha256",
        default="69264a7a211bf5029830d07bc3370f879769d62ebc5b5488e90c9343a2da0e1f",
    )
    parser.add_argument("--release-root", required=True)
    parser.add_argument("--staging-dir", type=Path, required=True)
    parser.add_argument("--bundle-path", type=Path, required=True)
    parser.add_argument("--deployment-manifest", type=Path, required=True)
    parser.add_argument("--build-command", default=SERVER_BUILD_COMMAND)
    parser.add_argument("--java-version", required=True)
    parser.add_argument("--maven-version", required=True)
    parser.add_argument("--matsim-version", default=MATSIM_VERSION)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    snapshot = commands.add_parser(
        "create-source-snapshot",
        help="Create a deterministic git-archive snapshot and provenance manifest",
    )
    snapshot.add_argument("--source-commit-sha", required=True)
    snapshot.add_argument("--snapshot-path", type=Path, required=True)
    snapshot.add_argument("--snapshot-manifest", type=Path, required=True)
    verifier = commands.add_parser(
        "verify-source-snapshot",
        help="Verify archive, manifest, Git tree and extracted source without .git",
    )
    verifier.add_argument("--source-commit-sha", required=True)
    verifier.add_argument("--source-root", type=Path)
    verifier.add_argument("--source-snapshot", type=Path, required=True)
    verifier.add_argument("--source-snapshot-manifest", type=Path, required=True)
    verifier.add_argument(
        "--source-snapshot-manifest-sha256",
        required=True,
    )
    bundle = commands.add_parser(
        "build-bundle",
        help="Build the deployment bundle after exact source identity validation",
    )
    add_bundle_arguments(bundle)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "create-source-snapshot":
        result = create_source_snapshot(
            args.source_commit_sha,
            args.snapshot_path,
            args.snapshot_manifest,
        )
    elif args.command == "verify-source-snapshot":
        if args.source_root is None:
            result, _ = verify_source_snapshot_archive(
                args.source_commit_sha,
                args.source_snapshot,
                args.source_snapshot_manifest,
                args.source_snapshot_manifest_sha256,
            )
        else:
            result = verify_source_snapshot(
                args.source_commit_sha,
                args.source_root,
                args.source_snapshot,
                args.source_snapshot_manifest,
                args.source_snapshot_manifest_sha256,
            )
    else:
        result = build_bundle(args)
    if args.command != "build-bundle":
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
