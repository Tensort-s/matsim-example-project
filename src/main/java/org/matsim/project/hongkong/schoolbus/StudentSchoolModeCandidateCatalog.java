package org.matsim.project.hongkong.schoolbus;

import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.network.Link;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.api.core.v01.population.Person;
import org.matsim.api.core.v01.population.Plan;
import org.matsim.api.core.v01.population.PlanElement;
import org.matsim.core.population.PopulationUtils;
import org.matsim.core.router.TripStructureUtils;
import org.matsim.pt.transitSchedule.api.TransitStopFacility;

import java.io.BufferedReader;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;

/** Immutable all-student mode and physical school-bus candidate registry. */
public final class StudentSchoolModeCandidateCatalog {

	public static final String UNIVERSE_FILE = "school_trip_universe_v6.csv";
	public static final String SCHOOL_BUS_FILE = "school_bus_physical_route_candidates_v6.csv";
	public static final String CANDIDATE_ID_ATTRIBUTE = "hkSchoolBusCandidateId";

	public record TripKey(String personId, int tripIndex) {
	}

	public record SchoolBusOption(
			String candidateId,
			String direction,
			String routeId,
			String transitLineId,
			String transitRouteId,
			String departureId,
			String vehicleId,
			String boardingFacilityId,
			String alightingFacilityId,
			String boardingLinkId,
			String alightingLinkId,
			double scheduledBoardTimeS,
			double scheduledAlightTimeS,
			double homeStopDistanceM,
			double campusStopDistanceM) {
	}

	public record TripCandidate(
			TripKey key,
			String direction,
			String studentStage,
			String originalModeAuditOnly,
			double crowflyDistanceM,
			boolean walkAvailable,
			List<SchoolBusOption> schoolBusOptions) {
		public TripCandidate {
			schoolBusOptions = List.copyOf(schoolBusOptions);
		}
	}

	private final Map<TripKey, TripCandidate> trips;
	private final Set<String> physicalSchoolBusStopIds;
	private final Map<String, SchoolBusOption> schoolBusOptionsById;
	private final Map<Id<Person>, List<SchoolBusTripSnapshot>> selectedSchoolBusTripSnapshots =
			new LinkedHashMap<>();
	private final Map<Id<Person>, List<SchoolBusLegGuard>> selectedSchoolBusLegs =
			new LinkedHashMap<>();

	private record SchoolBusTripSnapshot(int tripIndex, List<PlanElement> elements) {
	}

	public record SelectedSchoolBusTiming(
			double plannedLegDepartureTimeS, double scheduledBoardTimeS) {
	}

	private record SchoolBusLegGuard(
			String candidateId, Id<Link> boardingLinkId,
			double plannedLegDepartureTimeS, double scheduledBoardTimeS) {
	}

	private StudentSchoolModeCandidateCatalog(Map<TripKey, TripCandidate> trips) {
		this.trips = Map.copyOf(trips);
		Set<String> stopIds = new HashSet<>();
		Map<String, SchoolBusOption> optionsById = new LinkedHashMap<>();
		for (TripCandidate trip : trips.values()) {
			for (SchoolBusOption option : trip.schoolBusOptions()) {
				stopIds.add(option.boardingFacilityId());
				stopIds.add(option.alightingFacilityId());
				if (optionsById.putIfAbsent(option.candidateId(), option) != null) {
					throw new IllegalArgumentException(
							"Duplicate physical school-bus candidate " + option.candidateId());
				}
			}
		}
		this.physicalSchoolBusStopIds = Set.copyOf(stopIds);
		this.schoolBusOptionsById = Map.copyOf(optionsById);
	}

	public static StudentSchoolModeCandidateCatalog empty() {
		return new StudentSchoolModeCandidateCatalog(Map.of());
	}

