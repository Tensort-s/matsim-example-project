package org.matsim.project.hongkong.scoring;

import org.junit.jupiter.api.Test;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.population.Person;
import org.matsim.core.population.PopulationUtils;
import org.matsim.core.scoring.ScoringFunctionFactory;

import java.util.List;
import java.util.Set;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertInstanceOf;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class HongKongMultimodalScoringFunctionFactoryTest {

	@Test
	void componentOrderAndModeOwnershipAreDeterministic() {
		HongKongMultimodalScoringFunctionFactory factory =
				new HongKongMultimodalScoringFunctionFactory(
						zeroDelegate(),
						List.of(
								new StubFactory("z_component", Set.of("z_mode")),
								new StubFactory("a_component", Set.of("a_mode"))));

		assertEquals(
				List.of("a_component", "z_component"),
				factory.componentIds());
		assertEquals("a_component", factory.activeModeOwners().get("a_mode"));
		assertEquals("z_component", factory.activeModeOwners().get("z_mode"));
		HongKongComposableScoringFunction scoring = assertInstanceOf(
				HongKongComposableScoringFunction.class,
				factory.createNewScoringFunction(person()));
		assertEquals(
				List.of("a_component", "z_component"),
				scoring.componentIds());
	}

	@Test
	void duplicateComponentIdsFailClosed() {
		IllegalArgumentException error = assertThrows(
				IllegalArgumentException.class,
				() -> new HongKongMultimodalScoringFunctionFactory(
						zeroDelegate(),
						List.of(
								new StubFactory("duplicate", Set.of("taxi")),
								new StubFactory("duplicate", Set.of("pt")))));
		assertTrue(error.getMessage().contains("Duplicate"));
		assertTrue(error.getMessage().contains("component factory id"));
	}

	@Test
	void duplicateModeOwnershipFailsClosed() {
		IllegalArgumentException error = assertThrows(
				IllegalArgumentException.class,
				() -> new HongKongMultimodalScoringFunctionFactory(
						zeroDelegate(),
						List.of(
								new StubFactory("taxi_a", Set.of("taxi")),
								new StubFactory("taxi_b", Set.of("taxi")))));
		assertTrue(error.getMessage().contains("Duplicate"));
		assertTrue(error.getMessage().contains("mode=taxi"));
	}

	@Test
	void factoryAndComponentIdentityMismatchFailsClosed() {
		HongKongScoringComponentFactory mismatched =
				new StubFactory("declared", Set.of("taxi")) {
					@Override
					public HongKongScoringComponent createComponent(Person person) {
						return new StubComponent("actual");
					}
				};
		HongKongMultimodalScoringFunctionFactory factory =
				new HongKongMultimodalScoringFunctionFactory(
						zeroDelegate(), List.of(mismatched));

		IllegalStateException error = assertThrows(
				IllegalStateException.class,
				() -> factory.createNewScoringFunction(person()));
		assertTrue(error.getMessage().contains("id mismatch"));
	}

	private static ScoringFunctionFactory zeroDelegate() {
		return person -> new StubComponent("standard_delegate");
	}

	private static Person person() {
		return PopulationUtils.getFactory().createPerson(
				Id.createPersonId("composition-test"));
	}

	private static class StubFactory
			implements HongKongScoringComponentFactory {

		private final String componentId;
		private final Set<String> activeModes;

		private StubFactory(String componentId, Set<String> activeModes) {
			this.componentId = componentId;
			this.activeModes = activeModes;
		}

		@Override
		public String componentId() {
			return componentId;
		}

		@Override
		public Set<String> activeModes() {
			return activeModes;
		}

		@Override
		public HongKongScoringComponent createComponent(Person person) {
			return new StubComponent(componentId);
		}
	}

	private record StubComponent(String componentId)
			implements HongKongScoringComponent {

		@Override
		public double getScore() {
			return 0.0;
		}
	}
}
