package org.matsim.project.hongkong.car;

import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.events.ActivityStartEvent;
import org.matsim.api.core.v01.events.Event;
import org.matsim.api.core.v01.events.LinkEnterEvent;
import org.matsim.api.core.v01.events.PersonArrivalEvent;
import org.matsim.api.core.v01.events.VehicleEntersTrafficEvent;
import org.matsim.api.core.v01.events.VehicleLeavesTrafficEvent;
import org.matsim.api.core.v01.network.Link;
import org.matsim.api.core.v01.network.Network;
import org.matsim.api.core.v01.population.Person;
import org.matsim.facilities.ActivityFacility;
import org.matsim.project.hongkong.scoring.HongKongScoringComponent;
import org.matsim.vehicles.Vehicle;

import java.util.Objects;

/**
 * Experienced-event Car scorer using the same energy/toll link rules as the
 * router and vehicle-to-vehicle parking intervals for destination charges.
 */
public final class HongKongDynamicCarCostScoring
		implements HongKongScoringComponent {

	private record PendingArrival(double timeS, Id<Link> linkId, Id<Vehicle> vehicleId) {
	}

	private record OpenParking(
			double arrivalTimeS,
			Id<Link> destinationLinkId,
			String destinationFacilityId,
			String activityType,
			Id<Vehicle> vehicleId) {
	}

	private final Person person;
	private final Network network;
	private final HongKongDynamicCarCostRules rules;
	private final HongKongDynamicCarCostRunAudit audit;
	private final double marginalUtilityOfMoney;
	private final double simulationEndTimeS;

	private Id<Vehicle> activeVehicle;
	private Id<Vehicle> mostRecentCarVehicle;
	private PendingArrival pendingArrival;
	private OpenParking openParking;
	private double score;
	private double energyHkd;
	private double tollHkd;
	private double parkingHkd;
	private long linkEntries;
	private long tollEntries;
	private long parkingEvents;
	private long parkingFacilityMismatches;
	private long terminalParkingEvents;
	private boolean finished;

	public HongKongDynamicCarCostScoring(
			Person person,
			Network network,
			HongKongDynamicCarCostRules rules,
			HongKongDynamicCarCostRunAudit audit,
			double marginalUtilityOfMoney,
			double simulationEndTimeS) {
		this.person = Objects.requireNonNull(person, "person");
		this.network = Objects.requireNonNull(network, "network");
		this.rules = Objects.requireNonNull(rules, "rules");
		this.audit = Objects.requireNonNull(audit, "audit");
		if (!Double.isFinite(marginalUtilityOfMoney) || marginalUtilityOfMoney < 0.0
				|| !Double.isFinite(simulationEndTimeS) || simulationEndTimeS < 0.0) {
			throw new IllegalArgumentException("Invalid dynamic Car scoring parameters.");
		}
		this.marginalUtilityOfMoney = marginalUtilityOfMoney;
		this.simulationEndTimeS = simulationEndTimeS;
	}

	@Override
	public String componentId() {
		return HongKongDynamicCarCostScoringComponentFactory.COMPONENT_ID;
	}

	@Override
	public void handleEvent(Event event) {
		Objects.requireNonNull(event, "event");
		if (finished) {
			throw new IllegalStateException("Dynamic Car event received after scoring finish for " + person.getId());
		}
		if (event instanceof VehicleEntersTrafficEvent enters) {
			handleVehicleEnters(enters);
		} else if (event instanceof LinkEnterEvent linkEnter) {
			handleLinkEnter(linkEnter);
		} else if (event instanceof VehicleLeavesTrafficEvent leaves) {
			handleVehicleLeaves(leaves);
		} else if (event instanceof PersonArrivalEvent arrival) {
			handleArrival(arrival);
		} else if (event instanceof ActivityStartEvent activityStart) {
			handleActivityStart(activityStart);
		}
	}

	private void handleVehicleEnters(VehicleEntersTrafficEvent event) {
		if (!"car".equals(event.getNetworkMode())
				|| !rules.isPrivateCarVehicleId(event.getVehicleId().toString())) {
			return;
		}
		if (activeVehicle != null) {
			throw new IllegalStateException("Overlapping Car traffic sessions for " + person.getId());
		}
		if (openParking != null) {
			boolean vehicleMismatch = !openParking.vehicleId().equals(event.getVehicleId());
			if (vehicleMismatch) {
				throw new IllegalStateException("Parking vehicle changed for person " + person.getId());
			}
			boolean facilityMismatch = !openParking.destinationLinkId().equals(event.getLinkId());
			settleParking(event.getTime(), facilityMismatch, false);
		}
		activeVehicle = event.getVehicleId();
		mostRecentCarVehicle = event.getVehicleId();
	}

	private void handleLinkEnter(LinkEnterEvent event) {
		if (activeVehicle == null || !activeVehicle.equals(event.getVehicleId())) {
			return;
		}
		Link link = network.getLinks().get(event.getLinkId());
		if (link == null) {
			throw new IllegalStateException("Experienced Car entered missing network link " + event.getLinkId());
		}
		HongKongDynamicCarCostRules.LinkCost cost = rules.quoteLink(link, event.getTime());
		addCost(cost.totalHkd());
		energyHkd += cost.energyHkd();
		tollHkd += cost.tollHkd();
		linkEntries++;
		if (cost.tollHkd() > 0.0) tollEntries++;
		audit.link(cost);
	}

	private void handleVehicleLeaves(VehicleLeavesTrafficEvent event) {
		if (activeVehicle == null || !activeVehicle.equals(event.getVehicleId())) {
			return;
		}
		activeVehicle = null;
		mostRecentCarVehicle = event.getVehicleId();
	}

	private void handleArrival(PersonArrivalEvent event) {
		if (!"car".equals(event.getLegMode()) || mostRecentCarVehicle == null) {
			return;
		}
		pendingArrival = new PendingArrival(event.getTime(), event.getLinkId(), mostRecentCarVehicle);
	}

	private void handleActivityStart(ActivityStartEvent event) {
		if (pendingArrival == null || event.getActType().endsWith("interaction")) {
			return;
		}
		if (openParking != null) {
			throw new IllegalStateException("New parking arrival before previous settlement for " + person.getId());
		}
		Id<ActivityFacility> facilityId = event.getFacilityId();
		if (facilityId == null) {
			throw new IllegalStateException("Actual Car destination has no facility for " + person.getId());
		}
		if (!pendingArrival.linkId().equals(event.getLinkId())) {
			throw new IllegalStateException("Arrival/activity link mismatch for " + person.getId());
		}
		openParking = new OpenParking(
				pendingArrival.timeS(), pendingArrival.linkId(), facilityId.toString(),
				event.getActType(), pendingArrival.vehicleId());
		pendingArrival = null;
	}

	private void settleParking(double departureTimeS, boolean facilityMismatch, boolean terminal) {
		HongKongDynamicCarCostRules.ParkingCost cost = rules.quoteParking(
				openParking.destinationFacilityId(), openParking.activityType(),
				openParking.arrivalTimeS(), Math.max(departureTimeS, openParking.arrivalTimeS()));
		addCost(cost.costHkd());
		parkingHkd += cost.costHkd();
		parkingEvents++;
		if (facilityMismatch) parkingFacilityMismatches++;
		if (terminal) terminalParkingEvents++;
		audit.parking(cost, facilityMismatch, terminal);
		openParking = null;
	}

	private void addCost(double costHkd) {
		double contribution = -costHkd * marginalUtilityOfMoney;
		if (!Double.isFinite(contribution)) {
			throw new IllegalStateException("Dynamic Car cost produced non-finite utility.");
		}
		score += contribution;
	}

	@Override
	public void finish() {
		if (openParking != null) {
			settleParking(Math.max(simulationEndTimeS, openParking.arrivalTimeS()), false, true);
		}
		finished = true;
	}

	@Override
	public double getScore() {
		if (!Double.isFinite(score)) {
			throw new IllegalStateException("Dynamic Car score is non-finite for " + person.getId());
		}
		return score;
	}

	@Override
	public void explainScore(StringBuilder out) {
		out.append("hongKongDynamicCarCost[person_id=").append(person.getId())
				.append(",linkEntries=").append(linkEntries)
				.append(",tollEntries=").append(tollEntries)
				.append(",parkingEvents=").append(parkingEvents)
				.append(",parkingFacilityMismatches=").append(parkingFacilityMismatches)
				.append(",terminalParkingEvents=").append(terminalParkingEvents)
				.append(",energyHkd=").append(energyHkd)
				.append(",tollHkd=").append(tollHkd)
				.append(",parkingHkd=").append(parkingHkd)
				.append(",fixedOwnershipHkd=0.0,score=").append(score).append(']');
	}

	double energyHkd() { return energyHkd; }
	double tollHkd() { return tollHkd; }
	double parkingHkd() { return parkingHkd; }
	long linkEntries() { return linkEntries; }
	long tollEntries() { return tollEntries; }
	long parkingEvents() { return parkingEvents; }
}
