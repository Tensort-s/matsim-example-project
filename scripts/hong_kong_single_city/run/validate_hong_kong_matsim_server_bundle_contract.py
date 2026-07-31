#!/usr/bin/env python3
"""Validate the Stage 8D bundle contract without building or contacting a server."""

from __future__ import annotations

import importlib.util
import io
import json
import shutil
import tarfile
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


def expect_rejection(action: object, label: str) -> bool:
    try:
        action()
    except (FileNotFoundError, KeyError, OSError, ValueError):
        return True
    raise AssertionError(f"Invalid snapshot was accepted: {label}")


def create_fixture_snapshot(
    preparer: ModuleType,
    temporary: Path,
) -> dict[str, object]:
    source_root = temporary / "source"
    (source_root / "src").mkdir(parents=True)
    files = {
        "pom.xml": b"<project/>\n",
        "src/run.sh": b"#!/usr/bin/env bash\nprintf 'fixture\\n'\n",
    }
    entries = []
    for relative, content in files.items():
        path = source_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        mode = "100755" if relative.endswith(".sh") else "100644"
        if mode == "100755":
            path.chmod(0o755)
        with path.open("rb") as handle:
            blob_sha, content_sha = preparer.git_blob_hashes(
                handle, len(content)
            )
        entries.append(
            {
                "path": relative,
                "mode": mode,
                "git_blob_sha1": blob_sha,
                "size_bytes": len(content),
                "sha256": content_sha,
            }
        )
    entries.sort(key=lambda entry: entry["path"])
    tree_sha = preparer.compute_git_tree_sha1(entries)
    archive_path = temporary / "source.tar"
    with tarfile.open(archive_path, "w") as archive:
        for entry in entries:
            content = files[entry["path"]]
            member = tarfile.TarInfo(entry["path"])
            member.size = len(content)
            member.mode = 0o755 if entry["mode"] == "100755" else 0o644
            member.mtime = 0
            archive.addfile(member, io.BytesIO(content))
    source_commit_sha = "1" * 40
    manifest = {
        "schema_version": preparer.SOURCE_SNAPSHOT_SCHEMA,
        "source_commit_sha": source_commit_sha,
        "source_tree_sha": tree_sha,
        "source_archive_format": "git_archive_tar",
        "source_archive_sha256": preparer.sha256_file(archive_path),
        "source_archive_size_bytes": archive_path.stat().st_size,
        "tracked_file_count": len(entries),
        "git_blob_inventory_sha256":
            preparer.canonical_git_blob_inventory_sha256(entries),
        "inventory_sha256": preparer.canonical_inventory_sha256(entries),
        "entries": entries,
        "git_metadata_included": False,
    }
    manifest_path = temporary / "source-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return {
        "source_root": source_root,
        "source_commit_sha": source_commit_sha,
        "tree_sha": tree_sha,
        "archive_path": archive_path,
        "manifest_path": manifest_path,
        "manifest_sha256": preparer.sha256_file(manifest_path),
        "manifest": manifest,
        "files": files,
        "expected_identity": {
            "expected_commit_sha": source_commit_sha,
            "expected_tree_sha": tree_sha,
            "expected_file_count": len(entries),
            "expected_git_blob_inventory_sha256":
                manifest["git_blob_inventory_sha256"],
        },
    }


