package org.matsim.project.hongkong.car;

import com.google.inject.Scopes;
import com.google.inject.multibindings.Multibinder;
import org.matsim.core.controler.AbstractModule;
import org.matsim.project.hongkong.scoring.HongKongScoringComponentFactory;

import java.nio.file.Path;
import java.util.Objects;

/** Contributes only the Stage 8A Car fuel-or-electricity component. */
public final class HongKongCarEnergyScoringComponentModule
		extends AbstractModule {

	private final Path carCostRoot;

	public HongKongCarEnergyScoringComponentModule() {
		this(HongKongCarEnergyCostCatalog.DEFAULT_CAR_COST_ROOT);
	}

	public HongKongCarEnergyScoringComponentModule(Path carCostRoot) {
		this.carCostRoot = Objects.requireNonNull(
						carCostRoot, "carCostRoot")
				.toAbsolutePath().normalize();
	}

	@Override
	public void install() {
		bind(HongKongCarEnergyCostCatalog.class)
				.toProvider(() ->
						HongKongCarEnergyCostCatalog.load(carCostRoot))
				.in(Scopes.SINGLETON);
		bind(HongKongCarEnergyScoringComponentFactory.class)
				.in(Scopes.SINGLETON);
		Multibinder.newSetBinder(
						binder(), HongKongScoringComponentFactory.class)
				.addBinding()
				.to(HongKongCarEnergyScoringComponentFactory.class);
	}
}
