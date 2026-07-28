package org.matsim.project.hongkong.taxi;

import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.api.core.v01.population.Person;
import org.matsim.utils.objectattributes.attributable.Attributes;

import java.util.Objects;

/** Strict typed interface to the six taxi attributes embedded in each taxi leg. */
public final class HongKongTaxiLegAttributes {

	public static final String FARE_BASELINE_HKD = "hkTaxiFareBaselineHkd";
	public static final String TAXI_TYPE = "hkTaxiType";
	public static final String FARE_SCOPE = "hkTaxiFareScope";
	public static final String FARE_MODEL_VERSION = "hkTaxiFareModelVersion";
	public static final String CLASSIFICATION_SOURCE = "hkTaxiClassificationSource";
	public static final String MAIN_TRIP_INDEX = "hkTaxiMainTripIndex";

	private HongKongTaxiLegAttributes() {
	}

	public static Metadata readAndValidate(
			Leg leg,
			Id<Person> personId,
			HongKongTaxiScoringParameters parameters) {
		Objects.requireNonNull(leg, "leg");
		Objects.requireNonNull(personId, "personId");
		Objects.requireNonNull(parameters, "parameters");

		Attributes attributes = leg.getAttributes();
		Object fareValue = required(attributes, leg, personId, FARE_BASELINE_HKD, "java.lang.Double or Number");
		if (!(fareValue instanceof Number fareNumber)) {
			throw invalid(leg, personId, FARE_BASELINE_HKD, fareValue, "java.lang.Double or Number");
		}
		double fareHkd = fareNumber.doubleValue();
		if (!Double.isFinite(fareHkd) || fareHkd < 0.0) {
			throw invalid(
					leg,
					personId,
					FARE_BASELINE_HKD,
					fareValue,
					"finite non-negative java.lang.Double or Number"
			);
		}

		String taxiType = requiredNonBlankString(attributes, leg, personId, TAXI_TYPE);
		String fareScope = requiredNonBlankString(attributes, leg, personId, FARE_SCOPE);
		if (!parameters.fareScope().equals(fareScope)) {
			throw invalid(
					leg,
					personId,
					FARE_SCOPE,
					fareScope,
					"java.lang.String value='" + parameters.fareScope() + "'"
			);
		}
		String fareModelVersion = requiredNonBlankString(
				attributes,
				leg,
				personId,
				FARE_MODEL_VERSION
		);
		if (!parameters.fareModelVersion().equals(fareModelVersion)) {
			throw invalid(
					leg,
					personId,
					FARE_MODEL_VERSION,
					fareModelVersion,
					"java.lang.String value='" + parameters.fareModelVersion() + "'"
			);
		}
		String classificationSource = requiredNonBlankString(
				attributes,
				leg,
				personId,
				CLASSIFICATION_SOURCE
		);

		Object mainTripValue = required(
				attributes,
				leg,
				personId,
				MAIN_TRIP_INDEX,
				"non-negative java.lang.Integer"
		);
		if (!(mainTripValue instanceof Integer mainTripIndex) || mainTripIndex < 0) {
			throw invalid(
					leg,
					personId,
					MAIN_TRIP_INDEX,
					mainTripValue,
					"non-negative java.lang.Integer"
			);
		}

		return new Metadata(
				fareHkd,
				taxiType,
				fareScope,
				fareModelVersion,
				classificationSource,
				mainTripIndex
		);
	}

	private static Object required(
			Attributes attributes,
			Leg leg,
			Id<Person> personId,
			String name,
			String expected) {
		/*
		 * MATSim Attributes is a map, so a name can have at most one runtime
		 * value. containsKey distinguishes a missing attribute from an invalid
		 * explicit null value.
		 */
		if (!attributes.getAsMap().containsKey(name)) {
			throw invalid(leg, personId, name, null, expected);
		}
		Object value = attributes.getAttribute(name);
		if (value == null) {
			throw invalid(leg, personId, name, null, expected);
		}
		return value;
	}

	private static String requiredNonBlankString(
			Attributes attributes,
			Leg leg,
			Id<Person> personId,
			String name) {
		Object value = required(attributes, leg, personId, name, "non-blank java.lang.String");
		if (!(value instanceof String text) || text.isBlank()) {
			throw invalid(leg, personId, name, value, "non-blank java.lang.String");
		}
		return text;
	}

	private static IllegalArgumentException invalid(
			Leg leg,
			Id<Person> personId,
			String attributeName,
			Object actualValue,
			String expected) {
		String actualType = actualValue == null
				? "<missing>"
				: actualValue.getClass().getName();
		return new IllegalArgumentException(
				"Invalid Hong Kong taxi leg attribute: person_id=" + personId
						+ ", leg_mode=" + leg.getMode()
						+ ", attribute=" + attributeName
						+ ", actual_value=" + String.valueOf(actualValue)
						+ ", actual_type=" + actualType
						+ ", expected=" + expected
		);
	}

	/** Immutable, fully validated fare metadata for one taxi leg. */
	public record Metadata(
			double fareBaselineHkd,
			String taxiType,
			String fareScope,
			String fareModelVersion,
			String classificationSource,
			int mainTripIndex) {
	}
}
