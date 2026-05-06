from __future__ import annotations

import re
from html import escape
from typing import Any, Dict, Iterable, List

from src.safety import validate_prospect_copy


DEFAULT_WEBSITE = "https://anvisco.com"
SIGNATURE_HTML = (
    "Warmly,<br>"
    "Brian Nguyen<br>"
    "Anvis | Websites built to run, grow, and get discovered<br>"
    '<a href="https://forms.gle/tNPhqQRGYSWQvbZ99">Get a free website audit</a> | '
    '<a href="https://calendly.com/nducanhnguyenn/15-minute-discovery-call">Book a discovery call</a>'
)
EMAIL_2_SUBJECT = "Follow-up"
EMAIL_3_SUBJECT = "Follow-up"
FALLBACK_RECOMMENDED_OFFER = "Website improvements"
FALLBACK_ANGLE_BUCKET = "visibility_trust_booking"
SERVICE_PHRASE_MAP = {
    "cleaning": "dental hygiene / cleaning",
    "cosmetic": "cosmetic dentistry",
    "denture": "denture care",
    "invisalign": "Invisalign care",
    "implant": "implant dentistry",
    "emergency": "emergency dental care",
    "orthodont": "orthodontic care",
    "orthodontic": "orthodontic care",
    "root canal": "root canal treatment",
}
COMMON_NAME_REPLACEMENTS = (
    (" Family and Cosmetic Dentistry", " Dentistry"),
    (" Family Dentistry", " Dentistry"),
    (" Cosmetic Dentistry", " Dentistry"),
    (" Dental Clinic", " Dentistry"),
    (" Dental Center", " Dentistry"),
    (" Dental Care", " Dentistry"),
)


def _extract_text(value: Dict[str, Any]) -> str:
    if not value:
        return ""
    if isinstance(value.get("rich_text"), list) and value["rich_text"]:
        return "".join(part.get("plain_text", "") for part in value["rich_text"]).strip()
    if isinstance(value.get("title"), list) and value["title"]:
        return "".join(part.get("plain_text", "") for part in value["title"]).strip()
    if isinstance(value.get("url"), str):
        return value["url"]
    if isinstance(value.get("email"), str):
        return value["email"]
    if isinstance(value.get("select"), dict):
        return value["select"].get("name", "")
    if isinstance(value.get("status"), dict):
        return value["status"].get("name", "")
    if isinstance(value.get("number"), (int, float)):
        return str(value["number"])
    if isinstance(value.get("checkbox"), bool):
        return "true" if value["checkbox"] else "false"
    return ""


def _get_property(lead: Dict[str, Any], property_name: str) -> Dict[str, Any]:
    return lead.get("properties", {}).get(property_name, {})


def _get_property_text(lead: Dict[str, Any], property_name: str) -> str:
    return _extract_text(_get_property(lead, property_name)).strip()


def _get_first_property_text(lead: Dict[str, Any], property_names: Iterable[str]) -> str:
    for property_name in property_names:
        text = _get_property_text(lead, property_name)
        if text:
            return text
    return ""


def _get_text_with_fallback(lead: Dict[str, Any], keys: Iterable[str]) -> str:
    for key in keys:
        value = lead.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return _get_first_property_text(lead, keys)


def _get_number_text(lead: Dict[str, Any], property_names: Iterable[str]) -> str:
    for property_name in property_names:
        text = _get_property_text(lead, property_name)
        if text:
            return text
    return ""


def _get_checkbox_value(lead: Dict[str, Any], property_names: Iterable[str]) -> bool:
    for property_name in property_names:
        value = _get_property(lead, property_name)
        if isinstance(value.get("checkbox"), bool):
            return bool(value["checkbox"])
    return False


def _split_fragments(text: str) -> List[str]:
    if not text:
        return []
    pieces: List[str] = []
    for raw_piece in text.replace("\n", ";").split(";"):
        fragment = raw_piece.strip(" -•\t\r")
        if fragment:
            pieces.extend([part.strip() for part in fragment.split(",") if part.strip()])
    return pieces


