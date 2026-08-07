package org.matsim.project.hongkong.car;

import org.apache.logging.log4j.LogManager;
import org.apache.logging.log4j.Logger;
import org.matsim.core.controler.events.AfterMobsimEvent;
import org.matsim.core.controler.events.BeforeMobsimEvent;
import org.matsim.core.controler.listener.AfterMobsimListener;
import org.matsim.core.controler.listener.BeforeMobsimListener;

import java.util.concurrent.atomic.DoubleAdder;
import java.util.concurrent.atomic.LongAdder;

/** Thread-safe per-iteration counters for the dynamic Car cost consumer. */
public final class HongKongDynamicCarCostRunAudit
		implements BeforeMobsimListener, AfterMobsimListener {

	private static final Logger LOG = LogManager.getLogger(HongKongDynamicCarCostRunAudit.class);

	private LongAdder linkEntries;
	private LongAdder tollEntries;
	private LongAdder parkingEvents;
	private LongAdder parkingFacilityMismatches;
	private LongAdder terminalParkingEvents;
	private DoubleAdder energyHkd;
	private DoubleAdder tollHkd;
	private DoubleAdder parkingHkd;

	public HongKongDynamicCarCostRunAudit() {
		reset();
	}

	@Override
	public synchronized void notifyBeforeMobsim(BeforeMobsimEvent event) {
		reset();
	}

	@Override
	public void notifyAfterMobsim(AfterMobsimEvent event) {
		LOG.info(
				"HK_DYNAMIC_CAR_COST_AUDIT iteration={} linkEntries={} tollEntries={} "
						+ "parkingEvents={} parkingFacilityMismatches={} terminalParkingEvents={} "
						+ "energyHkd={} tollHkd={} parkingHkd={}",
				event.getIteration(), linkEntries.sum(), tollEntries.sum(),
				parkingEvents.sum(), parkingFacilityMismatches.sum(), terminalParkingEvents.sum(),
				energyHkd.sum(), tollHkd.sum(), parkingHkd.sum());
	}

	void link(HongKongDynamicCarCostRules.LinkCost cost) {
		linkEntries.increment();
		energyHkd.add(cost.energyHkd());
		if (cost.tollHkd() > 0.0) {
			tollEntries.increment();
			tollHkd.add(cost.tollHkd());
		}
	}

	void parking(HongKongDynamicCarCostRules.ParkingCost cost, boolean facilityMismatch, boolean terminal) {
		parkingEvents.increment();
		parkingHkd.add(cost.costHkd());
		if (facilityMismatch) parkingFacilityMismatches.increment();
		if (terminal) terminalParkingEvents.increment();
	}

	private synchronized void reset() {
		linkEntries = new LongAdder();
		tollEntries = new LongAdder();
		parkingEvents = new LongAdder();
		parkingFacilityMismatches = new LongAdder();
		terminalParkingEvents = new LongAdder();
		energyHkd = new DoubleAdder();
		tollHkd = new DoubleAdder();
		parkingHkd = new DoubleAdder();
	}
}
