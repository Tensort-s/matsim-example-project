package org.matsim.project.hongkong.schoolbus;

import com.google.inject.Singleton;
import com.google.inject.multibindings.OptionalBinder;
import org.matsim.core.config.Config;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.mobsim.qsim.AbstractQSimModule;
import org.matsim.core.mobsim.qsim.components.QSimComponentsConfigGroup;
import org.matsim.core.mobsim.qsim.qnetsimengine.QNetsimEngineModule;
import org.matsim.core.mobsim.qsim.pt.TransitDriverAgentFactory;

import java.util.ArrayList;
import java.util.List;

/** Installs the guarded physical PT passenger handler before teleportation. */
public final class SchoolBusPassengerPhysicalQSimModule extends AbstractQSimModule {

	public static final String COMPONENT_NAME = "SchoolBusPassengerPhysicalEngine";

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
		OptionalBinder.newOptionalBinder(binder(), TransitDriverAgentFactory.class)
				.setBinding().to(SchoolBusAwareTransitDriverAgentFactory.class);
		bind(SchoolBusPassengerPhysicalEngine.class).in(Singleton.class);
		addQSimComponentBinding(COMPONENT_NAME).to(SchoolBusPassengerPhysicalEngine.class);
	}
}
