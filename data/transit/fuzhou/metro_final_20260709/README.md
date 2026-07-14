# Fuzhou Metro Final Dataset (2026-07-09)

This directory consolidates the final metro-related outputs and removes intermediate test folders.

## Contents

- `amap_active/`: final AMap metro data filtered to active lines only. Construction/planned segments matching `??|??` were excluded in the source run.
- `osm_pbf_extraction/`: local Fujian PBF/OSM extraction products for metro stations, station groups, rail/subway ways, and route relations.
- `visualization/`: final preview images. `amap_active_metro_preview.png` is generated from the active AMap line/station GeoJSON files.
- `metadata/`: inventory, manifest, and cleanup report.

## Notes

- `amap_metro_service_frequency_with_manual_observations.csv` is the preferred frequency table because it includes manual mobile AMap observation rows where available.
- `amap_metro_active_data_coverage_and_missing_items.csv` is the preferred coverage/QA table.
- Raw AMap busline responses are retained as provenance for the final active dataset.
- Old folders deleted after consolidation: fuzhou_metro, fuzhou_metro_amap, fuzhou_metro_amap_metro_only, fuzhou_metro_amap_active, fuzhou_metro_amap_mobile_observations.
