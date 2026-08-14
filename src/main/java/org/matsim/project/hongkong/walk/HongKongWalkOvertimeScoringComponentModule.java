package org.matsim.project.hongkong.walk;

import com.google.inject.Scopes;
import com.google.inject.multibindings.Multibinder;
import org.matsim.core.controler.AbstractModule;
import org.matsim.project.hongkong.scoring.HongKongScoringComponentFactory;

/** Adds the optional cumulative Walk overtime score to the composed scorer. */
public final class HongKongWalkOvertimeScoringComponentModule extends AbstractModule {
	@Override
	public void install() {
		bind(HongKongWalkOvertimeScoringComponentFactory.class).in(Scopes.SINGLETON);
		Multibinder.newSetBinder(binder(), HongKongScoringComponentFactory.class)
				.addBinding().to(HongKongWalkOvertimeScoringComponentFactory.class);
	}
}
