package org.matsim.project.hongkong.schoolbus;

import org.matsim.core.mobsim.qsim.InternalInterface;
import org.matsim.core.mobsim.qsim.pt.AbstractTransitDriverAgent;
import org.matsim.core.mobsim.qsim.pt.TransitDriverAgentFactory;
import org.matsim.core.mobsim.qsim.pt.TransitDriverAgentImpl;
import org.matsim.core.mobsim.qsim.pt.TransitStopAgentTracker;
import org.matsim.pt.Umlauf;

/** Uses the physical school_bus network mode only for school-bus vehicle duties. */
public final class SchoolBusAwareTransitDriverAgentFactory implements TransitDriverAgentFactory {
	public static final String SCHOOL_BUS_VEHICLE_MODE = "school_bus_vehicle";

	@Override
	public AbstractTransitDriverAgent createTransitDriver(
			Umlauf umlauf,
			InternalInterface internalInterface,
			TransitStopAgentTracker tracker) {
		boolean hasService = false;
		boolean allSchoolBus = true;
		for (var piece : umlauf.getUmlaufStuecke()) {
			if (!piece.isFahrt() || piece.getRoute() == null) continue;
			hasService = true;
			allSchoolBus &= "school_bus".equals(piece.getRoute().getTransportMode());
		}
		String networkMode = hasService && allSchoolBus ? SCHOOL_BUS_VEHICLE_MODE : "car";
		return new TransitDriverAgentImpl(umlauf, networkMode, tracker, internalInterface);
	}
}