	public static StudentSchoolModeCandidateCatalog load(Path directory) {
		Path root = directory.toAbsolutePath().normalize();
		Path universe = root.resolve(UNIVERSE_FILE);
		Path schoolBus = root.resolve(SCHOOL_BUS_FILE);
		if (!Files.isRegularFile(universe) || !Files.isRegularFile(schoolBus)) {
			throw new IllegalArgumentException("Student school-mode candidate directory is incomplete: " + root);
		}

		Map<TripKey, MutableTrip> mutable = new LinkedHashMap<>();
		for (Map<String, String> row : readCsv(universe)) {
			TripKey key = new TripKey(required(row, "person_id"), integer(row, "trip_index"));
			MutableTrip previous = mutable.putIfAbsent(key, new MutableTrip(
					key,
					required(row, "direction"),
					required(row, "student_stage"),
					required(row, "original_mode_audit_only"),
					number(row, "crowfly_distance_m"),
					number(row, "crowfly_distance_m") <= 5_000.0));
			if (previous != null) {
				throw new IllegalArgumentException("Duplicate student school trip " + key);
			}
		}
		if (mutable.isEmpty()) {
			throw new IllegalArgumentException("Student school-mode universe is empty: " + universe);
		}

		Set<String> candidateIds = new HashSet<>();
		for (Map<String, String> row : readCsv(schoolBus)) {
			String candidateId = required(row, "candidate_id");
			if (!candidateIds.add(candidateId)) {
				throw new IllegalArgumentException("Duplicate physical school-bus candidate " + candidateId);
			}
			TripKey key = new TripKey(required(row, "person_id"), integer(row, "trip_index"));
			MutableTrip trip = mutable.get(key);
			if (trip == null) {
				throw new IllegalArgumentException("Physical school-bus option lacks universe trip " + key);
			}
			String direction = required(row, "direction");
			if (!trip.direction.equals(direction)) {
				throw new IllegalArgumentException("School-bus direction mismatch for " + candidateId);
			}
			trip.options.add(new SchoolBusOption(
					candidateId,
					direction,
					required(row, "route_id"),
					required(row, "transit_line_id"),
					required(row, "transit_route_id"),
					required(row, "departure_id"),
					required(row, "vehicle_id"),
					required(row, "boarding_facility_id"),
					required(row, "alighting_facility_id"),
					required(row, "boarding_link_id"),
					required(row, "alighting_link_id"),
					number(row, "scheduled_board_time_s"),
					number(row, "scheduled_alight_time_s"),
					number(row, "home_stop_distance_m"),
					number(row, "campus_stop_distance_m")));
		}

		Map<TripKey, TripCandidate> result = new LinkedHashMap<>();
		for (MutableTrip trip : mutable.values()) {
			trip.options.sort(java.util.Comparator.comparing(SchoolBusOption::candidateId));
			result.put(trip.key, new TripCandidate(
					trip.key, trip.direction, trip.studentStage, trip.originalMode,
					trip.crowflyDistanceM, trip.walkAvailable, trip.options));
		}
		return new StudentSchoolModeCandidateCatalog(result);
	}

	public boolean enabled() {
		return !trips.isEmpty();
	}

	public Map<TripKey, TripCandidate> trips() {
		return trips;
	}

	public int physicalSchoolBusOptionCount() {
		return trips.values().stream().mapToInt(value -> value.schoolBusOptions().size()).sum();
	}

	public boolean isPhysicalSchoolBusStop(Id<TransitStopFacility> stopId) {
		return stopId != null && physicalSchoolBusStopIds.contains(stopId.toString());
	}

