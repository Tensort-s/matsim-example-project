package org.matsim.project.hongkong.household;

import com.google.inject.Inject;
import org.apache.logging.log4j.LogManager;
import org.apache.logging.log4j.Logger;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.TransportMode;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.api.core.v01.population.Person;
import org.matsim.api.core.v01.population.Plan;
import org.matsim.core.population.PopulationUtils;
import org.matsim.core.router.TripRouter;
import org.matsim.core.router.TripStructureUtils;
import org.matsim.project.hongkong.taxi.HongKongTaxiFareCalculator;
import org.matsim.project.hongkong.taxi.HongKongTaxiLegAttributes;
import org.matsim.project.hongkong.taxi.HongKongTaxiScoringParameters;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Set;

/** Adds unselected person-plan templates for every household joint candidate. */
public final class HouseholdJointPlanAlternativeGenerator {

	public static final String CANDIDATE_ID_ATTRIBUTE = "hkHouseholdJointCandidateId";
	public static final String HOUSEHOLD_ID_ATTRIBUTE = "hkHouseholdJointHouseholdId";
	public static final String ROLE_ATTRIBUTE = "hkHouseholdJointPlanRole";
	public static final String TEMPLATE_ATTRIBUTE = "hkHouseholdJointTemplate";
	public static final String VEHICLE_ID_ATTRIBUTE = "hkHouseholdJointVehicleId";
	public static final String ORIGINAL_TRIP_INDEX_ATTRIBUTE = "hkHouseholdJointOriginalTripIndex";
	public static final String ORIGINAL_MODE_ATTRIBUTE = "hkHouseholdJointOriginalMode";
	public static final String UNBIND_MODE_ATTRIBUTE = "hkHouseholdJointUnbindMode";
	public static final String BASELINE_ROLE = "baseline";
	public static final String UNBIND_ROLE = "car_passenger_unbind";
	public static final Set<String> RELEASE_MODES = Set.of(
			TransportMode.pt, HongKongJointPlanModes.TAXI, TransportMode.walk);

	private static final Logger LOG = LogManager.getLogger(HouseholdJointPlanAlternativeGenerator.class);

	private final HouseholdJointPlanCandidateCatalog candidates;
	private final Scenario scenario;
	private boolean applied;

	@Inject
	public HouseholdJointPlanAlternativeGenerator(
			HouseholdJointPlanCandidateCatalog candidates,
			Scenario scenario) {
		this.candidates = candidates;
		this.scenario = scenario;
	}

