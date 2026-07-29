package org.matsim.project.hongkong.taxi;

import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.api.core.v01.population.Person;
import org.matsim.api.core.v01.population.Plan;
import org.matsim.api.core.v01.population.PlanElement;
import org.matsim.api.core.v01.population.Population;
import org.matsim.api.core.v01.population.Route;
import org.matsim.core.population.routes.GenericRouteImpl;
import org.matsim.core.utils.misc.OptionalTime;
import org.matsim.pt.routes.DefaultTransitPassengerRoute;
import org.matsim.pt.routes.TransitPassengerRoute;
import org.matsim.pt.transitSchedule.api.TransitLine;
import org.matsim.pt.transitSchedule.api.TransitRoute;
import org.matsim.pt.transitSchedule.api.TransitSchedule;
import org.matsim.pt.transitSchedule.api.TransitStopFacility;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.TreeMap;

import static org.matsim.project.hongkong.taxi.HongKongTaxiSmokeOutputAudit.ordered;

/**
 * Baseline-aligned, one-shot PT startup preparation and immutable Taxi/PT
 * audits. It never routes a Taxi leg or constructs a transit-passenger route.
 */
public final class HongKongTaxiPtRoutePreparation {

	public static final long EXPECTED_PERSONS = 385_820L;
	public static final long EXPECTED_PT_LEGS = 557_104L;
	public static final long EXPECTED_TAXI_LEGS = 37_286L;

	private HongKongTaxiPtRoutePreparation() {
	}

	/**
	 * Mirrors {@code RunHongKong5Pct --clear-pt-routes}: every plan is scanned
	 * and only a non-null route on a {@code mode=pt} leg is cleared.
	 */
	public static PreparationAudit clearPtRoutes(Scenario scenario) {
		Objects.requireNonNull(scenario, "scenario");
		Population population = scenario.getPopulation();
		Map<LegLocation, RouteFingerprint> nonPtBefore =
				captureNonPtRoutes(population);
		TaxiSnapshot taxiBefore = captureSelectedTaxi(population);

		long persons = population.getPersons().size();
		long plans = 0;
		long totalPt = 0;
		long routeNullBefore = 0;
		long nonNullBefore = 0;
		long genericBefore = 0;
		long legalBefore = 0;
		long cleared = 0;
		for (Person person : population.getPersons().values()) {
			for (Plan plan : person.getPlans()) {
				plans++;
				for (PlanElement element : plan.getPlanElements()) {
					if (!(element instanceof Leg leg) || !"pt".equals(leg.getMode())) {
						continue;
					}
					totalPt++;
					Route route = leg.getRoute();
					if (route == null) {
						routeNullBefore++;
						continue;
					}
					nonNullBefore++;
					if (route instanceof GenericRouteImpl) {
						genericBefore++;
					}
					if (route instanceof TransitPassengerRoute) {
						legalBefore++;
					}
					leg.setRoute(null);
					cleared++;
				}
			}
		}

		long nullAfter = countNullPtRoutes(population);
		Map<LegLocation, RouteFingerprint> nonPtAfter =
				captureNonPtRoutes(population);
		long nonPtChanged = changedEntries(nonPtBefore, nonPtAfter);
		TaxiInvarianceAudit taxiDuringClear =
				compareTaxi(taxiBefore, captureSelectedTaxi(population));
		if (!taxiDuringClear.exact()) {
			throw new IllegalStateException(
					"PT route clear changed Taxi content: " + taxiDuringClear.toMap());
		}
		return new PreparationAudit(
				persons,
				plans,
				totalPt,
				routeNullBefore,
				nonNullBefore,
				genericBefore,
				legalBefore,
				cleared,
				nullAfter,
				nonPtChanged
		);
	}

