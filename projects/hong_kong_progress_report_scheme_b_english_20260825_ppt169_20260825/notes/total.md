# 01_cover

This report focuses on what has changed in the Hong Kong multimodal MATSim model during the latest development period. The central point is not that several parameters were added. The model now brings monetary costs, scarce physical vehicles, signal control, and event-level audits into one coherent operating framework. The eight evidence plates that follow move between territory-wide patterns and cases resolved to a named person, vehicle, link, or second. The deck reports completed implementation and validation evidence only; it contains no outlook section.

---

# 02_baseline

This single slide defines the comparison baseline. The original model already had activity plans, road and public-transport supply, and score-based mode choice, so the essential demand, supply, and selection structure was in place. Four important layers were still abstract: private-car energy, toll, and parking could not be audited in Hong Kong dollars; experienced PT fares were absent from mode costs; school-bus access and boarding lacked event-level verification; and a household car was not yet represented as a physical resource with ownership and temporal continuity. The remaining slides focus on how those gaps became observable.

---

# 03_model_evolution

This figure places the recent work within the full model architecture. The central map aggregates 742,189 realised iteration-49 trips across all 18 districts, giving the cost, vehicle, and control layers a shared simulation context. Four connected additions now sit on the original plan-and-supply foundation: real-money costs for car, PT, and Taxi; physical resources including household cars, school buses, and a finite Taxi fleet; signal systems and corridor offsets; and audit records based on named entities, event times, and explicit missing-value rules. These are candidate or validation results and do not redefine the adopted production scenario.

---

# 04_school_bus_timing

The school-bus case shows how a small timing implementation detail can change interaction with a physical vehicle. For student hk_person_00632810, integer rounding on each walk link placed arrival at 07:38:17 in run56, while the vehicle boarding event occurred at 07:38:14. The student therefore arrived three seconds late. Scheduling the next link from the previous continuous due time moved arrival to 07:38:07 in run57 and restored boarding. The lower panel traces how ten seconds of error accumulated over twenty walk links, so the repair addresses a reproducible mechanical cause rather than manually changing the selected plan.

---

# 05_household_car

Here the private car is no longer a mode label that can be selected independently for every leg. It is a household resource with a continuous day. The example follows household hk_hh_1251667, driver hk_person_03051340, student hk_person_03051341, and vehicle hk_vehicle_0210204. The realised events show the same car completing the school drop-off, continuing to work, returning for the afternoon pickup, and carrying the household home. Vehicle location, occupancy, and availability therefore constrain the joint plan. The retained Walk plan is a comparison alternative; the MATSim scores in the figure are utilities, not Hong Kong dollars and not observed household preferences.

---

# 06_finite_taxi

The key Taxi change is the move from an abstract or teleported mode to a finite, reusable operating fleet with an explicit request ledger. The result contains 15,500 physical taxis, 186,144 completed requests, 17 requests still waiting at the simulation horizon, and a 16.5 percent empty-VKT share. The district flow map and the radial request-versus-active-fleet view come from the same execution result, so geography, hourly activity, and fleet utilisation can be read together. The monetary boundary is separate: Taxi cost elsewhere in the deck is based on realised occupied distance, while waiting disutility is not converted into Hong Kong dollars.

---

# 07_car_cost

This page shows an executed private-car trip, not a generic score penalty. The selected trip for hk_person_01925581 costs HK$122.7. HK$20.7 comes from route energy, HK$30.0 from entering the Cross-Harbour Tunnel at the actual LinkEnter time, and HK$72.0 from settled destination parking. Each component can be traced back through events and explicit model rules, making the final amount explainable. Fixed ownership cost remains in a vehicle-day sidecar and has deliberately not been allocated to this trip.

---

# 08_pt_fare

Public-transport fare is resolved from the passenger’s experienced boarding, alighting, and transfer chain rather than approximated from straight-line or route distance. From the 1.2-kilometre Central–Admiralty source area, the iteration-49 result contains 10,066 experienced itineraries. Of these, 9,792, or 97.28 percent, have a fully resolved strict fare, reaching 42 leading destination stops. Four actual itineraries expose segment-level MTR, bus, ferry, and transfer-chain amounts. Ten fare tables and crosswalks are verified by SHA256. The logic uses no distance, reverse-order, full-route, or zero-value fallback; unresolved chains remain missing. Amounts represent adult-reference and base-Octopus rules, without individual concessions or transfer discounts.

---

# 09_cost_geography

Once individual trip costs are auditable, they can be aggregated into a monetary geography for Hong Kong. The priced universe contains 566,437 trips: 364,160 fully resolved PT trips, 16,133 complete private-car trips, and 186,144 completed Taxi trips. The four maps compare total, PT, car, and Taxi mean model-rule costs across the fixed-link grid. The distinction between null and zero remains essential: unresolved PT chains stay null and are never silently counted as zero cost. The figure notes also retain the specific inclusion and exclusion scope for car and Taxi.

---

# 10_signals

The Candidate11 package extends road supply from static capacity to explicit traffic control. It contains 1,445 signal systems, 3,243 groups, and 6,941 controlled turns. Fourteen implemented corridors include 47 distinct corridor systems. The representative reverse direction of corridor_002 uses fixed offsets of zero, three, eight, and twelve seconds, displayed for the 20:15 to 20:30 coordination bin. The territory-wide distribution, local controlled-turn view, and time-space diagram all use the same compiled definitions. The signal cycles and corridor offsets remain modelled research candidates, not observations of Hong Kong signal timing.

---

# 11_synthesis

Taken together, the evidence supports three conclusions. First, the model is monetized: private-car cost components, strict PT fares, and Taxi distance costs can be expressed in real model-rule Hong Kong dollars. Second, it is physicalized: household cars, school-bus boarding, and the finite Taxi fleet introduce ownership, continuity, and scarcity. Third, it is auditable: people, vehicles, routes, events, fare-table hashes, signal systems, offsets, null values, and exclusions remain traceable. The practical advance is from a model that can run to a model that can explain critical operational outcomes, while keeping candidate and production boundaries visible.
