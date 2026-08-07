# Household joint-plan potential audit v2

This is a superseded Stage 11 candidate screen for delayed household joint-plan
innovation. It contains 9,312 passenger-driver pairs in 5,798 households.
Each row is one passenger main trip, so outbound and return directions remain
independent. Passenger source modes are `car_passenger`, `pt`, `taxi`, and
`walk`; `school_bus` is explicitly excluded in this phase.

The detour path is evaluated as driver origin -> passenger pickup -> passenger
drop-off -> driver destination. Existing driver Car trips may be reused;
otherwise the implementation must switch the driver's complete home-based day
chain to Car. The CSV is a geometric/time candidate screen rather than proof
that a routed waypoint plan is schedule-feasible. The runtime selector performs
that routed check and household resource selection after iteration 0.

It is retained as the historical pre-QSim screen. It included 23 candidate
rows whose passenger pickup and drop-off resolved to the same network link;
those rows cannot produce distinct boarding and alighting events. The current
registry is `household_joint_plan_potential_audit_v3`.
