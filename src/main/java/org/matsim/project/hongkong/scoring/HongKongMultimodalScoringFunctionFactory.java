package org.matsim.project.hongkong.scoring;

import com.google.inject.Inject;
import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.population.Person;
import org.matsim.core.scoring.ScoringFunction;
import org.matsim.core.scoring.ScoringFunctionFactory;
import org.matsim.core.scoring.functions.CharyparNagelScoringFunctionFactory;

import java.util.Collection;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;

/**
 * Canonical Hong Kong scoring composition: one standard MATSim delegate plus
 * uniquely identified, uniquely mode-owning components.
 */
public final class HongKongMultimodalScoringFunctionFactory
		implements ScoringFunctionFactory {

	private final ScoringFunctionFactory delegateFactory;
	private final List<HongKongScoringComponentFactory> componentFactories;
	private final Map<String, String> activeModeOwners;

	@Inject
	public HongKongMultimodalScoringFunctionFactory(
			Scenario scenario,
			Set<HongKongScoringComponentFactory> componentFactories) {
		this(
				new CharyparNagelScoringFunctionFactory(
						Objects.requireNonNull(scenario, "scenario")),
				componentFactories
		);
	}

	public HongKongMultimodalScoringFunctionFactory(
			ScoringFunctionFactory delegateFactory,
			Collection<HongKongScoringComponentFactory> componentFactories) {
		this.delegateFactory = Objects.requireNonNull(delegateFactory, "delegateFactory");
		this.componentFactories = Objects.requireNonNull(
						componentFactories, "componentFactories")
				.stream()
				.map(factory -> Objects.requireNonNull(factory, "componentFactory"))
				.sorted((left, right) -> left.componentId().compareTo(right.componentId()))
				.toList();

		Map<String, HongKongScoringComponentFactory> ids = new LinkedHashMap<>();
		Map<String, String> modeOwners = new LinkedHashMap<>();
		for (HongKongScoringComponentFactory factory : this.componentFactories) {
			String componentId = requireIdentifier(factory.componentId(), "componentId");
			if (ids.putIfAbsent(componentId, factory) != null) {
				throw new IllegalArgumentException(
						"Duplicate Hong Kong scoring component factory id: " + componentId);
			}
			Set<String> activeModes = Set.copyOf(
					Objects.requireNonNull(factory.activeModes(), "activeModes"));
			for (String mode : activeModes.stream().sorted().toList()) {
				String normalizedMode = requireIdentifier(mode, "activeMode");
				String previous = modeOwners.putIfAbsent(normalizedMode, componentId);
				if (previous != null) {
					throw new IllegalArgumentException(
							"Duplicate Hong Kong scoring mode ownership: mode="
									+ normalizedMode + ", first_component=" + previous
									+ ", second_component=" + componentId);
				}
			}
		}
		this.activeModeOwners = Collections.unmodifiableMap(
				new LinkedHashMap<>(modeOwners));
	}

	@Override
	public ScoringFunction createNewScoringFunction(Person person) {
		Objects.requireNonNull(person, "person");
		List<HongKongScoringComponent> components = componentFactories.stream()
				.map(factory -> {
					HongKongScoringComponent component = Objects.requireNonNull(
							factory.createComponent(person),
							"component returned by " + factory.componentId());
					if (!factory.componentId().equals(component.componentId())) {
						throw new IllegalStateException(
								"Hong Kong scoring component id mismatch: factory="
										+ factory.componentId() + ", component="
										+ component.componentId());
					}
					return component;
				})
				.toList();
		return new HongKongComposableScoringFunction(
				delegateFactory.createNewScoringFunction(person),
				components);
	}

	public List<String> componentIds() {
		return componentFactories.stream()
				.map(HongKongScoringComponentFactory::componentId)
				.toList();
	}

	public Map<String, String> activeModeOwners() {
		return activeModeOwners;
	}

	private static String requireIdentifier(String value, String name) {
		if (Objects.requireNonNull(value, name).isBlank()) {
			throw new IllegalArgumentException(name + " must not be blank.");
		}
		return value;
	}
}
