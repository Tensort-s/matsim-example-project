# Hong Kong Light Rail station-OD fare rules v1

This directory contains adult Octopus base fares for explicit ordered Light
Rail stop IDs. It is separate from domestic MTR and Airport Express scopes.
The official source is a complete unique 68 by 68 matrix: all 4,624 OD
records are available, including 68 explicit same-stop zero fares.

No reverse substitution, distance interpolation, nearest match, path sum,
cross-scope fallback, full-route replacement, or missing-value zero fill is
used. Transfer concessions are not modelled. The query interface does not
read or price the 557,104 generic production PT legs.
