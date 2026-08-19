package org.matsim.project.hongkong.road;

import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.network.Link;
import org.matsim.core.controler.OutputDirectoryHierarchy;
import org.matsim.core.controler.events.AfterMobsimEvent;
import org.matsim.core.controler.listener.AfterMobsimListener;

import jakarta.inject.Inject;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.Map;

/** Per-iteration evidence that requested storage/flow equal QSim, plus bounded congestion observations. */
public final class HongKongExplicitStorageAudit implements AfterMobsimListener {
	public static final class LinkStats {
		private final Id<Link> linkId;
		private final double requested;
		private final double actual;
		private final double requestedFlowCapacityVph;
		private final double expectedFlowCapacityPcuPerStep;
		private final double actualFlowCapacityPcuPerStep;
		private double peakOccupiedPcu;
		private long blockedChecks;
		private double blockedSeconds;
		private double lastBlockedTime = Double.NaN;

		LinkStats(Id<Link> linkId, double requested, double actual,
				double requestedFlowCapacityVph, double expectedFlowCapacityPcuPerStep,
				double actualFlowCapacityPcuPerStep) {
			this.linkId = linkId; this.requested = requested; this.actual = actual;
			this.requestedFlowCapacityVph = requestedFlowCapacityVph;
			this.expectedFlowCapacityPcuPerStep = expectedFlowCapacityPcuPerStep;
			this.actualFlowCapacityPcuPerStep = actualFlowCapacityPcuPerStep;
		}
		public synchronized void observeOccupancy(double pcu) { peakOccupiedPcu = Math.max(peakOccupiedPcu, pcu); }
		public synchronized void observeBlocked(double now, double step) {
			blockedChecks++;
			if (Double.isNaN(lastBlockedTime) || Math.abs(now - lastBlockedTime) > 1e-9) {
				blockedSeconds += step; lastBlockedTime = now;
			}
		}
		public synchronized String csv() {
			return linkId + "," + requested + "," + actual + ","
					+ requestedFlowCapacityVph + "," + expectedFlowCapacityPcuPerStep + ","
					+ actualFlowCapacityPcuPerStep + "," + peakOccupiedPcu
					+ "," + blockedSeconds + "," + blockedChecks;
		}
	}

	private final OutputDirectoryHierarchy output;
	private final HongKongRoadSupplyRegistry registry;
	private final Map<Id<Link>, LinkStats> current = new LinkedHashMap<>();

	@Inject
	public HongKongExplicitStorageAudit(
			OutputDirectoryHierarchy output, HongKongRoadSupplyRegistry registry) {
		this.output = output;
		this.registry = registry;
	}

	public synchronized LinkStats register(Id<Link> linkId, double requested, double actual,
			double requestedFlowCapacityVph, double expectedFlowCapacityPcuPerStep,
			double actualFlowCapacityPcuPerStep) {
		double tolerance = 1e-8 * Math.max(1.0, Math.abs(requested));
		if (Math.abs(requested - actual) > tolerance) {
			throw new IllegalStateException("MATSim silently changed explicit storage for " + linkId
					+ ": requested=" + requested + ", actual=" + actual);
		}
		double flowTolerance = 1e-8 * Math.max(1.0, Math.abs(expectedFlowCapacityPcuPerStep));
		if (Math.abs(expectedFlowCapacityPcuPerStep - actualFlowCapacityPcuPerStep) > flowTolerance) {
			throw new IllegalStateException("MATSim silently changed explicit QSim flow for " + linkId
					+ ": requestedVph=" + requestedFlowCapacityVph
					+ ", expectedPcuPerStep=" + expectedFlowCapacityPcuPerStep
					+ ", actualPcuPerStep=" + actualFlowCapacityPcuPerStep);
		}
		LinkStats stats = new LinkStats(linkId, requested, actual, requestedFlowCapacityVph,
				expectedFlowCapacityPcuPerStep, actualFlowCapacityPcuPerStep);
		current.put(linkId, stats);
		return stats;
	}

	@Override
	public synchronized void notifyAfterMobsim(AfterMobsimEvent event) {
		if (current.size() != registry.overrides().size()) {
			throw new IllegalStateException("Expected " + registry.overrides().size()
					+ " explicit storage lanes; built " + current.size());
		}
		Path path = Path.of(output.getIterationFilename(
				event.getIteration(), "explicit_storage_capacity_audit.csv"));
		try {
			Files.createDirectories(path.getParent());
			var lines = new ArrayList<String>();
			lines.add("link_id,requested_storage_qsim_pcu,actual_storage_qsim_pcu,"
					+ "requested_flow_capacity_vph,expected_flow_capacity_qsim_pcu_per_step,"
					+ "actual_flow_capacity_qsim_pcu_per_step,peak_occupied_pcu,"
					+ "blocked_inflow_seconds,blocked_inflow_checks");
			current.values().stream().sorted(Comparator.comparing(stats -> stats.linkId.toString()))
					.map(LinkStats::csv).forEach(lines::add);
			Files.write(path, lines, StandardCharsets.UTF_8);
		} catch (IOException error) {
			throw new IllegalStateException("Cannot write explicit-storage audit: " + path, error);
		}
		current.clear();
	}
}
