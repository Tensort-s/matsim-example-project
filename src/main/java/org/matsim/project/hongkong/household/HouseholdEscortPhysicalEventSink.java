package org.matsim.project.hongkong.household;

import org.matsim.api.core.v01.events.LinkEnterEvent;
import org.matsim.api.core.v01.events.PersonArrivalEvent;
import org.matsim.api.core.v01.events.PersonStuckEvent;
import org.matsim.api.core.v01.events.VehicleEntersTrafficEvent;

/** Internal event and mobsim-lifecycle surface implemented by the physical escort engine. */
interface HouseholdEscortPhysicalEventSink {

	void onVehicleEntersTraffic(VehicleEntersTrafficEvent event);

	void onLinkEnter(LinkEnterEvent event);

	void onPersonArrival(PersonArrivalEvent event);

	void onPersonStuck(PersonStuckEvent event);

	void reset(int iteration);

	void cleanupAfterMobsim(int iteration);
}
