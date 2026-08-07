package org.matsim.project.hongkong.household;

import org.junit.jupiter.api.Test;
import org.matsim.api.core.v01.TransportMode;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class HouseholdJointPlanSelectorTest {

	@Test
	void permitsIndependentDirectionsButNotTwoPassengersOnOneDriverLeg() {
		var outbound = candidate("out", "passenger", 0, "driver", 0, false);
		var inbound = candidate("in", "passenger", 1, "driver", 1, false);
		var competingPassenger = candidate("other", "other-passenger", 0, "driver", 0, false);
		var roleConflict = candidate("role-conflict", "driver", 0, "other-driver", 0, false);

		assertFalse(HouseholdJointPlanSelector.candidatesConflict(outbound, inbound));
		assertTrue(HouseholdJointPlanSelector.candidatesConflict(outbound, competingPassenger));
		assertTrue(HouseholdJointPlanSelector.candidatesConflict(outbound, roleConflict));
	}

	@Test
	void fullDayDriverSwitchReservesTheVehicleDay() {
		var switchCandidate = candidate("switch", "passenger", 0, "driver", 0, true);
		var existingCarCandidate = candidate("existing", "other-passenger", 0, "driver", 1, false);

		assertTrue(HouseholdJointPlanSelector.candidatesConflict(
				switchCandidate, existingCarCandidate));
	}

	private static HouseholdJointPlanCandidateCatalog.Candidate candidate(
			String id, String passenger, int passengerTrip, String driver,
			int driverTrip, boolean switchDriver) {
		return new HouseholdJointPlanCandidateCatalog.Candidate(
				id, "household", passenger, passengerTrip, TransportMode.pt,
				driver, driverTrip, switchDriver ? TransportMode.pt : TransportMode.car,
				"vehicle", switchDriver, 1_000.0, 1_000.0,
				"pickup", "dropoff", "destination", 0.0, 0.0);
	}
}