	public static void requireFormalSource(PreparationAudit audit) {
		Map<String, Boolean> checks = new LinkedHashMap<>();
		checks.put("persons_exact", audit.personsScanned() == EXPECTED_PERSONS);
		checks.put("plans_exact", audit.plansScanned() == EXPECTED_PERSONS);
		checks.put("total_pt_legs_exact", audit.totalPtLegs() == EXPECTED_PT_LEGS);
		checks.put("all_source_pt_routes_non_null",
				audit.ptRoutesNonNullBefore() == EXPECTED_PT_LEGS
						&& audit.ptRoutesNullBefore() == 0);
		checks.put("all_source_pt_routes_generic",
				audit.genericPtRoutesBefore() == EXPECTED_PT_LEGS);
		checks.put("no_legal_source_transit_routes",
				audit.legalTransitPassengerRoutesBefore() == 0);
		checks.put("all_pt_routes_cleared",
				audit.ptRoutesCleared() == EXPECTED_PT_LEGS);
		checks.put("all_pt_routes_null_after_clear",
				audit.ptRoutesNullAfterClear() == EXPECTED_PT_LEGS);
		checks.put("non_pt_routes_unchanged", audit.nonPtRoutesChanged() == 0);
		requireChecks("Taxi PT source preparation", checks);
	}

	/** Audits the actual selected-plan route objects visible to QSim. */
	public static PtRuntimeAudit auditPreparedSelectedPt(Scenario scenario) {
		Objects.requireNonNull(scenario, "scenario");
		return auditPreparedSelectedPt(
				scenario.getPopulation(),
				scenario.getTransitSchedule()
		);
	}

	static PtRuntimeAudit auditPreparedSelectedPt(
			Population population,
			TransitSchedule schedule) {
		long total = 0;
		long routeNull = 0;
		long generic = 0;
		long legal = 0;
		long defaults = 0;
		long otherLegal = 0;
		long accessMissing = 0;
		long egressMissing = 0;
		long lineMissing = 0;
		long routeIdMissing = 0;
		long accessNotSchedule = 0;
		long egressNotSchedule = 0;
		long lineNotSchedule = 0;
		long routeNotSchedule = 0;
		Map<String, Long> runtimeClasses = new TreeMap<>();
		List<Map<String, Object>> invalidExamples = new ArrayList<>();
		MessageDigest digest = sha256();

		for (Person person : population.getPersons().values()) {
			Plan plan = requireSelectedPlan(person);
			int ptOrdinal = 0;
			for (PlanElement element : plan.getPlanElements()) {
				if (!(element instanceof Leg leg) || !"pt".equals(leg.getMode())) {
					continue;
				}
				total++;
				Route rawRoute = leg.getRoute();
				String runtimeClass =
						rawRoute == null ? "<null>" : rawRoute.getClass().getName();
				runtimeClasses.merge(runtimeClass, 1L, Long::sum);
				boolean isNull = rawRoute == null;
				boolean isGeneric = rawRoute instanceof GenericRouteImpl;
				boolean isLegal = rawRoute instanceof TransitPassengerRoute;
				boolean isDefault = rawRoute instanceof DefaultTransitPassengerRoute;
				routeNull += bool(isNull);
				generic += bool(isGeneric);
				legal += bool(isLegal);
				defaults += bool(isDefault);
				otherLegal += bool(isLegal && !isDefault);

				String access = null;
				String egress = null;
				String lineId = null;
				String transitRouteId = null;
				if (rawRoute instanceof TransitPassengerRoute route) {
					access = id(route.getAccessStopId());
					egress = id(route.getEgressStopId());
					lineId = id(route.getLineId());
					transitRouteId = id(route.getRouteId());
				}
				ChainAudit chain = rawRoute instanceof TransitPassengerRoute route
						? auditChain(route, schedule)
						: ChainAudit.empty();
				accessMissing += chain.accessMissing();
				egressMissing += chain.egressMissing();
				lineMissing += chain.lineMissing();
				routeIdMissing += chain.routeMissing();
				accessNotSchedule += chain.accessUnknown();
				egressNotSchedule += chain.egressUnknown();
				lineNotSchedule += chain.lineUnknown();
				routeNotSchedule += chain.routeUnknown();

				boolean invalid = isNull || !isLegal || !chain.exact();
				if (invalid && invalidExamples.size() < 10) {
					invalidExamples.add(ordered(
							"person_id", person.getId().toString(),
							"pt_ordinal", ptOrdinal,
							"runtime_class", runtimeClass,
							"access_stop", String.valueOf(access),
							"egress_stop", String.valueOf(egress),
							"line_id", String.valueOf(lineId),
							"transit_route_id", String.valueOf(transitRouteId),
							"chain_components", chain.components()
					));
				}
				update(digest, person.getId() + "\t" + ptOrdinal + "\t"
						+ runtimeClass + "\t" + routeFingerprint(rawRoute) + "\t"
						+ access + "\t" + egress + "\t" + lineId + "\t"
						+ transitRouteId + "\n");
				ptOrdinal++;
			}
		}
		return new PtRuntimeAudit(
				total,
				routeNull,
				generic,
				legal,
				defaults,
				otherLegal,
				accessMissing,
				egressMissing,
				lineMissing,
				routeIdMissing,
				accessNotSchedule,
				egressNotSchedule,
				lineNotSchedule,
				routeNotSchedule,
				Map.copyOf(runtimeClasses),
				List.copyOf(invalidExamples),
				hex(digest.digest())
		);
	}

