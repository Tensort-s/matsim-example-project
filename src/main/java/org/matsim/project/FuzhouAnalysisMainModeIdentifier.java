package org.matsim.project;

import org.matsim.api.core.v01.population.Leg;
import org.matsim.api.core.v01.population.PlanElement;
import org.matsim.core.router.AnalysisMainModeIdentifier;
import org.matsim.core.router.DefaultAnalysisMainModeIdentifier;

import java.util.List;

/**
 * Analysis main-mode identifier that accepts Fuzhou's split public transport
 * passenger modes.
 *
 * <p>MATSim's default analysis main-mode identifier knows the built-in modes
 * such as car, walk and pt, but it rejects custom passenger modes such as
 * "bus" and "metro".  The actual routing is still handled by SwissRailRaptor;
 * this class only prevents analysis listeners from failing after an iteration
 * when plans contain those split modes.</p>
 */
public final class FuzhouAnalysisMainModeIdentifier implements AnalysisMainModeIdentifier {

	private final DefaultAnalysisMainModeIdentifier delegate = new DefaultAnalysisMainModeIdentifier();

	@Override
	public String identifyMainMode(List<? extends PlanElement> tripElements) {
		boolean hasMetro = false;
		boolean hasBus = false;
		boolean hasPt = false;
		boolean hasCar = false;
		boolean hasRideHailing = false;
		boolean hasWalk = false;

		for (PlanElement element : tripElements) {
			if (element instanceof Leg leg) {
				String mode = leg.getMode();
				if ("metro".equals(mode)) {
					hasMetro = true;
				} else if ("bus".equals(mode)) {
					hasBus = true;
				} else if ("pt".equals(mode)) {
					hasPt = true;
				} else if ("car".equals(mode)) {
					hasCar = true;
				} else if ("ride_hailing".equals(mode)) {
					hasRideHailing = true;
				} else if ("walk".equals(mode) || "non_network_walk".equals(mode) || "transit_walk".equals(mode)) {
					hasWalk = true;
				}
			}
		}

		if (hasMetro) {
			return "metro";
		}
		if (hasBus) {
			return "bus";
		}
		if (hasPt) {
			return "pt";
		}
		if (hasCar) {
			return "car";
		}
		if (hasRideHailing) {
			return "ride_hailing";
		}
		if (hasWalk) {
			return "walk";
		}

		return delegate.identifyMainMode(tripElements);
	}
}
