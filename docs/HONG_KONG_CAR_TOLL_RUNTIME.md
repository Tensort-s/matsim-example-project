# Hong Kong confirmed Car toll runtime

## Stage 8B scope

Stage 8B adds the canonical confirmed-toll subcomponent beside the accepted
Car energy subcomponent:

```text
car -> car_marginal_cost_v1
       - car_fuel_or_electricity_v1
       - car_confirmed_toll_v1
```

There remains exactly one top-level owner for mode `car`; the subcomponents do
not bypass the duplicate-mode-owner guard. Destination parking, fixed
ownership, and motorcycles remain inactive or out of scope.

## Canonical source identity

`HongKongCarTollCostCatalog` verifies the exact SHA256 of:

- the canonical Car manifest, base unified component table, and component
  registry;
- `toll_rate_application_v1/car_leg_toll_cost_estimates_base.parquet`;
- `toll_network_mapping_v1/car_leg_toll_identification.parquet`;
- `toll_rate_application_v1/car_toll_passage_events.parquet`.

Only the `base` scenario is loaded. The component does not select another
scenario, infer a rate, inspect road class to manufacture a charge, or fall
back to a candidate value.

## Confirmation and null policy

| Canonical status | Rows | Runtime behavior |
|---|---:|---|
| `confirmed_charge` | 25,858 | charge the canonical finite positive leg sum exactly once |
| `confirmed_no_charge` | 38,931 | consume the confirmed legal zero without a monetary contribution |
| private-car unresolved | 0 | any future occurrence fails closed and remains null |
| motorcycle out of scope | 2,929 | preserve null and never treat as private car |

The 25,858 charged legs contain 30,837 confirmed base physical passage
events and total 751,760 HKD. Resolved mean/median/p90/max tolls are
11.603204247634629 / 0 / 40 / 141 HKD across all resolved private-car legs.
The median zero is a confirmed-no-charge value, not unresolved filling.

## Route and duplicate guards

Each selected prepared Car leg must match the canonical `person_id +
leg_sequence`, source route distance, full route-link count, and route
fingerprint. Every confirmed passage must retain its canonical facility and
matched link sequence inside the audited source index span. Western Harbour
alias/complementary fragments may contain audited gap links; their confirmed
matched links must still appear in order.

Only `handleLeg` can charge. Ordinals are consumed once; extra, missing,
reordered, changed-route, ambiguous, or non-finite input fails closed. Money,
event, trip, and external-score callbacks are inert, and no
`PersonMoneyEvent` is emitted.

The Stage 8A energy scorer remains unchanged inside the composite. Standard
Car `monetaryDistanceRate` must still already be zero; neither energy nor toll
mutates or interprets it. Destination parking and fixed ownership load no
runtime rows.

## Evidence

- `data/transport_costs/hongkong/integration_stage8b_validation_v1/stage8b_car_confirmed_toll_runtime_validation.json`
- `data/transport_costs/hongkong/integration_stage8b_validation_v1/toll_runtime_confirmation_matrix.csv`
- `data/transport_costs/hongkong/integrated_multimodal_cost_source_interface_manifest_v1.json`

Stage 8B runs deterministic tests and release validators only. It changes no
production config, plans, network, supply, demand, capacity, city metadata,
run manifest, or server output, and performs no Hong Kong scenario run.