	private static ChainAudit auditChain(
			TransitPassengerRoute first,
			TransitSchedule schedule) {
		long accessMissing = 0;
		long egressMissing = 0;
		long lineMissing = 0;
		long routeMissing = 0;
		long accessUnknown = 0;
		long egressUnknown = 0;
		long lineUnknown = 0;
		long routeUnknown = 0;
		int components = 0;
		Set<TransitPassengerRoute> visited =
				java.util.Collections.newSetFromMap(new java.util.IdentityHashMap<>());
		TransitPassengerRoute current = first;
		while (current != null) {
			if (!visited.add(current)) {
				routeUnknown++;
				break;
			}
			components++;
			boolean missingAccess = current.getAccessStopId() == null;
			boolean missingEgress = current.getEgressStopId() == null;
			boolean missingLine = current.getLineId() == null;
			boolean missingRoute = current.getRouteId() == null;
			accessMissing += bool(missingAccess);
			egressMissing += bool(missingEgress);
			lineMissing += bool(missingLine);
			routeMissing += bool(missingRoute);

			TransitStopFacility access = missingAccess ? null
					: schedule.getFacilities().get(current.getAccessStopId());
			TransitStopFacility egress = missingEgress ? null
					: schedule.getFacilities().get(current.getEgressStopId());
			TransitLine line = missingLine ? null
					: schedule.getTransitLines().get(current.getLineId());
			TransitRoute route = line == null || missingRoute ? null
					: line.getRoutes().get(current.getRouteId());
			accessUnknown += bool(!missingAccess && access == null);
			egressUnknown += bool(!missingEgress && egress == null);
			lineUnknown += bool(!missingLine && line == null);
			routeUnknown += bool(!missingRoute && route == null);
			current = current.getChainedRoute();
		}
		return new ChainAudit(
				accessMissing, egressMissing, lineMissing, routeMissing,
				accessUnknown, egressUnknown, lineUnknown, routeUnknown,
				components);
	}

	public static void requireFormalPrepared(PtRuntimeAudit audit) {
		requirePrepared(audit, EXPECTED_PT_LEGS);
	}

	static void requirePrepared(PtRuntimeAudit audit, long expectedPtLegs) {
		Map<String, Boolean> checks = new LinkedHashMap<>();
		checks.put("total_pt_legs_exact", audit.totalPtLegs() == expectedPtLegs);
		checks.put("route_null_zero", audit.routeNull() == 0);
		checks.put("generic_route_zero", audit.genericRouteImpl() == 0);
		checks.put("all_routes_legal_transit_passenger",
				audit.transitPassengerRoute() == expectedPtLegs);
		checks.put("access_stop_missing_zero", audit.accessStopMissing() == 0);
		checks.put("egress_stop_missing_zero", audit.egressStopMissing() == 0);
		checks.put("line_id_missing_zero", audit.lineIdMissing() == 0);
		checks.put("transit_route_id_missing_zero",
				audit.transitRouteIdMissing() == 0);
		checks.put("access_stop_not_in_schedule_zero",
				audit.accessStopNotInSchedule() == 0);
		checks.put("egress_stop_not_in_schedule_zero",
				audit.egressStopNotInSchedule() == 0);
		checks.put("line_not_in_schedule_zero", audit.lineNotInSchedule() == 0);
		checks.put("route_not_in_schedule_zero", audit.routeNotInSchedule() == 0);
		requireChecks("Prepared PT BeforeMobsim", checks);
	}

