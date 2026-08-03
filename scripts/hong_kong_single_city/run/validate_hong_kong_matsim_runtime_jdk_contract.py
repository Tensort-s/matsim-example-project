#!/usr/bin/env python3
"""Validate Stage 8D-R1 JDK closure plus the bounded Stage 9 member repair."""

from __future__ import annotations

import importlib.util
import inspect
import io
import json
import tarfile
import tempfile
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Callable


PREPARER_PATH = Path(__file__).with_name(
    "prepare_hong_kong_matsim_server_bundle.py"
)


def load_preparer() -> ModuleType:
    spec = importlib.util.spec_from_file_location("stage8d_preparer", PREPARER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {PREPARER_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def add_tar_member(
    archive: tarfile.TarFile,
    name: str,
    content: bytes | None,
    mode: int,
) -> None:
    member = tarfile.TarInfo(name)
    member.mode = mode
    member.mtime = 0
    if content is None:
        member.type = tarfile.DIRTYPE
        archive.addfile(member)
    else:
        member.size = len(content)
        archive.addfile(member, io.BytesIO(content))


def create_jdk_fixture(
    path: Path,
    *,
    root: str = "jdk-25.0.3+9",
    java_mode: int = 0o755,
    include_java: bool = True,
    unsafe_name: str | None = None,
) -> None:
    with tarfile.open(path, "x:gz") as archive:
        add_tar_member(archive, f"{root}/", None, 0o755)
        add_tar_member(archive, f"{root}/bin/", None, 0o755)
        if include_java:
            add_tar_member(
                archive,
                f"{root}/bin/java",
                b"#!/usr/bin/env sh\nexit 0\n",
                java_mode,
            )
        add_tar_member(
            archive,
            f"{root}/release",
            b'JAVA_VERSION="25.0.3"\n',
            0o644,
        )
        if unsafe_name:
            add_tar_member(archive, unsafe_name, b"unsafe\n", 0o644)


def create_link_fixture(path: Path) -> None:
    with tarfile.open(path, "x:gz") as archive:
        add_tar_member(archive, "jdk-25.0.3+9/", None, 0o755)
        add_tar_member(archive, "jdk-25.0.3+9/bin/", None, 0o755)
        add_tar_member(
            archive,
            "jdk-25.0.3+9/bin/java",
            b"fixture\n",
            0o755,
        )
        link = tarfile.TarInfo("jdk-25.0.3+9/lib/unsafe-link")
        link.type = tarfile.SYMTYPE
        link.linkname = "../../outside"
        archive.addfile(link)


def create_special_member_fixture(path: Path) -> None:
    with tarfile.open(path, "x:gz") as archive:
        add_tar_member(archive, "jdk-25.0.3+9/", None, 0o755)
        add_tar_member(archive, "jdk-25.0.3+9/bin/", None, 0o755)
        add_tar_member(
            archive,
            "jdk-25.0.3+9/bin/java",
            b"fixture\n",
            0o755,
        )
        device = tarfile.TarInfo("jdk-25.0.3+9/legal/unsafe-device")
        device.type = tarfile.CHRTYPE
        device.mode = 0o644
        archive.addfile(device)


def add_symlink_member(
    archive: tarfile.TarFile,
    name: str,
    target: str,
    mode: int = 0o777,
    pax_headers: dict[str, str] | None = None,
) -> None:
    member = tarfile.TarInfo(name)
    member.type = tarfile.SYMTYPE
    member.linkname = target
    member.mode = mode
    member.mtime = 0
    member.pax_headers = pax_headers or {}
    archive.addfile(member)


def create_legal_symlink_fixture(
    path: Path,
    *,
    link_relative: str = "legal/jdk.jshell/ADDITIONAL_LICENSE_INFO",
    target_relative: str = "legal/java.base/ADDITIONAL_LICENSE_INFO",
    link_target: str = "../java.base/ADDITIONAL_LICENSE_INFO",
    include_target: bool = True,
    target_kind: str = "regular",
    target_mode: int = 0o644,
    duplicate_link_path: bool = False,
    link_pax_headers: dict[str, str] | None = None,
) -> bytes:
    root = "jdk-25.0.3+9"
    content = b"fixture approved JDK legal metadata\n"
    with tarfile.open(path, "x:gz") as archive:
        add_tar_member(archive, f"{root}/", None, 0o755)
        add_tar_member(archive, f"{root}/bin/", None, 0o755)
        add_tar_member(
            archive,
            f"{root}/bin/java",
            b"#!/usr/bin/env sh\nexit 0\n",
            0o755,
        )
        if include_target and target_kind == "regular":
            add_tar_member(
                archive,
                f"{root}/{target_relative}",
                content,
                target_mode,
            )
        elif include_target and target_kind == "directory":
            add_tar_member(
                archive,
                f"{root}/{target_relative}/",
                None,
                0o755,
            )
        elif include_target and target_kind == "symlink":
            add_tar_member(
                archive,
                f"{root}/legal/java.base/LICENSE",
                content,
                0o644,
            )
            add_symlink_member(
                archive,
                f"{root}/{target_relative}",
                "LICENSE",
            )
        elif include_target and target_kind == "hardlink":
            add_tar_member(
                archive,
                f"{root}/legal/java.base/LICENSE",
                content,
                0o644,
            )
            add_hardlink_member(
                archive,
                f"{root}/{target_relative}",
                f"{root}/legal/java.base/LICENSE",
            )
        if duplicate_link_path:
            add_tar_member(
                archive,
                f"{root}/{link_relative}",
                content,
                0o644,
            )
        add_symlink_member(
            archive,
            f"{root}/{link_relative}",
            link_target,
            pax_headers=link_pax_headers,
        )
    return content


def add_hardlink_member(
    archive: tarfile.TarFile,
    name: str,
    target: str,
    mode: int = 0o644,
) -> None:
    member = tarfile.TarInfo(name)
    member.type = tarfile.LNKTYPE
    member.linkname = target
    member.mode = mode
    member.mtime = 0
    archive.addfile(member)


def create_legal_hardlink_fixture(
    path: Path,
    *,
    link_relative: str = "legal/jdk.jshell/ADDITIONAL_LICENSE_INFO",
    target_relative: str = "legal/java.base/ADDITIONAL_LICENSE_INFO",
    link_target: str | None = None,
    include_target: bool = True,
    link_mode: int = 0o644,
    target_mode: int = 0o644,
    target_is_hardlink: bool = False,
) -> bytes:
    root = "jdk-25.0.3+9"
    content = b"fixture approved JDK legal metadata\n"
    with tarfile.open(path, "x:gz") as archive:
        add_tar_member(archive, f"{root}/", None, 0o755)
        add_tar_member(archive, f"{root}/bin/", None, 0o755)
        add_tar_member(
            archive,
            f"{root}/bin/java",
            b"#!/usr/bin/env sh\nexit 0\n",
            0o755,
        )
        if include_target and not target_is_hardlink:
            add_tar_member(
                archive,
                f"{root}/{target_relative}",
                content,
                target_mode,
            )
        elif include_target:
            add_tar_member(
                archive,
                f"{root}/legal/java.base/LICENSE",
                content,
                0o644,
            )
            add_hardlink_member(
                archive,
                f"{root}/{target_relative}",
                f"{root}/legal/java.base/LICENSE",
            )
        add_hardlink_member(
            archive,
            f"{root}/{link_relative}",
            link_target or f"{root}/{target_relative}",
            link_mode,
        )
    return content


def version_runner(version: str, returncode: int = 0) -> Callable[..., object]:
    def run(*_args: object, **_kwargs: object) -> object:
        return SimpleNamespace(
            returncode=returncode,
            stdout="",
            stderr=f'openjdk version "{version}" 2026-04-21\n',
        )

    return run


def expect_rejection(action: Callable[[], object], label: str) -> bool:
    try:
        action()
    except (FileExistsError, FileNotFoundError, OSError, ValueError):
        return True
    raise AssertionError(f"Invalid runtime-JDK contract was accepted: {label}")


def create_bundle_fixture(path: Path, *, java_mode: int | None) -> None:
    with tarfile.open(path, "x") as archive:
        add_tar_member(archive, "runtime/", None, 0o750)
        add_tar_member(archive, "runtime/jdk-25/", None, 0o750)
        add_tar_member(archive, "runtime/jdk-25/bin/", None, 0o750)
        if java_mode is not None:
            add_tar_member(
                archive,
                "runtime/jdk-25/bin/java",
                b"fixture\n",
                java_mode,
            )


def main() -> int:
    preparer = load_preparer()
    with tempfile.TemporaryDirectory(prefix="stage8d_r1_jdk_") as raw_temp:
        temporary = Path(raw_temp)
        approved_archive = temporary / "approved.tar.gz"
        create_jdk_fixture(approved_archive)
        approved_hash = preparer.sha256_file(approved_archive)
        runtime_root = temporary / "valid/runtime/jdk-25"
        materialized = preparer.materialize_runtime_jdk(
            approved_archive,
            approved_hash,
            runtime_root,
            version_runner=version_runner(preparer.APPROVED_JAVA_VERSION),
            executable_checker=lambda _path: True,
        )

        wrong_hash_target = temporary / "wrong-hash/runtime/jdk-25"
        wrong_hash_rejected = expect_rejection(
            lambda: preparer.materialize_runtime_jdk(
                approved_archive,
                "0" * 64,
                wrong_hash_target,
                version_runner=version_runner(preparer.APPROVED_JAVA_VERSION),
                executable_checker=lambda _path: True,
            ),
            "wrong archive SHA256",
        ) and not wrong_hash_target.exists()

        unsafe_archive = temporary / "unsafe.tar.gz"
        create_jdk_fixture(unsafe_archive, unsafe_name="../escape")
        unsafe_target = temporary / "unsafe/runtime/jdk-25"
        unsafe_path_rejected = expect_rejection(
            lambda: preparer.materialize_runtime_jdk(
                unsafe_archive,
                preparer.sha256_file(unsafe_archive),
                unsafe_target,
                version_runner=version_runner(preparer.APPROVED_JAVA_VERSION),
                executable_checker=lambda _path: True,
            ),
            "unsafe archive path",
        ) and not unsafe_target.exists()

        stale_archive = temporary / "stale.tar.gz"
        create_jdk_fixture(stale_archive, root="jdk-17.0.12")
        stale_target = temporary / "stale/runtime/jdk-25"
        stale_layout_rejected = expect_rejection(
            lambda: preparer.materialize_runtime_jdk(
                stale_archive,
                preparer.sha256_file(stale_archive),
                stale_target,
                version_runner=version_runner(preparer.APPROVED_JAVA_VERSION),
                executable_checker=lambda _path: True,
            ),
            "stale JDK layout",
        ) and not stale_target.exists()

        outside_legal_symlink_archive = temporary / "symlink-outside-legal.tar.gz"
        create_link_fixture(outside_legal_symlink_archive)
        outside_legal_symlink_rejected = expect_rejection(
            lambda: preparer.validate_jdk_archive_layout(
                outside_legal_symlink_archive
            ),
            "symbolic link outside legal metadata",
        )

        device_archive = temporary / "device.tar.gz"
        create_special_member_fixture(device_archive)
        device_member_rejected = expect_rejection(
            lambda: preparer.validate_jdk_archive_layout(device_archive),
            "device archive member",
        )

        legal_symlink_archive = temporary / "legal-symlink.tar.gz"
        legal_symlink_content = create_legal_symlink_fixture(
            legal_symlink_archive
        )
        _, legal_symlink_entries = preparer.validate_jdk_archive_layout(
            legal_symlink_archive
        )
        legal_symlink_entry = next(
            entry
            for entry in legal_symlink_entries
            if entry["relative_path"]
            == "legal/jdk.jshell/ADDITIONAL_LICENSE_INFO"
        )
        legal_symlink_runtime = temporary / "legal-symlink/runtime/jdk-25"
        legal_symlink_materialized = preparer.materialize_runtime_jdk(
            legal_symlink_archive,
            preparer.sha256_file(legal_symlink_archive),
            legal_symlink_runtime,
            version_runner=version_runner(preparer.APPROVED_JAVA_VERSION),
            executable_checker=lambda _path: True,
        )
        legal_symlink_output = (
            legal_symlink_runtime
            / "legal/jdk.jshell/ADDITIONAL_LICENSE_INFO"
        )
        diagnosed_legal_symlink_accepted_and_materialized = all(
            (
                legal_symlink_entry["member_type"]
                == "legal_metadata_symlink",
                legal_symlink_entry["link_name"]
                == "../java.base/ADDITIONAL_LICENSE_INFO",
                legal_symlink_entry["archive_mode"] == 0o777,
                legal_symlink_entry["archive_size_bytes"] == 0,
                legal_symlink_entry["pax_headers"] == {},
                legal_symlink_entry["source_relative_path"]
                == "legal/java.base/ADDITIONAL_LICENSE_INFO",
                legal_symlink_output.is_file(),
                not legal_symlink_output.is_symlink(),
                legal_symlink_output.read_bytes() == legal_symlink_content,
                legal_symlink_materialized[
                    "materialized_legal_metadata_symlink_count"
                ]
                == 1,
            )
        )

        absolute_symlink_archive = temporary / "symlink-absolute.tar.gz"
        create_legal_symlink_fixture(
            absolute_symlink_archive,
            link_target="/legal/java.base/ADDITIONAL_LICENSE_INFO",
        )
        absolute_symlink_target_rejected = expect_rejection(
            lambda: preparer.validate_jdk_archive_layout(
                absolute_symlink_archive
            ),
            "absolute legal symbolic-link target",
        )

        escaping_symlink_archive = temporary / "symlink-escape.tar.gz"
        create_legal_symlink_fixture(
            escaping_symlink_archive,
            link_target="../../../outside",
        )
        escaping_symlink_target_rejected = expect_rejection(
            lambda: preparer.validate_jdk_archive_layout(
                escaping_symlink_archive
            ),
            "escaping legal symbolic-link target",
        )

        nonlegal_symlink_archive = temporary / "symlink-nonlegal.tar.gz"
        create_legal_symlink_fixture(
            nonlegal_symlink_archive,
            link_target="../../bin/java",
        )
        nonlegal_symlink_target_rejected = expect_rejection(
            lambda: preparer.validate_jdk_archive_layout(
                nonlegal_symlink_archive
            ),
            "non-legal symbolic-link target",
        )

        missing_symlink_archive = temporary / "symlink-missing.tar.gz"
        create_legal_symlink_fixture(
            missing_symlink_archive,
            include_target=False,
        )
        missing_symlink_target_rejected = expect_rejection(
            lambda: preparer.validate_jdk_archive_layout(
                missing_symlink_archive
            ),
            "missing legal symbolic-link target",
        )

        chained_symlink_archive = temporary / "symlink-chain.tar.gz"
        create_legal_symlink_fixture(
            chained_symlink_archive,
            target_kind="symlink",
        )
        chained_symlink_target_rejected = expect_rejection(
            lambda: preparer.validate_jdk_archive_layout(
                chained_symlink_archive
            ),
            "chained legal symbolic-link target",
        )

        hardlink_target_archive = temporary / "symlink-to-hardlink.tar.gz"
        create_legal_symlink_fixture(
            hardlink_target_archive,
            target_kind="hardlink",
        )
        hardlink_symlink_target_rejected = expect_rejection(
            lambda: preparer.validate_jdk_archive_layout(
                hardlink_target_archive
            ),
            "hard-link target of legal symbolic link",
        )

        directory_symlink_archive = temporary / "symlink-directory.tar.gz"
        create_legal_symlink_fixture(
            directory_symlink_archive,
            target_kind="directory",
        )
        directory_symlink_target_rejected = expect_rejection(
            lambda: preparer.validate_jdk_archive_layout(
                directory_symlink_archive
            ),
            "directory legal symbolic-link target",
        )

        executable_symlink_archive = temporary / "symlink-executable.tar.gz"
        create_legal_symlink_fixture(
            executable_symlink_archive,
            target_mode=0o755,
        )
        executable_symlink_target_rejected = expect_rejection(
            lambda: preparer.validate_jdk_archive_layout(
                executable_symlink_archive
            ),
            "executable legal symbolic-link target",
        )

        duplicate_symlink_archive = temporary / "symlink-duplicate.tar.gz"
        create_legal_symlink_fixture(
            duplicate_symlink_archive,
            duplicate_link_path=True,
        )
        duplicate_symlink_path_rejected = expect_rejection(
            lambda: preparer.validate_jdk_archive_layout(
                duplicate_symlink_archive
            ),
            "duplicate legal symbolic-link path",
        )

        pax_symlink_archive = temporary / "symlink-pax.tar.gz"
        create_legal_symlink_fixture(
            pax_symlink_archive,
            link_pax_headers={"comment": "unexpected"},
        )
        pax_symlink_metadata_rejected = expect_rejection(
            lambda: preparer.validate_jdk_archive_layout(
                pax_symlink_archive
            ),
            "PAX metadata on legal symbolic link",
        )

        legal_archive = temporary / "legal-hardlink.tar.gz"
        legal_content = create_legal_hardlink_fixture(legal_archive)
        _, legal_entries = preparer.validate_jdk_archive_layout(legal_archive)
        legal_entry = next(
            entry
            for entry in legal_entries
            if entry["relative_path"]
            == "legal/jdk.jshell/ADDITIONAL_LICENSE_INFO"
        )
        legal_runtime = temporary / "legal-hardlink/runtime/jdk-25"
        legal_materialized = preparer.materialize_runtime_jdk(
            legal_archive,
            preparer.sha256_file(legal_archive),
            legal_runtime,
            version_runner=version_runner(preparer.APPROVED_JAVA_VERSION),
            executable_checker=lambda _path: True,
        )
        legal_output = (
            legal_runtime / "legal/jdk.jshell/ADDITIONAL_LICENSE_INFO"
        )
        legal_hardlink_accepted_and_materialized = all(
            (
                legal_entry["member_type"] == "legal_metadata_hardlink",
                legal_entry["source_relative_path"]
                == "legal/java.base/ADDITIONAL_LICENSE_INFO",
                legal_output.is_file(),
                legal_output.read_bytes() == legal_content,
                legal_materialized[
                    "materialized_legal_metadata_hardlink_count"
                ]
                == 1,
            )
        )

        root_relative_archive = temporary / "root-relative-hardlink.tar.gz"
        create_legal_hardlink_fixture(
            root_relative_archive,
            link_target="legal/java.base/ADDITIONAL_LICENSE_INFO",
        )
        _, root_relative_entries = preparer.validate_jdk_archive_layout(
            root_relative_archive
        )
        root_relative_hardlink_accepted = any(
            entry.get("source_relative_path")
            == "legal/java.base/ADDITIONAL_LICENSE_INFO"
            for entry in root_relative_entries
            if entry["member_type"] == "legal_metadata_hardlink"
        )

        outside_legal_archive = temporary / "outside-legal-hardlink.tar.gz"
        create_legal_hardlink_fixture(
            outside_legal_archive,
            link_relative="lib/ADDITIONAL_LICENSE_INFO",
        )
        outside_legal_hardlink_rejected = expect_rejection(
            lambda: preparer.validate_jdk_archive_layout(outside_legal_archive),
            "hard link outside legal metadata",
        )

        traversal_target_archive = temporary / "hardlink-traversal.tar.gz"
        create_legal_hardlink_fixture(
            traversal_target_archive,
            link_target="../outside",
        )
        hardlink_traversal_rejected = expect_rejection(
            lambda: preparer.validate_jdk_archive_layout(
                traversal_target_archive
            ),
            "hard-link traversal target",
        )

        absolute_target_archive = temporary / "hardlink-absolute.tar.gz"
        create_legal_hardlink_fixture(
            absolute_target_archive,
            link_target="/legal/java.base/ADDITIONAL_LICENSE_INFO",
        )
        hardlink_absolute_target_rejected = expect_rejection(
            lambda: preparer.validate_jdk_archive_layout(
                absolute_target_archive
            ),
            "hard-link absolute target",
        )

        missing_target_archive = temporary / "hardlink-missing.tar.gz"
        create_legal_hardlink_fixture(
            missing_target_archive,
            include_target=False,
        )
        hardlink_missing_target_rejected = expect_rejection(
            lambda: preparer.validate_jdk_archive_layout(missing_target_archive),
            "missing hard-link target",
        )

        chained_target_archive = temporary / "hardlink-chain.tar.gz"
        create_legal_hardlink_fixture(
            chained_target_archive,
            target_is_hardlink=True,
        )
        hardlink_chain_rejected = expect_rejection(
            lambda: preparer.validate_jdk_archive_layout(chained_target_archive),
            "hard-link target chain",
        )

        executable_legal_archive = temporary / "hardlink-executable.tar.gz"
        create_legal_hardlink_fixture(
            executable_legal_archive,
            link_mode=0o755,
        )
        executable_legal_hardlink_rejected = expect_rejection(
            lambda: preparer.validate_jdk_archive_layout(
                executable_legal_archive
            ),
            "executable legal metadata hard link",
        )

        executable_target_archive = temporary / "hardlink-target-exec.tar.gz"
        create_legal_hardlink_fixture(
            executable_target_archive,
            target_mode=0o755,
        )
        executable_hardlink_target_rejected = expect_rejection(
            lambda: preparer.validate_jdk_archive_layout(
                executable_target_archive
            ),
            "executable legal metadata hard-link target",
        )

        missing_archive = temporary / "missing-java.tar.gz"
        create_jdk_fixture(missing_archive, include_java=False)
        missing_java_rejected = expect_rejection(
            lambda: preparer.validate_jdk_archive_layout(missing_archive),
            "missing bin/java",
        )

        nonexec_archive = temporary / "nonexec.tar.gz"
        create_jdk_fixture(nonexec_archive, java_mode=0o644)
        nonexec_java_rejected = expect_rejection(
            lambda: preparer.validate_jdk_archive_layout(nonexec_archive),
            "non-executable bin/java",
        )

        wrong_version_root = temporary / "wrong-version/runtime/jdk-25"
        wrong_version_rejected = expect_rejection(
            lambda: preparer.materialize_runtime_jdk(
                approved_archive,
                approved_hash,
                wrong_version_root,
                version_runner=version_runner("25.0.2"),
                executable_checker=lambda _path: True,
            ),
            "wrong java -version",
        )

        existing_root = temporary / "existing/runtime/jdk-25"
        existing_root.mkdir(parents=True)
        sentinel = existing_root / "sentinel.txt"
        sentinel.write_text("preserve\n", encoding="utf-8")
        existing_target_rejected = expect_rejection(
            lambda: preparer.materialize_runtime_jdk(
                approved_archive,
                approved_hash,
                existing_root,
                version_runner=version_runner(preparer.APPROVED_JAVA_VERSION),
                executable_checker=lambda _path: True,
            ),
            "pre-existing runtime root",
        ) and sentinel.read_text(encoding="utf-8") == "preserve\n"

        valid_bundle = temporary / "valid-bundle.tar"
        create_bundle_fixture(valid_bundle, java_mode=0o750)
        bundle_contract = preparer.verify_bundle_runtime_contract(valid_bundle)
        missing_bundle = temporary / "missing-bundle.tar"
        create_bundle_fixture(missing_bundle, java_mode=None)
        missing_bundle_rejected = expect_rejection(
            lambda: preparer.verify_bundle_runtime_contract(missing_bundle),
            "bundle missing runtime Java",
        )
        nonexec_bundle = temporary / "nonexec-bundle.tar"
        create_bundle_fixture(nonexec_bundle, java_mode=0o640)
        nonexec_bundle_rejected = expect_rejection(
            lambda: preparer.verify_bundle_runtime_contract(nonexec_bundle),
            "bundle runtime Java non-executable",
        )

        worker = preparer.worker_script(
            "/mnt/DiskM/by/stage8d_r1_not_deployed",
            "config_smoke_qsim.xml",
            "a" * 64,
        )
        worker_guard_passed = all(
            marker in worker
            for marker in (
                'test -x "$JAVA_HOME/bin/java"',
                '"$JAVA_HOME/bin/java" -version',
                f'version "{preparer.APPROVED_JAVA_VERSION}"',
                'sha256sum "$APP_JAR"',
                preparer.DEPENDENCY_PREFLIGHT_SOURCE_RELATIVE,
            )
        )
        build_bundle_source = inspect.getsource(preparer.build_bundle)
        build_bundle_wiring_passed = all(
            marker in build_bundle_source
            for marker in (
                "materialize_runtime_jdk(",
                '"jdk_runtime": jdk_runtime',
                "verify_bundle_runtime_contract(args.bundle_path)",
                '"bundle_runtime_contract": bundle_runtime_contract',
            )
        )

        checks = {
            "approved_production_archive_lock": (
                preparer.APPROVED_JDK_ARCHIVE_SHA256
                == "69264a7a211bf5029830d07bc3370f879769d62ebc5b5488e90c9343a2da0e1f"
            ),
            "archive_hash_verified_before_extraction": materialized[
                "archive_verified_before_extraction"
            ],
            "confined_runtime_path": (
                materialized["extraction_confined_to"]
                == preparer.RUNTIME_JDK_RELATIVE
            ),
            "runtime_java_exists": (runtime_root / "bin/java").is_file(),
            "runtime_java_executable": materialized[
                "java_executable_check_passed"
            ],
            "java_25_0_3_preflight": materialized[
                "java_version_preflight_passed"
            ],
            "wrong_hash_rejected_before_target_creation": wrong_hash_rejected,
            "unsafe_archive_path_rejected_before_target_creation": (
                unsafe_path_rejected
            ),
            "stale_jdk_layout_rejected_before_target_creation": (
                stale_layout_rejected
            ),
            "symlink_outside_legal_rejected": (
                outside_legal_symlink_rejected
            ),
            "device_member_rejected": device_member_rejected,
            "diagnosed_legal_symlink_accepted_and_materialized": (
                diagnosed_legal_symlink_accepted_and_materialized
            ),
            "absolute_symlink_target_rejected": (
                absolute_symlink_target_rejected
            ),
            "escaping_symlink_target_rejected": (
                escaping_symlink_target_rejected
            ),
            "nonlegal_symlink_target_rejected": (
                nonlegal_symlink_target_rejected
            ),
            "missing_symlink_target_rejected": (
                missing_symlink_target_rejected
            ),
            "chained_symlink_target_rejected": (
                chained_symlink_target_rejected
            ),
            "hardlink_symlink_target_rejected": (
                hardlink_symlink_target_rejected
            ),
            "directory_symlink_target_rejected": (
                directory_symlink_target_rejected
            ),
            "executable_symlink_target_rejected": (
                executable_symlink_target_rejected
            ),
            "duplicate_symlink_path_rejected": (
                duplicate_symlink_path_rejected
            ),
            "pax_symlink_metadata_rejected": pax_symlink_metadata_rejected,
            "approved_legal_hardlink_accepted_and_materialized": (
                legal_hardlink_accepted_and_materialized
            ),
            "root_relative_legal_hardlink_target_accepted": (
                root_relative_hardlink_accepted
            ),
            "hardlink_outside_legal_rejected": (
                outside_legal_hardlink_rejected
            ),
            "hardlink_traversal_target_rejected": hardlink_traversal_rejected,
            "hardlink_absolute_target_rejected": (
                hardlink_absolute_target_rejected
            ),
            "hardlink_missing_target_rejected": (
                hardlink_missing_target_rejected
            ),
            "hardlink_chain_rejected": hardlink_chain_rejected,
            "executable_legal_hardlink_rejected": (
                executable_legal_hardlink_rejected
            ),
            "executable_hardlink_target_rejected": (
                executable_hardlink_target_rejected
            ),
            "missing_java_rejected": missing_java_rejected,
            "non_executable_java_rejected": nonexec_java_rejected,
            "wrong_java_version_rejected": wrong_version_rejected,
            "preexisting_target_rejected_and_preserved": existing_target_rejected,
            "bundle_runtime_java_present_and_executable": all(
                (
                    bundle_contract["bundle_member_present"],
                    bundle_contract["bundle_member_executable"],
                )
            ),
            "bundle_missing_java_rejected": missing_bundle_rejected,
            "bundle_non_executable_java_rejected": nonexec_bundle_rejected,
            "launcher_preflight_agrees_with_bundle_contract": worker_guard_passed,
            "build_bundle_records_runtime_dependency_closure": (
                build_bundle_wiring_passed
            ),
        }
        if not all(checks.values()):
            raise AssertionError(
                "Stage 8D-R1 runtime-JDK checks failed: "
                + ", ".join(key for key, value in checks.items() if not value)
            )
        result = {
            "schema_version": "stage8d_r1_runtime_jdk_contract_test_v3",
            "status": "pass",
            "approved_runtime_contract": {
                "archive_sha256_production_lock": (
                    preparer.APPROVED_JDK_ARCHIVE_SHA256
                ),
                "runtime_path": preparer.RUNTIME_JDK_RELATIVE,
                "java_executable": preparer.RUNTIME_JAVA_RELATIVE,
                "java_version": preparer.APPROVED_JAVA_VERSION,
            },
            "checks": checks,
            "server_access_performed": False,
            "bundle_uploaded": False,
            "matsim_or_stage9_run_performed": False,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
