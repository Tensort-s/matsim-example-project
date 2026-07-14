# Documentation audit

This audit records the July 2026 Markdown cleanup after the data layout migration.

## What was checked

Project-owned Markdown files were checked in:

- root docs: `README.md`, `PYTHON_ENV.md`, `WEDAN_ENV.md`
- `docs/`
- `cities/`
- `scenarios/`
- `scripts/`
- final transit README files under `data/transit/fuzhou/`

Third-party package docs, virtual environments, `.tools`, build outputs, and run outputs were intentionally excluded.

## Main fixes

- Added `docs/PROJECT_ONBOARDING.md` as the new-session entry point.
- Updated `README.md`, `cities/fuzhou/README.md`, and `docs/DATA_LAYOUT_MIGRATION_FUZHOU.md` to point at the current
  city-layer data layout.
- Preserved legacy experiment documents for provenance, but made the active source of truth explicit.
- Replaced active references to root-level output/log folders with `runs/fuzhou/outputs/` and `runs/fuzhou/logs/`.

## QA result

- Active old-path pattern scan passed with zero residual matches outside the migration mapping document.
- Key paths listed in `docs/PROJECT_ONBOARDING.md` were checked and exist locally.
- `docs/DATA_LAYOUT_MIGRATION_FUZHOU.md` intentionally keeps old paths only as old-to-new mapping records.
- Project-owned Markdown files were validated as UTF-8. If Chinese appears garbled in a Windows terminal, use
  `Get-Content -Encoding UTF8 ...` or Python `open(..., encoding="utf-8")`.

## Current source of truth

For future sessions, read these first:

1. `README.md`
2. `docs/PROJECT_ONBOARDING.md`
3. `cities/fuzhou/city.yaml`
4. `runs/fuzhou/run_manifest.json`

## Legacy notes

Older docs may still describe retired workflows: early AMap discovery, 30k car-only agents, initial multi-activity
routing, 5% population experiments, and ride-hailing tests. These are historical records. Current runnable inputs are
listed in `docs/PROJECT_ONBOARDING.md`.
