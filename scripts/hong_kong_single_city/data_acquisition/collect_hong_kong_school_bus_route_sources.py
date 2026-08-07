#!/usr/bin/env python3
"""Create an auditable first-party Hong Kong school-bus source collection."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen


ACCESS_DATE = date.today().isoformat()

SOURCES = [
    dict(source_id="td_nfb_overview", title="Non-franchised bus overview", provider="Transport Department", url="https://www.td.gov.hk/en/transport_in_hong_kong/public_transport/non_franchised/index.html", validity="statistics as at 2025-12-31; page accessed current", coverage="Hong Kong regulatory totals", evidence_class="official_current", content_class="official_aggregate_or_definition", official="yes", licence="Hong Kong Government copyright; cite and use for research, no bulk republication", calibrate="no", notes="Counts NFB and B01 endorsements; contains no student route table."),
    dict(source_id="td_nfb_descriptions", title="Brief description of non-franchised bus services", provider="Transport Department", url="https://www.td.gov.hk/en/transport_in_hong_kong/public_transport/non_franchised/brief_description_of_nfb_services/index.html", validity="current web page", coverage="Hong Kong regulatory definitions", evidence_class="official_current", content_class="official_aggregate_or_definition", official="yes", licence="Hong Kong Government copyright", calibrate="no", notes="Defines A03 student service and B01 school/private-bus student service."),
    dict(source_id="td_psl_application", title="Application for Passenger Service Licence", provider="Transport Department", url="https://www.td.gov.hk/en/transport_in_hong_kong/public_transport/non_franchised/application_for_passenger_service_licence_psl/index.html?print=1", validity="current web page", coverage="Hong Kong licensing process", evidence_class="official_current", content_class="school_transport_service_no_route", official="yes", licence="Hong Kong Government copyright", calibrate="no", notes="Applications contain routes, periods and vehicles, but approved A03 route tables are not published here."),
    dict(source_id="edb_school_bus_safety", title="Safety of school bus services", provider="Education Bureau", url="https://www.edb.gov.hk/en/student-parents/safety/sch-bus-services/index.html", validity="updated 2026-07", coverage="Hong Kong school transport guidance", evidence_class="official_current", content_class="school_transport_service_no_route", official="yes", licence="Hong Kong Government copyright", calibrate="no", notes="Safety and escort guidance only."),
    dict(source_id="edb_cross_boundary_operators", title="Local vehicles for cross-boundary students", provider="Education Bureau", url="https://www.edb.gov.hk/en/student-parents/events-services/programs/localnannybus.html", validity="2025/26 list valid to 2026-07; 2026/27 page", coverage="Lok Ma Chau and Lo Wu", evidence_class="official_current", content_class="school_or_stop_list_only", official="yes", licence="Hong Kong Government copyright", calibrate="no", notes="Operator list and boundary-control-point coverage; not a route/stop timetable."),
    dict(source_id="tcs2022_report", title="Travel Characteristics Survey 2022 Final Report", provider="Transport Department", url="https://www.td.gov.hk/filemanager/en/content_5349/tcs2022_eng.pdf", validity="survey year 2022", coverage="Hong Kong household travel", evidence_class="official_historical_survey", content_class="official_aggregate_or_definition", official="yes", licence="Hong Kong Government copyright", calibrate="no", notes="SPB includes company, school, resident, tourist, shuttle and cross-boundary buses; not school-bus-only."),
    dict(source_id="tcs2022_appendix", title="Travel Characteristics Survey 2022 Appendix", provider="Transport Department", url="https://www.td.gov.hk/filemanager/en/content_5349/tcs2022app_eng.pdf", validity="survey year 2022", coverage="Hong Kong household travel tables", evidence_class="official_historical_survey", content_class="official_aggregate_or_definition", official="yes", licence="Hong Kong Government copyright", calibrate="no", notes="Source of HBS mode boarding constraints."),
    dict(source_id="csd2021_education_transport", title="2021 Population Census Main Results", provider="Census and Statistics Department", url="https://www.censtatd.gov.hk/en/data/stat_report/product/B1120109/att/B11201092021XXXXB0100.pdf", validity="2021 Population Census", coverage="Full-time students in Hong Kong by education level and transport mode", evidence_class="official_historical_survey", content_class="official_aggregate_or_definition", official="yes", licence="Hong Kong Government copyright", calibrate="yes", notes="Tables 5.12 and 5.14 support the estimated non-tertiary school-bus share within HBS SPB; this is a cross-source estimate, not a direct TCS SPB breakdown."),
    dict(source_id="edb_school_locations", title="School Location and Information", provider="Education Bureau / DATA.GOV.HK", url="http://www.edb.gov.hk/attachment/en/student-parents/sch-info/sch-search/sch-location-info/SCH_LOC_EDB.csv", validity="monthly dataset; catalogue dated 2025-05-06 when inventoried", coverage="Hong Kong schools", evidence_class="official_current", content_class="school_or_stop_list_only", official="yes", licence="DATA.GOV.HK terms with attribution", calibrate="no", notes="School coordinates and attributes; no routes and no official school-level enrolment field."),
    dict(source_id="gov_school_bus_reply_2013", title="LCQ7: School bus services", provider="Hong Kong Government / Legislative Council reply", url="https://www.info.gov.hk/gia/general/201310/09/P201310090218.htm", validity="published 2013-10-09; historical", coverage="Hong Kong historical vehicle/service categories", evidence_class="official_historical", content_class="official_aggregate_or_definition", official="yes", licence="Hong Kong Government copyright", calibrate="no", notes="Historical fleet/category evidence only; not current totals or routes."),
    dict(source_id="data_gov_terms", title="DATA.GOV.HK Terms and Conditions of Use", provider="DATA.GOV.HK", url="https://data.gov.hk/en/terms-and-conditions", validity="current page accessed 2026-08-06", coverage="DATA.GOV.HK datasets", evidence_class="official_current", content_class="licence_or_terms", official="yes", licence="Terms permit browsing/downloading/distribution/reproduction subject to stated conditions and attribution", calibrate="no", notes="Applies to eligible DATA.GOV.HK resources; does not grant rights over unrelated school/operator documents."),
    dict(source_id="govhk_copyright", title="Copyright notice", provider="GovHK", url="https://www.gov.hk/en/about/copyright.htm", validity="current page accessed 2026-08-06", coverage="Hong Kong Government digital content", evidence_class="official_current", content_class="licence_or_terms", official="yes", licence="Government copyright notice; conditions differ by content and intended use", calibrate="no", notes="Check the source-specific notice before redistribution."),
    dict(source_id="dgs_tender_2026", title="Tender for Provision of School Bus Service", provider="Diocesan Girls' School / Junior School", url="https://www.dgs.edu.hk/api/file?id=1773200619983", validity="issued 2026-03-09; contract 2026-09-01 to 2029-08-31; routes based on 2025/26", coverage="27 DGS/DGJS routes; about 509 subscribers", evidence_class="first_party_current", content_class="actual_school_bus_route", official="school_first_party", licence="Restricted tender document: internal calibration only; do not redistribute route/stop tables without consent", calibrate="summary_only", notes="Exact route/stop tables exist; only aggregate capacity and duration evidence may enter derived documentation."),
    dict(source_id="hktayy3_routes_2526", title="School Bus Route 2025/26", provider="HKTA The Yuen Yuen Institute No.3 Secondary School", url="https://www.hktayy3.edu.hk/CustomPage/33/School_Bus_Route_2526v2.pdf", validity="2025/26", coverage="Sai Kung; Lei Yue Mun/Lam Tin/Sau Mau Ping to Tseung Kwan O", evidence_class="first_party_current", content_class="actual_school_bus_route", official="school_first_party", licence="School copyright; research/audit use with citation; no open-data licence stated", calibrate="yes", notes="Two routes with ordered stops and morning pickup times."),
    dict(source_id="twtaps_routes_2526", title="Application for taking school bus in 2025/26", provider="Tsuen Wan Trade Association Primary School", url="https://twtapsweb01.twtaps.edu.hk/twtapsweb/notes/2024-2025_notes/24-205%20Circular%20on%20the%20application%20for%20t%20aking%20school%20bus%20in%202025-2026.pdf", validity="2025/26", coverage="Tsing Yi, Kwai Chung, Tsuen Wan, Tsing Lung Tau", evidence_class="first_party_current", content_class="actual_school_bus_route", official="school_first_party", licence="School copyright; no open-data licence stated", calibrate="yes", notes="Five broad route/stop-area groups and fares."),
    dict(source_id="cccklc_routes_2526", title="School Bus Services", provider="CCC Kung Lee College", url="https://www.cccklc.edu.hk/en/site/page?name=School+Bus+Services", validity="2025/26", coverage="Hong Kong Island to Tai Hang", evidence_class="first_party_current", content_class="actual_school_bus_route", official="school_first_party", licence="School copyright; no open-data licence stated", calibrate="yes", notes="Two routes, seat counts and morning departure times."),
    dict(source_id="bfhmc_routes_2526", title="School Bus Service 2025/26", provider="Buddhist Fat Ho Memorial College", url="https://www.bfhmc.edu.hk/content.php?id=1003&lng=us-en", validity="published 2025-06-11; 2025/26", coverage="Tung Chung and Mui Wo to Tai O", evidence_class="first_party_current", content_class="actual_school_bus_route", official="school_first_party", licence="School copyright; no open-data licence stated", calibrate="yes", notes="Pickup places for two routes."),
    dict(source_id="mary_rose_routes_2425", title="School bus routes and fare", provider="Mary Rose School", url="https://www.mrs.edu.hk/cakecms/app/webroot/upload/schoollists/2940/2024-25%20school%20bus%20routes%20and%20fare_eng_original.pdf", validity="revised 2024-09-05; 2024/25 historical", coverage="Special-school routes across Kowloon, New Territories and Hong Kong Island", evidence_class="first_party_historical", content_class="actual_school_bus_route", official="school_first_party", licence="School copyright; no open-data licence stated", calibrate="yes", notes="Ten historical routes with exact route locations and 19/27/28/50-seat vehicles."),
    dict(source_id="jcctm_route_2025", title="Tuen Mun school bus second-stage application", provider="Ju Ching Chu Secondary School (Tuen Mun)", url="https://www.jcctm.edu.hk/web/wp-content/uploads/%E5%AE%B6%E9%95%B7%E9%80%9A%E5%91%8A2025-2026_166_%E5%B1%AF%E9%96%80%E7%B7%9A%E6%A0%A1%E5%B7%B4%E7%AC%AC%E4%BA%8C%E9%9A%8E%E6%AE%B5%E7%94%B3%E8%AB%8B.pdf", validity="issued 2025-11-17; 2025-12 to 2026-02", coverage="Queen's Hill/Fanling/Sheung Shui/Fu Tai to Tuen Mun", evidence_class="first_party_current", content_class="actual_school_bus_route", official="school_first_party", licence="School copyright; no open-data licence stated", calibrate="yes", notes="One long route, 06:45 first pickup and 08:00 arrival."),
    dict(source_id="apsw_routes_2526", title="School Bus Routes 2025/26", provider="Alliance Primary School, Whampoa", url="https://www.apsw.edu.hk/sites/default/files/files/2526xiao_ba_lu_xian__0.pdf", validity="2025/26", coverage="Kowloon and nearby districts to Whampoa", evidence_class="first_party_current", content_class="actual_school_bus_route", official="school_first_party", licence="School copyright; no open-data licence stated", calibrate="yes", notes="Five numbered routes (1, 3, 5, 6 and 7) with visual inbound/outbound stop sequences; no pickup times."),
    dict(source_id="fls_routes_2526", title="School bus", provider="ELCHK Lutheran Academy", url="https://www.fls.edu.hk/%E6%A0%A1%E8%BB%8A/", validity="2025/26", coverage="New Territories school service", evidence_class="first_party_current", content_class="actual_school_bus_route", official="school_first_party", licence="School copyright; no open-data licence stated", calibrate="yes", notes="Operator and nine pickup locations."),
    dict(source_id="kcm_isf_routes_2526", title="ISF tentative home schedule", provider="Kwoon Chung Motors", url="https://school.kcm.com.hk/ors/download/25-26%20ISF_RT.pdf", validity="2025/26 tentative", coverage="Multiple corridors to/from ISF", evidence_class="operator_first_party_current", content_class="actual_school_bus_route", official="operator_first_party", licence="Operator copyright; tentative schedule; no open-data licence stated", calibrate="yes", notes="Twenty-two proposed inbound route IDs with ordered stops and times; routes may change with applications."),
    dict(source_id="plkctslps_service", title="School Bus Service", provider="PLK Camões Tan Siu Lin Primary School", url="https://www.plkctslps.edu.hk/en/content.php?wid=103", validity="current page", coverage="Service areas for one school", evidence_class="first_party_current", content_class="school_transport_service_no_route", official="school_first_party", licence="School copyright; no open-data licence stated", calibrate="no", notes="Operator/service areas only; routes may regroup or be cancelled."),
    dict(source_id="existing_regular_pt_excluded", title="Existing Hong Kong regular public transport supply", provider="TD/CSDI/operator APIs already held by project", url="", validity="current project baseline 0b964e0", coverage="Franchised bus, GMB, MTR, LRT, tram and ferry", evidence_class="project_observed_and_processed", content_class="ordinary_public_bus_excluded", official="mixed", licence="See existing public-transport source manifests", calibrate="no", notes="Inventory pointer only. Deliberately not downloaded by this collector."),
]

FIELDS = ["source_id", "title", "provider", "url", "validity", "access_date", "coverage", "evidence_class", "content_class", "official", "licence", "download_filename", "download_status", "sha256", "bytes", "calibrate", "notes"]


def safe_name(source: dict, content_type: str) -> str:
    url_path = source["url"].lower().split("?")[0]
    if "pdf" in content_type.lower() or url_path.endswith(".pdf"):
        suffix = ".pdf"
    elif "csv" in content_type.lower() or url_path.endswith(".csv"):
        suffix = ".csv"
    else:
        suffix = ".html"
    return source["source_id"] + suffix


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--catalog-only", action="store_true", help="Write metadata without downloading documents")
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    documents = args.output_dir / "documents"
    if not args.catalog_only:
        documents.mkdir(exist_ok=True)

    rows = []
    for item in SOURCES:
        row = dict(item, access_date=ACCESS_DATE, download_filename="", download_status="not_requested", sha256="", bytes="")
        if not args.catalog_only and item["url"] and item["content_class"] != "ordinary_public_bus_excluded":
            try:
                req = Request(item["url"], headers={"User-Agent": "HK-school-bus-research/1.0 (+source-audit)"})
                with urlopen(req, timeout=args.timeout) as response:
                    payload = response.read()
                    name = safe_name(item, response.headers.get("Content-Type", ""))
                target = documents / name
                target.write_bytes(payload)
                row.update(download_filename=str(Path("documents") / name), download_status="downloaded", sha256=hashlib.sha256(payload).hexdigest(), bytes=len(payload))
            except Exception as exc:  # keep a complete catalogue even when a site blocks automation
                row["download_status"] = "failed: " + str(exc)[:240]
        rows.append(row)

    catalog = args.output_dir / "source_catalog.csv"
    with catalog.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    with (args.output_dir / "SOURCE_MANIFEST.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["path", "sha256", "bytes", "source_url", "accessed_at_utc"])
        writer.writeheader()
        stamp = datetime.now(timezone.utc).isoformat()
        for row in rows:
            if row["sha256"]:
                writer.writerow(dict(path=row["download_filename"], sha256=row["sha256"], bytes=row["bytes"], source_url=row["url"], accessed_at_utc=stamp))
    counts = {}
    for row in rows:
        counts[row["content_class"]] = counts.get(row["content_class"], 0) + 1
    summary = {"created_at_utc": datetime.now(timezone.utc).isoformat(), "access_date": ACCESS_DATE, "source_count": len(rows), "class_counts": counts, "downloaded": sum(r["download_status"] == "downloaded" for r in rows), "failed": sum(str(r["download_status"]).startswith("failed:") for r in rows), "warning": "A catalogue entry or downloaded document is evidence, not permission to redistribute it."}
    (args.output_dir / "acquisition_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
