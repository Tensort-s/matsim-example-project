package org.matsim.project.hongkong.taxi;

import com.google.inject.Inject;
import org.matsim.api.core.v01.Scenario;
import org.matsim.core.controler.events.BeforeMobsimEvent;
import org.matsim.core.controler.listener.BeforeMobsimListener;

/** Revalidates Taxi routes and metadata after every replanning phase. */
public final class HongKongPhysicalTaxiBeforeMobsimListener implements BeforeMobsimListener {
	private final Scenario scenario;

	@Inject
	public HongKongPhysicalTaxiBeforeMobsimListener(Scenario scenario) {
		this.scenario = scenario;
	}

	@Override
	public void notifyBeforeMobsim(BeforeMobsimEvent event) {
		HongKongPhysicalTaxiRoutePreparation.prepare(scenario);
	}
}
