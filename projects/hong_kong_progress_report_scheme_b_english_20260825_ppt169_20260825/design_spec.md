<!-- ppt-master-schema: design-spec/v1 -->
# Hong Kong Progress Report — Scheme B English - Design Spec

## I. Project Information

| Item | Value |
| --- | --- |
| Project Name | Hong Kong Progress Report — Scheme B English |
| Canvas Format | PPT 16:9 (1280 × 720) |
| Page Count | 11 |
| Primary Language | en |
| Target Audience | Research supervisor familiar with the Hong Kong MATSim programme and interested in verifiable recent progress. |
| Communication Intent | Report the recent implementation progress relative to the pre-cost, pre-fare, pre-school-bus, and pre-physical-car baseline; foreground the new observability and auditability rather than future work. |
| Desired Audience Outcome | The supervisor can identify what is newly modelled, what each new layer makes measurable, and which results remain candidate or validation evidence rather than adopted production. |
| Core Message / Ask / Action | The model has moved from score-based multimodal demand to a monetized, resource-constrained, event-auditable system while preserving explicit provenance boundaries. |
| Delivery Context | Presenter-led progress meeting with the deck retained as a concise review artifact. |
| Artifact Afterlife | Supervisor review, progress record, and later reuse in research documentation. |
| Reading Mode | presentation |
| Content Strategy | Reframe the source into a visual-first evidence sequence while preserving all quantitative claims, caveats, and candidate-versus-production boundaries. |
| Design Style | Scheme B — large-visual scientific storytelling with sparse English copy and strong page-to-page rhythm. |
| AI Image Acquisition Path | not applicable |
| Generation Mode | continuous |
| Spec Refinement | disabled |
| Speaker Notes | enabled — workflow default and required for presenter-led explanation |
| Custom Animations | disabled — workflow default |
| Narration Audio | disabled — workflow default |
| Created Date | 2026-08-25 |

## II. Canvas Specification

| Property | Value |
| --- | --- |
| Format | PPT 16:9 |
| Dimensions | 1280 × 720 |
| viewBox | `0 0 1280 720` |
| Margins | 52 px left/right; 38 px top; 34 px bottom |
| Content Area | 1176 × 648 px within the safe frame |

## III. Visual Theme

### Theme Style

- **Mode**: custom
- **Mode References**: showcase, briefing
- **Mode Behavior**: Advance one evidence-backed conclusion per page; use a dominant scientific figure as the primary carrier and reserve visible prose for a short claim, one evidence anchor, and one boundary statement.
- **Visual style**: custom
- **Visual Style References**: photo-editorial, swiss-minimal
- **Visual Style Behavior**: Treat each supplied scientific figure as an editorial hero plate within a strict Swiss grid, using flat color fields, generous white space, precise rules, and no ornamental texture, shadow, or generic card grids.
- **Theme**: Hong Kong transport evidence atlas
- **Tone**: rigorous, contemporary, confident, and explicitly qualified

### Color Scheme

| Role | HEX | Purpose |
| --- | --- | --- |
| Background | #FFFFFF | Main scientific canvas and figure surround |
| Secondary background | #EEF1EF | Quiet bands, caption fields, and baseline structure |
| Primary | #2F7895 | Section identity, evidence anchors, and monetized/physical progress |
| Accent | #C45139 | Exceptions, operational tension, and critical comparison |
| Secondary accent | #D1A04A | Candidate status, timing, and monetary highlights |
| Body text | #202629 | Titles, labels, and explanatory copy |

## IV. Typography System

### Font Plan

| Role | Character (Reference) | Primary | English if non-English | Fallback tail |
| --- | --- | --- | --- | --- |
| Title | modern grotesk / compact | Arial | Arial | Aptos, sans-serif |
| Body | neutral sans / highly legible | Arial | Arial | Aptos, sans-serif |
| Annotation | neutral sans / compact | Arial | Arial | Aptos, sans-serif |

- **Title stack**: Arial, Aptos, sans-serif
- **Body stack**: Arial, Aptos, sans-serif
- **Annotation stack**: Arial, Aptos, sans-serif

### Font Size Hierarchy

