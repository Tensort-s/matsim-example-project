package org.matsim.core.mobsim.qsim.qnetsimengine;

import com.google.inject.Inject;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.network.Link;
import org.matsim.api.core.v01.network.Node;
import org.matsim.contrib.signals.SignalSystemsConfigGroup;
import org.matsim.contrib.signals.data.SignalsData;
import org.matsim.core.api.experimental.events.EventsManager;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.gbl.Gbl;
import org.matsim.core.mobsim.framework.MobsimTimer;
import org.matsim.core.mobsim.qsim.interfaces.AgentCounter;
import org.matsim.core.mobsim.qsim.interfaces.MobsimVehicle;
import org.matsim.core.mobsim.qsim.interfaces.SignalGroupState;
import org.matsim.core.mobsim.qsim.interfaces.SignalizeableItem;
import org.matsim.core.mobsim.qsim.qnetsimengine.QNetsimEngineI.NetsimInternalInterface;
import org.matsim.core.mobsim.qsim.qnetsimengine.linkspeedcalculator.LinkSpeedCalculator;
import org.matsim.core.mobsim.qsim.qnetsimengine.parking.ParkingSearchTimeCalculator;
import org.matsim.core.mobsim.qsim.qnetsimengine.vehicle_handler.VehicleHandler;
import org.matsim.lanes.Lane;
import org.matsim.project.hongkong.road.HongKongExplicitStorageAudit;
import org.matsim.project.hongkong.road.HongKongRoadSupplyRegistry;
import org.matsim.vehicles.Vehicle;
import org.matsim.vis.snapshotwriters.AgentSnapshotInfo;
import org.matsim.vis.snapshotwriters.SnapshotLinkWidthCalculator;

import java.util.Collection;
import java.util.Collections;
import java.util.Set;

/** MATSim-2026 adapter for exact storage and optional QSim-only flow without changing physical links. */
public final class HongKongExplicitStorageQNetworkFactory implements QNetworkFactory {
	private final EventsManager events;
	private final Scenario scenario;
	private final HongKongRoadSupplyRegistry registry;
	private final HongKongExplicitStorageAudit audit;
	@Inject(optional = true) private Set<LinkSpeedCalculator> calculators = Collections.emptySet();
	@Inject(optional = true) private Set<VehicleHandler> vehicleHandlers = Collections.emptySet();
	@Inject(optional = true) private Set<ParkingSearchTimeCalculator> parkingSearchTimeCalculators = Collections.emptySet();
	private NetsimEngineContext context;
	private NetsimInternalInterface netsimEngine;

	@Inject
	public HongKongExplicitStorageQNetworkFactory(
			EventsManager events, Scenario scenario, HongKongRoadSupplyRegistry registry,
			HongKongExplicitStorageAudit audit) {
		this.events = events; this.scenario = scenario; this.registry = registry; this.audit = audit;
	}

	@Override
	public void initializeFactory(AgentCounter counter, MobsimTimer timer, NetsimInternalInterface engine) {
		SnapshotLinkWidthCalculator width = new SnapshotLinkWidthCalculator();
		width.setLinkWidthForVis(scenario.getConfig().qsim().getLinkWidthForVis());
		width.setLaneWidth(scenario.getNetwork().getEffectiveLaneWidth());
		AbstractAgentSnapshotInfoBuilder snapshots = QNetsimEngineWithThreadpool
				.createAgentSnapshotInfoBuilder(scenario, width);
		context = new NetsimEngineContext(events, scenario.getNetwork().getEffectiveCellSize(),
				counter, snapshots, scenario.getConfig().qsim(), timer, width);
		Gbl.assertNotNull(context);
		netsimEngine = engine;
	}

	@Override
	public QLinkI createNetsimLink(Link link, QNodeI toNode) {
		QLinkImpl.Builder builder = new QLinkImpl.Builder(context, netsimEngine);
		DefaultLinkSpeedCalculator speed = new DefaultLinkSpeedCalculator();
		for (LinkSpeedCalculator calculator : calculators) speed.addLinkSpeedCalculator(calculator);
		builder.setLinkSpeedCalculator(speed);
		DefaultVehicleHandler vehicles = new DefaultVehicleHandler();
		for (VehicleHandler handler : vehicleHandlers) vehicles.addVehicleHandler(handler);
		builder.setVehicleHandler(vehicles);
		DefaultParkingSearchTime parking = new DefaultParkingSearchTime();
		for (ParkingSearchTimeCalculator calculator : parkingSearchTimeCalculators) parking.addHandler(calculator);
		builder.setParkingSearchTimeCalculator(parking);
		var override = registry.override(link.getId());
		if (override != null) builder.setLaneFactory(qLink -> explicitLane(qLink, override));
		return builder.build(qsimCapacityLink(link, override), toNode);
	}

