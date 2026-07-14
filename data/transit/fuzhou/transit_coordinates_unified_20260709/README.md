# Fuzhou Transit Coordinates Unified Dataset

Created for MATSim transit preparation.  All outputs preserve source coordinate
provenance and provide MATSim-ready `EPSG:32650` coordinates.

## Coordinate policy

- Bus stop tables already contained `GCJ-02`, `WGS84`, and `EPSG:32650`
  coordinates in the final AMap stop/line dataset; this directory validates and
  copies them.
- Bus line trajectory GeoJSON was already converted from AMap `GCJ-02` to
  `WGS84`; this directory only projects it to `EPSG:32650` and does not apply a
  second GCJ correction.
- Metro active station and trajectory coordinates are treated as AMap `GCJ-02`
  and converted to `WGS84`, then projected to `EPSG:32650`.

## Main files

- `bus/`: unified bus stops, stop sequences, and line trajectories.
- `metro/`: unified metro stations, stop sequences, and line trajectories.
- `combined/`: bus + metro stop table and point layers with `mode=bus/metro`.
- `visualization/unified_bus_metro_epsg32650_preview.png`: quick spatial QA.
- `metadata/coordinate_unification_summary.json`: counts and source inputs.
- `metadata/coordinate_quality_report.csv`: coordinate QA checks.

This dataset is an input for later MATSim transit network and schedule
generation. It does not yet contain `transitSchedule.xml.gz` or
`transitVehicles.xml.gz`.