def _normalize_service_token(token: str) -> str:
    cleaned = re.sub(r"[^\w\s/+-]", " ", token).strip().lower()
    if not cleaned:
        return ""
    for key, phrase in SERVICE_PHRASE_MAP.items():
        if key in cleaned:
            return phrase
    return " ".join(cleaned.split())


def _dedupe_preserve_order(items: Iterable[str]) -> List[str]:
    seen: set[str] = set()
    ordered: List[str] = []
    for item in items:
        normalized = item.strip()
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(normalized)
    return ordered


def _format_count(value: str, label: str) -> str:
    try:
        count = int(float(value))
    except ValueError:
        return ""
    if count <= 0:
        return ""
    noun = label if count == 1 else f"{label}s"
    return f"{count} {noun}"


def _field_candidates(*names: str) -> tuple[str, ...]:
    return tuple(names)


SUBJECT_ANGLE_FIELDS = _field_candidates("Subject Angle", "Email Angle")
CLINIC_STRENGTH_FIELDS = _field_candidates("Clinic Strengths", "Strongest Advantage", "Services", "Languages")
STRONGEST_ADVANTAGE_FIELDS = _field_candidates("Strongest Advantage", "Recommended Fix")
PATIENT_TYPE_LOCATION_FIELDS = _field_candidates("Patient Type / Location Angle", "City", "Niche")
TOP_3_ISSUES_FIELDS = _field_candidates("Top 3 Issues", "Top Issue")
BUSINESS_IMPACT_FIELDS = _field_candidates("Business Impact", "Notes", "Top 3 Issues", "Top Issue")
RECOMMENDED_FIX_FIELDS = _field_candidates("Recommended Fix", "Recommended Offer", "Email Angle", "Outreach Angle")
EMAIL_ANGLE_FIELDS = _field_candidates("Email Angle", "Outreach Angle")
LOOM_LINK_FIELDS = _field_candidates("Loom Link")
REVIEW_COUNT_FIELDS = _field_candidates("Review Count")
RATING_FIELDS = _field_candidates("Rating")
BOOKING_FIELDS = _field_candidates("Booking URL", "Contact Page URL")
CITY_FIELDS = _field_candidates("City")
SERVICE_FIELDS = _field_candidates("Services")
LANGUAGE_FIELDS = _field_candidates("Languages")
TOP_ISSUE_FIELDS = _field_candidates("Top 3 Issues", "Top Issue")
RECOMMENDED_OFFER_FIELDS = _field_candidates("Recommended Offer")
COUNTRY_FIELDS = _field_candidates("Country")
PROVINCE_FIELDS = _field_candidates("Province")
EMAIL_FIELDS = _field_candidates("Email", "Contact Email")
WEBSITE_FIELDS = _field_candidates("Website")
NOTE_FIELDS = _field_candidates("Notes", "Scrape Notes")


def _lead_business_name(lead: Dict[str, Any]) -> str:
    return _get_first_property_text(lead, ("Business Name", "Practice Name", "Clinic Name", "Name")) or "there"


def _lead_city(lead: Dict[str, Any]) -> str:
    return _get_first_property_text(lead, CITY_FIELDS)


def _lead_country(lead: Dict[str, Any]) -> str:
    return _get_first_property_text(lead, COUNTRY_FIELDS) or "Canada"


def _lead_province(lead: Dict[str, Any]) -> str:
    return _get_first_property_text(lead, PROVINCE_FIELDS)


def _lead_services(lead: Dict[str, Any]) -> List[str]:
    raw_services = _split_fragments(_get_first_property_text(lead, SERVICE_FIELDS))
    mapped: List[str] = []
    for service in raw_services:
        normalized = _normalize_service_token(service)
        if normalized:
            mapped.append(normalized)
    return _dedupe_preserve_order(mapped)


def _lead_languages(lead: Dict[str, Any]) -> List[str]:
    return _dedupe_preserve_order(_split_fragments(_get_first_property_text(lead, LANGUAGE_FIELDS)))


def _lead_review_count(lead: Dict[str, Any]) -> str:
    return _get_first_property_text(lead, REVIEW_COUNT_FIELDS)


def _lead_rating(lead: Dict[str, Any]) -> str:
    return _get_first_property_text(lead, RATING_FIELDS)


