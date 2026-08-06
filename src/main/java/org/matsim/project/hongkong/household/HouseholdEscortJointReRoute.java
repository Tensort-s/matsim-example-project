package org.matsim.project.hongkong.household;

import com.google.inject.Inject;
import com.google.inject.Provider;
import org.apache.logging.log4j.LogManager;
import org.apache.logging.log4j.Logger;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.population.Activity;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.api.core.v01.population.Person;
import org.matsim.api.core.v01.population.Plan;
import org.matsim.api.core.v01.population.PlanElement;
import org.matsim.core.controler.events.IterationEndsEvent;
import org.matsim.core.controler.listener.IterationEndsListener;
import org.matsim.core.population.routes.NetworkRoute;
import org.matsim.core.router.TripRouter;
import org.matsim.facilities.ActivityFacilities;
import org.matsim.facilities.FacilitiesUtils;
import org.matsim.vehicles.Vehicle;

import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

/** One-shot, fixed-binding-aware reroute of the school-escort driver Car legs. */
public final class HouseholdEscortJointReRoute implements IterationEndsListener {

	private static final Logger LOG = LogManager.getLogger(HouseholdEscortJointReRoute.class);

	private record DriverTrip(Leg leg, Activity origin, Activity destination) {
	}

	private final HouseholdEscortBindingCatalog catalog;
	private final Scenario scenario;
	private final ActivityFacilities facilities;
	private final Provider<TripRouter> tripRouterProvider;
	private boolean applied;

	@Inject
	public HouseholdEscortJointReRoute(
			HouseholdEscortBindingCatalog catalog,
			Scenario scenario,
			ActivityFacilities facilities,
			Provider<TripRouter> tripRouterProvider) {
		this.catalog = catalog;
		this.scenario = scenario;
		this.facilities = facilities;
		this.tripRouterProvider = tripRouterProvider;
	}

	@Override
	public void notifyIterationEnds(IterationEndsEvent event) {
		if (event.getIteration() != 0 || applied) {
			return;
		}
		if (event.isLastIteration()) {
			throw new IllegalStateException(
					"Household JointReRoute requires an iteration after it.0 for physical validation.");
		}
		TripRouter router = tripRouterProvider.get();
		Set<String> routedDriverLegs = new HashSet<>();
		Set<Id<Person>> drivers = new HashSet<>();
		int changedRoutes = 0;
		int unchangedRoutes = 0;
		for (HouseholdEscortBindingCatalog.Binding binding : catalog.bindings()) {
			drivers.add(binding.driverId());
			String driverLegKey = binding.driverId() + "/" + binding.driverLegIndex();
			if (!routedDriverLegs.add(driverLegKey)) {
				continue;
			}
			Person driver = requiredPerson(binding.driverId());
			DriverTrip trip = selectedDriverTrip(driver, binding.driverLegIndex());
			NetworkRoute oldRoute = requiredBoundRoute(trip.leg(), binding, "before JointReRoute");
			List<Id<org.matsim.api.core.v01.network.Link>> oldLinks = fullLinkSequence(oldRoute);
			List<? extends PlanElement> routed = router.calcRoute(
					"car",
					FacilitiesUtils.toFacility(trip.origin(), facilities),
					FacilitiesUtils.toFacility(trip.destination(), facilities),
					binding.driverPlannedDepartureTimeSeconds(),
					driver,
					trip.leg().getAttributes());
			List<Leg> routedCarLegs = routed.stream()
					.filter(Leg.class::isInstance)
					.map(Leg.class::cast)
					.filter(candidate -> "car".equals(candidate.getMode()))
					.toList();
			if (routedCarLegs.size() != 1) {
				List<String> returnedElements = routed.stream()
						.map(element -> element instanceof Leg candidate
								? "leg:" + candidate.getMode()
								: element.getClass().getSimpleName())
						.toList();
				throw new IllegalStateException("JointReRoute did not return exactly one main Car leg for "
						+ driverLegKey + "; elements=" + returnedElements);
			}
			Leg routedLeg = routedCarLegs.getFirst();
			if (!(routedLeg.getRoute() instanceof NetworkRoute newRoute)) {
				throw new IllegalStateException("JointReRoute did not return a network route for " + driverLegKey);
			}
			newRoute.setVehicleId(binding.vehicleId());
			trip.leg().setRoute(newRoute);
			if (routedLeg.getTravelTime().isDefined()) {
				trip.leg().setTravelTime(routedLeg.getTravelTime().seconds());
			} else {
				trip.leg().setTravelTimeUndefined();
			}
			NetworkRoute installed = requiredBoundRoute(trip.leg(), binding, "after JointReRoute");
			if (oldLinks.equals(fullLinkSequence(installed))) {
				unchangedRoutes++;
			} else {
				changedRoutes++;
			}
		}
		for (HouseholdEscortBindingCatalog.Binding binding : catalog.bindings()) {
			Person driver = requiredPerson(binding.driverId());
			requiredBoundRoute(
					selectedDriverTrip(driver, binding.driverLegIndex()).leg(),
					binding,
					"binding validation after JointReRoute");
		}
		applied = true;
		LOG.info("Household school-escort JointReRoute: source_iteration=0, drivers={}, "
				+ "unique_driver_legs={}, changed_routes={}, unchanged_routes={}, bindings_valid={}",
				drivers.size(), routedDriverLegs.size(), changedRoutes, unchangedRoutes,
				catalog.bindings().size());
	}