| Purpose | Anchor Size (px) |
| --- | ---: |
| Body | 22 |
| Title | 42 |
| Subtitle | 28 |
| Annotation | 16 |
| Claim | 34 |
| Hero | 56 |

## V. Layout Principles

### Deck-wide Direction

- **Hierarchy direction**: Read the page claim first, enter the figure through one highlighted evidence cue, and finish at the lower boundary/caveat line.
- **Composition tendency**: Use near-full-canvas figures with asymmetric title rails, occasional full-bleed color fields, and one deliberate pause page rather than repeated multi-card layouts.
- **Cross-page continuity**: Maintain a small page index, a thin evidence rule, and the same bottom boundary position; vary figure scale and title placement to fit each image ratio.
- **Spacing posture**: Open on cover, baseline, and synthesis pages; dense but disciplined on evidence pages; never crop the supplied figures.

## VI. Icon Usage Specification

- **Primary bundled library**: none

| Icon Path | Suitable Scenarios |
| --- | --- |

## VIII. Image Resource List

| Filename | Dimensions | Ratio | Purpose | Type | Layout pattern | Crop Policy | Acquire Via | Status | Reference | text_policy | page_role |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 01_hong_kong_model_evolution.png | 3443 × 2206 | 1.56 | Show the full-system evolution from the baseline to the new monetary, physical, signal, and audit layers. | scientific figure | large centered plate with a narrow left claim rail | no-crop | user | Existing | Use the complete supplied figure; preserve its internal labels. | P03 hero evidence |
| figure02_school_bus_walk_timing_repair.png | 3277 × 1965 | 1.67 | Explain how a ten-second accumulated walk-timing error caused and then repaired a missed physical boarding. | scientific figure | broad figure below a short headline strip | no-crop | user | Existing | Use the complete supplied figure; preserve its internal labels. | P04 hero evidence |
| figure03_household_joint_car_timeline.png | 3701 × 1965 | 1.88 | Demonstrate one household coordinating a full day around one physical vehicle. | scientific figure | panoramic plate with a compact right evidence marker | no-crop | user | Existing | Use the complete supplied figure; preserve its internal labels. | P05 hero evidence |
| 05_hong_kong_finite_taxi_operations.png | 3180 × 2443 | 1.30 | Show finite Taxi fleet geography and the request-versus-active-fleet operational rhythm. | scientific figure | tall centered plate with a slim metric rail | no-crop | user | Existing | Use the complete supplied figure; preserve its internal labels. | P06 hero evidence |
| figure_04_private_car_cost_anatomy.png | 5034 × 1952 | 2.58 | Decompose an executed private-car trip into energy, toll, and parking in real HKD. | scientific figure | ultra-wide evidence band across the page | no-crop | user | Existing | Use the complete supplied figure; preserve its internal labels. | P07 hero evidence |
| figure_8_pt_fare_network_central.png | 4325 × 2620 | 1.65 | Expose experienced PT itineraries and exact fare resolution across the network. | scientific figure | large figure with a top-left claim tab | no-crop | user | Existing | Use the complete supplied figure; preserve its internal labels. | P08 hero evidence |
| figure_b_hong_kong_monetary_cost_maps.png | 4504 × 2301 | 1.96 | Compare the spatial distribution of total, PT, car, and Taxi real-money costs. | scientific figure | panoramic map plate with one large universe count | no-crop | user | Existing | Use the complete supplied figure; preserve its internal labels. | P09 hero evidence |
| figure_a_candidate11_signals_greenwave.png | 3828 × 2634 | 1.45 | Present the territory-wide signal package and one candidate green-wave corridor. | scientific figure | tall figure framed by a candidate-status color field | no-crop | user | Existing | Use the complete supplied figure; preserve its internal labels. | P10 hero evidence |

## IX. Content Outline

### Part 1: Framing

#### Slide 01 - From Scores to Observable Urban Operations

- **Audience move**: Move from expecting a routine progress update to seeing a concrete change in what the model can observe and audit.
- **Layout**: A deep-blue field with one oversized headline, a compact subtitle, and three large English keywords—MONETIZED, PHYSICALIZED, AUDITABLE—arranged as the visual hook.
- **Title**: From Scores to Observable Urban Operations
- **Core message**: Recent work changes the model’s observable reality, not only its parameter list.
- **Content**: Hong Kong MATSim progress report. Subtitle: “Private-car costs · PT fares · school bus · physical cars · finite Taxi · signals”. Small footer: “Scheme B · English edition · 25 Aug 2026”.
- **Cover impact**: The binding hook is the transition from abstract scores to auditable money, vehicles, and events.

