package org.matsim.project.hongkong.car;

import com.google.inject.Scopes;
import com.google.inject.multibindings.Multibinder;
import org.matsim.core.controler.AbstractModule;
import org.matsim.project.hongkong.scoring.HongKongScoringComponentFactory;
import com.google.inject.name.Names;

import java.nio.file.Path;
import java.util.Objects;

/** Installs dynamic Car scoring and the matching Car routing disutility. */
public final class HongKongDynamicCarCostModule extends AbstractModule {
	static final String CAR_COST_ROOT_BINDING = "hongKongDynamicCarCostRoot";

	private final Path carCostRoot;

	public HongKongDynamicCarCostModule(Path carCostRoot) {
		this.carCostRoot = Objects.requireNonNull(carCostRoot, "carCostRoot")
				.toAbsolutePath().normalize();
	}

	@Override
	public void install() {
		bind(Path.class).annotatedWith(Names.named(CAR_COST_ROOT_BINDING))
				.toInstance(carCostRoot);
		bind(HongKongDynamicCarCostRules.class)
				.toProvider(HongKongDynamicCarCostRulesProvider.class)
				.in(Scopes.SINGLETON);
		bind(HongKongDynamicCarCostRunAudit.class).in(Scopes.SINGLETON);
		bind(HongKongDynamicCarCostScoringComponentFactory.class).in(Scopes.SINGLETON);
		Multibinder.newSetBinder(binder(), HongKongScoringComponentFactory.class)
				.addBinding().to(HongKongDynamicCarCostScoringComponentFactory.class);
		addTravelDisutilityFactoryBinding("car")
				.to(HongKongDynamicCarTravelDisutilityFactory.class)
				.in(Scopes.SINGLETON);
		addControlerListenerBinding().to(HongKongDynamicCarCostRunAudit.class);
	}
}