def _lead_booking_url(lead: Dict[str, Any]) -> str:
    return _get_first_property_text(lead, BOOKING_FIELDS)


def _lead_website(lead: Dict[str, Any]) -> str:
    return _get_first_property_text(lead, WEBSITE_FIELDS) or DEFAULT_WEBSITE


def _lead_subject_angle(lead: Dict[str, Any]) -> str:
    return _get_first_property_text(lead, SUBJECT_ANGLE_FIELDS)


def _lead_strongest_advantage(lead: Dict[str, Any]) -> str:
    return _get_first_property_text(lead, STRONGEST_ADVANTAGE_FIELDS)


def _lead_patient_type_location_angle(lead: Dict[str, Any]) -> str:
    return _get_first_property_text(lead, PATIENT_TYPE_LOCATION_FIELDS)


def _lead_top_issues(lead: Dict[str, Any]) -> List[str]:
    text = _get_first_property_text(lead, TOP_3_ISSUES_FIELDS)
    if text:
        return _dedupe_preserve_order(_split_fragments(text))[:3]
    fallback = _get_first_property_text(lead, TOP_ISSUE_FIELDS)
    return [fallback] if fallback else []


def _lead_business_impact(lead: Dict[str, Any]) -> str:
    return _get_first_property_text(lead, BUSINESS_IMPACT_FIELDS)


def _lead_recommended_fix(lead: Dict[str, Any]) -> str:
    return _get_first_property_text(lead, RECOMMENDED_FIX_FIELDS)


def _lead_email_angle(lead: Dict[str, Any]) -> str:
    return _get_first_property_text(lead, EMAIL_ANGLE_FIELDS)


def _lead_loom_link(lead: Dict[str, Any]) -> str:
    return _get_first_property_text(lead, LOOM_LINK_FIELDS)


def _lead_recommended_offer(lead: Dict[str, Any]) -> str:
    return _get_first_property_text(lead, RECOMMENDED_OFFER_FIELDS) or FALLBACK_RECOMMENDED_OFFER


def _service_summary(lead: Dict[str, Any]) -> str:
    services = _lead_services(lead)
    if not services:
        return ""

    grouped = _dedupe_preserve_order(services)
    if not grouped:
        return ""
    if len(grouped) == 1:
        return grouped[0]
    if len(grouped) == 2:
        return f"{grouped[0]} and {grouped[1]}"
    return ", ".join(grouped[:-1]) + f", and {grouped[-1]}"


def _service_search_label(lead: Dict[str, Any]) -> str:
    services = _lead_services(lead)
    lowered = [service.lower() for service in services]
    if any("invisalign" in service for service in lowered):
        return "Invisalign"
    if any("emergency" in service for service in lowered):
        return "emergency"
    if any("implant" in service for service in lowered):
        return "implant"
    if any("orthodontic" in service for service in lowered):
        return "orthodontic"
    if services:
        return "multi-service"
    return "dental"


def _service_search_phrase(lead: Dict[str, Any]) -> str:
    label = _service_search_label(lead)
    if label == "Invisalign":
        return "Invisalign dentist"
    if label == "emergency":
        return "emergency dentist"
    if label == "implant":
        return "implant dentist"
    if label == "orthodontic":
        return "orthodontic provider"
    if label == "multi-service":
        return "family dentist"
    return "dental clinic"


def _indefinite_article(phrase: str) -> str:
    normalized = phrase.strip().lower()
    if not normalized:
        return "a"
    if normalized.startswith(("honest", "hour", "heir", "honor", "invisalign", "emergency", "implant", "orthodontic", "a", "e", "i", "o", "u")):
        return "an"
    return "a"


def _discovery_sentence(lead: Dict[str, Any]) -> str:
    city = _lead_city(lead)
    if not city:
        return ""
    service_focus = _service_search_phrase(lead)
    if not service_focus:
        return ""
    article = _indefinite_article(service_focus)
    return (
        f"It also matters for how people search now. When someone asks Google, Maps, or AI tools for {article} {service_focus} "
        f"or a {city} dental clinic, the clinic with the clearest service structure and trust signals has the advantage."
    )


