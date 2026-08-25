package org.matsim.project.hongkong.household;

import jakarta.inject.Singleton;
import org.matsim.core.controler.PrepareForMobsim;
import org.matsim.core.controler.PrepareForMobsimImpl;
import org.matsim.core.controler.AbstractModule;
import org.matsim.project.hongkong.schoolbus.SchoolBusAwarePrepareForMobsim;
import org.matsim.project.hongkong.schoolbus.StudentSchoolModeCandidateCatalog;
import org.matsim.project.hongkong.walk.HongKongWalkScoringParameters;

/** Installs the household selector after ordinary replanning and before iteration 1. */
public final class HouseholdJointPlanInnovationModule extends AbstractModule {
	private final StudentSchoolModeCandidateCatalog studentCandidates;
	private final HouseholdJointPlanSelectionSchedule selectionSchedule;
	private final HongKongWalkScoringParameters walkScoringParameters;

	public HouseholdJointPlanInnovationModule() {
		this(StudentSchoolModeCandidateCatalog.empty(), false);
	}

	public HouseholdJointPlanInnovationModule(StudentSchoolModeCandidateCatalog studentCandidates) {
		this(studentCandidates, false);
	}

	public HouseholdJointPlanInnovationModule(
			StudentSchoolModeCandidateCatalog studentCandidates,
			boolean targetIterations5_10_15) {
		this(studentCandidates, targetIterations5_10_15
				? HouseholdJointPlanSelectionSchedule.targetIterations5_10_15()
				: HouseholdJointPlanSelectionSchedule.historicalOneShot());
	}

	public HouseholdJointPlanInnovationModule(
			StudentSchoolModeCandidateCatalog studentCandidates,
			HouseholdJointPlanSelectionSchedule selectionSchedule) {
		this(studentCandidates, selectionSchedule, HongKongWalkScoringParameters.legacyV1());
	}

	public HouseholdJointPlanInnovationModule(
			StudentSchoolModeCandidateCatalog studentCandidates,
			HouseholdJointPlanSelectionSchedule selectionSchedule,
			HongKongWalkScoringParameters walkScoringParameters) {
		this.studentCandidates = studentCandidates;
		this.selectionSchedule = java.util.Objects.requireNonNull(selectionSchedule);
		this.walkScoringParameters = java.util.Objects.requireNonNull(walkScoringParameters);
	}

	@Override
	public void install() {
		bind(StudentSchoolModeCandidateCatalog.class).toInstance(studentCandidates);
		bind(HouseholdJointPlanSelectionSchedule.class).toInstance(selectionSchedule);
		bind(HongKongWalkScoringParameters.class).toInstance(walkScoringParameters);
		bind(HouseholdJointPlanAlternativeGenerator.class).in(Singleton.class);
		bind(HouseholdJointPlanSelector.class).in(Singleton.class);
		addControlerListenerBinding().to(HouseholdJointPlanSelector.class);
		if (studentCandidates.enabled()) {
			bind(PrepareForMobsimImpl.class);
			bind(PrepareForMobsim.class).to(SchoolBusAwarePrepareForMobsim.class);
		}
	}
}
