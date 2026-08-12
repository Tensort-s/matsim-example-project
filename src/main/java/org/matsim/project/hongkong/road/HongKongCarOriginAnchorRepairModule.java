package org.matsim.project.hongkong.road;

import org.matsim.core.controler.AbstractModule;

/** Installs the bounded iteration-1 private-Car origin-anchor audit and repair. */
public final class HongKongCarOriginAnchorRepairModule extends AbstractModule {

	private final HongKongCarOriginAnchorObservationCatalog observations;

	public HongKongCarOriginAnchorRepairModule(
			HongKongCarOriginAnchorObservationCatalog observations) {
		this.observations = observations;
	}

	@Override
	public void install() {
		bind(HongKongCarOriginAnchorObservationCatalog.class).toInstance(observations);
		bind(HongKongCarOriginAnchorRepair.class).asEagerSingleton();
		addControlerListenerBinding().to(HongKongCarOriginAnchorRepair.class);
	}
}
