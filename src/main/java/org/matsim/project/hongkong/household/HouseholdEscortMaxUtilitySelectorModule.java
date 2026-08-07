package org.matsim.project.hongkong.household;

import org.matsim.core.controler.AbstractModule;

import jakarta.inject.Singleton;

/** Installs the one-shot deterministic bound-versus-unbound household selector. */
public final class HouseholdEscortMaxUtilitySelectorModule extends AbstractModule {
	@Override
	public void install() {
		bind(HouseholdEscortMaxUtilitySelector.class).in(Singleton.class);
		addControlerListenerBinding().to(HouseholdEscortMaxUtilitySelector.class);
	}
}