	/** Strict selected-plan Taxi fingerprint, independent of PT stage indexes. */
	public static TaxiSnapshot captureSelectedTaxi(Population population) {
		Map<TaxiKey, TaxiRecord> records = new LinkedHashMap<>();
		Map<String, List<Integer>> sequences = new LinkedHashMap<>();
		long duplicates = 0;
		Set<String> taxiPersons = new LinkedHashSet<>();
		Set<MainTripIdentity> mainTripIdentities = new LinkedHashSet<>();
		MessageDigest digest = sha256();
		for (Person person : population.getPersons().values()) {
			Plan plan = requireSelectedPlan(person);
			int taxiOrdinal = 0;
			List<Integer> sequence = new ArrayList<>();
			for (PlanElement element : plan.getPlanElements()) {
				if (!(element instanceof Leg leg) || !"taxi".equals(leg.getMode())) {
					continue;
				}
				HongKongTaxiLegAttributes.Metadata metadata =
						HongKongTaxiLegAttributes.readAndValidate(
								leg,
								person.getId(),
								HongKongTaxiScoringParameters.centralV1()
						);
				TaxiKey key = new TaxiKey(person.getId().toString(), taxiOrdinal);
				TaxiRecord record = TaxiRecord.from(key, leg, metadata);
				MainTripIdentity identity = new MainTripIdentity(
						key.personId(), metadata.mainTripIndex());
				if (records.put(key, record) != null
						|| !mainTripIdentities.add(identity)) {
					duplicates++;
				}
				taxiPersons.add(key.personId());
				sequence.add(metadata.mainTripIndex());
				update(digest, record.canonical() + "\n");
				taxiOrdinal++;
			}
			if (!sequence.isEmpty()) {
				sequences.put(person.getId().toString(), List.copyOf(sequence));
			}
		}
		return new TaxiSnapshot(
				records.size(),
				taxiPersons.size(),
				duplicates,
				Map.copyOf(records),
				Map.copyOf(sequences),
				hex(digest.digest())
		);
	}

	public static TaxiInvarianceAudit compareTaxi(
			TaxiSnapshot before,
			TaxiSnapshot after) {
		long missing = 0;
		long extra = 0;
		long attributeChanges = 0;
		long routeChanges = 0;
		long modeChanges = 0;
		for (Map.Entry<TaxiKey, TaxiRecord> entry : before.records().entrySet()) {
			TaxiRecord right = after.records().get(entry.getKey());
			if (right == null) {
				missing++;
				continue;
			}
			TaxiRecord left = entry.getValue();
			attributeChanges += bool(!left.attributesCanonical()
					.equals(right.attributesCanonical()));
			routeChanges += bool(!left.routeCanonical().equals(right.routeCanonical()));
			modeChanges += bool(!left.modeCanonical().equals(right.modeCanonical()));
		}
		for (TaxiKey key : after.records().keySet()) {
			if (!before.records().containsKey(key)) {
				extra++;
			}
		}
		long sequenceChanges = changedEntries(before.sequences(), after.sequences());
		Map<MainTripIdentity, Integer> beforeOrdinals = ordinalMap(before);
		Map<MainTripIdentity, Integer> afterOrdinals = ordinalMap(after);
		long ordinalChanges = 0;
		for (Map.Entry<MainTripIdentity, Integer> entry : beforeOrdinals.entrySet()) {
			Integer right = afterOrdinals.get(entry.getKey());
			if (right != null && !entry.getValue().equals(right)) {
				ordinalChanges++;
			}
		}
		long duplicate = before.duplicateKeys() + after.duplicateKeys();
		boolean exact = before.taxiLegs() == after.taxiLegs()
				&& missing == 0
				&& extra == 0
				&& duplicate == 0
				&& attributeChanges == 0
				&& routeChanges == 0
				&& modeChanges == 0
				&& ordinalChanges == 0
				&& sequenceChanges == 0
				&& before.fingerprintSha256().equals(after.fingerprintSha256());
		return new TaxiInvarianceAudit(
				before.taxiLegs(),
				after.taxiLegs(),
				missing,
				extra,
				duplicate,
				ordinalChanges,
				attributeChanges,
				routeChanges,
				modeChanges,
				sequenceChanges,
				before.fingerprintSha256(),
				after.fingerprintSha256(),
				exact
		);
	}