	public void generate() {
		if (applied) throw new IllegalStateException("Household joint-plan templates may be added only once.");
		int passengerTemplates = 0;
		int driverTemplates = 0;
		int driverSwitchTemplates = 0;
		int unbindTemplates = 0;
		int originalCarPassengerTrips = 0;
		for (Person person : scenario.getPopulation().getPersons().values()) {
			Plan baseline = person.getSelectedPlan();
			if (baseline == null) continue;
			baseline.getAttributes().putAttribute(ROLE_ATTRIBUTE, BASELINE_ROLE);
			List<TripStructureUtils.Trip> trips = List.copyOf(TripStructureUtils.getTrips(baseline));
			for (int tripIndex = 0; tripIndex < trips.size(); tripIndex++) {
				if (!isCarPassengerTrip(trips.get(tripIndex))) continue;
				originalCarPassengerTrips++;
				for (String releaseMode : orderedReleaseModes()) {
					Plan unbindTemplate = copyPlan(baseline, person);
					replaceTripWithMode(unbindTemplate, tripIndex, releaseMode);
					unbindTemplate.getAttributes().putAttribute(ROLE_ATTRIBUTE, UNBIND_ROLE);
					unbindTemplate.getAttributes().putAttribute(TEMPLATE_ATTRIBUTE, true);
					unbindTemplate.getAttributes().putAttribute(
							ORIGINAL_TRIP_INDEX_ATTRIBUTE, tripIndex);
					unbindTemplate.getAttributes().putAttribute(
							ORIGINAL_MODE_ATTRIBUTE, "car_passenger");
					unbindTemplate.getAttributes().putAttribute(UNBIND_MODE_ATTRIBUTE, releaseMode);
					person.addPlan(unbindTemplate);
					unbindTemplates++;
				}
			}
		}
		for (HouseholdJointPlanCandidateCatalog.Candidate candidate : candidates.candidates()) {
			Person passenger = requiredPerson(candidate.passengerPersonId());
			Person driver = requiredPerson(candidate.driverPersonId());
			if (passenger.getSelectedPlan() == null || driver.getSelectedPlan() == null) {
				throw new IllegalStateException("Joint-plan candidate person lacks a selected baseline plan: "
						+ candidate.candidateId());
			}

			Plan passengerTemplate = copyPlan(passenger.getSelectedPlan(), passenger);
			replaceTripWithMode(
					passengerTemplate, candidate.passengerTripIndex(), "car_passenger");
			tag(passengerTemplate, candidate, "passenger");
			passenger.addPlan(passengerTemplate);
			passengerTemplates++;

			Plan driverTemplate = copyPlan(driver.getSelectedPlan(), driver);
			if (candidate.driverRequiresCarSwitch()) {
				List<Integer> tripIndexes = new ArrayList<>();
				for (int index = 0; index < TripStructureUtils.getTrips(driverTemplate).size(); index++) {
					tripIndexes.add(index);
				}
				tripIndexes.sort(Comparator.reverseOrder());
				for (int tripIndex : tripIndexes) {
					replaceTripWithMode(driverTemplate, tripIndex, TransportMode.car);
				}
				driverSwitchTemplates++;
			} else {
				replaceTripWithMode(driverTemplate, candidate.driverTripIndex(), TransportMode.car);
			}
			tag(driverTemplate, candidate, "driver");
			driver.addPlan(driverTemplate);
			driverTemplates++;
		}
		applied = true;
		LOG.info("Household joint-plan alternatives: candidates={}, passenger_templates={}, "
				+ "driver_templates={}, driver_switch_templates={}, selected_templates=0, "
				+ "original_car_passenger_trips={}, car_passenger_unbind_templates={}, "
				+ "car_passenger_release_modes=pt|taxi|walk, "
				+ "baseline_selected_plans_preserved=true, school_bus_candidates=0",
				candidates.candidates().size(), passengerTemplates, driverTemplates,
				driverSwitchTemplates, originalCarPassengerTrips, unbindTemplates);
	}

	/**
	 * Removes the temporary person-plan templates after the household selector
	 * has evaluated them and installed the selected composite plans.  Templates
	 * are an internal choice-set representation, not independent MATSim plans:
	 * leaving them in plan memory would allow a later generic plan selector to
	 * choose an unbound {@code car_passenger} leg without its paired driver.
	 */
	public int removeTemplates() {
		if (!applied) {
			throw new IllegalStateException("Household joint-plan templates have not been generated.");
		}
		int removed = 0;
		for (Person person : scenario.getPopulation().getPersons().values()) {
			List<? extends Plan> templates = person.getPlans().stream()
					.filter(HouseholdJointPlanAlternativeGenerator::isTemplate)
					.toList();
			for (Plan template : templates) {
				if (template == person.getSelectedPlan()) {
					throw new IllegalStateException(
							"Cannot remove a selected household candidate template for " + person.getId());
				}
				if (!person.removePlan(template)) {
					throw new IllegalStateException(
							"Cannot remove household candidate template for " + person.getId());
				}
				removed++;
			}
		}
		return removed;
	}

	private static boolean isTemplate(Plan plan) {
		return Boolean.TRUE.equals(plan.getAttributes().getAttribute(TEMPLATE_ATTRIBUTE));
	}

	private Person requiredPerson(String personId) {
		Person person = scenario.getPopulation().getPersons().get(Id.createPersonId(personId));
		if (person == null) throw new IllegalArgumentException("Candidate references missing person " + personId);
		return person;
	}