def _clinic_strength_fragments(lead: Dict[str, Any]) -> List[str]:
    strengths: List[str] = []
    seen: set[str] = set()

    def add_strength(text: str) -> None:
        normalized = text.strip()
        if not normalized:
            return
        key = normalized.lower()
        if key in seen:
            return
        seen.add(key)
        strengths.append(normalized)

    strongest_advantage = _lead_strongest_advantage(lead)
    if strongest_advantage:
        add_strength(strongest_advantage)

    service_summary = _service_summary(lead)
    if service_summary:
        add_strength(f"a wide service mix across {service_summary}")

    languages = _lead_languages(lead)
    if languages:
        add_strength(f"multilingual support in {', '.join(languages)}")

    review_count = _lead_review_count(lead)
    review_text = _format_count(review_count, "review")
    if review_text:
        add_strength(f"{review_text} patient reviews")

    rating = _lead_rating(lead)
    if rating:
        add_strength(f"a strong {rating}-star review profile")

    booking_url = _lead_booking_url(lead)
    if booking_url:
        add_strength("a clear booking path")

    website = _lead_website(lead)
    if website.startswith("https://"):
        add_strength("a secure HTTPS site")

    city = _lead_city(lead)
    if city:
        add_strength(f"a local presence in {city}")

    return _dedupe_preserve_order(strengths)[:7]


def _subject_hook(lead: Dict[str, Any], fallback: str) -> str:
    subject_angle = _lead_subject_angle(lead)
    if subject_angle:
        return _shorten_subject_text(subject_angle, lead)

    business_name = _short_business_name(_lead_business_name(lead))
    strongest_advantage = _lead_strongest_advantage(lead)
    explicit_patient_type_location_angle = _get_property_text(lead, "Patient Type / Location Angle")
    city = _lead_city(lead)
    review_count = _lead_review_count(lead)
    rating = _lead_rating(lead)

    avoid_possessive = _subject_should_avoid_possessive(business_name)
    if strongest_advantage:
        if avoid_possessive:
            if city:
                return _shorten_subject_text(f"Are patients in {city} seeing why {business_name} is worth choosing?", lead)
            return _shorten_subject_text(f"Is {business_name} easy enough to choose online?", lead)
        return _shorten_subject_text(f"Is {business_name}'s {strongest_advantage} clear enough?", lead)
    if explicit_patient_type_location_angle:
        if avoid_possessive:
            if city:
                return _shorten_subject_text(
                    f"Are {explicit_patient_type_location_angle} seeing why {business_name} is worth choosing?",
                    lead,
                )
            return _shorten_subject_text(f"Is {business_name} easy enough to choose online?", lead)
        return _shorten_subject_text(
            f"Are {explicit_patient_type_location_angle} seeing {business_name}'s strongest reasons to book?",
            lead,
        )
    if city:
        if avoid_possessive:
            return _shorten_subject_text(f"Are patients in {city} seeing why {business_name} is worth choosing?", lead)
        return _shorten_subject_text(f"Are patients in {city} seeing {business_name}'s strongest reasons to book?", lead)
    if review_count or rating:
        if avoid_possessive:
            return _shorten_subject_text(f"Is {business_name} getting picked, or just compared?", lead)
        return _shorten_subject_text(f"Is {business_name} getting picked, or just compared?", lead)
    return _shorten_subject_text(fallback.format(business_name=business_name), lead)


def _short_business_name(business_name: str) -> str:
    shortened = " ".join(business_name.strip().split())
    if not shortened:
        return shortened

    if "," in shortened:
        shortened = shortened.split(",", 1)[0].strip()

    lowered = shortened.lower()
    if lowered.startswith(("dr ", "dr.")):
        for old, new in COMMON_NAME_REPLACEMENTS:
            if old.lower() in lowered:
                shortened = shortened.replace(old, new)
                lowered = shortened.lower()

    return shortened


def _subject_should_avoid_possessive(business_name: str) -> bool:
    cleaned = business_name.strip().rstrip("’'\"")
    if not cleaned:
        return True
    return cleaned.lower().endswith("s")


