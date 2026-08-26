# Hong Kong progress-report figures (2026-08-24)

## Purpose and status boundary

This figure set supports a supervisor progress report whose comparison baseline
predates the private-car monetary-cost model, the public-transport fare model,
the school-bus model, and the physical household private-car model.  It shows
what those additions make observable: real-money cost components, scarce
vehicles, coordinated household movement, signal control, and auditable event
outcomes.

The figures do **not** redefine the adopted Hong Kong production run.  Figures
1, 4, 5, 8 and B use iteration 49 of the documented run3-iteration-0--40 plus
run6-iteration-41--49 checkpoint-recovery sensitivity.  Figures 2 and 3 use
the Stage 11 run56/run57 mechanical gates.  Figure A uses the Candidate11
signal package.  These are candidate or validation results and are labelled as
such in the figure footnotes.

The common output directory is ignored by Git:

```text
runs/hongkong/outputs/progress_report_figures_20260824/
```

Every final figure is written as a presentation PNG and a vector PDF.  Where a
figure reconstructs non-trivial rules, a provenance or summary JSON is also
written beside it.

## Figure catalogue

### Figure 1: model evolution

`01_hong_kong_model_evolution` connects the original person-plan, transport
supply, and score-based-choice foundation to the newly implemented monetary,
physical-resource, signal-control, and audit layers.  The central map is not a
schematic: it aggregates 742,189 realised iteration-49 trips to the 18
districts and displays the dominant mode on the leading OD links.

Reproduction script:
`scripts/hong_kong_single_city/analysis_visualization/build_hong_kong_progress_figure01_model_evolution.py`.

### Figure 2: school-bus timing repair

`figure02_school_bus_walk_timing_repair` follows the real selected trip of
`hk_person_00632810`.  In run56, link-by-link integer rounding puts the student
at the pickup point at 07:38:17, three seconds after the 07:38:14 vehicle
boarding event.  The continuous-duration repair in run57 advances arrival to
07:38:07 and restores boarding.  The map uses the actual access-walk and
school-bus link sequences; the lower panel shows the measured accumulation of
the ten-second error over 20 walk links.

Reproduction script:
`scripts/hong_kong_single_city/analysis_visualization/plot_progress_school_bus_walk_timing_repair.py`.

### Figure 3: one household, one physical car

`figure03_household_joint_car_timeline` follows household `hk_hh_1251667`,
driver `hk_person_03051340`, student `hk_person_03051341`, and vehicle
`hk_vehicle_0210204`.  The realised morning LinkEnter sequence and broken
event-time axis show the school drop-off, onward drive to work, afternoon
pickup, and shared return.  The selected composite plan is compared with the
preserved Walk baseline.  MATSim scores shown in this figure are utilities,
not money and not observed household preferences.

Reproduction script:
`scripts/hong_kong_single_city/analysis_visualization/plot_progress_household_joint_car_timeline.py`.

### Figure 4: private-car trip cost anatomy

`figure_04_private_car_cost_anatomy` is an executed iteration-49 trip selected
reproducibly as the median-cost complete 8--35 km case with positive energy,
toll, and parking components.  The example (`hk_person_01925581`) costs
HK$122.7: HK$20.7 route energy, HK$30.0 Cross-Harbour Tunnel toll at the actual
LinkEnter time, and HK$72.0 destination parking.  Fixed ownership remains a
vehicle-day sidecar and is deliberately not allocated to the trip.

Reproduction script:
`scripts/hong_kong_single_city/analysis_visualization/plot_progress_private_car_cost_anatomy.py`.

### Figure 5: finite Taxi fleet

`05_hong_kong_finite_taxi_operations` aggregates realised Taxi trips to the 18
districts and combines the flow map with an hourly request-versus-active-fleet
radial inset.  The matching request and vehicle ledgers record 15,500 physical
vehicles, 186,144 completed requests, 17 requests waiting at the simulation
horizon, and a 16.5% fleet empty-VKT share.  The Taxi cost model used elsewhere
is distance-only; waiting disutility is not converted to HKD.

Reproduction script:
`scripts/hong_kong_single_city/analysis_visualization/build_hong_kong_progress_figure05_taxi_operations.py`.

### Figure 8: experienced PT fare network

`figure_8_pt_fare_network_central` starts from a 1.2 km Central--Admiralty
source area and aggregates actual iteration-49 boarding/alighting chains to
the 42 leading destination stops.  Of 10,066 experienced itineraries, 9,792
(97.28%) have a fully resolved strict fare.  Four actual itineraries expose
segment-by-segment MTR, bus, ferry, and transfer-chain amounts.

