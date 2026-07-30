# Hong Kong bus simulation fare layer v1

Coverage-first offline model layer, separate from the official audit and Bus
Core v1:

- 771,666/771,666 required ordered ODs have a non-null model fare.
- 2,363/2,363 bus routes have a non-null route fallback.
- Official unique values remain separate from duplicate consensus, relaxed
  scope, conflict selection, and route fallback assumptions.
- Eligibility, payment medium, transfer concessions, and route-specific
  effective dates are not modelled.
- No fare has entered production PT legs or MATSim scoring.