def _shorten_subject_text(subject_text: str, lead: Dict[str, Any]) -> str:
    full_name = _lead_business_name(lead).strip()
    short_name = _short_business_name(full_name)
    if full_name and short_name and full_name != short_name:
        subject_text = subject_text.replace(full_name, short_name)
    return subject_text


def _followup_subject(lead: Dict[str, Any], variant: int) -> str:
    if variant == 2:
        fallback = "Follow-up: Is {business_name} getting picked, or just compared?"
    else:
        fallback = "Follow-up: Is {business_name} making it easy enough to choose you?"
    return _subject_hook(lead, fallback)


def _html_paragraphs(*parts: str) -> str:
    paragraphs = []
    for part in parts:
        if not part:
            continue
        paragraphs.append(f"<p>{part}</p>")
    return "\n".join(paragraphs)


def _join_strengths(lead: Dict[str, Any]) -> str:
    strengths = _clinic_strength_fragments(lead)
    if not strengths:
        return ""
    if len(strengths) == 1:
        return strengths[0]
    if len(strengths) == 2:
        return f"{strengths[0]} and {strengths[1]}"
    return ", ".join(strengths[:-1]) + f", and {strengths[-1]}"


def _build_first_email_body(lead: Dict[str, Any], strengths: List[str], business_impact: str, email_angle: str) -> str:
    business_name = escape(_lead_business_name(lead))
    city = escape(_lead_city(lead))
    service_summary = escape(_service_summary(lead))
    strength_sentence = ""
    if strengths:
        review_count = _lead_review_count(lead)
        rating = _lead_rating(lead)
        review_phrase = []
        if rating:
            review_phrase.append(f"a strong {escape(rating)}-star review profile")
        if review_count:
            review_phrase.append(f"{escape(review_count)} patient reviews")
        review_text = ", ".join(review_phrase)
        parts = []
        if review_text:
            parts.append(review_text)
        languages = _lead_languages(lead)
        if languages:
            parts.append(f"multilingual support in {escape(', '.join(languages))}")
        if service_summary:
            parts.append(f"a wide service mix across {service_summary}")
        if parts:
            if len(parts) == 1:
                summary = parts[0]
            elif len(parts) == 2:
                summary = f"{parts[0]} and {parts[1]}"
            else:
                summary = ", ".join(parts[:-1]) + f", and {parts[-1]}"
            strength_sentence = f"The clinic has real strengths: {summary}. That is a lot to work with."
        else:
            strength_sentence = f"The clinic has real strengths: {escape(_join_strengths(lead))}. That is a lot to work with."
    else:
        strength_sentence = "There is still a solid base to work with."

    if city:
        issue_sentence = (
            f"The gap I noticed is that these strengths could be easier to scan and act on. "
            f"For patients comparing dentists in {city}, unclear service paths or booking steps can cost attention before someone ever books."
        )
    elif business_impact:
        issue_sentence = escape(business_impact)
    else:
        issue_sentence = "The gap I noticed is that these strengths could be easier to scan and act on."

    search_sentence = escape(_discovery_sentence(lead))

    cta_sentence = (
        "I can send over a free website audit pointing out 3 to 5 things I would immediately improve around "
        "visibility, trust, and booking flow."
    )

    return _html_paragraphs(
        f"Hi {business_name} team,",
        f"I took a quick look at your website. {strength_sentence}",
        issue_sentence,
        search_sentence,
        cta_sentence,
        SIGNATURE_HTML,
    )


