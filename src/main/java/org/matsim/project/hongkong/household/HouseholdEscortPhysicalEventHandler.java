package org.matsim.project.hongkong.household;

import com.google.inject.Inject;
import org.matsim.api.core.v01.events.LinkEnterEvent;
import org.matsim.api.core.v01.events.PersonArrivalEvent;
import org.matsim.api.core.v01.events.PersonStuckEvent;
import org.matsim.api.core.v01.events.VehicleEntersTrafficEvent;
import org.matsim.api.core.v01.events.handler.LinkEnterEventHandler;
import org.matsim.api.core.v01.events.handler.PersonArrivalEventHandler;
import org.matsim.api.core.v01.events.handler.PersonStuckEventHandler;
import org.matsim.api.core.v01.events.handler.VehicleEntersTrafficEventHandler;
import org.matsim.core.events.MobsimScopeEventHandler;

/**
 * Separates the monitor held by {@code EventsManagerImpl} from the physical
 * escort engine's state monitor. Event delivery may call back into QSim, while
 * QSim departures call the engine directly; using distinct monitor identities
 * prevents those two paths from forming a lock-order cycle.
 */
public final class HouseholdEscortPhysicalEventHandler implements
		PersonArrivalEventHandler, PersonStuckEventHandler, LinkEnterEventHandler,
		VehicleEntersTrafficEventHandler, MobsimScopeEventHandler {

	private final HouseholdEscortPhysicalEventSink sink;

	@Inject
	HouseholdEscortPhysicalEventHandler(HouseholdEscortPhysicalEventSink sink) {
		this.sink = sink;
	}

	@Override
	public void handleEvent(VehicleEntersTrafficEvent event) {
		sink.onVehicleEntersTraffic(event);
	}

	@Override
	public void handleEvent(LinkEnterEvent event) {
		sink.onLinkEnter(event);
	}

	@Override
	public void handleEvent(PersonArrivalEvent event) {
		sink.onPersonArrival(event);
	}

	@Override
	public void handleEvent(PersonStuckEvent event) {
		sink.onPersonStuck(event);
	}

	@Override
	public void reset(int iteration) {
		sink.reset(iteration);
	}

	@Override
	public void cleanupAfterMobsim(int iteration) {
		sink.cleanupAfterMobsim(iteration);
	}
}
