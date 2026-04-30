from __future__ import annotations

from typing import Any, Dict


EMAIL_1_SUBJECT = "quick thing I noticed on your site"
EMAIL_2_SUBJECT = "quick follow-up"
EMAIL_3_SUBJECT = "should I close this?"
DEFAULT_WEBSITE = "https://www.anvisco.com"
ANGLE_POSITIONING = {
    "No Booking Funnel": "You are losing patients who will not call.",
    "Too Many CTAs": "When everything is important, nothing gets clicked.",
    "Looks Good But Does Not Convert": "The site may look fine, but it is not working like a conversion system.",
    "Weak Mobile Experience": "Most patients are on mobile, and friction kills bookings.",
    "Outdated Website": "Patients judge credibility instantly.",
    "No Multilingual Support": "You may be missing part of your local patient market.",
    "Poor Content Structure": "People read but do not act.",
}


def _extract_text(value: Dict[str, Any]) -> str:
    if not value:
        return ""
    if isinstance(value.get("rich_text"), list) and value["rich_text"]:
        return "".join(part.get("plain_text", "") for part in value["rich_text"])
    if isinstance(value.get("title"), list) and value["title"]:
        return "".join(part.get("plain_text", "") for part in value["title"])
    if isinstance(value.get("url"), str):
        return value["url"]
    if isinstance(value.get("email"), str):
        return value["email"]
    if isinstance(value.get("select"), dict):
        return value["select"].get("name", "")
    if isinstance(value.get("status"), dict):
        return value["status"].get("name", "")
    if isinstance(value.get("checkbox"), bool):
        return "true" if value["checkbox"] else "false"
    return ""


def _get_property_text(lead: Dict[str, Any], property_name: str) -> str:
    properties = lead.get("properties", {})
    return _extract_text(properties.get(property_name, {})).strip()


def _get_first_property_text(lead: Dict[str, Any], property_names: tuple[str, ...]) -> str:
    for property_name in property_names:
        text = _get_property_text(lead, property_name)
        if text:
            return text
    return ""


def _get_mentionable_issue(lead: Dict[str, Any]) -> str:
    for field in ("Top Issue", "Notes", "Outreach Angle"):
        text = _get_property_text(lead, field)
        if text:
            return text
    return "there is room to make the website clearer and easier to use"


def _mentions_multilingual_opportunity(lead: Dict[str, Any]) -> bool:
    combined = " ".join(
        _get_property_text(lead, field)
        for field in ("Top Issue", "Notes", "Outreach Angle", "Languages")
    ).lower()
    return any(keyword in combined for keyword in ("multilingual", "translation", "translate", "language"))


def map_angle_bucket(lead: Dict[str, Any]) -> str:
    text = " ".join(
        _get_property_text(lead, field)
        for field in (
            "Top Issue",
            "Outreach Angle",
            "Recommended Offer",
            "Website Status",
            "Scrape Notes",
            "Notes",
            "Languages",
        )
    ).lower()
    website_status = _get_property_text(lead, "Website Status").lower()

    if any(phrase in text for phrase in ("no booking", "only phone", "only email", "unclear book", "booking funnel", "guided booking")):
        return "No Booking Funnel"
    if any(phrase in text for phrase in ("too many cta", "too many buttons", "competing", "everything is important", "many ctas")):
        return "Too Many CTAs"
    if any(phrase in text for phrase in ("looks good", "modern", "decent", "no conversion", "conversion system")):
        return "Looks Good But Does Not Convert"
    if any(phrase in text for phrase in ("mobile", "hard-to-click", "spacing", "mobile booking")):
        return "Weak Mobile Experience"
    if any(phrase in text for phrase in ("outdated", "old design", "slow", "cluttered", "low trust")) or "slow" in website_status:
        return "Outdated Website"
    if _mentions_multilingual_opportunity(lead):
        return "No Multilingual Support"
    if any(phrase in text for phrase in ("too much text", "weak hierarchy", "hard to scan", "poor service", "content structure")):
        return "Poor Content Structure"
    return "Looks Good But Does Not Convert"