The script reproduces the runtime five-layer exact-key logic and verifies the
ten fare tables/crosswalks by SHA256.  It does not use distance, reverse-order,
full-route, or zero-value fallbacks.  Amounts are adult-reference/base-Octopus
model rules; individual concessions and transfer discounts are not modelled.

Reproduction script:
`scripts/hong_kong_single_city/analysis_visualization/plot_progress_pt_fare_network.py`.

### Figure A: Candidate11 signals and green wave

`figure_a_candidate11_signals_greenwave` combines the full Hong Kong signal
distribution, a local road view of a reproducibly selected corridor, and its
time-space coordination diagram.  The compiled package contains 1,445 signal
systems, 3,243 groups, and 6,941 controlled turns.  Fourteen implemented
corridors contain 47 distinct corridor systems.  The representative
`corridor_002` reverse direction uses fixed offsets 0, 3, 8, and 12 seconds in
the displayed 20:15--20:30 peak coordination bin.

Signal locations and controlled turns come from the compiled MATSim package.
Cycle plans and corridor offsets are modelled research candidates, not
observed Hong Kong signal timings.

Reproduction script:
`scripts/hong_kong_single_city/analysis_visualization/plot_progress_candidate11_signals.py`.

### Figure B: Hong Kong real-money cost geography

`figure_b_hong_kong_monetary_cost_maps` maps mean model-rule HKD per priced
trip to the fixed-link grid for all priced modes, PT, private car, and Taxi.
The priced universe contains 566,437 trips: 364,160 fully resolved PT trips,
16,133 complete private-car trips, and 186,144 completed Taxi trips.

PT unresolved chains remain null, never zero.  Private-car cost includes route
energy, exact-time tolls, and settled destination parking, but excludes
motorcycles, fixed ownership, passenger-side allocation, and unresolved
terminal parking.  Taxi cost uses the vehicle type and realised occupied-trip
distance and excludes waiting, booking, baggage, and tunnel surcharges.

Reproduction script:
`scripts/hong_kong_single_city/analysis_visualization/plot_progress_hong_kong_monetary_cost_maps.py`.

## Shared visual language

`scripts/hong_kong_single_city/analysis_visualization/progress_report_figure_style.py`
defines the common white background, pale-grey land, thin district/road
boundaries, restrained blue and brick-red accents, compact legends, and bottom
method notes derived from the supplied reference figure.  The set avoids a
sequence of generic histograms: it uses flow maps, time-space diagrams,
event-time narratives, route anatomy, a radial operational inset, network
itineraries, and small-multiple geographic surfaces.

## Supervisor progress-report deck

The eight-figure set is assembled into an 11-slide, 16:9 supervisor report in:

```text
projects/hong_kong_progress_report_20260825_ppt169_20260825/
```

The deck uses one baseline slide, eight figure-led evidence slides, and one
three-part synthesis slide.  It deliberately contains no outlook section.
`design_spec.md` and `spec_lock.md` record the confirmed scientific-editorial
design and execution constraints; `notes/total.md` provides Chinese presenter
notes.  The native editable PowerPoint export is:

```text
projects/hong_kong_progress_report_20260825_ppt169_20260825/exports/hong_kong_progress_report_20260825_20260825_100045.pptx
```

The final SVG quality gate completed with zero blocking errors, and the PPTX
package postflight completed as `passed-with-warnings`.  The remaining warnings
are non-blocking text-estimation and source-image-size advisories; no figure,
speaker-note page, or image resource is missing.

### Scheme B English deck

A separate all-English, large-visual Scheme B edition is preserved in:

```text
projects/hong_kong_progress_report_scheme_b_english_20260825_ppt169_20260825/
```

It keeps the same 11-slide scientific narrative and the same eight no-crop
figures, but uses sparse English copy, oversized evidence anchors, asymmetric
figure rails, and English presenter notes.  It does not overwrite the earlier
Scheme A deck and contains no outlook section.  The native editable export is:

```text
projects/hong_kong_progress_report_scheme_b_english_20260825_ppt169_20260825/exports/hong_kong_progress_report_scheme_b_english_20260825_20260825_102520.pptx
```

The Scheme B final SVG gate completed with zero blocking errors.  PPTX
postflight completed as `passed-with-warnings`; the remaining items are
non-blocking SVG text-flow and large-source-image advisories.

## Reproduction environment and limitations

Use the project geospatial interpreter:

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe -B <script>
```

Source-data extracts in the output directory are compact report inputs copied
read-only from immutable server runs under `/mnt/DiskM/by`.  Complete events
and server simulations are not copied into Git.  The maps use EPSG:32650.  No
figure should be interpreted as observed Hong Kong behaviour, a calibrated
fare/payment statement, or acceptance of the candidate workflow as the
production scenario.
