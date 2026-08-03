#!/usr/bin/env python3
"""Validate the Stage 8D-R1 runtime-JDK closure without server access."""

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

        link_archive = temporary / "link.tar.gz"
        create_link_fixture(link_archive)
        linked_member_rejected = expect_rejection(
            lambda: preparer.validate_jdk_archive_layout(link_archive),
            "linked archive member",
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
        )
        worker_guard_passed = all(
            marker in worker
            for marker in (
                'test -x "$JAVA_HOME/bin/java"',
                '"$JAVA_HOME/bin/java" -version',
                f'version "{preparer.APPROVED_JAVA_VERSION}"',
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
            "linked_archive_member_rejected": linked_member_rejected,
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
            "schema_version": "stage8d_r1_runtime_jdk_contract_test_v1",
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
