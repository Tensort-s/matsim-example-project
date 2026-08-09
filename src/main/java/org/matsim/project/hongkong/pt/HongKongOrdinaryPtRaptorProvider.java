package org.matsim.project.hongkong.pt;

import ch.sbb.matsim.routing.pt.raptor.OccupancyData;
import ch.sbb.matsim.routing.pt.raptor.RaptorInVehicleCostCalculator;
import ch.sbb.matsim.routing.pt.raptor.RaptorParametersForPerson;
import ch.sbb.matsim.routing.pt.raptor.RaptorRouteSelector;
import ch.sbb.matsim.routing.pt.raptor.RaptorStopFinder;
import ch.sbb.matsim.routing.pt.raptor.RaptorTransferCostCalculator;
import ch.sbb.matsim.routing.pt.raptor.RaptorUtils;
import ch.sbb.matsim.routing.pt.raptor.SwissRailRaptor;
import ch.sbb.matsim.routing.pt.raptor.SwissRailRaptorData;
import com.google.inject.Inject;
import com.google.inject.Provider;
import com.google.inject.Singleton;
import org.matsim.api.core.v01.Scenario;
import org.matsim.core.config.Config;
import org.matsim.pt.transitSchedule.api.MinimalTransferTimes;
import org.matsim.pt.transitSchedule.api.TransitLine;
import org.matsim.pt.transitSchedule.api.TransitRoute;
import org.matsim.pt.transitSchedule.api.TransitSchedule;
import org.matsim.pt.transitSchedule.api.TransitStopFacility;

/**
 * Builds the ordinary-PT Raptor graph without school-bus routes.
 *
 * <p>The full scenario schedule remains untouched and is still used by TransitQSim. This separate
 * routing view prevents an ordinary {@code pt} passenger from boarding a school-bus departure,
 * while selected school-bus candidates retain their explicit transit routes.</p>
 */
@Singleton
public final class HongKongOrdinaryPtRaptorProvider implements Provider<SwissRailRaptor> {

	private final Scenario scenario;
	private final Config config;
	private final RaptorParametersForPerson parametersForPerson;
	private final RaptorRouteSelector routeSelector;
	private final Provider<RaptorStopFinder> stopFinderProvider;
	private final OccupancyData occupancyData;
	private final RaptorInVehicleCostCalculator inVehicleCostCalculator;
	private final RaptorTransferCostCalculator transferCostCalculator;
	private SwissRailRaptorData data;

	@Inject
	public HongKongOrdinaryPtRaptorProvider(
			Scenario scenario,
			Config config,
			RaptorParametersForPerson parametersForPerson,
			RaptorRouteSelector routeSelector,
			Provider<RaptorStopFinder> stopFinderProvider,
			OccupancyData occupancyData,
			RaptorInVehicleCostCalculator inVehicleCostCalculator,
			RaptorTransferCostCalculator transferCostCalculator) {
		this.scenario = scenario;
		this.config = config;
		this.parametersForPerson = parametersForPerson;
		this.routeSelector = routeSelector;
		this.stopFinderProvider = stopFinderProvider;
		this.occupancyData = occupancyData;
		this.inVehicleCostCalculator = inVehicleCostCalculator;
		this.transferCostCalculator = transferCostCalculator;
	}

	@Override
	public synchronized SwissRailRaptor get() {
		if (data == null) {
			TransitSchedule routingSchedule = ordinaryPtRoutingSchedule(
					scenario.getTransitSchedule());
			data = SwissRailRaptorData.create(
					routingSchedule,
					scenario.getTransitVehicles(),
					RaptorUtils.createStaticConfig(config),
					scenario.getNetwork(),
					occupancyData);
		}
		return new SwissRailRaptor(
				data,
				parametersForPerson,
				routeSelector,
				stopFinderProvider.get(),
				inVehicleCostCalculator,
				transferCostCalculator);
	}

	public static TransitSchedule ordinaryPtRoutingSchedule(TransitSchedule fullSchedule) {
		TransitSchedule filtered = fullSchedule.getFactory().createTransitSchedule();
		for (TransitStopFacility facility : fullSchedule.getFacilities().values()) {
			filtered.addStopFacility(facility);
		}

		int retainedRoutes = 0;
		int excludedSchoolBusRoutes = 0;
		for (TransitLine sourceLine : fullSchedule.getTransitLines().values()) {
			TransitLine filteredLine = fullSchedule.getFactory().createTransitLine(sourceLine.getId());
			filteredLine.setName(sourceLine.getName());
			for (TransitRoute route : sourceLine.getRoutes().values()) {
				if ("school_bus".equals(route.getTransportMode())) {
					excludedSchoolBusRoutes++;
				} else {
					filteredLine.addRoute(route);
					retainedRoutes++;
				}
			}
			if (!filteredLine.getRoutes().isEmpty()) {
				filtered.addTransitLine(filteredLine);
			}
		}

		copyMinimalTransferTimes(fullSchedule.getMinimalTransferTimes(),
				filtered.getMinimalTransferTimes());
		System.out.printf(
				"Ordinary-PT Raptor view: retained %,d routes and excluded %,d school-bus routes; "
						+ "the full schedule remains active in QSim.%n",
				retainedRoutes,
				excludedSchoolBusRoutes);
		if (excludedSchoolBusRoutes == 0) {
			throw new IllegalStateException(
					"Physical non-Taxi integration expected school_bus routes, but none were found.");
		}
		return filtered;
	}

	private static void copyMinimalTransferTimes(
			MinimalTransferTimes source,
			MinimalTransferTimes target) {
		MinimalTransferTimes.MinimalTransferTimesIterator iterator = source.iterator();
		while (iterator.hasNext()) {
			iterator.next();
			target.set(iterator.getFromStopId(), iterator.getToStopId(), iterator.getSeconds());
		}
	}
}