	/**
	 * Resolves a selected physical school-bus leg by stable plan identity.
	 *
	 * <p>QSim departure time is deliberately not part of the identity: a passenger can
	 * reach the boarding leg hours late after upstream delay. That is a missed-service
	 * outcome to audit, not evidence that the current plan leg ceased to be a school-bus
	 * leg.</p>
	 */
	public synchronized Optional<SelectedSchoolBusTiming> selectedSchoolBusTiming(
			Id<Person> personId, String candidateId, Id<Link> fromLinkId) {
		if (candidateId == null || fromLinkId == null) return Optional.empty();
		for (SchoolBusLegGuard guard : selectedSchoolBusLegs.getOrDefault(personId, List.of())) {
			if (guard.candidateId().equals(candidateId)
					&& guard.boardingLinkId().equals(fromLinkId)) {
				return Optional.of(new SelectedSchoolBusTiming(
						guard.plannedLegDepartureTimeS(), guard.scheduledBoardTimeS()));
			}
		}
		return Optional.empty();
	}

	/** Saves only physical school-bus trips before PrepareForSim can reroute them. */
	public synchronized void snapshotSelectedSchoolBusPlans(Scenario scenario) {
		selectedSchoolBusTripSnapshots.clear();
		selectedSchoolBusLegs.clear();
		for (Person person : scenario.getPopulation().getPersons().values()) {
			Plan selected = person.getSelectedPlan();
			if (selected == null) continue;
			List<SchoolBusTripSnapshot> snapshots = new ArrayList<>();
			List<SchoolBusLegGuard> legs = new ArrayList<>();
			List<TripStructureUtils.Trip> trips = TripStructureUtils.getTrips(selected);
			for (int tripIndex = 0; tripIndex < trips.size(); tripIndex++) {
				TripStructureUtils.Trip trip = trips.get(tripIndex);
				if (trip.getLegsOnly().stream()
						.noneMatch(leg -> "school_bus".equals(leg.getRoutingMode()))) continue;
				snapshots.add(new SchoolBusTripSnapshot(
						tripIndex, clonePlanElements(trip.getTripElements())));
				for (Leg leg : trip.getLegsOnly()) {
					if (!"pt".equals(leg.getMode())
							|| !"school_bus".equals(leg.getRoutingMode())
							|| leg.getRoute() == null || leg.getRoute().getStartLinkId() == null) continue;
					Object candidateId = leg.getAttributes().getAttribute(CANDIDATE_ID_ATTRIBUTE);
					if (!(candidateId instanceof String value) || value.isBlank()) {
						throw new IllegalStateException("Selected school-bus leg has no stable candidate ID for "
								+ person.getId());
					}
					SchoolBusOption option = schoolBusOptionsById.get(value);
					if (option == null) {
						throw new IllegalStateException("Selected school-bus candidate is absent from the catalog: "
								+ person.getId() + "/" + value);
					}
					legs.add(new SchoolBusLegGuard(
							value,
							leg.getRoute().getStartLinkId(),
							leg.getDepartureTime().orElseThrow(() -> new IllegalStateException(
									"Selected school-bus leg has no departure time for " + person.getId())),
							option.scheduledBoardTimeS()));
				}
			}
			if (!snapshots.isEmpty()) {
				if (legs.size() != snapshots.size()) {
					throw new IllegalStateException("Selected school-bus trip/departure mismatch for "
							+ person.getId());
				}
				selectedSchoolBusTripSnapshots.put(person.getId(), List.copyOf(snapshots));
				selectedSchoolBusLegs.put(person.getId(), List.copyOf(legs));
			}
		}
	}

