from __future__ import annotations

from typing import Any, Dict


EMAIL_2_SUBJECT = "quick follow-up"
EMAIL_3_SUBJECT = "should I close this?"
DEFAULT_WEBSITE = "https://www.anvisco.com"
SIGNATURE = "Brian Nguyen\nAnvisco\nhttps://www.anvisco.com"
ANGLE_SUBJECTS = {
    "No Booking Funnel": "Quick fix for your booking flow",
    "Too Many CTAs": "Quick thought on your website flow",
    "Looks Good But Does Not Convert": "Quick idea for your website",
    "Weak Mobile Experience": "Mobile experience on your site",
    "Outdated Website": "Quick idea for your website",
    "No Multilingual Support": "Quick idea for your Toronto audience",
    "Poor Content Structure": "Your site structure",
}
ANGLE_POSITIONING = {
    "No Booking Funnel": "You are losing patients who will not call.",
    "Too Many CTAs": "When everything is important, nothing gets clicked.",
    "Looks Good But Does Not Convert": "The site may look fine, but it is not working like a conversion system.",
    "Weak Mobile Experience": "Most patients are on mobile, and friction kills bookings.",
    "Outdated Website": "Patients judge credibility instantly.",
    "No Multilingual Support": "You may be missing part of your local patient market.",
    "Poor Content Structure": "People read but do not act.",
}
ANGLE_CONVERSION_EXPLANATIONS = {
    "No Booking Funnel": "When the booking path is not obvious, patients who are ready to act can end up calling later or leaving.",
    "Too Many CTAs": "When there are too many competing next steps, visitors can hesitate instead of choosing the booking path.",
    "Looks Good But Does Not Convert": "A site can look solid but still lose bookings if it does not guide visitors toward one clear action.",
    "Weak Mobile Experience": "Most patients browse on mobile, so small friction in layout or booking can cost real inquiries.",
    "Outdated Website": "Patients judge trust quickly, so an outdated experience can reduce confidence before they contact you.",
    "No Multilingual Support": "In a city like Toronto, missing language support can make part of the local audience harder to convert.",
    "Poor Content Structure": "If services and next steps are hard to scan, people read the page but do not take action.",
}
FALLBACK_TOP_ISSUE = "the site could use a clearer path from visitor interest to booking"
FALLBACK_ANGLE_BUCKET = "Looks Good But Does Not Convert"
FALLBACK_RECOMMENDED_OFFER = "Funnel Optimization"
HIGH_INTENT_BUCKETS = {"No Booking Funnel", "Too Many CTAs"}


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
    return FALLBACK_TOP_ISSUE


def _derive_outreach_angle(top_issue: str, angle_bucket: str) -> str:
    if angle_bucket in HIGH_INTENT_BUCKETS:
        return f"Turn {top_issue} into a clearer booking path for patients."
    return f"Improve the path from website visits to booked patients around {top_issue}."


def _mentions_multilingual_opportunity(lead: Dict[str, Any]) -> bool:
    combined = " ".join(
        _get_property_text(lead, field)
        for field in ("Top Issue", "Notes", "Outreach Angle", "Languages")
    ).lower()
    return any(keyword in combined for keyword in ("multilingual", "translation", "translate", "language"))


def map_angle_bucket(lead: Dict[str, Any]) -> str:
    existing_angle = _get_property_text(lead, "Angle Bucket")
    if existing_angle:
        return existing_angle

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
    top_issue = _get_mentionable_issue(lead)
    angle_bucket = map_angle_bucket(lead) or FALLBACK_ANGLE_BUCKET
    outreach_angle = _get_property_text(lead, "Outreach Angle") or _derive_outreach_angle(top_issue, angle_bucket)
    recommended_offer = _get_property_text(lead, "Recommended Offer") or FALLBACK_RECOMMENDED_OFFER
    email_1_subject = ANGLE_SUBJECTS.get(angle_bucket, "Quick idea for your website")
    loom_recommended = _loom_recommended(lead, angle_bucket)

    if angle_bucket in HIGH_INTENT_BUCKETS:
        email_1_body = (
            f"Hi {business_name} team,\n\n"
            f"I took a quick look at your website and noticed {top_issue}.\n\n"
            "The main issue is that the site has information, but the booking path does not feel as clear as it could be. "
            "That usually means some patients leave instead of taking the next step.\n\n"
            "I build websites that run, grow, and optimize your business. For clinics, I focus on the parts that turn visitors into booked patients: clearer service paths, stronger booking moments, and less friction.\n\n"
            "If useful, I can show you what I would tighten on your site.\n\n"
            f"{SIGNATURE}"
        )
    else:
        email_1_body = (
            f"Hi {business_name} team,\n\n"
            f"I took a quick look at your website and noticed {top_issue}.\n\n"
            "That usually creates friction for patients who are ready to book but do not get a clear next step.\n\n"
            "I build websites that run, grow, and optimize your business. For clinics, that means turning the site into a cleaner patient conversion flow, not just making it look better.\n\n"
            "If improving how your site turns visitors into booked patients is something you are considering, I can show you how I would approach it.\n\n"
            f"{SIGNATURE}"
        )
    email_2_body = (
        f"Hello {business_name} team,\n\n"
        "Wanted to follow up on this.\n\n"
        f"The angle I noticed was {angle_bucket.lower()}. A lot of dental sites have this issue, so even with traffic, bookings do not come through as consistently as they should.\n\n"
        "Small structural changes usually make a big difference, especially around how the booking path is presented.\n\n"
        "Happy to walk you through what I'd change on your site specifically if that's useful."
    )
    email_3_body = (
        f"Hello {business_name} team,\n\n"
        "Not sure if this is a priority on your end right now.\n\n"
        f"If improving {angle_bucket.lower()} and turning more website visitors into booked patients is something you're considering, I'm happy to share a few ideas tailored to your clinic.\n\n"
        "If not, no worries, I'll close this on my end."
    )

    return {
        "angle_bucket": angle_bucket,
        "loom_recommended": loom_recommended,
        "loom_script": _loom_script(angle_bucket) if loom_recommended else "",
        "recommended_offer": recommended_offer,
        "outreach_angle": outreach_angle,
        "emails": {
            "email_1": {"subject": email_1_subject, "body": email_1_body},
            "email_2": {"subject": EMAIL_2_SUBJECT, "body": email_2_body},
            "email_3": {"subject": EMAIL_3_SUBJECT, "body": email_3_body},
        },
    }


def generate_outreach_email(lead: Dict[str, Any]) -> Dict[str, str]:
    sequence = generate_email_sequence(lead)
    return sequence["emails"]["email_1"]
