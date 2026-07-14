# Fuzhou single-city scripts

These scripts are the original Fuzhou-specific workflow scripts. They are intentionally kept separate from future multi-city/generalized scripts.

The data layout keeps first-level `data/` domains stable and adds the city layer below them, for example:

```text
data/transit/fuzhou/
data/matsim_agents/fuzhou/
data/matsim_routes/fuzhou/
data/osm/fuzhou/
```

Shared assets use `_shared`, for example `data/models/_shared/remoteclip/`.

## Directory guide

- `data_acquisition/`  
  Downloading, API fetching, mobile capture, OSM/GEE/AMap source collection, and metro speed estimation.

- `feature_engineering/`  
  WorldPop, WEDAN, RemoteCLIP, POI, distance matrix, and OD inference feature generation.

- `demand_generation/`  
  Multi-activity agents and current car/pt/walk population preparation.

- `transit_supply/`  
  Bus/metro coordinate unification, bus map matching, bus-priority network, metro network, integration, speed/wait calibration.

- `analysis_visualization/`  
  PT submode analysis, congestion maps, SimWrapper hourly traffic products, and Kepler particle-flow animation.

- `run/`
  Windows helper scripts for reproducing current Fuzhou runs, including the final wait-penalty continuation reroute-50 run.
