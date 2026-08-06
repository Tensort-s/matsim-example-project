package org.matsim.project.hongkong.household;

import com.google.inject.Singleton;
import org.matsim.core.controler.AbstractModule;

/** Installs the one-shot fixed school-escort JointReRoute listener. */
public final class HouseholdEscortJointReRouteModule extends AbstractModule {

	private final HouseholdEscortBindingCatalog catalog;

	public HouseholdEscortJointReRouteModule(HouseholdEscortBindingCatalog catalog) {
		this.catalog = catalog;
	}

	@Override
	public void install() {
		bind(HouseholdEscortJointReRoute.class).in(Singleton.class);
		addControlerListenerBinding().to(HouseholdEscortJointReRoute.class);
	}
}