def _build_followup_body(lead: Dict[str, Any], variant: int = 1) -> str:
    business_name = escape(_lead_business_name(lead))
    city = escape(_lead_city(lead))
    strengths = _join_strengths(lead)
    top_issues = _lead_top_issues(lead)
    business_impact = _lead_business_impact(lead)
    recommended_fix = _lead_recommended_fix(lead)
    email_angle = _lead_email_angle(lead)
    loom_link = _lead_loom_link(lead)

    if loom_link:
        intro = "Just wanted to follow up on the quick video I sent last week."
    else:
        intro = "Just wanted to follow up on my note from last week."

    if variant == 2 and loom_link:
        main = (
            f"The main thing that stood out is that {escape(top_issues[0].lower()) if top_issues else 'the site has a few clarity gaps'}. "
            "The opportunity is making the path from interest to booking feel clearer."
        )
    else:
        if strengths:
            main = f"The main thing that stood out is that your site already has strong patient-facing signals: {escape(strengths)}."
        else:
            main = "The main thing that stood out is that your site already has some useful patient-facing signals."
        main += " The opportunity is making those signals easier to scan and act on."

    if city:
        city_sentence = (
            f"For patients comparing clinics near {city}, that clarity matters. "
            "If the call-to-action or booking steps take too much effort to understand, attention can shift to another clinic before they ever call."
        )
    else:
        city_sentence = (
            "For patients comparing clinics in the area, that clarity matters. "
            "If the call-to-action or booking steps take too much effort to understand, attention can shift to another clinic before they ever call."
        )

    search_sentence = email_angle or (
        "It also matters for how people search now. Google, Maps, and AI tools are increasingly pulling from structured, clearly written website content when deciding what businesses look most relevant."
    )
    if any(phrase in search_sentence.lower() for phrase in (
        "position the redesign",
        "patient-conversion system",
        "patient conversion system",
        "turns more website visitors into consultations",
        "redesign strategy",
        "funnel system",
    )):
        search_sentence = (
            "It also matters for how people search now. Google, Maps, and AI tools are increasingly pulling from structured, clearly written website content when deciding what businesses look most relevant."
        )
    search_sentence = escape(search_sentence)

    if business_impact:
        impact_sentence = escape(business_impact)
    elif recommended_fix:
        impact_sentence = escape(recommended_fix)
    else:
        impact_sentence = "I can send over a quick free audit with 3 to 5 things I would improve first around visibility, trust, and booking flow."

    followup_cta = "I can send over a quick free audit with 3 to 5 things I would improve first around visibility, trust, and booking flow."

    if loom_link:
        loom_line = f'If helpful, you can revisit the video here: <a href="{escape(loom_link)}">Loom link</a>.'
    else:
        loom_line = ""

    return _html_paragraphs(
        f"Hi {business_name} team,",
        intro,
        main,
        city_sentence,
        search_sentence,
        loom_line,
        followup_cta,
        SIGNATURE_HTML,
    )


def _fallback_top_issue(lead: Dict[str, Any]) -> str:
    for field in ("Top 3 Issues", "Top Issue", "Notes", "Email Angle", "Outreach Angle"):
        text = _get_property_text(lead, field)
        if text:
            return text
    return "the site could use a clearer path from visitor interest to booking"


def _derive_outreach_angle(top_issue: str, angle_bucket: str) -> str:
    if angle_bucket in {"No Booking Funnel", "Too Many CTAs"}:
        return f"Turn {top_issue} into a clearer booking path for patients."
    return f"Improve the path from website visits to booked patients around {top_issue}."


def _lead_angle_bucket(lead: Dict[str, Any]) -> str:
    existing_angle = _get_text_with_fallback(lead, ("angle_bucket", "Angle Bucket"))
    if existing_angle:
        return existing_angle

    explicit_angle = _get_text_with_fallback(lead, ("email_angle", "Email Angle", "Outreach Angle"))
    if explicit_angle:
        return explicit_angle

    explicit_top_issue = _get_text_with_fallback(lead, ("top_issue", "Top Issue"))
    if explicit_top_issue:
        return explicit_top_issue

    text = " ".join(
        _get_text_with_fallback(lead, (field,))
        for field in (
            "Top 3 Issues",
            "Top Issue",
            "Email Angle",
            "Outreach Angle",
            "Recommended Offer",
            "Website Status",
            "Scrape Notes",
            "Notes",
            "Languages",
        )
    ).lower()
    website_status = _get_text_with_fallback(lead, ("Website Status",)).lower()

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
    if any(keyword in text for keyword in ("multilingual", "translation", "language")):
        return "No Multilingual Support"
    if any(phrase in text for phrase in ("too much text", "weak hierarchy", "hard to scan", "poor service", "content structure")):
        return "Poor Content Structure"
    return FALLBACK_ANGLE_BUCKET


