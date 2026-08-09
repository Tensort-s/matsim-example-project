package org.matsim.project.hongkong.schoolbus;

import com.google.inject.Inject;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.network.Link;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.core.mobsim.framework.MobsimAgent;
import org.matsim.core.mobsim.framework.PlanAgent;
import org.matsim.core.config.Config;
import org.matsim.core.mobsim.qsim.InternalInterface;
import org.matsim.core.mobsim.qsim.interfaces.DepartureHandler;
import org.matsim.core.mobsim.qsim.interfaces.MobsimEngine;
import org.matsim.core.mobsim.qsim.pt.PTPassengerAgent;
import org.matsim.core.mobsim.qsim.pt.TransitStopAgentTracker;
import org.matsim.pt.transitSchedule.api.TransitSchedule;
import org.matsim.pt.transitSchedule.api.TransitStopFacility;
import org.matsim.core.router.TripStructureUtils;

import java.util.concurrent.atomic.AtomicLong;

/**
 * Sends every {@code pt} passenger leg to MATSim's physical transit stop
 * tracker. School-bus legs retain stricter candidate and stop guards; generic
 * PT is forbidden from boarding the dedicated school-bus supply.
 */
public final class SchoolBusPassengerPhysicalEngine implements MobsimEngine, DepartureHandler {

	public static int normalizeGenericPassengerTransitModes(Scenario scenario) {
		int normalized = 0;
		for (var person : scenario.getPopulation().getPersons().values()) {
			if (person.getSelectedPlan() == null) continue;
			for (var element : person.getSelectedPlan().getPlanElements()) {
				if (element instanceof Leg leg
						&& scenario.getConfig().transit().getTransitModes().contains(leg.getMode())) {
					leg.setMode("pt");
					normalized++;
				}
			}
		}
		return normalized;
	}

	private final TransitStopAgentTracker tracker;
	private final TransitSchedule schedule;
	private final StudentSchoolModeCandidateCatalog catalog;
	private final boolean physicalRegularPt;
	private final AtomicLong physicalSchoolBusDepartures = new AtomicLong();
	private final AtomicLong physicalRegularPtDepartures = new AtomicLong();
	private final AtomicLong delegatedPtDepartures = new AtomicLong();
	private InternalInterface internalInterface;

	@Inject
	public SchoolBusPassengerPhysicalEngine(
			TransitStopAgentTracker tracker,
			TransitSchedule schedule,
			StudentSchoolModeCandidateCatalog catalog,
			Config config) {
		this.tracker = tracker;
		this.schedule = schedule;
		this.catalog = catalog;
		this.physicalRegularPt = config.transit().getTransitModes().contains("pt");
	}

	@Override
	public boolean handleDeparture(double now, MobsimAgent agent, Id<Link> fromLinkId) {
		if (!(agent instanceof PTPassengerAgent passenger)) {
			return false;
		}
		if (!"pt".equals(agent.getMode())) {
			return false;
		}
		String routingMode = routingMode(agent);
		boolean selectedSchoolBus = catalog.matchesSelectedSchoolBusDeparture(
				agent.getId(), fromLinkId, now);
		if (!selectedSchoolBus && !physicalRegularPt) {
			delegatedPtDepartures.incrementAndGet();
			return false;
		}
		if ("school_bus".equals(routingMode) != selectedSchoolBus) {
			throw new IllegalStateException("PT physical-mode guard disagrees with the selected "
					+ "school-bus catalog: person=" + agent.getId() + ", routingMode="
					+ routingMode + ", fromLink=" + fromLinkId + ", departure=" + now);
		}
		Id<TransitStopFacility> stopId = passenger.getDesiredAccessStopId();
		if (selectedSchoolBus && !catalog.isPhysicalSchoolBusStop(stopId)) {
			throw new IllegalStateException("Selected school-bus passenger has a non-school-bus stop: "
					+ agent.getId() + " -> " + stopId);
		}
		if (!selectedSchoolBus && catalog.isPhysicalSchoolBusStop(stopId)) {
			throw new IllegalStateException("Generic PT passenger attempted to use a school-bus stop: "
					+ agent.getId() + " -> " + stopId);
		}
		TransitStopFacility stop = stopId == null ? null : schedule.getFacilities().get(stopId);
		if (stop == null) {
			throw new IllegalStateException("PT passenger has no physical access stop: "
					+ agent.getId());
		}
		if (stop.getLinkId() != null && !stop.getLinkId().equals(fromLinkId)) {
			throw new IllegalStateException("School-bus passenger departs on " + fromLinkId
					+ " but access stop " + stopId + " is on " + stop.getLinkId());
		}
		tracker.addAgentToStop(now, passenger, stopId);
		internalInterface.registerAdditionalAgentOnLink(agent);
		if (selectedSchoolBus) {
			physicalSchoolBusDepartures.incrementAndGet();
		} else {
			physicalRegularPtDepartures.incrementAndGet();
		}
		return true;
	}

	private static String routingMode(MobsimAgent agent) {
		if (!(agent instanceof PlanAgent planAgent)
				|| !(planAgent.getCurrentPlanElement() instanceof Leg leg)) {
			throw new IllegalStateException("PT passenger is not backed by a current plan leg: "
					+ agent.getId());
		}
		return TripStructureUtils.getRoutingMode(leg);
	}

	@Override
	public void doSimStep(double time) {
		// Boarding/alighting is performed by MATSim's TransitQSimEngine.
	}

	@Override
	public void beforeMobsim() {
		physicalSchoolBusDepartures.set(0);
		physicalRegularPtDepartures.set(0);
		delegatedPtDepartures.set(0);
	}

	@Override
	public void afterMobsim() {
		System.out.printf("Physical PT departure handler: school-bus=%,d; regular-pt=%,d; "
				+ "delegated-pt=%,d.%n", physicalSchoolBusDepartures.get(),
				physicalRegularPtDepartures.get(), delegatedPtDepartures.get());
	}

	@Override
	public void setInternalInterface(InternalInterface internalInterface) {
		this.internalInterface = internalInterface;
	}
}
