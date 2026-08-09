package org.matsim.project.hongkong.household;

import jakarta.inject.Singleton;
import org.matsim.core.controler.PrepareForMobsim;
import org.matsim.core.controler.PrepareForMobsimImpl;
import org.matsim.core.controler.AbstractModule;
import org.matsim.project.hongkong.schoolbus.SchoolBusAwarePrepareForMobsim;
import org.matsim.project.hongkong.schoolbus.StudentSchoolModeCandidateCatalog;

/** Installs the household selector after ordinary replanning and before iteration 1. */
public final class HouseholdJointPlanInnovationModule extends AbstractModule {
	private final StudentSchoolModeCandidateCatalog studentCandidates;

	public HouseholdJointPlanInnovationModule() {
		this(StudentSchoolModeCandidateCatalog.empty());
	}

	public HouseholdJointPlanInnovationModule(StudentSchoolModeCandidateCatalog studentCandidates) {
		this.studentCandidates = studentCandidates;
	}

	@Override
	public void install() {
		bind(StudentSchoolModeCandidateCatalog.class).toInstance(studentCandidates);
		bind(HouseholdJointPlanAlternativeGenerator.class).in(Singleton.class);
		bind(HouseholdJointPlanSelector.class).in(Singleton.class);
		addControlerListenerBinding().to(HouseholdJointPlanSelector.class);
		if (studentCandidates.enabled()) {
			bind(PrepareForMobsimImpl.class);
			bind(PrepareForMobsim.class).to(SchoolBusAwarePrepareForMobsim.class);
		}
	}
}
