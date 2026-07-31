#!/usr/bin/env python3
"""Validate the Stage 8D bundle contract without building or contacting a server."""

from __future__ import annotations

import base64
import importlib.util
import io
import json
import shutil
import tarfile
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from types import ModuleType, SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parents[3]
PREPARER_PATH = Path(__file__).with_name(
    "prepare_hong_kong_matsim_server_bundle.py"
)
DATA_ROOT = Path(r"F:\Matsim\matsim-example-project\data")
RELEASE_ROOT = "/mnt/DiskM/by/stage8d_contract_validation_not_deployed"
EXACT_INPUT_COMMIT_SHA = "c9fc2410fd329c9aceef16b3b7ce627bb74dedb6"
PRIOR_CONTROL_COMMIT_SHA = "6ce087af803da1a4b21717c1e0073ce4a04c608a"
PACK_CONTRACT_INPUT_SHA = "7cb827453c7327d0b3636a7f594091523309309f"


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
    raise AssertionError(f"Invalid contract was accepted: {label}")


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
    commit_payload = (
        f"tree {tree_sha}\n"
        "author Stage8D Fixture <fixture@example.invalid> 0 +0000\n"
        "committer Stage8D Fixture <fixture@example.invalid> 0 +0000\n"
        "\n"
        "deterministic snapshot fixture\n"
    ).encode("utf-8")
    source_commit_sha = preparer.git_object_sha1("commit", commit_payload)
    manifest = {
        "schema_version": preparer.SOURCE_SNAPSHOT_SCHEMA,
        "source_commit_sha": source_commit_sha,
        "source_commit_object_base64":
            base64.b64encode(commit_payload).decode("ascii"),
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
    }