def _loom_recommended(lead: Dict[str, Any], angle_bucket: str) -> bool:
    score_text = _get_property_text(lead, "Lead Quality Score")
    try:
        score = int(float(score_text))
    except ValueError:
        score = 0
    email = _get_first_property_text(lead, ("Email", "Contact Email"))
    visual_angles = {
        "No Booking Funnel",
        "Too Many CTAs",
        "Weak Mobile Experience",
        "Outdated Website",
        "Poor Content Structure",
    }
    return score >= 4 and bool(email) and angle_bucket in visual_angles


def _loom_script(angle_bucket: str) -> str:
    return (
        "Hey, Brian here. I took a quick look at your site and wanted to point out one thing I noticed. "
        f"The main issue is around {angle_bucket.lower()}, which can create friction for someone deciding whether to book, call, or keep looking. "
        "For dental clinics, that matters because people are often browsing quickly on mobile and comparing options. "
        "I would tighten the structure so the site works more like a patient conversion system, with clearer service paths, stronger booking moments, and less friction. "
        "If useful, I would be happy to walk you through how I would approach it."
    )


def generate_email_sequence(lead: Dict[str, Any]) -> Dict[str, Any]:
    business_name = _get_first_property_text(lead, ("Business Name", "Practice Name", "Clinic Name", "Name")) or "there"
    recipient_name = _get_first_property_text(
        lead,
        ("Dentist / Owner Name", "Owner Name", "Dentist Name", "Contact Name"),
    ) or business_name
    top_issue = _get_mentionable_issue(lead)
    outreach_angle = _get_property_text(lead, "Outreach Angle")
    angle_bucket = map_angle_bucket(lead)
    positioning = ANGLE_POSITIONING.get(angle_bucket, ANGLE_POSITIONING["Looks Good But Does Not Convert"])
    loom_recommended = _loom_recommended(lead, angle_bucket)

    email_1_body = (
        f"Hello {recipient_name},\n\n"
        "I build websites that run, grow, and optimize your business.\n\n"
        "I took a quick look at your site and one thing stood out.\n\n"
        f"{top_issue}\n\n"
        f"{positioning} This usually leads to patients hesitating instead of booking, especially on mobile.\n\n"
        "I help clinics fix this by turning the site into a clear booking flow instead of just an information page.\n\n"
        "If you're open to it, I can share how I'd approach improving it."
    )
    email_2_body = (
        f"Hello {recipient_name},\n\n"
        "Wanted to follow up on this.\n\n"
        f"The angle I noticed was {angle_bucket.lower()}. A lot of dental sites have this issue, so even with traffic, bookings do not come through as consistently as they should.\n\n"
        "Small structural changes usually make a big difference, especially around how the booking path is presented.\n\n"
        "Happy to walk you through what I'd change on your site specifically if that's useful."
    )
    email_3_body = (
        f"Hello {recipient_name},\n\n"
        "Not sure if this is a priority on your end right now.\n\n"
        f"If improving {angle_bucket.lower()} and turning more website visitors into booked patients is something you're considering, I'm happy to share a few ideas tailored to your clinic.\n\n"
        "If not, no worries, I'll close this on my end."
    )

    return {
        "angle_bucket": angle_bucket,
        "loom_recommended": loom_recommended,
        "loom_script": _loom_script(angle_bucket) if loom_recommended else "",
        "outreach_angle": outreach_angle,
        "emails": {
            "email_1": {"subject": EMAIL_1_SUBJECT, "body": email_1_body},
            "email_2": {"subject": EMAIL_2_SUBJECT, "body": email_2_body},
            "email_3": {"subject": EMAIL_3_SUBJECT, "body": email_3_body},
        },
    }


def generate_outreach_email(lead: Dict[str, Any]) -> Dict[str, str]:
    sequence = generate_email_sequence(lead)
    return sequence["emails"]["email_1"]
