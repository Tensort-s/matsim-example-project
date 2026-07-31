package org.matsim.project.hongkong.scoring;

import org.matsim.api.core.v01.population.Person;

import java.util.Set;

/** Creates one person-local scoring component and declares its mode ownership. */
public interface HongKongScoringComponentFactory {

	String componentId();

	Set<String> activeModes();

	HongKongScoringComponent createComponent(Person person);
}
