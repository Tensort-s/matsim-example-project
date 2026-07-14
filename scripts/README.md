# Scripts layout

This directory now keeps the original single-city Fuzhou scripts in one organized tree:

```text
scripts/
  fuzhou_single_city/
    data_acquisition/
    feature_engineering/
    demand_generation/
    transit_supply/
    analysis_visualization/
    run/

  archive/
    legacy_data_exploration/
    legacy_demand_routing/
    legacy_visualization/
```

`fuzhou_single_city/` contains the scripts that are still useful for reproducing or extending the current Fuzhou MATSim workflow. These scripts remain city-specific and are intended as the starting point for future multi-city generalization.

`archive/` contains old experiments, retired routing/demand variants, one-off exploration helpers, and visualizations that are no longer part of the active workflow. They are kept for provenance rather than deleted.

The current final Fuzhou rerun helper is:

```text
scripts/fuzhou_single_city/run/run_waitpenalty_from_cont20_reroute50.cmd
```

Because the files were moved out of the old flat `scripts/` layout, older legacy documentation may still describe
retired command snippets. For active commands, use `docs/PROJECT_ONBOARDING.md` and `cities/fuzhou/city.yaml`.
