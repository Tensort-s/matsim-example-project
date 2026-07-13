# Fuzhou AMap Bus Stop/Line Final Dataset (2026-07-09)

This folder keeps the final reproducible version of the Fuzhou AMap bus stop and bus line extraction workflow.

## Workflow

1. Use the Greenspace Fuzhou city boundary to run tiled AMap POI polygon search for bus stops (`types=150700`).
2. Keep bus-stop POIs inside the Fuzhou boundary / 500 m buffer and de-duplicate by AMap POI ID.
3. Select POI IDs within a 2 km Fuzhou-boundary buffer.
4. Query AMap `/v3/bus/stopid` to discover line IDs serving each bus stop.
5. Query AMap `/v3/bus/lineid?extensions=all` for full line details: line records, trajectories, stop sequences, adjacent-stop edges, service time and `timedesc`.
6. Merge original POI stops and line-detail stops into a complete bus-stop set.

## Main scripts

- `fetch_fuzhou_bus_stop_pois_from_amap.py`: tiled bus-stop POI discovery.
- `fetch_fuzhou_bus_lines_from_stop_ids_amap.py`: stop ID -> line ID -> full line details.
- `visualize_fuzhou_bus_stop_pois_amap.py`: bus-stop POI visualization.
- `visualize_fuzhou_bus_lines_stopid_lineid.py`: line/stop visualization.

## Key outputs

- `bus_stop_pois/`: final bus-stop POI candidates and raw POI pages.
- `bus_lines/`: selected stop IDs, stop-to-line pairs, full bus lines, trajectories, stop sequences, adjacent-stop edges and merged complete stops.
- `metadata/cleanup_report.json`: validation counts and cleanup record.

The AMap API key is not stored in this dataset.