#### Slide 02 - Baseline: Multimodal, but Still Abstract

- **Audience move**: Establish one concise comparison baseline before the progress evidence begins.
- **Layout**: One horizontal baseline spine with three large nodes—person plans, transport supply, score-based choice—followed by a red gap statement.
- **Title**: Baseline: Multimodal, but Still Abstract
- **Core message**: The original model could route and score travel, but key costs and scarce resources were not yet explicit.
- **Content**: “Available: person plans, road/PT supply, score-based mode choice.” “Not yet explicit: private-car HKD, experienced PT fares, physical school buses, household vehicle continuity.” Bottom statement: “This deck reports what became observable after those layers were introduced.”

### Part 2: Eight Evidence Plates

#### Slide 03 - The Model Now Connects Choice to Operations

- **Audience move**: See the recent work as one integrated model evolution rather than unrelated features.
- **Layout**: Narrow left claim rail and a large complete figure plate; a small blue evidence tag names the realised-trip universe.
- **Title**: The Model Now Connects Choice to Operations
- **Core message**: Monetary rules, physical resources, signal control, and audits now attach to the original demand-and-supply foundation.
- **Content**: Evidence tag: “742,189 realised iteration-49 trips · 18 districts”. Boundary: “Candidate / validation evidence; not a redefinition of the adopted production run.”
- **Images**: 01_hong_kong_model_evolution.png as the dominant no-crop figure.

#### Slide 04 - Ten Seconds Determined Whether a Student Boarded

- **Audience move**: Understand why event-level timing precision matters for physical school-bus execution.
- **Layout**: Short top claim strip over a broad no-crop figure; a red-to-blue timing marker highlights before/after arrival.
- **Title**: Ten Seconds Determined Whether a Student Boarded
- **Core message**: Continuous due-time scheduling removed accumulated link-rounding error and restored the selected boarding.
- **Content**: “Run56: arrival 07:38:17 · boarding 07:38:14.” “Run57: arrival 07:38:07 · boarding restored.” “The 10-second error accumulated across 20 walk links.”
- **Images**: figure02_school_bus_walk_timing_repair.png as the dominant no-crop figure.

#### Slide 05 - One Household, One Car, One Coordinated Day

- **Audience move**: Recognize that a private car is now a continuous household resource rather than an independent leg label.
- **Layout**: Panoramic no-crop figure with a compact right-side identity strip for household, people, and vehicle.
- **Title**: One Household, One Car, One Coordinated Day
- **Core message**: The realised day links school drop-off, work, afternoon pickup, and return through the same physical vehicle.
- **Content**: “Household hk_hh_1251667 · vehicle hk_vehicle_0210204.” Boundary: “Shown MATSim scores are utility—not money and not observed preferences.”
- **Images**: figure03_household_joint_car_timeline.png as the dominant no-crop figure.

#### Slide 06 - Taxi Is Now a Finite Operating Fleet

- **Audience move**: Shift from treating Taxi as a teleported mode to reading it as a scarce, reusable fleet with explicit request states.
- **Layout**: Tall complete figure centered on a pale field; a slim left metric rail carries fleet and service anchors.
- **Title**: Taxi Is Now a Finite Operating Fleet
- **Core message**: Physical vehicles, request ledgers, and empty movement make supply–demand tension visible.
- **Content**: “15,500 physical taxis.” “186,144 completed requests.” “17 waiting at the horizon.” “16.5% empty-VKT.” Boundary: “Taxi monetary cost is distance-only; waiting disutility is not converted to HKD.”
- **Images**: 05_hong_kong_finite_taxi_operations.png as the dominant no-crop figure.

#### Slide 07 - A Car Trip Can Be Read in Real HKD

