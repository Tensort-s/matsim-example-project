package org.matsim.project.hongkong.taxi;

import org.matsim.core.controler.AbstractModule;

/** Registers behavioral-statistics filtering for a one-iteration operational run. */
public final class HongKongTaxiOperationalRequestGateModule extends AbstractModule {
	@Override
	public void install() {
		bind(HongKongTaxiOperationalBehaviorAudit.class).asEagerSingleton();
		addControllerListenerBinding().to(HongKongTaxiOperationalBehaviorAudit.class);
	}
}
