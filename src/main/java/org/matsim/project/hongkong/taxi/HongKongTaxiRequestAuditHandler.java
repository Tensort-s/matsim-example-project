package org.matsim.project.hongkong.taxi;

import com.google.inject.Inject;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.events.PersonScoreEvent;
import org.matsim.api.core.v01.events.LinkEnterEvent;
import org.matsim.api.core.v01.events.handler.LinkEnterEventHandler;
import org.matsim.api.core.v01.network.Network;
import org.matsim.api.core.v01.population.Person;
import org.matsim.contrib.dvrp.optimizer.Request;
import org.matsim.contrib.dvrp.passenger.PassengerDroppedOffEvent;
import org.matsim.contrib.dvrp.passenger.PassengerDroppedOffEventHandler;
import org.matsim.contrib.dvrp.passenger.PassengerPickedUpEvent;
import org.matsim.contrib.dvrp.passenger.PassengerPickedUpEventHandler;
import org.matsim.contrib.dvrp.passenger.PassengerRequestRejectedEvent;
import org.matsim.contrib.dvrp.passenger.PassengerRequestRejectedEventHandler;
import org.matsim.contrib.dvrp.passenger.PassengerRequestSubmittedEvent;
import org.matsim.contrib.dvrp.passenger.PassengerRequestSubmittedEventHandler;
import org.matsim.core.api.experimental.events.EventsManager;
import org.matsim.core.controler.OutputDirectoryHierarchy;
import org.matsim.core.events.MobsimScopeEventHandler;
import org.matsim.core.mobsim.framework.events.MobsimBeforeCleanupEvent;
import org.matsim.core.mobsim.framework.listeners.MobsimBeforeCleanupListener;
import org.matsim.core.mobsim.qsim.interfaces.Netsim;
import org.matsim.core.utils.io.IOUtils;
import org.matsim.api.core.v01.Scenario;
import org.matsim.vehicles.Vehicle;

