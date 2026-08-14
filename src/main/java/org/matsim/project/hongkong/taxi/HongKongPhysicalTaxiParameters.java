package org.matsim.project.hongkong.taxi;

/** Immutable physical Taxi scoring/runtime options. */
public record HongKongPhysicalTaxiParameters(
		double baseTravelUtilityPerHour,
		double totalWaitUtilityPerHour) {

	public HongKongPhysicalTaxiParameters {
		if (!Double.isFinite(baseTravelUtilityPerHour)
				|| !Double.isFinite(totalWaitUtilityPerHour)
				|| totalWaitUtilityPerHour > baseTravelUtilityPerHour) {
			throw new IllegalArgumentException(
					"Taxi waiting utility must be finite and no greater than the base travel utility: base="
							+ baseTravelUtilityPerHour + ", wait=" + totalWaitUtilityPerHour);
		}
	}

	public double extraWaitUtilityPerSecond() {
		return (totalWaitUtilityPerHour - baseTravelUtilityPerHour) / 3600.0;
	}

	public double baseTravelUtilityPerSecond() {
		return baseTravelUtilityPerHour / 3600.0;
	}

	public double totalWaitUtilityPerSecond() {
		return totalWaitUtilityPerHour / 3600.0;
	}
}