	public static void requireFormalTaxiInvariant(TaxiInvarianceAudit audit) {
		if (audit.beforeTaxiLegs() != EXPECTED_TAXI_LEGS
				|| audit.afterTaxiLegs() != EXPECTED_TAXI_LEGS
				|| !audit.exact()) {
			throw new IllegalStateException(
					"Taxi fingerprint invariance failed: " + audit.toMap());
		}
	}

	private static Map<MainTripIdentity, Integer> ordinalMap(TaxiSnapshot snapshot) {
		Map<MainTripIdentity, Integer> result = new LinkedHashMap<>();
		snapshot.records().values().forEach(record -> result.put(
				new MainTripIdentity(record.key().personId(), record.mainTripIndex()),
				record.key().ordinal()
		));
		return result;
	}

	private static Map<LegLocation, RouteFingerprint> captureNonPtRoutes(
			Population population) {
		Map<LegLocation, RouteFingerprint> result = new LinkedHashMap<>();
		for (Person person : population.getPersons().values()) {
			int planIndex = 0;
			for (Plan plan : person.getPlans()) {
				List<PlanElement> elements = plan.getPlanElements();
				for (int elementIndex = 0; elementIndex < elements.size(); elementIndex++) {
					PlanElement element = elements.get(elementIndex);
					if (element instanceof Leg leg && !"pt".equals(leg.getMode())) {
						result.put(
								new LegLocation(
										person.getId().toString(), planIndex, elementIndex),
								RouteFingerprint.from(leg)
						);
					}
				}
				planIndex++;
			}
		}
		return result;
	}

	private static long countNullPtRoutes(Population population) {
		long count = 0;
		for (Person person : population.getPersons().values()) {
			for (Plan plan : person.getPlans()) {
				for (PlanElement element : plan.getPlanElements()) {
					if (element instanceof Leg leg
							&& "pt".equals(leg.getMode())
							&& leg.getRoute() == null) {
						count++;
					}
				}
			}
		}
		return count;
	}

	private static Plan requireSelectedPlan(Person person) {
		Plan plan = person.getSelectedPlan();
		if (plan == null) {
			throw new IllegalStateException(
					"Missing selected plan for person " + person.getId());
		}
		return plan;
	}

	private static long changedEntries(Map<?, ?> before, Map<?, ?> after) {
		Set<Object> keys = new LinkedHashSet<>();
		keys.addAll(before.keySet());
		keys.addAll(after.keySet());
		return keys.stream().filter(key ->
				!Objects.equals(before.get(key), after.get(key))).count();
	}

	private static void requireChecks(String label, Map<String, Boolean> checks) {
		List<String> failed = checks.entrySet().stream()
				.filter(entry -> !entry.getValue())
				.map(Map.Entry::getKey)
				.toList();
		if (!failed.isEmpty()) {
			throw new IllegalStateException(label + " failed: " + failed);
		}
	}

	private static String routeFingerprint(Route route) {
		if (route == null) {
			return "<null>";
		}
		return route.getClass().getName()
				+ "|" + route.getStartLinkId()
				+ "|" + route.getEndLinkId()
				+ "|" + Double.toHexString(route.getDistance())
				+ "|" + optional(route.getTravelTime())
				+ "|" + String.valueOf(route.getRouteDescription());
	}

	private static String optional(OptionalTime time) {
		return time.isDefined()
				? Double.toHexString(time.seconds()) : "<undefined>";
	}

	private static String id(Object value) {
		return value == null ? null : value.toString();
	}

	private static long bool(boolean value) {
		return value ? 1L : 0L;
	}

	private static MessageDigest sha256() {
		try {
			return MessageDigest.getInstance("SHA-256");
		} catch (NoSuchAlgorithmException error) {
			throw new IllegalStateException(error);
		}
	}

	private static void update(MessageDigest digest, String text) {
		digest.update(text.getBytes(StandardCharsets.UTF_8));
	}

	private static String hex(byte[] bytes) {
		StringBuilder result = new StringBuilder(bytes.length * 2);
		for (byte value : bytes) {
			result.append(String.format(Locale.ROOT, "%02x", value));
		}
		return result.toString();
	}

