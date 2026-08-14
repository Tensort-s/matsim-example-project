package org.matsim.project.hongkong.taxi;

import org.junit.jupiter.api.Test;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.events.PersonScoreEvent;
import org.matsim.api.core.v01.events.handler.PersonScoreEventHandler;
import org.matsim.contrib.dvrp.fleet.DvrpVehicle;
import org.matsim.contrib.dvrp.load.IntegerLoad;
import org.matsim.contrib.dvrp.optimizer.Request;
import org.matsim.contrib.dvrp.passenger.PassengerPickedUpEvent;
import org.matsim.contrib.dvrp.passenger.PassengerRequestSubmittedEvent;
import org.matsim.core.events.EventsUtils;

import java.util.ArrayList;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;

class HongKongTaxiRequestAuditHandlerTest {
	@Test
	void scoresCompletedPickupAsExtraWaitOnly() {
		var events = EventsUtils.createEventsManager();
		List<PersonScoreEvent> scores = capture(events);
		var handler = new HongKongTaxiRequestAuditHandler(events, null, -6.0 / 3600.0);
		handler.reset(0);
		var request = Id.create("r1", Request.class);
		var person = Id.createPersonId("p1");
		handler.handleEvent(submitted(request, person, 100));
		handler.handleEvent(new PassengerPickedUpEvent(
				220, "taxi", request, person, Id.create("hk_taxi_1", DvrpVehicle.class)));
		assertEquals(1, scores.size());
		assertEquals(-0.2, scores.getFirst().getAmount(), 1e-12);
		assertEquals(HongKongTaxiRequestAuditHandler.SCORE_KIND, scores.getFirst().getKind());
	}

	@Test
	void scoresNeverPickedRequestAtTotalWaitSlope() {
		var events = EventsUtils.createEventsManager();
		List<PersonScoreEvent> scores = capture(events);
		var handler = new HongKongTaxiRequestAuditHandler(
				events, null, -6.0 / 3600.0, -6.0 / 3600.0, -12.0 / 3600.0,
				null, null);
		handler.reset(0);
		var request = Id.create("r1", Request.class);
		var person = Id.createPersonId("p1");
		handler.handleEvent(submitted(request, person, 100));
		handler.finalizeScoringAtHorizon(400);
		assertEquals(1, scores.size());
		assertEquals(-1.0, scores.getFirst().getAmount(), 1e-12);
		assertEquals(HongKongTaxiRequestAuditHandler.UNSERVED_SCORE_KIND, scores.getFirst().getKind());
	}

	@Test
	void onboardAtHorizonScoresWaitAtMinusTwelveAndRideAtMinusSix() {
		var events = EventsUtils.createEventsManager();
		List<PersonScoreEvent> scores = capture(events);
		var handler = new HongKongTaxiRequestAuditHandler(
				events, null, -6.0 / 3600.0, -6.0 / 3600.0, -12.0 / 3600.0,
				null, null);
		handler.reset(0);
		var request = Id.create("r1", Request.class);
		var person = Id.createPersonId("p1");
		handler.handleEvent(submitted(request, person, 100));
		handler.handleEvent(new PassengerPickedUpEvent(
				200, "taxi", request, person, Id.create("hk_taxi_1", DvrpVehicle.class)));
		handler.finalizeScoringAtHorizon(400);
		assertEquals(2, scores.size());
		assertEquals(-2.0 / 3.0, scores.stream().mapToDouble(PersonScoreEvent::getAmount).sum(), 1e-12);
		assertEquals(HongKongTaxiRequestAuditHandler.ONBOARD_BASE_SCORE_KIND, scores.getLast().getKind());
	}

	private static PassengerRequestSubmittedEvent submitted(
			Id<Request> request, Id<org.matsim.api.core.v01.population.Person> person, double time) {
		return new PassengerRequestSubmittedEvent(time, "taxi", request, List.of(person),
				Id.createLinkId("l1"), Id.createLinkId("l2"), IntegerLoad.fromValue(1), "1");
	}

	private static List<PersonScoreEvent> capture(org.matsim.core.api.experimental.events.EventsManager events) {
		List<PersonScoreEvent> scores = new ArrayList<>();
		events.addHandler((PersonScoreEventHandler) scores::add);
		return scores;
	}
}
