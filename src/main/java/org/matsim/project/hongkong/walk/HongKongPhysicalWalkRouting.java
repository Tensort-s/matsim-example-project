package org.matsim.project.hongkong.walk;

import com.google.inject.Inject;
import com.google.inject.name.Named;
import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.TransportMode;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.api.core.v01.population.PlanElement;
import org.matsim.core.population.routes.NetworkRoute;
import org.matsim.core.router.RoutingModule;
import org.matsim.core.router.RoutingRequest;

import java.util.List;

/** Recomputes Walk route duration with the same link rule used by QSim. */
public final class HongKongPhysicalWalkRouting implements RoutingModule {

	private final RoutingModule delegate;
	private final Scenario scenario;

	@Inject
	public HongKongPhysicalWalkRouting(
			@Named(HongKongPhysicalWalkModule.DELEGATE_BINDING) RoutingModule delegate,
			Scenario scenario) {
		this.delegate = delegate;
		this.scenario = scenario;
	}

	@Override
	public List<? extends PlanElement> calcRoute(RoutingRequest request) {
		List<? extends PlanElement> elements = delegate.calcRoute(request);
		if (elements == null) return null;
		int physicalLegs = 0;
		for (PlanElement element : elements) {
			if (!(element instanceof Leg leg) || !TransportMode.walk.equals(leg.getMode())) continue;
			if (!(leg.getRoute() instanceof NetworkRoute route)) {
				throw new IllegalStateException("Physical Walk router returned a non-network route.");
			}
			double distance = 0.0;
			double travelTime = 0.0;
			for (var linkId : HongKongPhysicalWalkEngine.traversedLinks(route)) {
				var link = scenario.getNetwork().getLinks().get(linkId);
				if (link == null) {
					throw new IllegalStateException("Physical Walk router returned missing link " + linkId);
				}
				distance += link.getLength();
				travelTime += Math.max(1.0,
						link.getLength() / HongKongPhysicalWalkModule.WALK_SPEED_M_S);
			}
			route.setDistance(distance);
			route.setTravelTime(travelTime);
			leg.setTravelTime(travelTime);
			physicalLegs++;
		}
		if (physicalLegs != 1) {
			throw new IllegalStateException("Physical Walk routing must return exactly one Walk NetworkRoute; got "
					+ physicalLegs);
		}
		return elements;
	}
}
