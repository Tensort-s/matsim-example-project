# Fuzhou city package

This directory describes the current single-city Fuzhou MATSim package. The heavy data remain under the stable
first-level `data/` domains, with `fuzhou/` added as the city layer.

Start with:

- `city.yaml` for the active city metadata and current model paths.
- `../../docs/PROJECT_ONBOARDING.md` for the full project workflow.
- `../../runs/fuzhou/run_manifest.json` for retained simulation outputs and continuation relationships.
- `../../docs/DATA_LAYOUT_MIGRATION_FUZHOU.md` for old-to-new path mappings.

## Current active model

```text
CRS:                    EPSG:32650
population sample:      2%
main modes:             car / pt / walk
final config:           scenarios/fuzhou/config-transit-mode-choice-2pct-waitpenalty-metroprefer-from-cont20-reroute50.xml
final output:           runs/fuzhou/outputs/waitpenalty-metroprefer-from-cont20-reroute50/
```

## Current active inputs

```text
boundary:
data/osm/fuzhou/city_23/fuzhou_city_23_boundary.geojson

demand:
data/matsim_routes/fuzhou/greenspace_grid_multi_activity_2pct_carown197_pt/mode_choice_plans_car_pt_walk_2pct_carown197.xml.gz

private vehicles:
data/matsim_routes/fuzhou/greenspace_grid_multi_activity_2pct_carown197_pt/private_car_vehicles_2pct_carown197.xml.gz

network / transit schedule / transit vehicles:
data/transit/fuzhou/transit_matsim_integrated_20260709_bus_priority_transferwait_metro40/
```

Older Fuzhou configs and scripts are retained as provenance under `scenarios/fuzhou/archive/` and `scripts/archive/`.