	private record ChainAudit(
			long accessMissing,
			long egressMissing,
			long lineMissing,
			long routeMissing,
			long accessUnknown,
			long egressUnknown,
			long lineUnknown,
			long routeUnknown,
			int components) {

		static ChainAudit empty() {
			return new ChainAudit(0, 0, 0, 0, 0, 0, 0, 0, 0);
		}

		boolean exact() {
			return accessMissing == 0
					&& egressMissing == 0
					&& lineMissing == 0
					&& routeMissing == 0
					&& accessUnknown == 0
					&& egressUnknown == 0
					&& lineUnknown == 0
					&& routeUnknown == 0;
		}
	}

	public record PreparationAudit(
			long personsScanned,
			long plansScanned,
			long totalPtLegs,
			long ptRoutesNullBefore,
			long ptRoutesNonNullBefore,
			long genericPtRoutesBefore,
			long legalTransitPassengerRoutesBefore,
			long ptRoutesCleared,
			long ptRoutesNullAfterClear,
			long nonPtRoutesChanged) {

		public Map<String, Object> toMap() {
			return ordered(
					"persons_scanned", personsScanned,
					"plans_scanned", plansScanned,
					"total_pt_legs", totalPtLegs,
					"pt_routes_null_before", ptRoutesNullBefore,
					"pt_routes_non_null_before", ptRoutesNonNullBefore,
					"generic_pt_routes_before", genericPtRoutesBefore,
					"legal_transit_passenger_routes_before",
							legalTransitPassengerRoutesBefore,
					"pt_routes_cleared", ptRoutesCleared,
					"pt_routes_null_after_clear", ptRoutesNullAfterClear,
					"non_pt_routes_changed", nonPtRoutesChanged
			);
		}
	}

	public record PtRuntimeAudit(
			long totalPtLegs,
			long routeNull,
			long genericRouteImpl,
			long transitPassengerRoute,
			long defaultTransitPassengerRoute,
			long otherLegalTransitPassengerRoute,
			long accessStopMissing,
			long egressStopMissing,
			long lineIdMissing,
			long transitRouteIdMissing,
			long accessStopNotInSchedule,
			long egressStopNotInSchedule,
			long lineNotInSchedule,
			long routeNotInSchedule,
			Map<String, Long> runtimeClassCounts,
			List<Map<String, Object>> invalidExamples,
			String fingerprintSha256) {

		public Map<String, Object> toMap() {
			return ordered(
					"total_pt_legs", totalPtLegs,
					"route_null", routeNull,
					"generic_route_impl", genericRouteImpl,
					"transit_passenger_route", transitPassengerRoute,
					"default_transit_passenger_route", defaultTransitPassengerRoute,
					"other_legal_transit_passenger_route",
							otherLegalTransitPassengerRoute,
					"access_stop_missing", accessStopMissing,
					"egress_stop_missing", egressStopMissing,
					"line_id_missing", lineIdMissing,
					"transit_route_id_missing", transitRouteIdMissing,
					"access_stop_not_in_schedule", accessStopNotInSchedule,
					"egress_stop_not_in_schedule", egressStopNotInSchedule,
					"line_not_in_schedule", lineNotInSchedule,
					"route_not_in_schedule", routeNotInSchedule,
					"runtime_class_counts", runtimeClassCounts,
					"invalid_examples", invalidExamples,
					"fingerprint_sha256", fingerprintSha256
			);
		}
	}

	public record TaxiKey(String personId, int ordinal) {
	}

	record MainTripIdentity(String personId, int mainTripIndex) {
	}

