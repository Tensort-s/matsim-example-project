package org.matsim.project.hongkong.household;

import org.matsim.api.core.v01.Scenario;
import org.matsim.core.controler.events.BeforeMobsimEvent;
import org.matsim.core.controler.listener.BeforeMobsimListener;

/** One-shot post-PrepareForSim refresh for a resumed household checkpoint. */
public final class HouseholdJointPlanCheckpointRefreshListener implements BeforeMobsimListener {

	private final Scenario scenario;
	private final HouseholdJointPlanCandidateCatalog candidates;
	private final HouseholdEscortBindingCatalog bindings;
	private final int expectedBindings;
	private boolean refreshed;

	public HouseholdJointPlanCheckpointRefreshListener(
			Scenario scenario,
			HouseholdJointPlanCandidateCatalog candidates,
			HouseholdEscortBindingCatalog bindings,
			int expectedBindings) {
		this.scenario = scenario;
		this.candidates = candidates;
		this.bindings = bindings;
		this.expectedBindings = expectedBindings;
	}

	@Override
	public synchronized void notifyBeforeMobsim(BeforeMobsimEvent event) {
		if (refreshed) return;
		int count = HouseholdJointPlanCheckpointRestorer.refreshAfterPrepare(
				scenario, candidates, bindings, expectedBindings);
		refreshed = true;
		System.out.printf("Refreshed %,d frozen household bindings after PrepareForSim.%n", count);
	}
}
