package org.matsim.project.hongkong.taxi;

import org.matsim.core.controler.AbstractModule;

/** Registers exact request/pickup waiting scoring and compact per-request output. */
public final class HongKongPhysicalTaxiAuditModule extends AbstractModule {
	private final HongKongPhysicalTaxiParameters parameters;
	private final HongKongPhysicalTaxiFleetRegistry fleetRegistry;

	public HongKongPhysicalTaxiAuditModule(
			HongKongPhysicalTaxiParameters parameters,
			HongKongPhysicalTaxiFleetRegistry fleetRegistry) {
		this.parameters = parameters;
		this.fleetRegistry = fleetRegistry;
	}

	@Override
	public void install() {
		bind(HongKongPhysicalTaxiParameters.class).toInstance(parameters);
		bind(HongKongPhysicalTaxiFleetRegistry.class).toInstance(fleetRegistry);
		bind(HongKongTaxiRequestAuditHandler.class).asEagerSingleton();
		bind(HongKongPhysicalTaxiBeforeMobsimListener.class).asEagerSingleton();
		addEventHandlerBinding().to(HongKongTaxiRequestAuditHandler.class);
		addMobsimListenerBinding().to(HongKongTaxiRequestAuditHandler.class);
		addControllerListenerBinding().to(HongKongPhysicalTaxiBeforeMobsimListener.class);
	}
}
