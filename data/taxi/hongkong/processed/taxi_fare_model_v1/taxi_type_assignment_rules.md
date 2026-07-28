# Hong Kong taxi type assignment rules v1

This file records the conservative offline assignment used by
`estimate_hong_kong_taxi_leg_fares.py`. It is not written back to MATSim plans.

Official source:
Transport Department, "Details of taxi operating areas".

Rules:

1. If the candidate tour contains unresolved TCS zones (`-1`) or unresolved
   facility-area evidence, assign `unresolved`.
2. If all known tour zones are in the North Lantau set `{22}`, assign
   `lantau_taxi`.
3. If all known tour zones are in the New Territories set
   `{14,15,16,17,18,19,20,21,23,24,25}`, assign
   `new_territories_taxi`.
4. If the tour uses urban/Hong Kong Island/Kowloon/Tsuen Wan/Kwai Chung/Tsing
   Yi zones `{1,2,3,4,5,6,7,8,9,10,11,12,13}` or crosses urban and ordinary
   New Territories zones, assign `urban_taxi`, because urban taxis are the
   general Hong Kong taxi type except for restricted Lantau roads.
5. If a tour mixes Lantau evidence with non-Lantau zones, assign `unresolved`
   and calculate fare ranges under all three taxi fare tables.

The rule deliberately avoids allocating taxi type by fleet proportion alone.
Unresolved tours remain explicit in the fare outputs.
