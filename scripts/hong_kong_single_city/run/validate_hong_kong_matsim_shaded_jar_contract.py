#!/usr/bin/env python3
"""Validate deterministic shaded-JAR selection and runtime dependency closure."""

from __future__ import annotations

import importlib.util
import inspect
import io
import json
import shutil
import tarfile
import tempfile
import zipfile
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Callable


PREPARER_PATH = Path(__file__).with_name(
    "prepare_hong_kong_matsim_server_bundle.py"
)


def load_preparer() -> ModuleType:
    spec = importlib.util.spec_from_file_location("stage9_preparer", PREPARER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {PREPARER_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def create_jar(path: Path, class_names: tuple[str, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "x", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\n")
        for class_name in class_names:
            archive.writestr(class_name, b"fixture-class-bytes\n")


def create_bundle(path: Path, jar_path: Path) -> None:
    payload = jar_path.read_bytes()
    with tarfile.open(path, "x") as archive:
        member = tarfile.TarInfo(
            "app/matsim-example-project-0.0.1-SNAPSHOT.jar"
        )
        member.mode = 0o640
        member.size = len(payload)
        archive.addfile(member, io.BytesIO(payload))


def expect_rejection(action: Callable[[], object], label: str) -> bool:
    try:
        action()
    except (FileNotFoundError, NotADirectoryError, OSError, ValueError):
        return True
    raise AssertionError(f"Invalid shaded-JAR contract was accepted: {label}")


def completed(
    returncode: int,
    stdout: str = "",
    stderr: str = "",
) -> SimpleNamespace:
    return SimpleNamespace(
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


def main() -> int:
    preparer = load_preparer()
    with tempfile.TemporaryDirectory(prefix="stage9_shaded_jar_") as raw_temp:
        temporary = Path(raw_temp)
        build_root = temporary / "build_root"
        root_jar = build_root / preparer.APPLICATION_JAR_NAME
        thin_jar = build_root / "target" / preparer.APPLICATION_JAR_NAME
        create_jar(thin_jar, preparer.REQUIRED_RUNTIME_CLASSES)
        create_jar(root_jar, preparer.REQUIRED_DEPLOYMENT_CLASSES)

        selected = preparer.resolve_deployment_jar(build_root)
        selected_hash, selected_classes = preparer.verify_fat_jar(selected)
        two_same_name_artifacts_reproduced = all(
            (
                thin_jar.is_file(),
                root_jar.is_file(),
                thin_jar.name == root_jar.name,
                thin_jar.stat().st_size < root_jar.stat().st_size,
            )
        )
        root_shade_jar_selected = selected.resolve() == root_jar.resolve()
        dependency_inventory_complete = all(
            name in selected_classes
            for name in preparer.REQUIRED_DEPENDENCY_CLASSES
        )
        target_thin_jar_rejected = expect_rejection(
            lambda: preparer.verify_fat_jar(thin_jar),
            "target thin JAR dependency inventory",
        )

        target_only_root = temporary / "target_only_root"
        create_jar(
            target_only_root / "target" / preparer.APPLICATION_JAR_NAME,
            preparer.REQUIRED_RUNTIME_CLASSES,
        )
        target_path_selection_rejected = expect_rejection(
            lambda: preparer.resolve_deployment_jar(target_only_root),
            "target-only deployment artifact",
        )

        release_root = temporary / "release"
        release_jar = release_root / preparer.APPLICATION_JAR_RELATIVE
        release_jar.parent.mkdir(parents=True)
        shutil.copy2(root_jar, release_jar)
        release_contract = preparer.verify_release_application_contract(
            release_root,
            selected_hash,
        )

        bundle_path = temporary / "bundle.tar"
        create_bundle(bundle_path, root_jar)
        bundle_contract = preparer.verify_bundle_application_contract(
            bundle_path,
            selected_hash,
        )
        sha_continuity_passed = all(
            value == selected_hash
            for value in (
                release_contract["release_app_jar_sha256"],
                bundle_contract["bundle_app_jar_sha256"],
            )
        )

        tampered_jar = temporary / "tampered.jar"
        create_jar(tampered_jar, preparer.REQUIRED_RUNTIME_CLASSES)
        tampered_bundle = temporary / "tampered-bundle.tar"
        create_bundle(tampered_bundle, tampered_jar)
        tampered_bundle_rejected = expect_rejection(
            lambda: preparer.verify_bundle_application_contract(
                tampered_bundle,
                selected_hash,
            ),
            "bundle application JAR SHA drift",
        )

        preflight_source = preparer.dependency_preflight_source()
        preflight_source_path = temporary / "RuntimeDependencyPreflight.java"
        preflight_source_path.write_text(preflight_source, encoding="utf-8")
        fake_java = temporary / "runtime/jdk-25/bin/java"
        fake_java.parent.mkdir(parents=True)
        fake_java.write_bytes(b"fixture\n")
        expected_marker = (
            "dependency_preflight_passed="
            f"{len(preparer.REQUIRED_DEPLOYMENT_CLASSES)}"
        )
        captured_command: list[str] = []

        def passing_runner(command: list[str], **_kwargs: object) -> object:
            captured_command.extend(command)
            return completed(0, stdout=expected_marker + "\n")

        preflight_result = preparer.run_release_class_preflight(
            fake_java,
            root_jar,
            preflight_source_path,
            runner=passing_runner,
        )
        preflight_command_closed = captured_command == [
            str(fake_java),
            "--class-path",
            str(root_jar),
            str(preflight_source_path),
        ]
        preflight_source_complete = all(
            path.removesuffix(".class").replace("/", ".")
            in preflight_source
            for path in preparer.REQUIRED_DEPLOYMENT_CLASSES
        )
        preflight_failure_guards_present = all(
            marker in preflight_source
            for marker in (
                "ClassNotFoundException",
                "NoClassDefFoundError",
                "LinkageError",
                "Class.forName(className, false, loader)",
            )
        )
        class_not_found_rejected = expect_rejection(
            lambda: preparer.run_release_class_preflight(
                fake_java,
                root_jar,
                preflight_source_path,
                runner=lambda *_args, **_kwargs: completed(
                    101,
                    stderr="ClassNotFoundException: missing",
                ),
            ),
            "ClassNotFoundException",
        )
        no_class_def_rejected = expect_rejection(
            lambda: preparer.run_release_class_preflight(
                fake_java,
                root_jar,
                preflight_source_path,
                runner=lambda *_args, **_kwargs: completed(
                    101,
                    stderr="NoClassDefFoundError: missing",
                ),
            ),
            "NoClassDefFoundError",
        )
        linkage_error_rejected = expect_rejection(
            lambda: preparer.run_release_class_preflight(
                fake_java,
                root_jar,
                preflight_source_path,
                runner=lambda *_args, **_kwargs: completed(
                    101,
                    stderr="LinkageError: incompatible",
                ),
            ),
            "LinkageError",
        )
        incomplete_success_rejected = expect_rejection(
            lambda: preparer.run_release_class_preflight(
                fake_java,
                root_jar,
                preflight_source_path,
                runner=lambda *_args, **_kwargs: completed(0, stdout="partial"),
            ),
            "missing success marker",
        )

        worker = preparer.worker_script(
            "/mnt/DiskM/by/stage9_shaded_jar_fixture",
            "config_smoke_qsim.xml",
            selected_hash,
        )
        worker_hash_and_preflight_ordered = all(
            (
                selected_hash in worker,
                "sha256sum" in worker,
                preparer.DEPENDENCY_PREFLIGHT_SOURCE_RELATIVE in worker,
                worker.index("sha256sum")
                < worker.index("--class-path")
                < worker.index("org.matsim.project.RunHongKong5Pct"),
            )
        )
        parser_source = inspect.getsource(preparer.add_bundle_arguments)
        deterministic_cli = all(
            (
                '"--build-root"' in parser_source,
                '"--fat-jar"' not in parser_source,
            )
        )
        build_source = inspect.getsource(preparer.build_bundle)
        build_bundle_wiring_passed = all(
            marker in build_source
            for marker in (
                "resolve_deployment_jar(args.build_root)",
                "verify_release_application_contract(",
                "run_release_class_preflight(",
                "verify_bundle_application_contract(",
                '"application_jar_sha_identity_continuity"',
            )
        )

        checks = {
            "two_same_name_artifacts_reproduced": (
                two_same_name_artifacts_reproduced
            ),
            "root_shade_jar_selected": root_shade_jar_selected,
            "target_thin_jar_dependency_inventory_rejected": (
                target_thin_jar_rejected
            ),
            "target_only_path_selection_rejected": (
                target_path_selection_rejected
            ),
            "required_dependency_inventory_complete": (
                dependency_inventory_complete
            ),
            "release_app_jar_sha_matches_built": release_contract[
                "built_to_release_sha256_equal"
            ],
            "bundle_app_jar_sha_matches_built": bundle_contract[
                "built_to_bundle_sha256_equal"
            ],
            "built_bundle_release_sha_continuity": sha_continuity_passed,
            "tampered_bundle_app_jar_rejected": tampered_bundle_rejected,
            "preflight_source_contains_all_required_classes": (
                preflight_source_complete
            ),
            "preflight_source_fail_closed_guards_present": (
                preflight_failure_guards_present
            ),
            "preflight_command_uses_only_release_java_jar_source": (
                preflight_command_closed
            ),
            "preflight_success_marker_required": (
                preflight_result["status"] == "passed"
            ),
            "class_not_found_rejected": class_not_found_rejected,
            "no_class_def_found_rejected": no_class_def_rejected,
            "linkage_error_rejected": linkage_error_rejected,
            "incomplete_success_marker_rejected": incomplete_success_rejected,
            "worker_sha_and_class_preflight_before_matsim": (
                worker_hash_and_preflight_ordered
            ),
            "deterministic_build_root_cli": deterministic_cli,
            "build_bundle_dependency_closure_wiring": (
                build_bundle_wiring_passed
            ),
        }
        if not all(checks.values()):
            raise AssertionError(
                "Stage 9 shaded-JAR checks failed: "
                + ", ".join(key for key, value in checks.items() if not value)
            )
        result = {
            "schema_version": "stage9_shaded_jar_dependency_contract_test_v1",
            "status": "pass",
            "required_project_class_count": len(
                preparer.REQUIRED_RUNTIME_CLASSES
            ),
            "required_dependency_class_count": len(
                preparer.REQUIRED_DEPENDENCY_CLASSES
            ),
            "required_dependency_classes": list(
                preparer.REQUIRED_DEPENDENCY_CLASSES
            ),
            "checks": checks,
            "server_access_performed": False,
            "bundle_uploaded": False,
            "matsim_or_stage9_run_performed": False,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
