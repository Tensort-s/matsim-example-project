package org.matsim.project.hongkong.taxi;

import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.api.core.v01.population.Person;
import org.matsim.api.core.v01.population.Plan;
import org.matsim.api.core.v01.population.PlanElement;

import java.util.ArrayList;
import java.util.List;
import java.util.Objects;

/**
 * Immutable, selected-plan-ordered route fares for one person's taxi legs.
 *
 * <p>The schedule is built before events are scored because MATSim reconstructs
 * experienced legs from events without copying custom source-plan attributes.
 */
public final class HongKongTaxiPersonFareSchedule {

	private final Id<Person> personId;
	private final List<RouteFare> fares;

	private HongKongTaxiPersonFareSchedule(
			Id<Person> personId,
			List<RouteFare> fares) {
		this.personId = Objects.requireNonNull(personId, "personId");
		this.fares = List.copyOf(fares);
	}

	public static HongKongTaxiPersonFareSchedule fromSelectedPlan(
			Person person,
			HongKongTaxiFareCalculator calculator) {
		Objects.requireNonNull(person, "person");
		Objects.requireNonNull(calculator, "calculator");

		Plan selectedPlan = person.getSelectedPlan();
		if (selectedPlan == null) {
			throw new IllegalArgumentException(
					"Cannot build Hong Kong taxi fare schedule: person_id=" + person.getId()
							+ ", selected_plan=<missing>"
			);
		}

		List<RouteFare> fares = new ArrayList<>();
		int planElementIndex = 0;
		for (PlanElement element : selectedPlan.getPlanElements()) {
			if (element instanceof Leg leg
					&& HongKongTaxiScoringParameters.TAXI_MODE.equals(leg.getMode())) {
				HongKongTaxiRouteContext context;
				try {
					context = HongKongTaxiRouteContext.from(leg);
				} catch (RuntimeException error) {
					throw new IllegalStateException(
							"Invalid selected Taxi leg: person_id=" + person.getId()
									+ ", plan_element_index=" + planElementIndex,
							error);
				}
				fares.add(new RouteFare(
						context,
						calculator.calculate(context.distanceMeters(), context.taxiType())));
			}
			planElementIndex++;
		}
		return new HongKongTaxiPersonFareSchedule(person.getId(), fares);
	}

	Id<Person> personId() {
		return personId;
	}

	int size() {
		return fares.size();
	}

	RouteFare fareAt(int zeroBasedTaxiOrdinal) {
		return fares.get(zeroBasedTaxiOrdinal);
	}

	record RouteFare(
			HongKongTaxiRouteContext routeContext,
			HongKongTaxiFareCalculator.FareResult calculation) {
	}
}
