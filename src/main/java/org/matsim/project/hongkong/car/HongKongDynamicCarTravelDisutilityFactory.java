package org.matsim.project.hongkong.car;

import com.google.inject.Inject;
import org.matsim.api.core.v01.TransportMode;
import org.matsim.core.config.Config;
import org.matsim.core.router.costcalculators.RandomizingTimeDistanceTravelDisutilityFactory;
import org.matsim.core.router.costcalculators.TravelDisutilityFactory;
import org.matsim.core.router.util.TravelDisutility;
import org.matsim.core.router.util.TravelTime;

import java.util.Objects;

/** Adds the shared dynamic energy/toll link price to the normal Car router. */
public final class HongKongDynamicCarTravelDisutilityFactory
		implements TravelDisutilityFactory {

	private final HongKongDynamicCarCostRules rules;
	private final RandomizingTimeDistanceTravelDisutilityFactory delegateFactory;
	private final double marginalUtilityOfMoney;

	@Inject
	public HongKongDynamicCarTravelDisutilityFactory(
			Config config,
			HongKongDynamicCarCostRules rules) {
		this.rules = Objects.requireNonNull(rules, "rules");
		this.delegateFactory = new RandomizingTimeDistanceTravelDisutilityFactory(
				TransportMode.car, Objects.requireNonNull(config, "config"));
		this.marginalUtilityOfMoney = config.scoring().getMarginalUtilityOfMoney();
		if (!Double.isFinite(marginalUtilityOfMoney) || marginalUtilityOfMoney < 0.0) {
			throw new IllegalArgumentException("marginalUtilityOfMoney must be finite and nonnegative.");
		}
	}

	@Override
	public TravelDisutility createTravelDisutility(TravelTime travelTime) {
		TravelDisutility delegate = delegateFactory.createTravelDisutility(travelTime);
		return new TravelDisutility() {
			@Override
			public double getLinkTravelDisutility(
					org.matsim.api.core.v01.network.Link link,
					double time,
					org.matsim.api.core.v01.population.Person person,
					org.matsim.vehicles.Vehicle vehicle) {
				double standard = delegate.getLinkTravelDisutility(link, time, person, vehicle);
				if (!rules.isPrivateCar(person, vehicle)) {
					return standard;
				}
				double result = standard + rules.quoteLink(link, time).totalHkd()
						* marginalUtilityOfMoney;
				if (!Double.isFinite(result)) {
					throw new IllegalStateException("Dynamic Car routing disutility became non-finite.");
				}
				return result;
			}

			@Override
			public double getLinkMinimumTravelDisutility(
					org.matsim.api.core.v01.network.Link link) {
				// Zero toll is an admissible lower bound; energy is time independent
				// and is therefore always included in the lower-bound hint.
				return delegate.getLinkMinimumTravelDisutility(link)
						+ rules.quoteLink(link, 0.0).energyHkd() * marginalUtilityOfMoney;
			}
		};
	}
}