	private Link qsimCapacityLink(Link physical,
			HongKongRoadSupplyRegistry.StorageOverride override) {
		if (override == null || !override.flowCapacityOverride()) return physical;
		Link adapted = scenario.getNetwork().getFactory().createLink(
				physical.getId(), physical.getFromNode(), physical.getToNode());
		adapted.setLength(physical.getLength());
		adapted.setFreespeed(physical.getFreespeed());
		adapted.setNumberOfLanes(physical.getNumberOfLanes());
		adapted.setCapacity(override.qsimFlowCapacityVehiclesPerHour());
		adapted.setAllowedModes(physical.getAllowedModes());
		return adapted;
	}

	private QLaneI explicitLane(AbstractQLink qLink, HongKongRoadSupplyRegistry.StorageOverride override) {
		double adapterLanes = override.storageCapacityQsimPcu()
				* scenario.getNetwork().getEffectiveCellSize()
				/ (override.physicalLengthMeters() * scenario.getConfig().qsim().getStorageCapFactor());
		QueueWithBuffer.Builder builder = new QueueWithBuffer.Builder(context);
		builder.setEffectiveNumberOfLanes(adapterLanes);
		QueueWithBuffer delegate = builder.createLane(qLink);
		double expectedFlowPerStep = override.qsimFlowCapacityVehiclesPerHour() / 3600.0
				* scenario.getConfig().qsim().getFlowCapFactor()
				* scenario.getConfig().qsim().getTimeStepSize();
		HongKongExplicitStorageAudit.LinkStats stats = audit.register(
				override.linkId(), override.storageCapacityQsimPcu(), delegate.getStorageCapacity(),
				override.qsimFlowCapacityVehiclesPerHour(), expectedFlowPerStep,
				delegate.getSimulatedFlowCapacityPerTimeStep());
		return new ExplicitStorageLane(delegate, adapterLanes, override.storageCapacityQsimPcu(), stats, context);
	}

	@Override
	public QNodeI createNetsimNode(Node node) {
		QNodeImpl.Builder builder = new QNodeImpl.Builder(
				netsimEngine, context, scenario.getConfig().qsim());
		SignalSystemsConfigGroup signals = ConfigUtils.addOrGetModule(
				scenario.getConfig(), SignalSystemsConfigGroup.class);
		if (signals.isUseSignalSystems()) {
			if (signals.getIntersectionLogic().equals(
					SignalSystemsConfigGroup.IntersectionLogic.CONFLICTING_DIRECTIONS_AND_TURN_RESTRICTIONS)) {
				SignalsData data = (SignalsData) scenario.getScenarioElement(SignalsData.ELEMENT_NAME);
				if (data == null) {
					throw new IllegalStateException(
							"Signals are enabled but the scenario has no SignalsData");
				}
				builder.setTurnAcceptanceLogic(new UnprotectedLeftTurnAcceptanceLogic(
						data.getConflictingDirectionsData(), scenario.getLanes()));
			} else {
				builder.setTurnAcceptanceLogic(new SignalTurnAcceptanceLogic());
			}
		}
		return builder.build(node);
	}

	private static final class ExplicitStorageLane implements QLaneI, SignalizeableItem {
		private final QueueWithBuffer delegate;
		private final double adapterLanes;
		private final double requested;
		private final HongKongExplicitStorageAudit.LinkStats stats;
		private final NetsimEngineContext context;
		private double occupiedPcu;

		private ExplicitStorageLane(QueueWithBuffer delegate, double adapterLanes, double requested,
				HongKongExplicitStorageAudit.LinkStats stats, NetsimEngineContext context) {
			this.delegate = delegate; this.adapterLanes = adapterLanes;
			this.requested = requested; this.stats = stats; this.context = context;
		}