	private static Plan copyPlan(Plan source, Person owner) {
		Plan copy = PopulationUtils.createPlan(owner);
		PopulationUtils.copyFromTo(source, copy);
		copy.setScore(null);
		return copy;
	}

	private static void replaceTripWithMode(Plan plan, int tripIndex, String mode) {
		List<TripStructureUtils.Trip> trips = List.copyOf(TripStructureUtils.getTrips(plan));
		if (tripIndex < 0 || tripIndex >= trips.size()) {
			throw new IllegalArgumentException("Missing trip " + tripIndex + " in candidate template");
		}
		TripStructureUtils.Trip trip = trips.get(tripIndex);
		Leg leg = PopulationUtils.createLeg(mode);
		leg.setRoutingMode(mode);
		if (HongKongJointPlanModes.TAXI.equals(mode)) {
			setTaxiTemplateRoutingAttributes(leg, tripIndex);
			for (String attribute : HongKongTaxiLegAttributes.NAMES) {
				trip.getOriginActivity().getAttributes().putAttribute(
						attribute, leg.getAttributes().getAttribute(attribute));
			}
		}
		TripRouter.insertTrip(
				plan, trip.getOriginActivity(), List.of(leg), trip.getDestinationActivity());
	}

	private static void setTaxiTemplateRoutingAttributes(Leg leg, int tripIndex) {
		HongKongTaxiScoringParameters parameters = HongKongTaxiScoringParameters.centralV1();
		leg.getAttributes().putAttribute(HongKongTaxiLegAttributes.FARE_BASELINE_HKD, 0.0);
		leg.getAttributes().putAttribute(
				HongKongTaxiLegAttributes.TAXI_TYPE, HongKongTaxiFareCalculator.UNRESOLVED);
		leg.getAttributes().putAttribute(
				HongKongTaxiLegAttributes.FARE_SCOPE, parameters.fareScope());
		leg.getAttributes().putAttribute(
				HongKongTaxiLegAttributes.FARE_MODEL_VERSION, parameters.fareModelVersion());
		leg.getAttributes().putAttribute(
				HongKongTaxiLegAttributes.CLASSIFICATION_SOURCE,
				"household_joint_plan_unselected_template_v1");
		leg.getAttributes().putAttribute(HongKongTaxiLegAttributes.MAIN_TRIP_INDEX, tripIndex);
	}

	private static void tag(
			Plan plan,
			HouseholdJointPlanCandidateCatalog.Candidate candidate,
			String role) {
		plan.getAttributes().putAttribute(CANDIDATE_ID_ATTRIBUTE, candidate.candidateId());
		plan.getAttributes().putAttribute(HOUSEHOLD_ID_ATTRIBUTE, candidate.householdId());
		plan.getAttributes().putAttribute(ROLE_ATTRIBUTE, role);
		plan.getAttributes().putAttribute(TEMPLATE_ATTRIBUTE, true);
		plan.getAttributes().putAttribute(VEHICLE_ID_ATTRIBUTE, candidate.vehicleId());
		plan.getAttributes().putAttribute(ORIGINAL_TRIP_INDEX_ATTRIBUTE,
				"passenger".equals(role)
						? candidate.passengerTripIndex() : candidate.driverTripIndex());
		plan.getAttributes().putAttribute(ORIGINAL_MODE_ATTRIBUTE,
				"passenger".equals(role)
						? candidate.passengerOriginalMode() : candidate.driverOriginalMode());
	}

	private static boolean isCarPassengerTrip(TripStructureUtils.Trip trip) {
		List<Leg> legs = trip.getTripElements().stream()
				.filter(Leg.class::isInstance).map(Leg.class::cast).toList();
		return legs.size() == 1 && "car_passenger".equals(legs.getFirst().getMode());
	}

	private static List<String> orderedReleaseModes() {
		return List.of(TransportMode.pt, HongKongJointPlanModes.TAXI, TransportMode.walk);
	}
}