	public record TaxiRecord(
			TaxiKey key,
			int mainTripIndex,
			String mode,
			String routingMode,
			double fareHkd,
			String fareRuntimeType,
			String taxiType,
			String taxiTypeRuntimeType,
			String fareScope,
			String fareScopeRuntimeType,
			String fareModelVersion,
			String fareModelVersionRuntimeType,
			String classificationSource,
			String classificationRuntimeType,
			String mainTripRuntimeType,
			String routeClass,
			String routeStartLink,
			String routeEndLink,
			String routeDistance,
			String routeTravelTime,
			String routeDescription) {

		static TaxiRecord from(
				TaxiKey key,
				Leg leg,
				HongKongTaxiLegAttributes.Metadata metadata) {
			Map<String, Object> attributes = leg.getAttributes().getAsMap();
			Route route = leg.getRoute();
			return new TaxiRecord(
					key,
					metadata.mainTripIndex(),
					leg.getMode(),
					String.valueOf(leg.getRoutingMode()),
					metadata.fareBaselineHkd(),
					type(attributes.get(HongKongTaxiLegAttributes.FARE_BASELINE_HKD)),
					metadata.taxiType(),
					type(attributes.get(HongKongTaxiLegAttributes.TAXI_TYPE)),
					metadata.fareScope(),
					type(attributes.get(HongKongTaxiLegAttributes.FARE_SCOPE)),
					metadata.fareModelVersion(),
					type(attributes.get(HongKongTaxiLegAttributes.FARE_MODEL_VERSION)),
					metadata.classificationSource(),
					type(attributes.get(
							HongKongTaxiLegAttributes.CLASSIFICATION_SOURCE)),
					type(attributes.get(HongKongTaxiLegAttributes.MAIN_TRIP_INDEX)),
					route == null ? "<null>" : route.getClass().getName(),
					route == null ? "<null>" : String.valueOf(route.getStartLinkId()),
					route == null ? "<null>" : String.valueOf(route.getEndLinkId()),
					route == null ? "<null>" : Double.toHexString(route.getDistance()),
					route == null ? "<null>" : optional(route.getTravelTime()),
					route == null ? "<null>"
							: String.valueOf(route.getRouteDescription())
			);
		}

		String attributesCanonical() {
			return mainTripIndex + "|" + Double.toHexString(fareHkd)
					+ "|" + fareRuntimeType + "|" + taxiType
					+ "|" + taxiTypeRuntimeType + "|" + fareScope
					+ "|" + fareScopeRuntimeType + "|" + fareModelVersion
					+ "|" + fareModelVersionRuntimeType + "|"
					+ classificationSource + "|" + classificationRuntimeType
					+ "|" + mainTripRuntimeType;
		}

		String routeCanonical() {
			return routeClass + "|" + routeStartLink + "|" + routeEndLink
					+ "|" + routeDistance + "|" + routeTravelTime
					+ "|" + routeDescription;
		}

		String modeCanonical() {
			return mode + "|" + routingMode;
		}

		String canonical() {
			return key.personId() + "|" + key.ordinal() + "|"
					+ attributesCanonical() + "|" + modeCanonical()
					+ "|" + routeCanonical();
		}

		private static String type(Object value) {
			return value == null ? "<missing>" : value.getClass().getName();
		}
	}

	public record TaxiSnapshot(
			long taxiLegs,
			long taxiPersons,
			long duplicateKeys,
			Map<TaxiKey, TaxiRecord> records,
			Map<String, List<Integer>> sequences,
			String fingerprintSha256) {

		public Map<String, Object> toMap() {
			return ordered(
					"taxi_legs", taxiLegs,
					"taxi_persons", taxiPersons,
					"duplicate_keys", duplicateKeys,
					"fingerprint_sha256", fingerprintSha256
			);
		}
	}

	public record TaxiInvarianceAudit(
			long beforeTaxiLegs,
			long afterTaxiLegs,
			long missing,
			long extra,
			long duplicate,
			long ordinalChanges,
			long attributeChanges,
			long routeChanges,
			long modeOrRoutingModeChanges,
			long selectedPlanSequenceChanges,
			String beforeFingerprintSha256,
			String afterFingerprintSha256,
			boolean exact) {

		public Map<String, Object> toMap() {
			return ordered(
					"taxi_legs_before", beforeTaxiLegs,
					"taxi_legs_after", afterTaxiLegs,
					"missing", missing,
					"extra", extra,
					"duplicate", duplicate,
					"taxi_ordinal_changes", ordinalChanges,
					"taxi_attribute_changes", attributeChanges,
					"taxi_route_changes", routeChanges,
					"taxi_mode_or_routing_mode_changes", modeOrRoutingModeChanges,
					"selected_plan_taxi_sequence_changes",
							selectedPlanSequenceChanges,
					"fingerprint_before_sha256", beforeFingerprintSha256,
					"fingerprint_after_sha256", afterFingerprintSha256,
					"exact", exact
			);
		}
	}

	record LegLocation(String personId, int planIndex, int elementIndex) {
	}

	record RouteFingerprint(
			String mode,
			String routingMode,
			String route) {

		static RouteFingerprint from(Leg leg) {
			return new RouteFingerprint(
					leg.getMode(),
					String.valueOf(leg.getRoutingMode()),
					routeFingerprint(leg.getRoute())
			);
		}
	}
}
