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

  archive/
    legacy_data_exploration/
    legacy_demand_routing/
    legacy_visualization/
```

`fuzhou_single_city/` contains the scripts that are still useful for reproducing or extending the current Fuzhou MATSim workflow. These scripts remain city-specific and are intended as the starting point for future multi-city generalization.

`archive/` contains old experiments, retired routing/demand variants, one-off exploration helpers, and visualizations that are no longer part of the active workflow. They are kept for provenance rather than deleted.

Because the files were moved out of the old flat `scripts/` layout, older documentation or command snippets may still reference paths such as `scripts/foo.py`. Update those commands to the new categorized path when re-running a script.

