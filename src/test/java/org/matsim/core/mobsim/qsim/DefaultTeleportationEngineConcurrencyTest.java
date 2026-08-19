package org.matsim.core.mobsim.qsim;

import org.junit.jupiter.api.Test;
import org.matsim.api.core.v01.Coord;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.network.Link;
import org.matsim.api.core.v01.network.Network;
import org.matsim.api.core.v01.network.NetworkFactory;
import org.matsim.api.core.v01.network.Node;
import org.matsim.api.core.v01.population.Person;
import org.matsim.core.api.experimental.events.EventsManager;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.events.EventsUtils;
import org.matsim.core.mobsim.framework.MobsimAgent;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.core.utils.misc.OptionalTime;

import java.lang.reflect.Field;
import java.lang.reflect.Proxy;
import java.util.Queue;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

class DefaultTeleportationEngineConcurrencyTest {

	@Test
	void concurrentDeparturesPreserveEveryQueueEntry() throws Exception {
		Scenario scenario = ScenarioUtils.createScenario(ConfigUtils.createConfig());
		Id<Link> departureLinkId = Id.createLinkId("departure");
		Id<Link> destinationLinkId = Id.createLinkId("destination");
		addLinks(scenario.getNetwork(), departureLinkId, destinationLinkId);
		EventsManager events = EventsUtils.createEventsManager();
		DefaultTeleportationEngine engine =
				new DefaultTeleportationEngine(scenario, events, false, true);

		int threadCount = 16;
		int departuresPerThread = 1_000;
		ExecutorService executor = Executors.newFixedThreadPool(threadCount);
		for (int thread = 0; thread < threadCount; thread++) {
			int threadIndex = thread;
			executor.submit(() -> {
				for (int sequence = 0; sequence < departuresPerThread; sequence++) {
					String agentId = "agent_" + threadIndex + "_" + sequence;
					engine.handleDeparture(
							sequence,
							agent(agentId, destinationLinkId),
							departureLinkId);
				}
			});
		}
		executor.shutdown();
		assertTrue(executor.awaitTermination(30, TimeUnit.SECONDS));

		Field queueField = DefaultTeleportationEngine.class.getDeclaredField("teleportationList");
		queueField.setAccessible(true);
		Queue<?> queue = (Queue<?>) queueField.get(engine);
		assertEquals(threadCount * departuresPerThread, queue.size());
	}

	private static MobsimAgent agent(String id, Id<Link> destinationLinkId) {
		return (MobsimAgent) Proxy.newProxyInstance(
				MobsimAgent.class.getClassLoader(),
				new Class<?>[] {MobsimAgent.class},
				(proxy, method, args) -> switch (method.getName()) {
					case "getId" -> Id.createPersonId(id);
					case "getExpectedTravelTime" -> OptionalTime.defined(60);
					case "getExpectedTravelDistance" -> 1_000.0;
					case "getMode" -> "walk";
					case "getDestinationLinkId" -> destinationLinkId;
					case "toString" -> id;
					case "hashCode" -> id.hashCode();
					case "equals" -> proxy == args[0];
					default -> null;
				});
	}

	private static void addLinks(
			Network network,
			Id<Link> departureLinkId,
			Id<Link> destinationLinkId) {
		NetworkFactory factory = network.getFactory();
		Node node0 = factory.createNode(Id.createNodeId("node0"), new Coord(0, 0));
		Node node1 = factory.createNode(Id.createNodeId("node1"), new Coord(1, 0));
		Node node2 = factory.createNode(Id.createNodeId("node2"), new Coord(2, 0));
		network.addNode(node0);
		network.addNode(node1);
		network.addNode(node2);
		network.addLink(factory.createLink(departureLinkId, node0, node1));
		network.addLink(factory.createLink(destinationLinkId, node1, node2));
	}
}
