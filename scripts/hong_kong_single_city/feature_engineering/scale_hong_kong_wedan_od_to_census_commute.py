#!/usr/bin/env python3
"""Compatibility wrapper for Census-based Hong Kong WEDAN OD validation.

The earlier version of this entry point performed a 3-area block calibration.
The current workflow uses the 2021 New Town boundary and keeps the official
4-area Census categories to infer the WEDAN flow unit and validate area OD
shares without overwriting the original model proportions.
"""

from __future__ import annotations

from validate_hong_kong_wedan_od_with_census_commute import main


if __name__ == "__main__":
    main()
