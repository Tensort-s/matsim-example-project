package org.matsim.project.hongkong.walk;

import org.matsim.api.core.v01.TransportMode;
import org.matsim.api.core.v01.population.Person;
import org.matsim.project.hongkong.scoring.HongKongScoringComponent;
import org.matsim.project.hongkong.scoring.HongKongScoringComponentFactory;

import java.util.Set;

public final class HongKongWalkOvertimeScoringComponentFactory
		implements HongKongScoringComponentFactory {
	public static final String COMPONENT_ID = "walk_overtime_per_main_trip_v1";

	@Override public String componentId() { return COMPONENT_ID; }
	@Override public Set<String> activeModes() {
		return Set.of(TransportMode.walk, TransportMode.non_network_walk);
	}
	@Override public HongKongScoringComponent createComponent(Person person) {
		return new HongKongWalkOvertimeScoring();
	}
}
