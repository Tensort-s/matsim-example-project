# Fuzhou data layout migration

The project now keeps the first-level `data/` domains stable and adds a city layer underneath them.

Examples:

```text
data/matsim_routes/fuzhou/
data/matsim_agents/fuzhou/
data/transit/fuzhou/
data/osm/fuzhou/
```

Shared, non-city-specific assets use `_shared`, for example:

```text
data/models/_shared/remoteclip/
data/worldcommuting_od/_shared/GeneratingCodeData/
```

## Important path changes

```text
data/matsim_agents/fuzhou_city_23_greenspace_grid_multi_activity_2pct_same_day_night
→ data/matsim_agents/fuzhou/greenspace_grid_multi_activity_2pct_same_day_night

data/matsim_routes/fuzhou_city_23_greenspace_grid_multi_activity_2pct_carown197_pt
→ data/matsim_routes/fuzhou/greenspace_grid_multi_activity_2pct_carown197_pt

data/transit/fuzhou_transit_matsim_integrated_20260709_bus_priority_transferwait_metro40
→ data/transit/fuzhou/transit_matsim_integrated_20260709_bus_priority_transferwait_metro40

data/osm/fuzhou_city_23
→ data/osm/fuzhou/city_23

data/gee/fuzhou_city_23
→ data/gee/fuzhou/city_23

data/imagery/esri_world_imagery/fuzhou_city_23_greenspace_boundary
→ data/imagery/fuzhou/esri_world_imagery/greenspace_boundary

data/worldcommuting_od/GeneratingCodeData
→ data/worldcommuting_od/_shared/GeneratingCodeData
```

Current run outputs were moved from root-level `output-*` directories to:

```text
runs/fuzhou/outputs/
```

The current final run is:

```text
runs/fuzhou/outputs/waitpenalty-metroprefer-from-cont20-reroute50
```

The run chain is documented in:

```text
runs/fuzhou/run_manifest.json
```

