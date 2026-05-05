from __future__ import annotations

from typing import Any, Dict

from src.safety import validate_prospect_copy

DEFAULT_WEBSITE = "https://anvisco.com"
SIGNATURE = "Warmly,\nBrian Nguyen\nAnvis | Websites built to run, grow, and get discovered\nGet a free website audit | Book a discovery call"
FALLBACK_TOP_ISSUE = "the site could use a clearer path from visitor interest to booking"
FALLBACK_ANGLE_BUCKET = "Looks Good But Does Not Convert"
HIGH_INTENT_BUCKETS = {"No Booking Funnel", "Too Many CTAs"}
TREATMENT_KEYWORDS = (
    "invisalign",
    "implant",
    "all-on-four",
    "all on four",
    "veneer",
    "smile makeover",
    "sedation",
    "emergency",
    "root canal",
    "orthodont",
    "whitening",
)


def _property_lines(value: str) -> list[str]:
    lines: list[str] = []
    for raw_line in value.replace("\r", "\n").split("\n"):
        for part in raw_line.split(","):
            cleaned = part.strip().strip("-").strip()
            if cleaned:
                lines.append(cleaned)
    return lines


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
    if isinstance(value.get("number"), (int, float)):
        number = value["number"]
        return str(int(number)) if float(number).is_integer() else str(number)
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


def _audit_field_text(lead: Dict[str, Any], *property_names: str) -> str:
    return _get_first_property_text(lead, property_names)


def _audit_field_lines(lead: Dict[str, Any], *property_names: str) -> list[str]:
    text = _audit_field_text(lead, *property_names)
    return _property_lines(text) if text else []


def _get_mentionable_issue(lead: Dict[str, Any]) -> str:
    for field in ("Top Issue", "Top 3 Issues", "Business Impact", "Recommended Fix", "Email Angle", "Notes", "Outreach Angle"):
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
        for field in ("Top Issue", "Top 3 Issues", "Business Impact", "Recommended Fix", "Email Angle", "Notes", "Outreach Angle", "Languages")
    ).lower()
    return any(keyword in combined for keyword in ("multilingual", "translation", "translate", "language"))


def _detect_service_hook(lead: Dict[str, Any]) -> str:
    services = _property_lines(_get_property_text(lead, "Services"))
    combined_services = " ".join(services).lower()
    for keyword in TREATMENT_KEYWORDS:
        if keyword in combined_services:
            if "all on four" in keyword:
                return "All-on-Four"
            if keyword == "orthodont":
                return "orthodontics"
            if keyword == "emergency":
                return "emergency care"
            if keyword == "smile makeover":
                return "smile makeovers"
            if keyword == "implant":
                return "implants"
            return keyword.replace("-", " ").title()
    return ""


def _detect_strength_hook(lead: Dict[str, Any]) -> str:
    review_count_text = _get_property_text(lead, "Review Count")
    try:
        review_count = int(float(review_count_text))
    except ValueError:
        review_count = 0
    service_hook = _detect_service_hook(lead)
    if service_hook:
        return service_hook
    languages = _property_lines(_get_property_text(lead, "Languages"))
    if len(languages) > 1:
        return "multilingual advantage"
    if review_count >= 50:
        return "review profile"
    city = _get_first_property_text(lead, ("City", "Location"))
    if city:
        return f"{city} visibility"
    return ""


def _build_subject_line(lead: Dict[str, Any], angle_bucket: str) -> str:
    business_name = _get_first_property_text(lead, ("Business Name", "Practice Name", "Clinic Name", "Name")) or "your clinic"
    hook = _detect_strength_hook(lead)
    city = _get_first_property_text(lead, ("City", "Location"))

    if hook == "multilingual advantage":
        return f"Is {business_name}'s multilingual advantage clear enough?"
    if hook == "review profile":
        return f"Is {business_name}'s review story clear enough?"
    if hook == "All-on-Four":
        return f"Is {business_name}'s All-on-Four advantage clear enough?"
    if hook in {"Invisalign", "Implants", "Smile Makeovers", "Emergency Care", "Orthodontics"}:
        return f"Is {business_name}'s {hook} advantage clear enough?"
    if hook.endswith("visibility"):
        return f"Are {city} patients seeing {business_name}'s strongest reasons to book?"
    if angle_bucket == "No Booking Funnel":
        return f"Is {business_name} making it easy enough to choose you?"
    if angle_bucket == "Too Many CTAs":
        return f"Is {business_name} getting picked, or just compared?"
    if angle_bucket == "Weak Mobile Experience":
        return f"Is {business_name} easy to use on mobile?"
    if angle_bucket == "No Multilingual Support":
        return f"Is {business_name}'s multilingual advantage clear enough?"
    if angle_bucket in {"Outdated Website", "Poor Content Structure"}:
        return f"A visibility gap I noticed for {business_name}"
    return f"Is {business_name} making it easy enough to choose you?"


