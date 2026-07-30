package org.matsim.project.hongkong.taxi;

import org.junit.jupiter.api.Test;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.events.PersonArrivalEvent;
import org.matsim.api.core.v01.events.PersonDepartureEvent;
import org.matsim.api.core.v01.events.PersonStuckEvent;
import org.matsim.api.core.v01.network.Link;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.api.core.v01.population.Person;
import org.matsim.core.population.PopulationUtils;
import org.matsim.core.population.routes.GenericRouteImpl;
import org.matsim.pt.routes.DefaultTransitPassengerRoute;
import org.matsim.pt.transitSchedule.api.TransitLine;
import org.matsim.pt.transitSchedule.api.TransitRoute;
import org.matsim.pt.transitSchedule.api.TransitStopFacility;

import java.util.List;
import java.util.Map;
import java.util.Set;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class HongKongTaxiSmokeDependencyAuditTest {

	@Test
	void classifiesLegalTransitPassengerRouteAndGenericRoute() {
		HongKongTaxiSmokeDependencyAudit.SupplyIndex supply =
				new HongKongTaxiSmokeDependencyAudit.SupplyIndex(
						Map.of("access", "a", "egress", "b"),
						Map.of("line", Set.of("route")),
						Set.of("a", "b", "origin", "destination")
				);
		Leg legal = PopulationUtils.createLeg("pt");
		legal.setRoute(new DefaultTransitPassengerRoute(
				Id.createLinkId("origin"),
				Id.createLinkId("destination"),
				Id.create("access", TransitStopFacility.class),
				Id.create("egress", TransitStopFacility.class),
				Id.create("line", TransitLine.class),
				Id.create("route", TransitRoute.class)
		));
		HongKongTaxiSmokeDependencyAudit.RouteAudit legalAudit =
				HongKongTaxiSmokeDependencyAudit.classifyRoute(
						legal, null, null, supply);
		assertTrue(legalAudit.transitPassenger());
		assertTrue(legalAudit.defaultTransitRoute());
		assertFalse(legalAudit.invalid());

		Leg generic = PopulationUtils.createLeg("pt");
		generic.setRoute(new GenericRouteImpl(
				Id.createLinkId("a"),
				Id.createLinkId("b")
		));
		HongKongTaxiSmokeDependencyAudit.RouteAudit genericAudit =
				HongKongTaxiSmokeDependencyAudit.classifyRoute(
						generic, null, null, supply);
		assertTrue(genericAudit.genericRoute());
		assertFalse(genericAudit.transitPassenger());
		assertTrue(genericAudit.invalidReasons()
				.contains("not_transit_passenger_route"));
	}

	@Test
	void sourceAndTaxiPtMatchingRequiresStableActivitySignature() {
		HongKongTaxiSmokeDependencyAudit.PtKey key =
				new HongKongTaxiSmokeDependencyAudit.PtKey("person", 3);
		HongKongTaxiSmokeDependencyAudit.PtRecord source = pt(key, "home->work");
		HongKongTaxiSmokeDependencyAudit.PtRecord same = pt(key, "home->work");
		HongKongTaxiSmokeDependencyAudit.PtComparison match =
				HongKongTaxiSmokeDependencyAudit.comparePtRecords(
						Map.of(key, source),
						Map.of(key, same)
				);
		assertEquals(1, match.matched());
		assertEquals(1, match.completelyIdentical());
		assertEquals(0, match.ambiguous());

		HongKongTaxiSmokeDependencyAudit.PtRecord ambiguous =
				pt(key, "other->work");
		HongKongTaxiSmokeDependencyAudit.PtComparison mismatch =
				HongKongTaxiSmokeDependencyAudit.comparePtRecords(
						Map.of(key, source),
						Map.of(key, ambiguous)
				);
		assertEquals(0, mismatch.matched());
		assertEquals(1, mismatch.ambiguous());
	}

	@Test
	void invalidPtBeforeAndAfterTaxiAreDistinguishedByCategoryInputs() {
		assertEquals(
				"invalid_pt_before_taxi_agent_removed",
				HongKongTaxiSmokeDependencyAudit.categorizeMissing(
						true, false, Set.of(), true, false, true)
		);
		assertEquals(
				"taxi_departure_missing_without_observed_upstream_blocker",
				HongKongTaxiSmokeDependencyAudit.categorizeMissing(
						false, false, Set.of(), false, false, true)
		);
	}

	@Test
	void ptRemovalAndStuckIntersectionHasMutuallyExclusivePriority() {
		assertEquals(
				"multiple_blockers",
				HongKongTaxiSmokeDependencyAudit.categorizeMissing(
						true, true, Set.of("car"), true, false, true)
		);
		assertEquals(
				"car_stuck_before_taxi",
				HongKongTaxiSmokeDependencyAudit.categorizeMissing(
						false, true, Set.of("car"), false, false, true)
		);
		assertEquals(
				"walk_stuck_before_taxi",
				HongKongTaxiSmokeDependencyAudit.categorizeMissing(
						false, true, Set.of("walk"), false, false, true)
		);
		assertEquals(
				"null_mode_stuck_before_taxi",
				HongKongTaxiSmokeDependencyAudit.categorizeMissing(
						false, true, Set.of("<null>"), false, false, true)
		);
	}

	@Test
	void unknownEvidenceIsNotForcedIntoObservedBlockerCategory() {
		assertEquals(
				"unavailable_evidence",
				HongKongTaxiSmokeDependencyAudit.categorizeMissing(
						false, false, Set.of(), false, true, false)
		);
		assertEquals(
				"invalid_pt_before_taxi_without_observed_removal",
				HongKongTaxiSmokeDependencyAudit.categorizeMissing(
						false, false, Set.of(), true, false, true)
		);
	}

	@Test
	void eventCollectorDetectsDuplicateAndUnexpectedTaxiDepartures() {
		Set<String> taxiPersons = Set.of("p");
		HongKongTaxiSmokeDependencyAudit.EventCollector collector =
				new HongKongTaxiSmokeDependencyAudit.EventCollector(taxiPersons);
		Id<Person> person = Id.createPersonId("p");
		Id<Link> link = Id.createLinkId("l");
		collector.handleEvent(new PersonDepartureEvent(100.0, person, link, "taxi", "ride"));
		collector.handleEvent(new PersonDepartureEvent(100.0, person, link, "taxi", "ride"));
		collector.handleEvent(new PersonArrivalEvent(110.0, person, link, "taxi"));
		collector.handleEvent(new PersonStuckEvent(120.0, person, link, "car", null));
		HongKongTaxiSmokeDependencyAudit.EventAudit events =
				collector.finish();
		assertEquals(2, events.taxiDepartureCount());
		assertEquals(1, events.duplicateTaxiDepartures());
		assertEquals(1, events.stuckEvents().size());

		HongKongTaxiSmokeDependencyAudit.TaxiLegRecord expected =
				taxi("p", 0);
		HongKongTaxiSmokeDependencyAudit.TaxiReconciliation reconciliation =
				HongKongTaxiSmokeDependencyAudit.reconcileTaxiEvents(
						Map.of("p", List.of(expected)),
						events
				);
		assertEquals(1, reconciliation.unexpectedDepartures());
		assertEquals(1, reconciliation.unmatchedDepartures());
	}

	@Test
	void reconciliationSchemaClosesExpectedObservedAndMissing() {
		HongKongTaxiSmokeDependencyAudit.EventCollector collector =
				new HongKongTaxiSmokeDependencyAudit.EventCollector(Set.of("p"));
		Id<Person> person = Id.createPersonId("p");
		Id<Link> link = Id.createLinkId("l");
		collector.handleEvent(new PersonDepartureEvent(100.0, person, link, "taxi", "ride"));
		collector.handleEvent(new PersonArrivalEvent(110.0, person, link, "taxi"));
		HongKongTaxiSmokeDependencyAudit.EventAudit events =
				collector.finish();
		HongKongTaxiSmokeDependencyAudit.TaxiReconciliation reconciliation =
				HongKongTaxiSmokeDependencyAudit.reconcileTaxiEvents(
						Map.of("p", List.of(taxi("p", 0), taxi("p", 1))),
						events
				);
		assertEquals(2, reconciliation.expected());
		assertEquals(1, reconciliation.observedDepartures());
		assertEquals(1, reconciliation.missingDepartures());
		assertEquals(
				reconciliation.expected() + reconciliation.unexpectedDepartures(),
				reconciliation.observedDepartures() + reconciliation.missingDepartures()
		);
		Map<String, Object> schema = reconciliation.toMap();
		assertTrue(schema.containsKey("expected_taxi_legs"));
		assertTrue(schema.containsKey("observed_departures"));
		assertTrue(schema.containsKey("missing_departures"));
		assertTrue(schema.containsKey("duplicate_departures"));
		assertTrue(schema.containsKey("unexpected_departures"));
	}

	@Test
	void validationRequiredCheckSchemaIsExplicitAndStable() {
		Set<String> schema = HongKongTaxiSmokeDependencyAudit.requiredCheckSchema();
		assertTrue(schema.contains("pt_mapping_unique_and_closed"));
		assertTrue(schema.contains("observed_taxi_departures_match_validation"));
		assertTrue(schema.contains("stuck_events_match_validation"));
		assertTrue(schema.contains("attribution_categories_close"));
		assertTrue(schema.contains("fare_schedule_mismatch_absent"));
		assertEquals(26, schema.size());
	}

	private static HongKongTaxiSmokeDependencyAudit.PtRecord pt(
			HongKongTaxiSmokeDependencyAudit.PtKey key,
			String activitySignature) {
		return new HongKongTaxiSmokeDependencyAudit.PtRecord(
				key,
				"pt",
				"pt",
				activitySignature,
				GenericRouteImpl.class.getName(),
				false,
				"a|b|description",
				"",
				true
		);
	}

	private static HongKongTaxiSmokeDependencyAudit.TaxiLegRecord taxi(
			String person,
			int ordinal) {
		return new HongKongTaxiSmokeDependencyAudit.TaxiLegRecord(
				new HongKongTaxiSmokeDependencyAudit.TaxiKey(person, ordinal),
				ordinal,
				ordinal * 2 + 1,
				100.0 + ordinal,
				"",
				24.0,
				"urban_taxi",
				"test"
		);
	}
}
