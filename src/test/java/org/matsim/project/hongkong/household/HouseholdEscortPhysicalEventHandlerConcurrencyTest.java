package org.matsim.project.hongkong.household;

import org.junit.jupiter.api.Test;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.events.LinkEnterEvent;
import org.matsim.api.core.v01.network.Link;

import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;

import static org.junit.jupiter.api.Assertions.assertNotSame;
import static org.junit.jupiter.api.Assertions.assertTrue;

class HouseholdEscortPhysicalEventHandlerConcurrencyTest {

	@Test
	void qsimStateHolderDoesNotNeedTheEventHandlerMonitor() throws Exception {
		Object qsimStateLock = new Object();
		Object engineStateLock = new Object();
		CountDownLatch eventCallbackEntered = new CountDownLatch(1);
		CountDownLatch qsimStateHeld = new CountDownLatch(1);
		HouseholdEscortPhysicalEventSink sink = new NoopSink() {
			@Override
			public void onLinkEnter(LinkEnterEvent event) {
				synchronized (engineStateLock) {
					// The real engine releases its narrow state lock before QSim callbacks.
				}
				eventCallbackEntered.countDown();
				synchronized (qsimStateLock) {
					// Models arrangeNextAgentState from the parallel event thread.
				}
			}
		};
		HouseholdEscortPhysicalEventHandler handler =
				new HouseholdEscortPhysicalEventHandler(sink);
		assertNotSame(handler, sink);

		ExecutorService executor = Executors.newFixedThreadPool(2, runnable -> {
			Thread thread = new Thread(runnable);
			thread.setDaemon(true);
			return thread;
		});
		Future<?> qsim = executor.submit(() -> {
			synchronized (qsimStateLock) {
				qsimStateHeld.countDown();
				assertTrue(eventCallbackEntered.await(5, TimeUnit.SECONDS));
				synchronized (engineStateLock) {
					// Models handleDeparture mutating the engine while QSim owns its lock.
				}
			}
			return null;
		});
		assertTrue(qsimStateHeld.await(5, TimeUnit.SECONDS));
		Future<?> events = executor.submit(() -> {
			synchronized (handler) {
				handler.handleEvent(new LinkEnterEvent(
						0, Id.createVehicleId("vehicle"), Id.createLinkId("link")));
			}
			return null;
		});

		qsim.get(5, TimeUnit.SECONDS);
		events.get(5, TimeUnit.SECONDS);
		executor.shutdownNow();
	}

	private static class NoopSink implements HouseholdEscortPhysicalEventSink {
		@Override public void onVehicleEntersTraffic(
				org.matsim.api.core.v01.events.VehicleEntersTrafficEvent event) { }
		@Override public void onLinkEnter(LinkEnterEvent event) { }
		@Override public void onPersonArrival(
				org.matsim.api.core.v01.events.PersonArrivalEvent event) { }
		@Override public void onPersonStuck(
				org.matsim.api.core.v01.events.PersonStuckEvent event) { }
		@Override public void reset(int iteration) { }
		@Override public void cleanupAfterMobsim(int iteration) { }
	}
}
