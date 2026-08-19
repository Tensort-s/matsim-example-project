package org.matsim.project.hongkong.road;

import com.google.inject.Singleton;
import org.matsim.core.mobsim.qsim.AbstractQSimModule;
import org.matsim.core.mobsim.qsim.qnetsimengine.HongKongExplicitStorageQNetworkFactory;
import org.matsim.core.mobsim.qsim.qnetsimengine.QNetworkFactory;

/** Overrides the QNetworkFactory in the per-iteration QSim child injector. */
public final class HongKongExplicitStorageQSimModule extends AbstractQSimModule {
	@Override
	protected void configureQSim() {
		bind(QNetworkFactory.class).to(HongKongExplicitStorageQNetworkFactory.class)
				.in(Singleton.class);
	}
}
