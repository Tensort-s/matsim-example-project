package org.matsim.project.hongkong.pt;

import com.google.inject.Scopes;
import com.google.inject.multibindings.Multibinder;
import org.matsim.core.controler.AbstractModule;
import org.matsim.project.hongkong.scoring.HongKongScoringComponentFactory;

import java.nio.file.Path;
import java.util.Objects;

/** Contributes only the canonical five-layer PT fare scoring component. */
public final class HongKongPtFareScoringComponentModule
		extends AbstractModule {

	private final Path releaseRoot;

	public HongKongPtFareScoringComponentModule() {
		this(HongKongPtFareRuntimeCatalog.DEFAULT_RELEASE_ROOT);
	}

	public HongKongPtFareScoringComponentModule(Path releaseRoot) {
		this.releaseRoot = Objects.requireNonNull(
						releaseRoot, "releaseRoot")
				.toAbsolutePath().normalize();
	}

	@Override
	public void install() {
		bind(HongKongPtFareRuntimeCatalog.class)
				.toProvider(() ->
						HongKongPtFareRuntimeCatalog.load(releaseRoot))
				.in(Scopes.SINGLETON);
		bind(HongKongPtFareScoringComponentFactory.class)
				.in(Scopes.SINGLETON);
		Multibinder.newSetBinder(
						binder(), HongKongScoringComponentFactory.class)
				.addBinding()
				.to(HongKongPtFareScoringComponentFactory.class);
	}
}