def _loom_recommended(lead: Dict[str, Any], angle_bucket: str) -> bool:
    score_text = _get_property_text(lead, "Lead Quality Score")
    try:
        score = int(float(score_text))
    except ValueError:
        score = 0
    email = _get_first_property_text(lead, EMAIL_FIELDS)
    visual_angles = {
        "No Booking Funnel",
        "Too Many CTAs",
        "Weak Mobile Experience",
        "Outdated Website",
        "Poor Content Structure",
    }
    return score >= 4 and bool(email) and angle_bucket in visual_angles


def _best_followup_subject(lead: Dict[str, Any], angle_bucket: str) -> str:
    business_name = _short_business_name(_lead_business_name(lead))
    strongest_advantage = _lead_strongest_advantage(lead)
    patient_type_location_angle = _lead_patient_type_location_angle(lead)
    city = _lead_city(lead)
    avoid_possessive = _subject_should_avoid_possessive(business_name)

    if strongest_advantage:
        if avoid_possessive:
            if city:
                return f"Follow-up: Are patients in {city} seeing why {business_name} is worth choosing?"
            return f"Follow-up: Is {business_name} easy enough to choose online?"
        return f"Follow-up: Is {business_name}'s {strongest_advantage} clear enough?"
    if patient_type_location_angle:
        if avoid_possessive:
            if city:
                return f"Follow-up: Are {patient_type_location_angle} seeing why {business_name} is worth choosing?"
            return f"Follow-up: Is {business_name} easy enough to choose online?"
        return f"Follow-up: Are {patient_type_location_angle} seeing {business_name}'s strongest reasons to book?"
    if angle_bucket in {"No Booking Funnel", "Too Many CTAs"}:
        if avoid_possessive:
            return f"Follow-up: Is {business_name} easy enough to choose online?"
        return f"Follow-up: Is {business_name} losing ready-to-book patients?"
    if angle_bucket in {"Weak Mobile Experience", "Outdated Website"}:
        if avoid_possessive:
            return f"Follow-up: Is {business_name} getting picked, or just compared?"
        return f"Follow-up: Is {business_name}'s trust signal working properly?"
    if avoid_possessive:
        return f"Follow-up: Is {business_name} getting picked, or just compared?"
    return f"Follow-up: Is {business_name} getting picked, or just compared?"


def _secondary_followup_subject(lead: Dict[str, Any], angle_bucket: str) -> str:
    business_name = _short_business_name(_lead_business_name(lead))
    avoid_possessive = _subject_should_avoid_possessive(business_name)
    if angle_bucket in {"No Booking Funnel", "Too Many CTAs"}:
        if avoid_possessive:
            return f"Follow-up: Is {business_name} easy enough to choose online?"
        return f"Follow-up: Is {business_name} making it easy enough to choose you?"
    if angle_bucket in {"No Multilingual Support"}:
        if avoid_possessive:
            return f"Follow-up: Is {business_name} getting picked, or just compared?"
        return f"Follow-up: Is {business_name}'s multilingual advantage clear enough?"
    return f"Follow-up: A visibility gap I noticed for {business_name}"


def _validate_email_sequence(sequence: Dict[str, Any]) -> None:
    validate_prospect_copy(
        sequence["emails"]["email_1"]["subject"],
        sequence["emails"]["email_1"]["body"],
        sequence["emails"]["email_2"]["subject"],
        sequence["emails"]["email_2"]["body"],
        sequence["emails"]["email_3"]["subject"],
        sequence["emails"]["email_3"]["body"],
    )