		private void assertExact() {
			double actual = delegate.getStorageCapacity();
			if (Math.abs(actual - requested) > 1e-8 * Math.max(1.0, Math.abs(requested))) {
				throw new IllegalStateException("MATSim changed explicit storage for " + getId()
						+ ": requested=" + requested + ", actual=" + actual);
			}
		}
		private synchronized void vehicleEntered(QVehicle vehicle) {
			occupiedPcu += vehicle.getVehicle().getType().getPcuEquivalents();
			stats.observeOccupancy(occupiedPcu);
		}
		private synchronized void vehicleLeft(QVehicle vehicle) {
			occupiedPcu -= vehicle.getVehicle().getType().getPcuEquivalents();
			if (occupiedPcu < 0.0 && occupiedPcu > -1e-8) occupiedPcu = 0.0;
			if (occupiedPcu < -1e-8) {
				throw new IllegalStateException("Negative explicit-storage occupancy on " + getId()
						+ ": " + occupiedPcu + " PCU");
			}
		}
		private synchronized void cleared() {
			occupiedPcu = 0.0;
		}

		@Override public void addFromWait(QVehicle vehicle) {
			vehicleEntered(vehicle);
			try { delegate.addFromWait(vehicle); }
			catch (RuntimeException error) { vehicleLeft(vehicle); throw error; }
		}
		@Override public boolean isAcceptingFromWait(QVehicle vehicle) { return delegate.isAcceptingFromWait(vehicle); }
		@Override public boolean isActive() { return delegate.isActive(); }
		@Override public double getSimulatedFlowCapacityPerTimeStep() { return delegate.getSimulatedFlowCapacityPerTimeStep(); }
		@Override public void recalcTimeVariantAttributes() { delegate.recalcTimeVariantAttributes(); assertExact(); }
		@Override public QVehicle getVehicle(Id<Vehicle> id) { return delegate.getVehicle(id); }
		@Override public double getStorageCapacity() { return delegate.getStorageCapacity(); }
		@Override public VisData getVisData() { return delegate.getVisData(); }
		@Override public void addTransitSlightlyUpstreamOfStop(QVehicle vehicle) {
			vehicleEntered(vehicle);
			try { delegate.addTransitSlightlyUpstreamOfStop(vehicle); }
			catch (RuntimeException error) { vehicleLeft(vehicle); throw error; }
		}
		@Override public void changeUnscaledFlowCapacityPerSecond(double value) { delegate.changeUnscaledFlowCapacityPerSecond(value); assertExact(); }
		@Override public void changeEffectiveNumberOfLanes(double ignoredPhysicalLanes) { delegate.changeEffectiveNumberOfLanes(adapterLanes); assertExact(); }
		@Override public boolean doSimStep() { return delegate.doSimStep(); }
		@Override public void clearVehicles() { delegate.clearVehicles(); cleared(); }
		@Override public Collection<MobsimVehicle> getAllVehicles() { return delegate.getAllVehicles(); }
		@Override public void addFromUpstream(QVehicle vehicle) {
			vehicleEntered(vehicle);
			try { delegate.addFromUpstream(vehicle); }
			catch (RuntimeException error) { vehicleLeft(vehicle); throw error; }
		}
		@Override public boolean isNotOfferingVehicle() { return delegate.isNotOfferingVehicle(); }
		@Override public QVehicle popFirstVehicle() {
			QVehicle vehicle = delegate.popFirstVehicle();
			if (vehicle != null) vehicleLeft(vehicle);
			return vehicle;
		}
		@Override public QVehicle getFirstVehicle() { return delegate.getFirstVehicle(); }
		@Override public double getLastMovementTimeOfFirstVehicle() { return delegate.getLastMovementTimeOfFirstVehicle(); }
		@Override public boolean isAcceptingFromUpstream() {
			boolean accepting = delegate.isAcceptingFromUpstream();
			if (!accepting) stats.observeBlocked(context.getSimTimer().getTimeOfDay(), context.getSimTimer().getSimTimestepSize());
			return accepting;
		}
		@Override public double getLoadIndicator() { return delegate.getLoadIndicator(); }
		@Override public void initBeforeSimStep() { delegate.initBeforeSimStep(); }
		@Override public Id<Lane> getId() { return delegate.getId(); }
		@Override public void setSignalized(boolean value) { delegate.setSignalized(value); }
		@Override public void setSignalStateAllTurningMoves(SignalGroupState state) { delegate.setSignalStateAllTurningMoves(state); }
		@Override public void setSignalStateForTurningMove(SignalGroupState state, Id<Link> toLinkId) { delegate.setSignalStateForTurningMove(state, toLinkId); }
		@Override public boolean hasGreenForAllToLinks() { return delegate.hasGreenForAllToLinks(); }
		@Override public boolean hasGreenForToLink(Id<Link> toLinkId) { return delegate.hasGreenForToLink(toLinkId); }
	}
}
