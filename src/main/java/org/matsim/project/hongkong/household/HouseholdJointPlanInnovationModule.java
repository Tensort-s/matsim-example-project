package org.matsim.project.hongkong.household;

import jakarta.inject.Singleton;
import org.matsim.core.controler.AbstractModule;

/** Installs the household selector after ordinary replanning and before iteration 1. */
public final class HouseholdJointPlanInnovationModule extends AbstractModule {
	@Override
	public void install() {
		bind(HouseholdJointPlanAlternativeGenerator.class).in(Singleton.class);
		bind(HouseholdJointPlanSelector.class).in(Singleton.class);
		addControlerListenerBinding().to(HouseholdJointPlanSelector.class);
	}
}
