package org.matsim.project.hongkong.walk;

import com.google.inject.multibindings.Multibinder;
import org.matsim.core.controler.AbstractModule;
import org.matsim.project.hongkong.scoring.HongKongScoringComponentFactory;

/** Adds the optional cumulative Walk overtime score to the composed scorer. */
public final class HongKongWalkOvertimeScoringComponentModule extends AbstractModule {
	private final HongKongWalkScoringParameters parameters;

	public HongKongWalkOvertimeScoringComponentModule() {
		this(HongKongWalkScoringParameters.legacyV1());
	}

	public HongKongWalkOvertimeScoringComponentModule(
			HongKongWalkScoringParameters parameters) {
		this.parameters = parameters;
	}

	@Override
	public void install() {
		bind(HongKongWalkOvertimeScoringComponentFactory.class)
				.toInstance(new HongKongWalkOvertimeScoringComponentFactory(parameters));
		Multibinder.newSetBinder(binder(), HongKongScoringComponentFactory.class)
				.addBinding().to(HongKongWalkOvertimeScoringComponentFactory.class);
	}
}
