package org.matsim.project.hongkong.pt;

import ch.sbb.matsim.routing.pt.raptor.SwissRailRaptor;
import org.matsim.core.controler.AbstractModule;
import org.matsim.pt.router.TransitRouter;

/** Overrides only the Raptor data source, leaving its routing-module bindings unchanged. */
public final class HongKongOrdinaryPtRaptorModule extends AbstractModule {

	@Override
	public void install() {
		bind(HongKongOrdinaryPtRaptorProvider.class).asEagerSingleton();
		bind(SwissRailRaptor.class).toProvider(HongKongOrdinaryPtRaptorProvider.class);
		bind(TransitRouter.class).toProvider(HongKongOrdinaryPtRaptorProvider.class);
	}
}
