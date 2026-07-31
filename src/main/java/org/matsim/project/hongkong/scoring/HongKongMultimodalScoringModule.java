package org.matsim.project.hongkong.scoring;

import com.google.inject.multibindings.Multibinder;
import org.matsim.core.controler.AbstractModule;

/**
 * Installs the unique combined scoring factory and an extensible component
 * set. Mode-specific modules contribute components to that set.
 */
public final class HongKongMultimodalScoringModule extends AbstractModule {

	@Override
	public void install() {
		Multibinder.newSetBinder(
				binder(), HongKongScoringComponentFactory.class);
		bindScoringFunctionFactory()
				.to(HongKongMultimodalScoringFunctionFactory.class);
	}
}