def generate_email_sequence(lead: Dict[str, Any]) -> Dict[str, Any]:
    business_name = _lead_business_name(lead)
    top_issue = _fallback_top_issue(lead)
    angle_bucket = _lead_angle_bucket(lead)
    outreach_angle = _get_property_text(lead, "Email Angle") or _get_property_text(lead, "Outreach Angle") or _derive_outreach_angle(top_issue, angle_bucket)
    recommended_offer = _lead_recommended_offer(lead)
    strengths = _clinic_strength_fragments(lead)
    business_impact = _lead_business_impact(lead)
    recommended_fix = _lead_recommended_fix(lead)
    email_angle = _lead_email_angle(lead)
    subject_angle = _lead_subject_angle(lead)
    patient_type_location_angle = _lead_patient_type_location_angle(lead)
    top_3_issues = _lead_top_issues(lead)
    loom_link = _lead_loom_link(lead)
    loom_recommended = _loom_recommended(lead, angle_bucket)

    if not business_impact:
        if angle_bucket in {"No Booking Funnel", "Too Many CTAs"}:
            business_impact = (
                "For patients comparing clinics, an unclear booking path can cause people to leave before they ever book."
            )
        elif angle_bucket in {"Weak Mobile Experience"}:
            business_impact = (
                "Interested patients on mobile may drop off before calling if the experience feels clunky or hard to scan."
            )
        elif angle_bucket in {"No Multilingual Support"}:
            business_impact = (
                "If the site does not reflect the local language mix, some patients may not feel as comfortable moving forward."
            )
        else:
            business_impact = (
                "The strengths are there, but they are not yet structured so patients can quickly understand why this clinic is the right choice."
            )

    if not recommended_fix:
        if angle_bucket in {"No Booking Funnel", "Too Many CTAs"}:
            recommended_fix = "clarify the booking path, reduce competing CTAs, and tighten the patient journey"
        elif angle_bucket in {"Weak Mobile Experience"}:
            recommended_fix = "tighten the mobile layout and make the next step easier to tap"
        elif angle_bucket in {"No Multilingual Support"}:
            recommended_fix = "make the key patient paths clearer for multilingual visitors"
        else:
            recommended_fix = "restructure the page so trust, services, and booking flow are easier to scan"

    if not email_angle:
        if patient_type_location_angle:
            email_angle = f"For patients comparing clinics near {patient_type_location_angle}, clarity and trust have a direct impact on who gets chosen."
        elif _lead_city(lead):
            email_angle = (
                f"For patients comparing clinics in {_lead_city(lead)}, clarity and trust have a direct impact on who gets chosen."
            )
        else:
            email_angle = (
                "For patients comparing clinics, clarity and trust have a direct impact on who gets chosen."
            )

    first_subject = _subject_hook(lead, "A visibility gap I noticed for {business_name}")
    second_subject = _best_followup_subject(lead, angle_bucket)
    third_subject = _secondary_followup_subject(lead, angle_bucket)
    email_1_body = _build_first_email_body(lead, strengths, business_impact, email_angle)
    email_2_body = _build_followup_body(lead, variant=1)
    email_3_body = _build_followup_body(lead, variant=2)

    sequence = {
        "top_issue": top_issue,
        "angle_bucket": angle_bucket,
        "top_3_issues": ", ".join(top_3_issues),
        "business_impact": business_impact,
        "recommended_fix": recommended_fix,
        "subject": first_subject,
        "subject_angle": subject_angle or first_subject,
        "clinic_strengths": ", ".join(strengths),
        "strongest_advantage": _lead_strongest_advantage(lead) or (strengths[0] if strengths else ""),
        "patient_type_location_angle": patient_type_location_angle or _lead_city(lead) or _lead_country(lead),
        "email_angle": email_angle,
        "loom_link": loom_link,
        "loom_recommended": loom_recommended,
        "loom_script": (
            "Hey, Brian here. I took a quick look at your site and wanted to point out one thing I noticed. "
            f"The main issue is around {angle_bucket.lower()}, which can create friction for someone deciding whether to book, call, or keep looking. "
            "For dental clinics, that matters because people are often browsing quickly on mobile and comparing options. "
            "I would tighten the structure so the site works more like a clearer booking path, with stronger service pages, better booking moments, and less friction. "
            "If useful, I would be happy to walk you through how I would approach it."
            if loom_recommended
            else ""
        ),
        "recommended_offer": recommended_offer,
        "outreach_angle": outreach_angle,
        "emails": {
            "email_1": {"subject": first_subject, "body": email_1_body},
            "email_2": {"subject": second_subject, "body": email_2_body},
            "email_3": {"subject": third_subject, "body": email_3_body},
        },
    }
    _validate_email_sequence(sequence)
    return sequence


def generate_outreach_email(lead: Dict[str, Any]) -> Dict[str, str]:
    sequence = generate_email_sequence(lead)
    return sequence["emails"]["email_1"]
