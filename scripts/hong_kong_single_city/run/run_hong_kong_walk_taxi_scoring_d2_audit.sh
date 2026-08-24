#!/usr/bin/env bash
set -uo pipefail

AUDIT=/mnt/DiskM/by/hk_stage11_candidate11_taxi_dvrp_20260825_scorecalibration22_d2_audit1
/usr/bin/time -v python3 "$AUDIT/audit_hong_kong_walk_taxi_scoring_d2.py" \
  --base-script "$AUDIT/audit_hong_kong_walk_taxi_scoring_factorial.py" \
  --initial-plans /mnt/DiskM/by/hk_stage11_candidate10_corridor_signals_20260813_release11/input/plans_routed_selective_5pct_taxi_44000_no_ride.xml.gz \
  --run /mnt/DiskM/by/hk_stage11_candidate11_taxi_dvrp_20260824_scorecalibration22_d2_run1 \
  --factorial-summary /mnt/DiskM/by/hk_stage11_candidate11_taxi_dvrp_20260823_scorefactorial_audit2/results/factorial_summary.json \
  --incremental-summary /mnt/DiskM/by/hk_stage11_candidate11_taxi_dvrp_20260823_scorefactorial_v3_incremental_audit2/results/incremental_summary.json \
  --c1-summary /mnt/DiskM/by/hk_stage11_candidate11_taxi_dvrp_20260824_scorecalibration25_c1_audit1/results/c1_summary.json \
  --d1-summary /mnt/DiskM/by/hk_stage11_candidate11_taxi_dvrp_20260824_scorecalibration22_d1_audit1/results/d1_summary.json \
  --output-dir "$AUDIT/results" \
  >"$AUDIT/audit_stdout_stderr.log" 2>&1
code=$?
printf '%s\n' "$code" >"$AUDIT/exit_code.txt"
exit "$code"