	/** Restores only school-bus trip slices, preserving PrepareForSim routing of all other trips. */
	public synchronized int restoreSelectedSchoolBusPlans(Scenario scenario) {
		int restored = 0;
		for (var entry : selectedSchoolBusTripSnapshots.entrySet()) {
			Person person = scenario.getPopulation().getPersons().get(entry.getKey());
			if (person == null || person.getSelectedPlan() == null) continue;
			Plan selected = person.getSelectedPlan();
			List<TripStructureUtils.Trip> currentTrips = TripStructureUtils.getTrips(selected);
			List<SchoolBusTripSnapshot> snapshots = entry.getValue();
			for (int i = snapshots.size() - 1; i >= 0; i--) {
				SchoolBusTripSnapshot snapshot = snapshots.get(i);
				if (snapshot.tripIndex() >= currentTrips.size()) {
					throw new IllegalStateException("PrepareForSim removed student trip "
							+ snapshot.tripIndex() + " for " + person.getId());
				}
				TripStructureUtils.Trip current = currentTrips.get(snapshot.tripIndex());
				int origin = selected.getPlanElements().indexOf(current.getOriginActivity());
				int destination = selected.getPlanElements().indexOf(current.getDestinationActivity());
				if (origin < 0 || destination <= origin) {
					throw new IllegalStateException("Cannot locate student trip "
							+ snapshot.tripIndex() + " for " + person.getId());
				}
				selected.getPlanElements().subList(origin + 1, destination).clear();
				selected.getPlanElements().addAll(
						origin + 1, clonePlanElements(snapshot.elements()));
			}
			restored++;
		}
		return restored;
	}

	private static List<PlanElement> clonePlanElements(List<? extends PlanElement> source) {
		List<PlanElement> copy = new ArrayList<>(source.size());
		for (PlanElement element : source) {
			if (element instanceof Leg sourceLeg) {
				Leg destinationLeg = PopulationUtils.createLeg(sourceLeg);
				if (sourceLeg.getRoute() != null) {
					destinationLeg.setRoute(sourceLeg.getRoute().clone());
				}
				copy.add(destinationLeg);
			} else if (element instanceof org.matsim.api.core.v01.population.Activity activity) {
				copy.add(PopulationUtils.createActivity(activity));
			} else {
				throw new IllegalArgumentException("Unsupported school-bus trip element: "
						+ element.getClass().getName());
			}
		}
		return copy;
	}

	private static final class MutableTrip {
		final TripKey key;
		final String direction;
		final String studentStage;
		final String originalMode;
		final double crowflyDistanceM;
		final boolean walkAvailable;
		final List<SchoolBusOption> options = new ArrayList<>();

		MutableTrip(TripKey key, String direction, String studentStage, String originalMode,
				double crowflyDistanceM, boolean walkAvailable) {
			this.key = key;
			this.direction = direction;
			this.studentStage = studentStage;
			this.originalMode = originalMode;
			this.crowflyDistanceM = crowflyDistanceM;
			this.walkAvailable = walkAvailable;
		}
	}

	private static List<Map<String, String>> readCsv(Path path) {
		try (BufferedReader reader = Files.newBufferedReader(path, StandardCharsets.UTF_8)) {
			String headerLine = reader.readLine();
			if (headerLine == null) throw new IllegalArgumentException("Empty CSV: " + path);
			headerLine = headerLine.replace("\uFEFF", "");
			String[] header = headerLine.split(",", -1);
			List<Map<String, String>> rows = new ArrayList<>();
			String line;
			int lineNumber = 1;
			while ((line = reader.readLine()) != null) {
				lineNumber++;
				if (line.isBlank()) continue;
				String[] values = line.split(",", -1);
				if (values.length != header.length) {
					throw new IllegalArgumentException("Malformed CSV line " + lineNumber + " in " + path);
				}
				Map<String, String> row = new LinkedHashMap<>();
				for (int index = 0; index < header.length; index++) row.put(header[index], values[index]);
				rows.add(row);
			}
			return rows;
		} catch (IOException error) {
			throw new IllegalArgumentException("Cannot read candidate CSV: " + path, error);
		}
	}

	private static String required(Map<String, String> row, String field) {
		String value = row.get(field);
		if (value == null || value.isBlank()) throw new IllegalArgumentException("Missing candidate field " + field);
		return value.trim();
	}

	private static int integer(Map<String, String> row, String field) {
		return Integer.parseInt(required(row, field));
	}

	private static double number(Map<String, String> row, String field) {
		double value = Double.parseDouble(required(row, field));
		if (!Double.isFinite(value) || value < 0.0) {
			throw new IllegalArgumentException("Invalid candidate field " + field + "=" + value);
		}
		return value;
	}
}
