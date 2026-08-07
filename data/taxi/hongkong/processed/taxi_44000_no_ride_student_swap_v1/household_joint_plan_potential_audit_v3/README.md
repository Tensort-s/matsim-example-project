# Household joint-plan potential audit v3

This is the current Stage 11 candidate registry for delayed household
joint-plan innovation. It contains 9,289 passenger-driver pairs in 5,789
households. Each row is one passenger main trip, so outbound and return
directions remain independent. Passenger source modes are `car_passenger`,
`pt`, `taxi`, and `walk`; `school_bus` is excluded in this phase.

The detour path is screened as driver origin -> passenger pickup -> passenger
drop-off -> driver destination. Existing driver Car trips may be reused;
otherwise the runtime evaluates a complete home-based driver-day switch to
Car. The runtime selector performs routed schedule and household resource
checks after iteration 0.

Compared with v2, v3 excludes 90 passenger trips whose pickup and drop-off
resolve to the same network link. Twenty-three of those trips had survived the
v2 top-three pairing screen. A single QSim `LinkEnterEvent` cannot represent
both a distinct boarding and a later alighting waypoint, so these pairs are
structurally infeasible and are excluded rather than weakening physical
validation.

The companion parking-zone file contains 1,266 exact facility-to-TCS-zone
rows for all retained full-day driver-switch candidates. Ten border facilities
remain explicitly unresolved; no default or nearest-zone fallback is used.
