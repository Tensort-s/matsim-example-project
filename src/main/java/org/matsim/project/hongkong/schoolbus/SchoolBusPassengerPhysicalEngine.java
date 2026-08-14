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
import java.util.concurrent.atomic.AtomicReference;

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
						&& scenario.getConfig().transit().getTransitModes().contains(leg.getMode())
						&& !"pt".equals(leg.getMode())) {
					String routingMode = TripStructureUtils.getRoutingMode(leg);
					leg.setMode("pt");
					// Leg.setMode deliberately clears routingMode. Preserve the
					// main-trip identity while only changing the QSim execution mode;
					// this also protects unfinished plans that end in a stage activity
					// and therefore are not returned by TripStructureUtils.getTrips().
					if (routingMode != null) leg.setRoutingMode(routingMode);
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
	private final AtomicLong delayedSchoolBusStopArrivals = new AtomicLong();
	private final AtomicLong missedSchoolBusDepartures = new AtomicLong();
	private final AtomicReference<Double> maximumMissedSchoolBusLatenessS = new AtomicReference<>(0.0);
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
		Leg currentLeg = currentLeg(agent);
		String routingMode = TripStructureUtils.getRoutingMode(currentLeg);
		Object candidateValue = currentLeg.getAttributes().getAttribute(
				StudentSchoolModeCandidateCatalog.CANDIDATE_ID_ATTRIBUTE);
		String candidateId = candidateValue instanceof String value ? value : null;
		boolean schoolBusRoutingMode = "school_bus".equals(routingMode);
		var schoolBusTiming = catalog.selectedSchoolBusTiming(
				agent.getId(), candidateId, fromLinkId);
		if (schoolBusTiming.isEmpty() && schoolBusRoutingMode) {
			schoolBusTiming = catalog.inferTruncatedSchoolBusTiming(
					agent.getId(), currentLeg, fromLinkId);
			Object restored = currentLeg.getAttributes().getAttribute(
					StudentSchoolModeCandidateCatalog.CANDIDATE_ID_ATTRIBUTE);
			candidateId = restored instanceof String value ? value : candidateId;
		}
		boolean selectedSchoolBus = schoolBusTiming.isPresent();
		if (schoolBusRoutingMode != selectedSchoolBus) {
			throw new IllegalStateException("PT physical-mode guard disagrees with the selected "
					+ "school-bus catalog: person=" + agent.getId() + ", routingMode="
					+ routingMode + ", candidateId=" + candidateId + ", fromLink="
					+ fromLinkId + ", departure=" + now);
		}
		if (!selectedSchoolBus && !physicalRegularPt) {
			delegatedPtDepartures.incrementAndGet();
			return false;
		}
		if (selectedSchoolBus) {
			var timing = schoolBusTiming.orElseThrow();
			if (now > timing.plannedLegDepartureTimeS() + 1e-6) {
				delayedSchoolBusStopArrivals.incrementAndGet();
			}
			double missedBy = Math.max(0.0, now - timing.scheduledBoardTimeS());
			if (missedBy > 1e-6) missedSchoolBusDepartures.incrementAndGet();
			maximumMissedSchoolBusLatenessS.accumulateAndGet(missedBy, Math::max);
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

	private static Leg currentLeg(MobsimAgent agent) {
		if (!(agent instanceof PlanAgent planAgent)
				|| !(planAgent.getCurrentPlanElement() instanceof Leg leg)) {
			throw new IllegalStateException("PT passenger is not backed by a current plan leg: "
					+ agent.getId());
		}
		return leg;
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
		delayedSchoolBusStopArrivals.set(0);
		missedSchoolBusDepartures.set(0);
		maximumMissedSchoolBusLatenessS.set(0.0);
	}

	@Override
	public void afterMobsim() {
		System.out.printf("Physical PT departure handler: school-bus=%,d; regular-pt=%,d; "
				+ "delegated-pt=%,d; delayed-school-bus-stop-arrivals=%,d; "
				+ "missed-school-bus-departures=%,d; max-missed-school-bus-lateness-s=%.1f.%n",
				physicalSchoolBusDepartures.get(), physicalRegularPtDepartures.get(),
				delegatedPtDepartures.get(), delayedSchoolBusStopArrivals.get(),
				missedSchoolBusDepartures.get(), maximumMissedSchoolBusLatenessS.get());
	}

	@Override
	public void setInternalInterface(InternalInterface internalInterface) {
		this.internalInterface = internalInterface;
	}
}