def main() -> None:
    preparer = load_preparer()
    locked_tree_sha, locked_tree_entries = preparer.read_git_tree_entries(
        preparer.LOCKED_SNAPSHOT_SOURCE_COMMIT_SHA
    )
    if locked_tree_sha != preparer.LOCKED_SNAPSHOT_SOURCE_TREE_SHA:
        raise AssertionError("Locked source commit tree identity changed")
    locked_git_blob_inventory_sha256 = (
        preparer.canonical_git_blob_inventory_sha256(locked_tree_entries)
    )
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
        fixture = create_fixture_snapshot(preparer, temporary / "snapshot-fixture")
        valid_archive, _ = preparer.verify_source_snapshot_archive(
            fixture["source_commit_sha"],
            fixture["archive_path"],
            fixture["manifest_path"],
            fixture["manifest_sha256"],
            **fixture["expected_identity"],
        )
        valid_snapshot = preparer.verify_source_snapshot(
            fixture["source_commit_sha"],
            fixture["source_root"],
            fixture["archive_path"],
            fixture["manifest_path"],
            fixture["manifest_sha256"],
            **fixture["expected_identity"],
        )
        wrong_sha_rejected = expect_rejection(
            lambda: preparer.verify_source_snapshot(
                "2" * 40,
                fixture["source_root"],
                fixture["archive_path"],
                fixture["manifest_path"],
                fixture["manifest_sha256"],
                **fixture["expected_identity"],
            ),
            "wrong source commit",
        )
        wrong_tree_manifest = temporary / "wrong-tree-manifest.json"
        wrong_tree = dict(fixture["manifest"])
        wrong_tree["source_tree_sha"] = "0" * 40
        wrong_tree_manifest.write_text(
            json.dumps(wrong_tree, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        wrong_tree_rejected = expect_rejection(
            lambda: preparer.verify_source_snapshot(
                fixture["source_commit_sha"],
                fixture["source_root"],
                fixture["archive_path"],
                wrong_tree_manifest,
                preparer.sha256_file(wrong_tree_manifest),
                **fixture["expected_identity"],
            ),
            "wrong source tree",
        )
        tampered_file = fixture["source_root"] / "pom.xml"
        tampered_file.write_bytes(b"<project tampered='true'/>\n")
        extracted_tampering_rejected = expect_rejection(
            lambda: preparer.verify_source_snapshot(
                fixture["source_commit_sha"],
                fixture["source_root"],
                fixture["archive_path"],
                fixture["manifest_path"],
                fixture["manifest_sha256"],
                **fixture["expected_identity"],
            ),
            "extracted source tampering",
        )
        tampered_file.write_bytes(fixture["files"]["pom.xml"])
        tampered_archive = temporary / "tampered-source.tar"
        shutil.copy2(fixture["archive_path"], tampered_archive)
        with tampered_archive.open("ab") as handle:
            handle.write(b"tampering")
        archive_tampering_rejected = expect_rejection(
            lambda: preparer.verify_source_snapshot(
                fixture["source_commit_sha"],
                fixture["source_root"],
                tampered_archive,
                fixture["manifest_path"],
                fixture["manifest_sha256"],
                **fixture["expected_identity"],
            ),
            "snapshot archive tampering",
        )
        wrong_manifest_hash_rejected = expect_rejection(
            lambda: preparer.verify_source_snapshot(
                fixture["source_commit_sha"],
                fixture["source_root"],
                fixture["archive_path"],
                fixture["manifest_path"],
                "0" * 64,
                **fixture["expected_identity"],
            ),
            "wrong manifest hash",
        )
        worktree_output_rejected = expect_rejection(
            lambda: preparer.require_outside_repository_output(
                REPO_ROOT / "prohibited-source-snapshot.tar"
            ),
            "source snapshot output inside the Git worktree",
        )
        prior_snapshot_sha_rejected = expect_rejection(
            lambda: preparer.create_source_snapshot(
                preparer.PRIOR_SNAPSHOT_SOURCE_COMMIT_SHA,
                temporary / "prohibited-prior-source.tar",
                temporary / "prohibited-prior-source-manifest.json",
            ),
            "prior snapshot source SHA",
        )
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
        "locked_snapshot_source_commit_sha":
            preparer.LOCKED_SNAPSHOT_SOURCE_COMMIT_SHA,
        "locked_snapshot_source_tree_sha": locked_tree_sha,
        "locked_snapshot_tracked_file_count": len(locked_tree_entries),
        "locked_snapshot_git_blob_inventory_sha256":
            locked_git_blob_inventory_sha256,
        "locked_snapshot_anchor_fixture": {
            "generated_from_git": True,
            "source_commit_sha": preparer.LOCKED_SNAPSHOT_SOURCE_COMMIT_SHA,
            "source_tree_sha": locked_tree_sha,
            "tracked_file_count": len(locked_tree_entries),
            "git_blob_inventory_sha256":
                locked_git_blob_inventory_sha256,
        },
        "locked_git_tree_reconstruction_passed": True,
        "valid_snapshot_fixture_accepted": bool(valid_snapshot),
        "valid_snapshot_archive_accepted_before_extraction":
            bool(valid_archive),
        "wrong_snapshot_sha_rejected": wrong_sha_rejected,
        "wrong_snapshot_tree_rejected": wrong_tree_rejected,
        "snapshot_archive_tampering_rejected": archive_tampering_rejected,
        "extracted_source_tampering_rejected": extracted_tampering_rejected,
        "wrong_snapshot_manifest_hash_rejected":
            wrong_manifest_hash_rejected,
        "snapshot_output_inside_worktree_rejected": worktree_output_rejected,
        "prior_snapshot_source_sha_rejected": prior_snapshot_sha_rejected,
        "server_access_performed": False,
        "bundle_built": False,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
