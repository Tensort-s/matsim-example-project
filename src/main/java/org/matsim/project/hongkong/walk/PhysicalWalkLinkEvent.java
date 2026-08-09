package org.matsim.project.hongkong.walk;

import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.events.Event;
import org.matsim.api.core.v01.events.HasLinkId;
import org.matsim.api.core.v01.events.HasPersonId;
import org.matsim.api.core.v01.network.Link;
import org.matsim.api.core.v01.population.Person;

/** Person-level link traversal event for capacity-free physical Walk. */
public final class PhysicalWalkLinkEvent extends Event implements HasPersonId, HasLinkId {

	public static final String ENTER_TYPE = "physical walk entered link";
	public static final String LEAVE_TYPE = "physical walk left link";

	private final String type;
	private final Id<Person> personId;
	private final Id<Link> linkId;

	public PhysicalWalkLinkEvent(double time, String type, Id<Person> personId, Id<Link> linkId) {
		super(time);
		if (!ENTER_TYPE.equals(type) && !LEAVE_TYPE.equals(type)) {
			throw new IllegalArgumentException("Unsupported physical Walk event type: " + type);
		}
		this.type = type;
		this.personId = personId;
		this.linkId = linkId;
	}

	@Override
	public String getEventType() {
		return type;
	}

	@Override
	public Id<Person> getPersonId() {
		return personId;
	}

	@Override
	public Id<Link> getLinkId() {
		return linkId;
	}
}
