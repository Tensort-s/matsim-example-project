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
 * Immutable, selected-plan-ordered fare metadata for one person's taxi legs.
 *
 * <p>The schedule is built before events are scored because MATSim reconstructs
 * experienced legs from events without copying custom source-plan attributes.
 */
public final class HongKongTaxiPersonFareSchedule {

	private final Id<Person> personId;
	private final List<HongKongTaxiLegAttributes.Metadata> fares;

	private HongKongTaxiPersonFareSchedule(
			Id<Person> personId,
			List<HongKongTaxiLegAttributes.Metadata> fares) {
		this.personId = Objects.requireNonNull(personId, "personId");
		this.fares = List.copyOf(fares);
	}

	public static HongKongTaxiPersonFareSchedule fromSelectedPlan(
			Person person,
			HongKongTaxiScoringParameters parameters) {
		Objects.requireNonNull(person, "person");
		Objects.requireNonNull(parameters, "parameters");

		Plan selectedPlan = person.getSelectedPlan();
		if (selectedPlan == null) {
			throw new IllegalArgumentException(
					"Cannot build Hong Kong taxi fare schedule: person_id=" + person.getId()
							+ ", selected_plan=<missing>"
			);
		}

		List<HongKongTaxiLegAttributes.Metadata> fares = new ArrayList<>();
		for (PlanElement element : selectedPlan.getPlanElements()) {
			if (element instanceof Leg leg
					&& HongKongTaxiScoringParameters.TAXI_MODE.equals(leg.getMode())) {
				fares.add(HongKongTaxiLegAttributes.readAndValidate(
						leg,
						person.getId(),
						parameters
				));
			}
		}
		return new HongKongTaxiPersonFareSchedule(person.getId(), fares);
	}

	Id<Person> personId() {
		return personId;
	}

	int size() {
		return fares.size();
	}

	HongKongTaxiLegAttributes.Metadata fareAt(int zeroBasedTaxiOrdinal) {
		return fares.get(zeroBasedTaxiOrdinal);
	}
}
