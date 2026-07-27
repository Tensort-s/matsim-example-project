# Hong Kong Immigration Control Point Locations

整理日期口径：`16-07-2026`（来自每日出入境人次统计 CSV）。

## Sources

- CSDI Control Points GeoJSON: `https://portal.csdi.gov.hk/csdi-webpage/file-api?dataset_id=immd_rcd_1633320081376_19895&format=geojson&layer_name=CP`
- CSDI metadata XML: `https://portal.csdi.gov.hk/geoportal/rest/metadata/item/immd_rcd_1633320081376_19895/xml`
- CSDI dataset info API reports `16` point records.
- Immigration Department control point page: `https://www.immd.gov.hk/hks/contactus/control_points.html`
- Daily passenger traffic CSV: `https://www.immd.gov.hk/opendata/hks/transport/immigration_clearance/statistics_on_daily_passenger_traffic.csv`

## Outputs

- `hong_kong_control_point_locations_2026-07-16.csv`: 16 CSDI control point locations with matched passenger traffic categories.
- `hong_kong_daily_traffic_control_point_match_2026-07-16.csv`: 2026-07-16 traffic CSV categories and their matched locations.
- `hong_kong_control_points_csdi_20260622.geojson`: raw CSDI point layer downloaded through the file API.

## Matching Notes

- `机场` is an aggregate passenger traffic category. CSDI has separate Terminal 1 and Terminal 2 points; the traffic total is repeated for reference and must not be summed across both rows.
- `港口管制` is also an aggregate/statistical category. CSDI includes `Harbour Control` and `River Trade Terminal Control Point`; the River Trade Terminal point has no separately named 2026-07-16 row in the passenger CSV.
- `沙头角` is retained as a location because it exists in both the CSDI layer and daily CSV, but its clearance service is suspended and its 2026-07-16 passenger total is zero.

## QA

- CSDI location rows written: `16`.
- Passenger traffic categories on `16-07-2026`: `14`.
- Total daily traffic across CSV categories: `821,038`.