	private Person requiredPerson(Id<Person> personId) {
		Person person = scenario.getPopulation().getPersons().get(personId);
		if (person == null) {
			throw new IllegalStateException("JointReRoute driver is absent: " + personId);
		}
		return person;
	}

	private static DriverTrip selectedDriverTrip(Person person, int requestedLegIndex) {
		Plan plan = person.getSelectedPlan();
		if (plan == null) {
			throw new IllegalStateException("JointReRoute driver has no selected plan: " + person.getId());
		}
		List<PlanElement> elements = plan.getPlanElements();
		int legIndex = 0;
		for (int elementIndex = 0; elementIndex < elements.size(); elementIndex++) {
			if (!(elements.get(elementIndex) instanceof Leg leg)) {
				continue;
			}
			if (legIndex++ != requestedLegIndex) {
				continue;
			}
			if (elementIndex == 0 || elementIndex + 1 >= elements.size()
					|| !(elements.get(elementIndex - 1) instanceof Activity origin)
					|| !(elements.get(elementIndex + 1) instanceof Activity destination)) {
				throw new IllegalStateException("Bound driver leg lacks adjacent activities: "
						+ person.getId() + "/" + requestedLegIndex);
			}
			return new DriverTrip(leg, origin, destination);
		}
		throw new IllegalStateException("JointReRoute driver leg is absent: "
				+ person.getId() + "/" + requestedLegIndex);
	}

	private static NetworkRoute requiredBoundRoute(
			Leg leg,
			HouseholdEscortBindingCatalog.Binding binding,
			String phase) {
		if (!"car".equals(leg.getMode()) || !(leg.getRoute() instanceof NetworkRoute route)) {
			throw new IllegalStateException("Bound driver leg is not routed Car " + phase + ": "
					+ binding.driverId() + "/" + binding.driverLegIndex());
		}
		if (!binding.vehicleId().equals(route.getVehicleId())
				|| !binding.driverDestinationLinkId().equals(route.getEndLinkId())) {
			throw new IllegalStateException("Bound driver vehicle/destination changed " + phase + ": "
					+ binding.driverId() + "/" + binding.driverLegIndex());
		}
		return route;
	}

	private static List<Id<org.matsim.api.core.v01.network.Link>> fullLinkSequence(NetworkRoute route) {
		List<Id<org.matsim.api.core.v01.network.Link>> result = new ArrayList<>();
		result.add(route.getStartLinkId());
		result.addAll(route.getLinkIds());
		result.add(route.getEndLinkId());
		return result;
	}
}