- **Audience move**: See how an executed route becomes an auditable monetary bill.
- **Layout**: Ultra-wide no-crop figure as a central evidence band; one oversized HK$122.7 anchor above it.
- **Title**: A Car Trip Can Be Read in Real HKD
- **Core message**: Route energy, exact-time tolls, and settled destination parking are combined without hiding component provenance.
- **Content**: “HK$122.7 = HK$20.7 energy + HK$30.0 Cross-Harbour Tunnel toll + HK$72.0 parking.” Boundary: “Fixed ownership remains a vehicle-day sidecar and is not allocated to this trip.”
- **Images**: figure_04_private_car_cost_anatomy.png as the dominant no-crop figure.

#### Slide 08 - PT Fare Is Resolved from Experienced Itineraries

- **Audience move**: Understand that PT price is reconstructed from actual boarding/alighting chains rather than a generic distance proxy.
- **Layout**: Large complete figure with a compact claim tab and a thin bottom methods line.
- **Title**: PT Fare Is Resolved from Experienced Itineraries
- **Core message**: Exact-key fare resolution makes multi-segment PT costs transparent and auditable.
- **Content**: “10,066 experienced itineraries.” “9,792 fully resolved · 97.28%.” “42 leading destination stops · four actual itinerary examples.” Boundary: “Adult-reference/base-Octopus rules; no distance, reverse-order, full-route, or zero fallback.”
- **Images**: figure_8_pt_fare_network_central.png as the dominant no-crop figure.

#### Slide 09 - 566,437 Trips Now Have a Monetary Geography

- **Audience move**: Read cost not only as a trip attribute but as a territory-wide spatial pattern by mode.
- **Layout**: Panoramic no-crop map plate under a large universe count; a four-word mode key sits above the map.
- **Title**: 566,437 Trips Now Have a Monetary Geography
- **Core message**: Total, PT, private-car, and Taxi costs can now be compared in real model-rule HKD across Hong Kong.
- **Content**: “364,160 PT · 16,133 car · 186,144 Taxi.” Boundary: “Unresolved PT chains remain null, never zero; each mode retains its documented inclusion and exclusion scope.”
- **Images**: figure_b_hong_kong_monetary_cost_maps.png as the dominant no-crop figure.

#### Slide 10 - Signals Add a New Layer of Network Coordination

- **Audience move**: See traffic control as a spatially distributed candidate system with inspectable corridor timing.
- **Layout**: Candidate-gold page field with the complete figure set into a large white viewing window; a compact candidate label sits in the title rail.
- **Title**: Signals Add a New Layer of Network Coordination
- **Core message**: The model can express territory-wide signal control and test a reproducible green-wave corridor.
- **Content**: “1,445 systems · 3,243 groups · 6,941 controlled turns.” “14 corridors · 47 distinct corridor systems.” “corridor_002 reverse offsets: 0, 3, 8, 12 seconds.” Boundary: “Candidate cycle plans and offsets—not observed Hong Kong timings.”
- **Images**: figure_a_candidate11_signals_greenwave.png as the dominant no-crop figure.

### Part 3: Synthesis

#### Slide 11 - Three Capabilities Now Work Together

- **Audience move**: Leave with a compact and defensible statement of what changed in this reporting period.
- **Layout**: Three oversized vertical words with one evidence sentence beneath each; the final statement spans the bottom edge.
- **Title**: Three Capabilities Now Work Together
- **Core message**: The progress is best understood as monetization, physicalization, and auditability operating together.
- **Content**: “MONETIZED — car, PT, and Taxi costs are expressed in real model-rule HKD.” “PHYSICALIZED — school buses, household cars, and Taxi fleets have continuity and scarcity.” “AUDITABLE — outcomes are traceable through routes, ledgers, events, hashes, and explicit null/fallback rules.” Closing line: “The result is a more interpretable urban simulation, with candidate and production boundaries kept visible.”
- **Closing impact**: The binding takeaway is that the new layers jointly turn abstract choices into interpretable, inspectable urban operations.

## X. Speaker Notes Requirements

- **Generation**: enabled
- **Filename**: match each SVG filename under `notes/`
- **Content**: English presenter notes grounded only in the supplied figure documentation and final page visuals; explain interpretation, provenance, and candidate-versus-production boundaries without adding new claims.
- **Total duration**: approximately 12 minutes
- **Notes style**: formal, conversational, and supervisor-facing
- **Presentation purpose**: report progress and explain scientific meaning