def main() -> None:
    preparer = load_preparer()
    exact_commit_payload, exact_commit_tree_sha = (
        preparer.read_git_commit_object(EXACT_INPUT_COMMIT_SHA)
    )
    exact_tree_sha, exact_tree_entries = preparer.read_git_tree_entries(
        EXACT_INPUT_COMMIT_SHA
    )
    if exact_tree_sha != exact_commit_tree_sha:
        raise AssertionError("Exact input commit object and tree inventory disagree")
    exact_git_blob_inventory_sha256 = (
        preparer.canonical_git_blob_inventory_sha256(exact_tree_entries)
    )
    sources = preparer.current_input_sources(DATA_ROOT)
    hashes = preparer.verify_current_inputs(sources)
    canonical_sources, canonical_contract = preparer.resolve_input_contract(
        SimpleNamespace(
            data_root=DATA_ROOT,
            data_root_mode="canonical_project_data_root",
            locked_input_pack_manifest=None,
            locked_input_pack_manifest_sha256=None,
            source_commit_sha=PACK_CONTRACT_INPUT_SHA,
            source_root=REPO_ROOT,
        )
    )
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
        )
        valid_snapshot = preparer.verify_source_snapshot(
            fixture["source_commit_sha"],
            fixture["source_root"],
            fixture["archive_path"],
            fixture["manifest_path"],
            fixture["manifest_sha256"],
        )
        wrong_sha_rejected = expect_rejection(
            lambda: preparer.verify_source_snapshot(
                "2" * 40,
                fixture["source_root"],
                fixture["archive_path"],
                fixture["manifest_path"],
                fixture["manifest_sha256"],
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
            ),
            "wrong manifest hash",
        )
        worktree_output_rejected = expect_rejection(
            lambda: preparer.require_outside_repository_output(
                REPO_ROOT / "prohibited-source-snapshot.tar"
            ),
            "source snapshot output inside the Git worktree",
        )
        prior_commit_payload, _ = preparer.read_git_commit_object(
            PRIOR_CONTROL_COMMIT_SHA
        )
        prior_snapshot_sha_rejected = expect_rejection(
            lambda: preparer.validate_git_commit_object(
                EXACT_INPUT_COMMIT_SHA,
                base64.b64encode(prior_commit_payload).decode("ascii"),
            ),
            "prior commit object under the current formal exact SHA",
        )
        tampered_commit_manifest = temporary / "tampered-commit-manifest.json"
        tampered_commit = dict(fixture["manifest"])
        tampered_payload = base64.b64decode(
            tampered_commit["source_commit_object_base64"]
        ) + b"tampering"
        tampered_commit["source_commit_object_base64"] = (
            base64.b64encode(tampered_payload).decode("ascii")
        )
        tampered_commit_manifest.write_text(
            json.dumps(tampered_commit, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        commit_object_tampering_rejected = expect_rejection(
            lambda: preparer.verify_source_snapshot(
                fixture["source_commit_sha"],
                fixture["source_root"],
                fixture["archive_path"],
                tampered_commit_manifest,
                preparer.sha256_file(tampered_commit_manifest),
            ),
            "tampered Git commit object",
        )
        pack_root = temporary / "external-locked-input-pack"
        pack_manifest = temporary / "external-locked-input-pack.json"
        pack_created = preparer.create_locked_input_pack(
            PACK_CONTRACT_INPUT_SHA,
            DATA_ROOT,
            pack_root,
            pack_manifest,
        )
        pack_manifest_inside_root_rejected = expect_rejection(
            lambda: preparer.create_locked_input_pack(
                PACK_CONTRACT_INPUT_SHA,
                DATA_ROOT,
                temporary / "prohibited-nested-pack",
                temporary / "prohibited-nested-pack/manifest.json",
            ),
            "locked-input-pack manifest inside pack root",
        )
        pack_manifest_sha256 = preparer.sha256_file(pack_manifest)
        valid_pack_sources, valid_pack = preparer.verify_locked_input_pack(
            PACK_CONTRACT_INPUT_SHA,
            pack_root,
            pack_manifest,
            pack_manifest_sha256,
        )
        resolved_pack_sources, resolved_pack = preparer.resolve_input_contract(
            SimpleNamespace(
                data_root=pack_root,
                data_root_mode=preparer.EXTERNAL_LOCKED_INPUT_PACK_MODE,
                locked_input_pack_manifest=pack_manifest,
                locked_input_pack_manifest_sha256=pack_manifest_sha256,
                source_commit_sha=PACK_CONTRACT_INPUT_SHA,
                source_root=REPO_ROOT,
            )
        )
        missing_pack_manifest_rejected = expect_rejection(
            lambda: preparer.resolve_input_contract(
                SimpleNamespace(
                    data_root=pack_root,
                    data_root_mode=preparer.EXTERNAL_LOCKED_INPUT_PACK_MODE,
                    locked_input_pack_manifest=None,
                    locked_input_pack_manifest_sha256=None,
                    source_commit_sha=PACK_CONTRACT_INPUT_SHA,
                    source_root=REPO_ROOT,
                )
            ),
            "missing locked-input-pack manifest",
        )
        pack_inside_source_root_rejected = expect_rejection(
            lambda: preparer.resolve_input_contract(
                SimpleNamespace(
                    data_root=REPO_ROOT / "prohibited-input-pack",
                    data_root_mode=preparer.EXTERNAL_LOCKED_INPUT_PACK_MODE,
                    locked_input_pack_manifest=pack_manifest,
                    locked_input_pack_manifest_sha256=pack_manifest_sha256,
                    source_commit_sha=PACK_CONTRACT_INPUT_SHA,
                    source_root=REPO_ROOT,
                )
            ),
            "locked-input pack inside source root",
        )
        wrong_pack_manifest_hash_rejected = expect_rejection(
            lambda: preparer.verify_locked_input_pack(
                PACK_CONTRACT_INPUT_SHA,
                pack_root,
                pack_manifest,
                "0" * 64,
            ),
            "wrong locked-input-pack manifest hash",
        )
        wrong_pack_source_sha_rejected = expect_rejection(
            lambda: preparer.verify_locked_input_pack(
                "f" * 40,
                pack_root,
                pack_manifest,
                pack_manifest_sha256,
            ),
            "wrong locked-input-pack source SHA",
        )
        mutation_relative = "input/privateVehicles_5pct.xml.gz"
        mutation_path = pack_root / mutation_relative
        held_path = temporary / "held-privateVehicles_5pct.xml.gz"
        shutil.move(mutation_path, held_path)
        missing_pack_file_rejected = expect_rejection(
            lambda: preparer.verify_locked_input_pack(
                PACK_CONTRACT_INPUT_SHA,
                pack_root,
                pack_manifest,
                pack_manifest_sha256,
            ),
            "missing locked input",
        )
        shutil.move(held_path, mutation_path)
        with mutation_path.open("ab") as handle:
            handle.write(b"tampering")
        mismatched_pack_file_rejected = expect_rejection(
            lambda: preparer.verify_locked_input_pack(
                PACK_CONTRACT_INPUT_SHA,
                pack_root,
                pack_manifest,
                pack_manifest_sha256,
            ),
            "mismatched locked input hash",
        )
        shutil.copy2(sources[mutation_relative], mutation_path)
        extra_path = pack_root / "input/old-v1-input.xml.gz"
        extra_path.write_bytes(b"prohibited")
        extra_pack_file_rejected = expect_rejection(
            lambda: preparer.verify_locked_input_pack(
                PACK_CONTRACT_INPUT_SHA,
                pack_root,
                pack_manifest,
                pack_manifest_sha256,
            ),
            "extra old locked input",
        )
        extra_path.unlink()
        wrong_entry_manifest = temporary / "wrong-pack-entry.json"
        wrong_entry = json.loads(pack_manifest.read_text(encoding="utf-8"))
        wrong_entry["entries"][0]["expected_sha256"] = "0" * 64
        wrong_entry_manifest.write_text(
            json.dumps(wrong_entry, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        mismatched_manifest_entry_rejected = expect_rejection(
            lambda: preparer.verify_locked_input_pack(
                PACK_CONTRACT_INPUT_SHA,
                pack_root,
                wrong_entry_manifest,
                preparer.sha256_file(wrong_entry_manifest),
            ),
            "mismatched expected locked-input hash",
        )
        stale_entry_manifest = temporary / "stale-pack-entry.json"
        stale_entry = json.loads(pack_manifest.read_text(encoding="utf-8"))
        stale_entry["entries"][0]["relative_path"] = (
            "input/plans_routed_5pct_v1.xml.gz"
        )
        stale_entry_manifest.write_text(
            json.dumps(stale_entry, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        stale_pack_entry_rejected = expect_rejection(
            lambda: preparer.verify_locked_input_pack(
                PACK_CONTRACT_INPUT_SHA,
                pack_root,
                stale_entry_manifest,
                preparer.sha256_file(stale_entry_manifest),
            ),
            "stale v1 locked-input-pack entry",
        )
        final_pack_sources, final_pack = preparer.verify_locked_input_pack(
            PACK_CONTRACT_INPUT_SHA,
            pack_root,
            pack_manifest,
            pack_manifest_sha256,
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
        "dynamic_exact_input_anchor_fixture": {
            "generated_from_git": True,
            "source_commit_sha": EXACT_INPUT_COMMIT_SHA,
            "source_commit_object_verified": (
                preparer.git_object_sha1("commit", exact_commit_payload)
                == EXACT_INPUT_COMMIT_SHA
            ),
            "source_tree_sha": exact_tree_sha,
            "tracked_file_count": len(exact_tree_entries),
            "git_blob_inventory_sha256":
                exact_git_blob_inventory_sha256,
        },
        "dynamic_git_tree_reconstruction_passed": True,
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
        "commit_object_tampering_rejected":
            commit_object_tampering_rejected,
        "external_locked_input_pack_fixture": {
            "source_commit_sha": PACK_CONTRACT_INPUT_SHA,
            "data_root_mode": preparer.EXTERNAL_LOCKED_INPUT_PACK_MODE,
            "manifest_sha256": pack_manifest_sha256,
            "locked_input_count": len(valid_pack_sources),
            "locked_input_sha256": valid_pack["locked_input_sha256"],
            "created": bool(pack_created),
            "verified": bool(final_pack),
            "build_bundle_input_resolution_verified": (
                set(resolved_pack_sources) == set(preparer.EXPECTED_INPUT_SHA256)
                and resolved_pack["verification_result"] == "passed"
                and set(final_pack_sources) == set(preparer.EXPECTED_INPUT_SHA256)
            ),
        },
        "canonical_project_data_root_mode_preserved": (
            set(canonical_sources) == set(preparer.EXPECTED_INPUT_SHA256)
            and canonical_contract["verification_result"] == "passed"
        ),
        "missing_locked_input_pack_manifest_rejected":
            missing_pack_manifest_rejected,
        "locked_input_pack_manifest_inside_root_rejected":
            pack_manifest_inside_root_rejected,
        "locked_input_pack_inside_source_root_rejected":
            pack_inside_source_root_rejected,
        "wrong_locked_input_pack_manifest_hash_rejected":
            wrong_pack_manifest_hash_rejected,
        "wrong_locked_input_pack_source_sha_rejected":
            wrong_pack_source_sha_rejected,
        "missing_locked_input_pack_file_rejected":
            missing_pack_file_rejected,
        "mismatched_locked_input_pack_file_rejected":
            mismatched_pack_file_rejected,
        "extra_locked_input_pack_file_rejected":
            extra_pack_file_rejected,
        "mismatched_locked_input_manifest_entry_rejected":
            mismatched_manifest_entry_rejected,
        "stale_v1_locked_input_pack_entry_rejected":
            stale_pack_entry_rejected,
        "server_access_performed": False,
        "bundle_built": False,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