def _build_followup_subject_line(lead: Dict[str, Any], angle_bucket: str) -> str:
    business_name = _get_first_property_text(lead, ("Business Name", "Practice Name", "Clinic Name", "Name")) or "your clinic"
    hook = _detect_strength_hook(lead)
    city = _get_first_property_text(lead, ("City", "Location"))

    if hook == "multilingual advantage":
        return f"Follow-up: Is {business_name}'s multilingual advantage clear enough?"
    if hook == "review profile":
        return f"Follow-up: Is {business_name}'s review story clear enough?"
    if hook == "All-on-Four":
        return f"Follow-up: Is {business_name}'s All-on-Four advantage clear enough?"
    if hook in {"Invisalign", "Implants", "Smile Makeovers", "Emergency Care", "Orthodontics"}:
        return f"Follow-up: Is {business_name}'s {hook} advantage clear enough?"
    if hook.endswith("visibility") and city:
        return f"Follow-up: Are {city} patients seeing {business_name}'s strongest reasons to book?"
    if angle_bucket == "No Booking Funnel":
        return f"Follow-up: Is {business_name} losing ready-to-book patients?"
    if angle_bucket == "Too Many CTAs":
        return f"Follow-up: Is {business_name} getting picked, or just compared?"
    if angle_bucket == "Weak Mobile Experience":
        return f"Follow-up: Is {business_name} easy to use on mobile?"
    if angle_bucket == "No Multilingual Support":
        return f"Follow-up: Is {business_name}'s multilingual advantage clear enough?"
    if angle_bucket in {"Outdated Website", "Poor Content Structure"}:
        return f"Follow-up: A visibility gap I noticed for {business_name}"
    return f"Follow-up: Is {business_name} making it easy enough to choose you?"


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
    angle_bucket = map_angle_bucket(lead) or FALLBACK_ANGLE_BUCKET
    top_issues = _audit_field_lines(lead, "Top 3 Issues")
    top_issue = _get_mentionable_issue(lead)
    business_impact = _audit_field_text(lead, "Business Impact")
    recommended_fix = _audit_field_text(lead, "Recommended Fix")
    email_angle = _audit_field_text(lead, "Email Angle")
    outreach_angle = _get_property_text(lead, "Outreach Angle") or email_angle or _derive_outreach_angle(top_issue, angle_bucket)
    recommended_offer = _audit_field_text(lead, "Recommended Offer") or "Funnel Optimization"
    loom_script = _audit_field_text(lead, "Loom Script")
    email_1_subject = _build_subject_line(lead, angle_bucket)
    email_2_subject = _build_followup_subject_line(lead, angle_bucket)
    email_3_subject = _build_followup_subject_line(lead, angle_bucket)
    loom_recommended = _loom_recommended(lead, angle_bucket)
    strengths: list[str] = []
    review_count_text = _get_first_property_text(lead, ("Review Count",))
    rating_text = _get_first_property_text(lead, ("Rating",))
    try:
        review_count = int(float(review_count_text)) if review_count_text else 0
    except ValueError:
        review_count = 0
    if review_count:
        strengths.append(f"{review_count} Google reviews")
    if rating_text:
        strengths.append(f"a {rating_text}-star rating")
    for service in _property_lines(_get_property_text(lead, "Services"))[:3]:
        if service:
            strengths.append(service)
    for language in _property_lines(_get_property_text(lead, "Languages"))[:2]:
        if language:
            strengths.append(language)
    if _get_property_text(lead, "Contact Page URL"):
        strengths.append("a clear contact page")
    if _get_property_text(lead, "Booking URL"):
        strengths.append("a booking path already in place")
    if _get_property_text(lead, "Website") or _get_property_text(lead, "Website URL"):
        strengths.append("a live website")
    if _get_first_property_text(lead, ("City", "Location")):
        strengths.append(f"a local presence in {_get_first_property_text(lead, ('City', 'Location'))}")
    strengths = [strength for strength in strengths if strength]
    if len(strengths) > 7:
        strengths = strengths[:7]

    if strengths:
        if len(strengths) == 1:
            strengths_sentence = strengths[0]
        elif len(strengths) == 2:
            strengths_sentence = f"{strengths[0]} and {strengths[1]}"
        else:
            strengths_sentence = ", ".join(strengths[:-1]) + f", and {strengths[-1]}"
    else:
        strengths_sentence = "a live website and a visible local footprint"

    gap_sentence = (
        "The gap I noticed is that those strengths are not structured in a way that is easy to scan or act on."
    )
    if business_impact:
        gap_sentence = business_impact
    city = _get_first_property_text(lead, ("City", "Location"))
    search_sentence = ""
    issue_blob = " ".join([top_issue, business_impact, recommended_fix, email_angle, " ".join(top_issues)]).lower()
    if city and any(term in issue_blob for term in ("local discovery", "maps", "google", "trust", "schema", "faq")):
        search_sentence = (
            f"When someone asks Google, Maps, or AI tools for a dentist in {city}, the clinic with the clearest service structure and trust signals has the advantage."
        )

    if recommended_fix:
        lowered_fix = recommended_fix.lower().rstrip(".")
        if lowered_fix.startswith("tighten "):
            audit_sentence = f"I would start by {lowered_fix.replace('tighten ', 'tightening ', 1)}."
        elif lowered_fix.startswith(("run ", "rebuild ", "set up ", "start ")):
            audit_sentence = f"I would start by {lowered_fix}."
        else:
            audit_sentence = f"I would start by tightening {lowered_fix}."
    elif top_issues:
        audit_sentence = f"I would start by tightening the main issue around {top_issues[0].lower()}."
    else:
        audit_sentence = "I would start by tightening the clearest friction points first."

    if angle_bucket in HIGH_INTENT_BUCKETS:
        email_1_body = (
            f"Hi {business_name} team,\n\n"
            f"I took a quick look at your website. The clinic has real strengths: {strengths_sentence}. That is a lot to work with.\n\n"
            f"{gap_sentence}\n\n"
            f"{search_sentence + ' ' if search_sentence else ''}"
            "I can send over a free website audit pointing out 3 to 5 things I would immediately improve around visibility, trust, and booking flow.\n\n"
            f"You can see my work here: {DEFAULT_WEBSITE}\n\n"
            f"{audit_sentence}\n\n"
            f"{SIGNATURE}"
        )
    else:
        email_1_body = (
            f"Hi {business_name} team,\n\n"
            f"I took a quick look at your website. The clinic has real strengths: {strengths_sentence}. That is a lot to work with.\n\n"
            f"{gap_sentence}\n\n"
            f"{search_sentence + ' ' if search_sentence else ''}"
            "I can send over a free website audit pointing out 3 to 5 things I would immediately improve around visibility, trust, and booking flow.\n\n"
            f"You can see my work here: {DEFAULT_WEBSITE}\n\n"
            f"{audit_sentence}\n\n"
            f"{SIGNATURE}"
        )
    use_loom_variant = loom_recommended or bool(loom_script)
    if use_loom_variant:
        email_2_body = (
            f"Hi {business_name} team,\n\n"
            "Just wanted to follow up on the quick video I sent last week.\n\n"
            f"The main thing that stood out is that {top_issue.lower() if top_issue else angle_bucket.lower()}. The opportunity is making the path from interest to booking feel clearer.\n\n"
            f"For patients comparing clinics near {city or 'you'}, that clarity matters. If the call-to-action, navigation, or booking flow takes too much effort to understand, attention can shift to another clinic before they ever call.\n\n"
            "It also matters for how people search now. Google, Maps, and AI tools are increasingly pulling from structured, clearly written website content when deciding what businesses look most relevant.\n\n"
            "I can send over a quick free audit with 3 to 5 things I would improve first around visibility, trust, and booking flow.\n\n"
            f"{SIGNATURE}"
        )
        email_3_body = (
            f"Hi {business_name} team,\n\n"
            "Circling back in case the quick video got buried.\n\n"
            f"If improving {angle_bucket.lower()} and making the booking path feel easier is on your radar, I can put together a quick free audit with the first 3 to 5 things I would tighten.\n\n"
            f"{SIGNATURE}"
        )
    else:
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

    emails = {
        "email_1": {"subject": email_1_subject, "body": email_1_body},
        "email_2": {"subject": email_2_subject, "body": email_2_body},
        "email_3": {"subject": email_3_subject, "body": email_3_body},
    }

    validate_prospect_copy(
        [
            email_1_subject,
            email_1_body,
            email_2_subject,
            email_2_body,
            email_3_subject,
            email_3_body,
            loom_script or "",
        ],
        context=f"email sequence for {business_name}",
    )

    return {
        "top_issue": top_issue,
        "top_3_issues": top_issues,
        "business_impact": business_impact,
        "recommended_fix": recommended_fix,
        "email_angle": email_angle or audit_sentence,
        "angle_bucket": angle_bucket,
        "loom_recommended": loom_recommended,
        "loom_script": loom_script or (_loom_script(angle_bucket) if loom_recommended else ""),
        "recommended_offer": recommended_offer,
        "outreach_angle": outreach_angle,
        "emails": emails,
    }


def generate_outreach_email(lead: Dict[str, Any]) -> Dict[str, str]:
    sequence = generate_email_sequence(lead)
    return sequence["emails"]["email_1"]
