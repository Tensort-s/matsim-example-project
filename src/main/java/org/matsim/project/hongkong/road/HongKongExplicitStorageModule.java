package org.matsim.project.hongkong.road;

import org.matsim.core.controler.AbstractModule;

/** Installs the explicit-storage queue-network factory behind an opt-in switch. */
public final class HongKongExplicitStorageModule extends AbstractModule {
	private final HongKongRoadSupplyRegistry registry;

	public HongKongExplicitStorageModule(HongKongRoadSupplyRegistry registry) {
		this.registry = registry;
	}

	@Override
	public void install() {
		bind(HongKongRoadSupplyRegistry.class).toInstance(registry);
		bind(HongKongExplicitStorageAudit.class).asEagerSingleton();
		addControllerListenerBinding().to(HongKongExplicitStorageAudit.class);
	}
}
