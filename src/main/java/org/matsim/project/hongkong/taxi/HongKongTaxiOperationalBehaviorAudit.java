package org.matsim.project.hongkong.taxi;

import com.google.inject.Inject;
import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.core.controler.OutputDirectoryHierarchy;
import org.matsim.core.controler.events.IterationEndsEvent;
import org.matsim.core.controler.listener.IterationEndsListener;
import org.matsim.core.utils.io.IOUtils;

import java.io.BufferedWriter;
import java.io.IOException;
import java.util.Map;
import java.util.TreeMap;

/** Writes mode/score statistics over behavioral persons without mutating population. */
public final class HongKongTaxiOperationalBehaviorAudit implements IterationEndsListener {
	private final Scenario scenario;
	private final OutputDirectoryHierarchy output;

	@Inject
	public HongKongTaxiOperationalBehaviorAudit(
			Scenario scenario, OutputDirectoryHierarchy output) {
		this.scenario = scenario;
		this.output = output;
	}

	@Override
	public void notifyIterationEnds(IterationEndsEvent event) {
		Map<String, Long> legs = new TreeMap<>();
		long behavioralPersons = 0;
		long operationalPersons = 0;
		double scoreSum = 0;
		long finiteScores = 0;
		for (var person : scenario.getPopulation().getPersons().values()) {
			if (HongKongTaxiOperationalRequestGate.isShadow(person)) {
				operationalPersons++;
				continue;
			}
			behavioralPersons++;
			var plan = person.getSelectedPlan();
			if (plan.getScore() != null && Double.isFinite(plan.getScore())) {
				scoreSum += plan.getScore();
				finiteScores++;
			}
			for (var element : plan.getPlanElements()) {
				if (element instanceof Leg leg) legs.merge(leg.getMode(), 1L, Long::sum);
			}
		}
		long totalLegs = legs.values().stream().mapToLong(Long::longValue).sum();
		String filename = output.getIterationFilename(
				event.getIteration(), "taxi_operational_filtered_behavior.csv");
		try (BufferedWriter writer = IOUtils.getBufferedWriter(filename)) {
			writer.write("mode,behavioral_legs,behavioral_leg_share,behavioral_persons,"
					+ "operational_persons,finite_selected_scores,mean_selected_plan_score\n");
			for (var entry : legs.entrySet()) {
				writer.write(entry.getKey() + "," + entry.getValue() + ","
						+ ratio(entry.getValue(), totalLegs) + "," + behavioralPersons + ","
						+ operationalPersons + "," + finiteScores + ","
						+ ratio(scoreSum, finiteScores) + "\n");
			}
		} catch (IOException error) {
			throw new IllegalStateException("Cannot write filtered Taxi behavior audit", error);
		}
	}

	private static double ratio(double numerator, double denominator) {
		return denominator == 0 ? 0 : numerator / denominator;
	}
}
