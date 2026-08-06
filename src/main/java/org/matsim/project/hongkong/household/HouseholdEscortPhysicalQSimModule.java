package org.matsim.project.hongkong.household;

import com.google.inject.Singleton;
import org.matsim.core.config.Config;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.mobsim.qsim.AbstractQSimModule;
import org.matsim.core.mobsim.qsim.components.QSimComponentsConfigGroup;
import org.matsim.core.mobsim.qsim.qnetsimengine.QNetsimEngineModule;

import java.util.ArrayList;
import java.util.List;

/** Installs the fixed-binding engine ahead of network and teleportation handlers. */
public final class HouseholdEscortPhysicalQSimModule extends AbstractQSimModule {

	public static final String COMPONENT_NAME = "HouseholdEscortPhysicalEngine";
	private final HouseholdEscortBindingCatalog catalog;

	public HouseholdEscortPhysicalQSimModule(HouseholdEscortBindingCatalog catalog) {
		this.catalog = catalog;
	}

	public static void activateInConfig(Config config) {
		QSimComponentsConfigGroup components = ConfigUtils.addOrGetModule(
				config, QSimComponentsConfigGroup.class);
		List<String> active = new ArrayList<>(components.getActiveComponents());
		active.remove(COMPONENT_NAME);
		int networkIndex = active.indexOf(QNetsimEngineModule.COMPONENT_NAME);
		if (networkIndex < 0) {
			throw new IllegalArgumentException("QSim NetsimEngine component is unavailable");
		}
		active.add(networkIndex, COMPONENT_NAME);
		components.setActiveComponents(active);
	}

	@Override
	protected void configureQSim() {
		bind(HouseholdEscortPhysicalEngine.class).in(Singleton.class);
		addQSimComponentBinding(COMPONENT_NAME).to(HouseholdEscortPhysicalEngine.class);
		addMobsimScopeEventHandlerBinding().to(HouseholdEscortPhysicalEngine.class);
	}
}
