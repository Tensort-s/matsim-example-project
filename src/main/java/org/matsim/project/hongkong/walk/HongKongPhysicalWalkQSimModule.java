package org.matsim.project.hongkong.walk;

import com.google.inject.Singleton;
import org.matsim.core.config.Config;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.mobsim.qsim.AbstractQSimModule;
import org.matsim.core.mobsim.qsim.components.QSimComponentsConfigGroup;
import org.matsim.core.mobsim.qsim.qnetsimengine.QNetsimEngineModule;

import java.util.ArrayList;
import java.util.List;

/** Installs capacity-free physical Walk before the road and teleport engines. */
public final class HongKongPhysicalWalkQSimModule extends AbstractQSimModule {

	public static final String COMPONENT_NAME = "HongKongPhysicalWalkEngine";

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
		bind(HongKongPhysicalWalkEngine.class).in(Singleton.class);
		addQSimComponentBinding(COMPONENT_NAME).to(HongKongPhysicalWalkEngine.class);
	}
}
