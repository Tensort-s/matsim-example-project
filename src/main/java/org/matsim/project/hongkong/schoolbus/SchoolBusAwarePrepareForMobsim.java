package org.matsim.project.hongkong.schoolbus;

import com.google.inject.Inject;
import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.api.core.v01.population.Person;
import org.matsim.api.core.v01.population.Plan;
import org.matsim.core.controler.PrepareForMobsim;
import org.matsim.core.controler.PrepareForMobsimImpl;
import org.matsim.core.router.TripStructureUtils;
import org.matsim.project.hongkong.household.HouseholdEscortBindingCatalog;

import java.util.LinkedHashSet;

/**
 * Runs MATSim's normal per-iteration route preparation, then restores the
 * exact selected school-bus trip slices before the QSim provider creates its
 * passenger agents.
 */
public final class SchoolBusAwarePrepareForMobsim implements PrepareForMobsim {

	private final PrepareForMobsimImpl delegate;
	private final StudentSchoolModeCandidateCatalog catalog;
	private final HouseholdEscortBindingCatalog householdCatalog;
	private final Scenario scenario;

	@Inject
	public SchoolBusAwarePrepareForMobsim(
			PrepareForMobsimImpl delegate,
			StudentSchoolModeCandidateCatalog catalog,
			HouseholdEscortBindingCatalog householdCatalog,
			Scenario scenario) {
		this.delegate = delegate;
		this.catalog = catalog;
		this.householdCatalog = householdCatalog;
		this.scenario = scenario;
	}

	@Override
	public void run() {
		int preNormalized = synchronizeMissingTripRoutingModes(scenario);
		delegate.run();
		int restoredHouseholdRoutes = householdCatalog.restoreSelectedDriverWaypointRoutes();
		int restored = catalog.restoreSelectedSchoolBusPlans(scenario);
		int normalized = SchoolBusPassengerPhysicalEngine
				.normalizeGenericPassengerTransitModes(scenario);
		int postNormalized = synchronizeMissingTripRoutingModes(scenario);
		if (restored > 0) {
			System.out.printf(
					"Post-PrepareForMobsim restored %,d selected physical school-bus plans before QSim agent creation.%n",
					restored);
		}
		if (restoredHouseholdRoutes > 0) {
			System.out.printf(
					"Post-PrepareForMobsim restored %,d selected household driver waypoint routes before QSim agent creation.%n",
					restoredHouseholdRoutes);
		}
		System.out.printf(
				"PrepareForMobsim synchronized %,d pre-route and %,d post-route missing routing modes; "
						+ "normalized %,d passenger transit-mode legs to execution mode pt.%n",
				preNormalized, postNormalized, normalized);
	}

	static int synchronizeMissingTripRoutingModes(Scenario scenario) {
		int synchronizedLegs = 0;
		for (Person person : scenario.getPopulation().getPersons().values()) {
			for (Plan plan : person.getPlans()) {
				for (var trip : TripStructureUtils.getTrips(plan)) {
					var legs = trip.getLegsOnly();
					LinkedHashSet<String> defined = new LinkedHashSet<>();
					boolean missing = false;
					for (Leg leg : legs) {
						String routingMode = TripStructureUtils.getRoutingMode(leg);
						if (routingMode == null) missing = true;
						else defined.add(routingMode);
					}
					if (!missing || defined.isEmpty()) continue;
					if (defined.size() != 1) {
						throw new IllegalStateException("Conflicting routing modes " + defined
								+ " in trip for person " + person.getId());
					}
					String routingMode = defined.getFirst();
					for (Leg leg : legs) {
						if (TripStructureUtils.getRoutingMode(leg) != null) continue;
						leg.setRoutingMode(routingMode);
						synchronizedLegs++;
					}
				}
			}
		}
		return synchronizedLegs;
	}
}
