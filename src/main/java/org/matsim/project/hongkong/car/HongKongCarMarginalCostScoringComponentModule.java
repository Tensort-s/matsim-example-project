package org.matsim.project.hongkong.car;

import com.google.inject.Scopes;
import com.google.inject.multibindings.Multibinder;
import org.matsim.core.controler.AbstractModule;
import org.matsim.project.hongkong.scoring.HongKongScoringComponentFactory;

import java.nio.file.Path;
import java.util.Objects;

/** Contributes one Car owner with energy, toll, and destination parking. */
public final class HongKongCarMarginalCostScoringComponentModule
		extends AbstractModule {

	private final Path carCostRoot;

	public HongKongCarMarginalCostScoringComponentModule() {
		this(HongKongCarEnergyCostCatalog.DEFAULT_CAR_COST_ROOT);
	}

	public HongKongCarMarginalCostScoringComponentModule(Path carCostRoot) {
		this.carCostRoot = Objects.requireNonNull(
				carCostRoot, "carCostRoot").toAbsolutePath().normalize();
	}

	@Override
	public void install() {
		bind(HongKongCarEnergyCostCatalog.class)
				.toProvider(() -> HongKongCarEnergyCostCatalog.load(carCostRoot))
				.in(Scopes.SINGLETON);
		bind(HongKongCarTollCostCatalog.class)
				.toProvider(() -> HongKongCarTollCostCatalog.load(carCostRoot))
				.in(Scopes.SINGLETON);
		bind(HongKongCarParkingCostCatalog.class)
				.toProvider(() -> HongKongCarParkingCostCatalog.load(carCostRoot))
				.in(Scopes.SINGLETON);
		bind(HongKongCarMarginalCostScoringComponentFactory.class)
				.in(Scopes.SINGLETON);
		Multibinder.newSetBinder(
					binder(), HongKongScoringComponentFactory.class)
				.addBinding()
				.to(HongKongCarMarginalCostScoringComponentFactory.class);
	}
}