import java.io.BufferedWriter;
import java.io.IOException;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/** Scores physical Taxi waiting and writes one compact request row per iteration. */
public final class HongKongTaxiRequestAuditHandler implements
		PassengerRequestSubmittedEventHandler,
		PassengerPickedUpEventHandler,
		PassengerDroppedOffEventHandler,
		PassengerRequestRejectedEventHandler,
		LinkEnterEventHandler,
		MobsimBeforeCleanupListener,
		MobsimScopeEventHandler {

	public static final String SCORE_KIND = "hk_taxi_wait_extra";
	public static final String UNSERVED_SCORE_KIND = "hk_taxi_wait_unserved_total";
	public static final String ONBOARD_BASE_SCORE_KIND = "hk_taxi_wait_onboard_base";
	private final EventsManager events;
	private final OutputDirectoryHierarchy output;
	private final double extraWaitUtilityPerSecond;
	private final double baseTravelUtilityPerSecond;
	private final double totalWaitUtilityPerSecond;
	private final HongKongPhysicalTaxiFleetRegistry fleetRegistry;
	private final Network network;
	private final Set<Id<Person>> operationalPersons;
	private final Map<Id<Request>, RequestState> requests = new LinkedHashMap<>();
	private final Map<Id<Vehicle>, VehicleState> vehicles = new LinkedHashMap<>();
	private int iteration = -1;

	@Inject
	public HongKongTaxiRequestAuditHandler(
			EventsManager events,
			OutputDirectoryHierarchy output,
			HongKongPhysicalTaxiParameters parameters,
			HongKongPhysicalTaxiFleetRegistry fleetRegistry,
			Scenario scenario) {
		this(events, output, parameters.extraWaitUtilityPerSecond(),
				parameters.baseTravelUtilityPerSecond(), parameters.totalWaitUtilityPerSecond(),
				fleetRegistry, scenario.getNetwork(), operationalPersons(scenario));
	}

	HongKongTaxiRequestAuditHandler(
			EventsManager events,
			OutputDirectoryHierarchy output,
			double extraWaitUtilityPerSecond) {
		this(events, output, extraWaitUtilityPerSecond, -6.0 / 3600.0,
				extraWaitUtilityPerSecond - 6.0 / 3600.0, null, null, Set.of());
	}

	HongKongTaxiRequestAuditHandler(
			EventsManager events,
			OutputDirectoryHierarchy output,
			double extraWaitUtilityPerSecond,
			double baseTravelUtilityPerSecond,
			double totalWaitUtilityPerSecond,
			HongKongPhysicalTaxiFleetRegistry fleetRegistry,
			Network network) {
		this(events, output, extraWaitUtilityPerSecond, baseTravelUtilityPerSecond,
				totalWaitUtilityPerSecond, fleetRegistry, network, Set.of());
	}

	HongKongTaxiRequestAuditHandler(
			EventsManager events,
			OutputDirectoryHierarchy output,
			double extraWaitUtilityPerSecond,
			double baseTravelUtilityPerSecond,
			double totalWaitUtilityPerSecond,
			HongKongPhysicalTaxiFleetRegistry fleetRegistry,
			Network network,
			Set<Id<Person>> operationalPersons) {
		this.events = events;
		this.output = output;
		if (!Double.isFinite(extraWaitUtilityPerSecond) || extraWaitUtilityPerSecond > 0
				|| !Double.isFinite(baseTravelUtilityPerSecond) || baseTravelUtilityPerSecond > 0
				|| !Double.isFinite(totalWaitUtilityPerSecond)
				|| totalWaitUtilityPerSecond > baseTravelUtilityPerSecond) {
			throw new IllegalArgumentException(
					"Illegal Taxi waiting utility rates");
		}
		this.extraWaitUtilityPerSecond = extraWaitUtilityPerSecond;
		this.baseTravelUtilityPerSecond = baseTravelUtilityPerSecond;
		this.totalWaitUtilityPerSecond = totalWaitUtilityPerSecond;
		this.fleetRegistry = fleetRegistry;
		this.network = network;
		this.operationalPersons = Set.copyOf(operationalPersons);
	}

	@Override
	public void reset(int iteration) {
		this.iteration = iteration;
		requests.clear();
		vehicles.clear();
		if (fleetRegistry != null) {
			fleetRegistry.serviceWindows().keySet().forEach(id -> vehicles.put(id, new VehicleState()));
		}
	}

	@Override
	public void handleEvent(PassengerRequestSubmittedEvent event) {
		if (!isTaxi(event.getMode())) return;
		boolean operational = event.getPersonIds().stream().allMatch(operationalPersons::contains);
		boolean anyOperational = event.getPersonIds().stream().anyMatch(operationalPersons::contains);
		if (operational != anyOperational) {
			throw new IllegalStateException("Taxi request mixes behavioral and operational passengers: "
					+ event.getRequestId());
		}
		RequestState state = new RequestState(
				event.getRequestId(), event.getPersonIds(), event.getTime(), operational);
		if (requests.put(event.getRequestId(), state) != null) {
			throw new IllegalStateException("Duplicate Taxi request submitted: " + event.getRequestId());
		}
	}

	@Override
	public void handleEvent(PassengerPickedUpEvent event) {
		if (!isTaxi(event.getMode())) return;
		RequestState state = require(event.getRequestId(), "pickup");
		if (!state.personIds.contains(event.getPersonId())) {
			throw new IllegalStateException(
					"Taxi pickup person is not in request: request=" + event.getRequestId()
							+ ", person=" + event.getPersonId());
		}
		if (state.pickupTimes.put(event.getPersonId(), event.getTime()) != null) {
			throw new IllegalStateException("Duplicate Taxi pickup: " + event.getRequestId());
		}
		scoreWait(state, event.getPersonId(), event.getTime(),
				extraWaitUtilityPerSecond, SCORE_KIND);
		state.vehicleId = event.getVehicleId().toString();
		Id<Vehicle> vehicleId = Id.createVehicleId(event.getVehicleId().toString());
		VehicleState vehicle = vehicles.get(vehicleId);
		if (vehicle != null) vehicle.occupancy++;
	}

	@Override
	public void handleEvent(PassengerDroppedOffEvent event) {
		if (!isTaxi(event.getMode())) return;
		RequestState state = require(event.getRequestId(), "dropoff");
		if (!state.pickupTimes.containsKey(event.getPersonId())) {
			throw new IllegalStateException("Taxi dropoff before pickup: " + event.getRequestId());
		}
		if (state.dropoffTimes.put(event.getPersonId(), event.getTime()) != null) {
			throw new IllegalStateException("Duplicate Taxi dropoff: " + event.getRequestId());
		}
		Id<Vehicle> vehicleId = Id.createVehicleId(event.getVehicleId().toString());
		VehicleState vehicle = vehicles.get(vehicleId);
		if (vehicle != null) {
			vehicle.occupancy--;
			if (vehicle.occupancy < 0) throw new IllegalStateException("Negative Taxi occupancy: " + vehicleId);
			vehicle.completedServices++;
			vehicle.onboardPassengerSeconds += event.getTime() - state.pickupTimes.get(event.getPersonId());
		}
	}

	@Override
	public void handleEvent(LinkEnterEvent event) {
		VehicleState vehicle = vehicles.get(event.getVehicleId());
		if (vehicle == null) return;
		var link = network.getLinks().get(event.getLinkId());
		if (link == null) throw new IllegalStateException("Taxi entered unknown link " + event.getLinkId());
		if (vehicle.occupancy > 0) vehicle.occupiedMeters += link.getLength();
		else vehicle.emptyMeters += link.getLength();
	}

	@Override
	public void handleEvent(PassengerRequestRejectedEvent event) {
		if (!isTaxi(event.getMode())) return;
		RequestState state = require(event.getRequestId(), "rejection");
		state.rejectionTime = event.getTime();
		state.rejectionCause = event.getCause();
		for (Id<Person> personId : state.personIds) {
			if (!state.pickupTimes.containsKey(personId)) {
				scoreWait(state, personId, event.getTime(),
						totalWaitUtilityPerSecond, UNSERVED_SCORE_KIND);
			}
		}
	}

	@Override
	public void notifyMobsimBeforeCleanup(MobsimBeforeCleanupEvent event) {
		double horizon = ((Netsim) event.getQueueSimulation()).getSimTimer().getTimeOfDay();
		finalizeScoringAtHorizon(horizon);
		writeAudit(horizon);
		writeOperatingAudit(horizon);
	}

	void finalizeScoringAtHorizon(double horizon) {
		for (RequestState state : requests.values()) {
			for (Id<Person> personId : state.personIds) {
				if (!state.pickupTimes.containsKey(personId)) {
					if (!state.waitScored.containsKey(personId)) {
						scoreWait(state, personId, horizon,
								totalWaitUtilityPerSecond, UNSERVED_SCORE_KIND);
					}
				} else if (!state.dropoffTimes.containsKey(personId)
						&& state.onboardBaseWaitScored.add(personId)) {
					// No PersonArrival means standard leg scoring may never apply its -6 util/h.
					// Add only that base waiting part; the extra -6 was emitted at pickup.
					double elapsed = Math.max(0, horizon - state.submissionTime);
					events.processEvent(new PersonScoreEvent(
							horizon, personId, baseTravelUtilityPerSecond * elapsed,
							ONBOARD_BASE_SCORE_KIND));
				}
			}
		}
		for (RequestState state : requests.values()) {
			for (var pickup : state.pickupTimes.entrySet()) {
				if (state.dropoffTimes.containsKey(pickup.getKey()) || state.vehicleId.isBlank()) continue;
				VehicleState vehicle = vehicles.get(Id.createVehicleId(state.vehicleId));
				if (vehicle != null) vehicle.onboardPassengerSeconds += Math.max(0, horizon - pickup.getValue());
			}
		}
	}

	private void scoreWait(RequestState state, Id<Person> personId, double endTime,
			double utilityPerSecond, String kind) {
		double wait = Math.max(0, endTime - state.submissionTime);
		double score = utilityPerSecond * wait;
		state.waitScored.put(personId, wait);
		if (state.operational) return;
		events.processEvent(new PersonScoreEvent(endTime, personId, score, kind));
	}

	private void writeAudit(double horizon) {
		if (iteration < 0) throw new IllegalStateException("Taxi audit iteration was not initialized");
		String filename = output.getIterationFilename(iteration, "taxi_request_audit.csv.gz");
		List<RequestState> rows = new ArrayList<>(requests.values());
		rows.sort(Comparator.comparing(state -> state.requestId.toString()));
		try (BufferedWriter writer = IOUtils.getBufferedWriter(filename)) {
			writer.write("request_id,person_ids,operational_only,submitted_s,picked_up_s,dropped_off_s,wait_s,vehicle_id,status,rejection_cause,horizon_s\n");
			for (RequestState state : rows) {
				double pickup = state.pickupTimes.values().stream().mapToDouble(Double::doubleValue).min().orElse(Double.NaN);
				double dropoff = state.dropoffTimes.values().stream().mapToDouble(Double::doubleValue).max().orElse(Double.NaN);
				double wait = state.waitScored.values().stream().mapToDouble(Double::doubleValue).max().orElse(Double.NaN);
				String status = state.rejectionTime != null ? "rejected"
						: state.dropoffTimes.size() == state.personIds.size() ? "completed"
						: state.pickupTimes.isEmpty() ? "waiting" : "onboard";
				writer.write(csv(state.requestId.toString()) + ","
						+ csv(state.personIds.stream().map(Object::toString).sorted().reduce((a, b) -> a + "|" + b).orElse("")) + ","
						+ state.operational + ","
						+ state.submissionTime + "," + number(pickup) + "," + number(dropoff) + ","
						+ number(wait) + "," + csv(state.vehicleId) + "," + status + ","
						+ csv(state.rejectionCause) + "," + horizon + "\n");
			}
		} catch (IOException error) {
			throw new IllegalStateException("Cannot write Taxi request audit " + filename, error);
		}
	}

	private void writeOperatingAudit(double horizon) {
		if (fleetRegistry == null) return;
		long completed = requests.values().stream().filter(s -> "completed".equals(status(s))).count();
		long waiting = requests.values().stream().filter(s -> "waiting".equals(status(s))).count();
		long onboard = requests.values().stream().filter(s -> "onboard".equals(status(s))).count();
		long rejected = requests.values().stream().filter(s -> "rejected".equals(status(s))).count();
		long operationalSubmitted = requests.values().stream().filter(s -> s.operational).count();
		long behavioralSubmitted = requests.size() - operationalSubmitted;
		if (requests.size() != completed + waiting + onboard + rejected) {
			throw new IllegalStateException("Taxi request conservation failed");
		}
		List<Double> waits = requests.values().stream()
				.flatMap(state -> state.waitScored.values().stream()).sorted().toList();
		double emptyMeters = vehicles.values().stream().mapToDouble(v -> v.emptyMeters).sum();
		double occupiedMeters = vehicles.values().stream().mapToDouble(v -> v.occupiedMeters).sum();
		double onboardSeconds = vehicles.values().stream().mapToDouble(v -> v.onboardPassengerSeconds).sum();
		long services = vehicles.values().stream().mapToLong(v -> v.completedServices).sum();
		long used = vehicles.values().stream().filter(VehicleState::used).count();
		double activeSeconds = fleetRegistry.serviceWindows().values().stream()
				.mapToDouble(window -> Math.max(0, Math.min(horizon, window.end()) - window.begin())).sum();
		double totalMeters = emptyMeters + occupiedMeters;
		String summary = output.getIterationFilename(iteration, "taxi_operating_summary.csv");
		try (BufferedWriter writer = IOUtils.getBufferedWriter(summary)) {
			writer.write("submitted,behavioral_submitted,operational_submitted,completed,waiting,onboard,rejected,wait_p50_s,wait_p90_s,wait_p95_s,wait_p99_s,"
					+ "fleet_vehicles,vehicles_used,completed_services,services_per_fleet_vehicle,services_per_used_vehicle,"
					+ "empty_vkt_km,occupied_vkt_km,empty_vkt_ratio,onboard_utilization,horizon_s\n");
			writer.write(requests.size() + "," + behavioralSubmitted + "," + operationalSubmitted
					+ "," + completed + "," + waiting + "," + onboard + "," + rejected + ","
					+ quantile(waits, .50) + "," + quantile(waits, .90) + "," + quantile(waits, .95) + ","
					+ quantile(waits, .99) + "," + vehicles.size() + "," + used + "," + services + ","
					+ ratio(services, vehicles.size()) + "," + ratio(services, used) + ","
					+ emptyMeters / 1000.0 + "," + occupiedMeters / 1000.0 + ","
					+ ratio(emptyMeters, totalMeters) + "," + ratio(onboardSeconds, activeSeconds) + ","
					+ horizon + "\n");
		} catch (IOException error) {
			throw new IllegalStateException("Cannot write Taxi operating summary " + summary, error);
		}

		String details = output.getIterationFilename(iteration, "taxi_vehicle_audit.csv.gz");
		try (BufferedWriter writer = IOUtils.getBufferedWriter(details)) {
			writer.write("vehicle_id,service_begin_s,service_end_s,completed_services,empty_vkt_km,occupied_vkt_km,"
					+ "empty_vkt_ratio,onboard_passenger_s,utilization\n");
			for (var entry : fleetRegistry.serviceWindows().entrySet().stream()
					.sorted(Map.Entry.comparingByKey(Comparator.comparing(Id::toString))).toList()) {
				VehicleState state = vehicles.get(entry.getKey());
				var window = entry.getValue();
				double active = Math.max(0, Math.min(horizon, window.end()) - window.begin());
				double total = state.emptyMeters + state.occupiedMeters;
				writer.write(csv(entry.getKey().toString()) + "," + window.begin() + "," + window.end() + ","
						+ state.completedServices + "," + state.emptyMeters / 1000.0 + ","
						+ state.occupiedMeters / 1000.0 + "," + ratio(state.emptyMeters, total) + ","
						+ state.onboardPassengerSeconds + "," + ratio(state.onboardPassengerSeconds, active) + "\n");
			}
		} catch (IOException error) {
			throw new IllegalStateException("Cannot write Taxi vehicle audit " + details, error);
		}
	}

	private static String status(RequestState state) {
		return state.rejectionTime != null ? "rejected"
				: state.dropoffTimes.size() == state.personIds.size() ? "completed"
				: state.pickupTimes.isEmpty() ? "waiting" : "onboard";
	}

	private static double quantile(List<Double> sorted, double probability) {
		if (sorted.isEmpty()) return Double.NaN;
		int index = Math.max(0, (int)Math.ceil(probability * sorted.size()) - 1);
		return sorted.get(index);
	}

	private static double ratio(double numerator, double denominator) {
		return denominator > 0 ? numerator / denominator : 0;
	}

	private RequestState require(Id<Request> id, String event) {
		RequestState state = requests.get(id);
		if (state == null) throw new IllegalStateException("Taxi " + event + " without submission: " + id);
		return state;
	}

	private static boolean isTaxi(String mode) {
		return HongKongTaxiScoringParameters.TAXI_MODE.equals(mode);
	}

	private static Set<Id<Person>> operationalPersons(Scenario scenario) {
		return scenario.getPopulation().getPersons().values().stream()
				.filter(HongKongTaxiOperationalRequestGate::isShadow)
				.map(Person::getId).collect(java.util.stream.Collectors.toUnmodifiableSet());
	}

	private static String number(double value) {
		return Double.isFinite(value) ? Double.toString(value) : "";
	}

	private static String csv(String value) {
		if (value == null) return "";
		return '"' + value.replace("\"", "\"\"") + '"';
	}

	private static final class RequestState {
		private final Id<Request> requestId;
		private final List<Id<Person>> personIds;
		private final double submissionTime;
		private final boolean operational;
		private final Map<Id<Person>, Double> pickupTimes = new LinkedHashMap<>();
		private final Map<Id<Person>, Double> dropoffTimes = new LinkedHashMap<>();
		private final Map<Id<Person>, Double> waitScored = new LinkedHashMap<>();
		private final java.util.Set<Id<Person>> onboardBaseWaitScored = new java.util.LinkedHashSet<>();
		private String vehicleId = "";
		private Double rejectionTime;
		private String rejectionCause = "";

		private RequestState(Id<Request> requestId, List<Id<Person>> personIds,
				double submissionTime, boolean operational) {
			this.requestId = requestId;
			this.personIds = List.copyOf(personIds);
			this.submissionTime = submissionTime;
			this.operational = operational;
		}
	}

	private static final class VehicleState {
		private int occupancy;
		private long completedServices;
		private double emptyMeters;
		private double occupiedMeters;
		private double onboardPassengerSeconds;

		private boolean used() {
			return completedServices > 0 || occupancy > 0 || emptyMeters > 0 || occupiedMeters > 0;
		}
	}
}
