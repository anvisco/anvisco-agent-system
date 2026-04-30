from __future__ import annotations

from .models import AuditedLead, FoundLead, ScrapedWebsite


def _top_issue(scraped: ScrapedWebsite) -> str:
    signals = scraped.issue_signals
    if "no booking funnel" in signals:
        return "The website has no clear booking funnel, so visitors are pushed toward phone or email instead of a guided patient flow."
    if "weak mobile layout" in signals:
        return "The website appears to have a weak mobile layout, which can make it harder for patients to take action from their phone."
    if "too much content without structure" in signals:
        return "The website has a lot of content without enough structure, which can make services and next steps harder to scan."
    if "high-value services could be framed more clearly" in signals:
        return "High-value services are present, but they could be framed more clearly around patient trust and booking intent."
    if "no multilingual support mentioned" in signals:
        return "The website does not clearly mention multilingual support, which may matter for patients in the local area."
    if signals:
        return f"The website shows a fixable conversion issue: {signals[0]}."
    return "The website has room to make the patient journey clearer and easier to act on."


def _recommended_offer(top_issue: str) -> str:
    lower = top_issue.lower()
    if "booking" in lower or "patient flow" in lower:
        return "Booking flow improvement"
    if "mobile" in lower:
        return "Mobile conversion improvement"
    if "slow" in lower:
        return "Speed optimization"
    if "structure" in lower or "services" in lower:
        return "Website cleanup and organization"
    if "multilingual" in lower:
        return "Website redesign"
    return "Funnel optimization"


def _angle_bucket(top_issue: str, scraped: ScrapedWebsite) -> str:
    issue_text = f"{top_issue} {' '.join(scraped.issue_signals)}".lower()
    if "booking" in issue_text or "patient flow" in issue_text or "phone or email" in issue_text:
        return "No Booking Funnel"
    if "too many cta" in issue_text or "competing" in issue_text:
        return "Too Many CTAs"
    if "mobile" in issue_text:
        return "Weak Mobile Experience"
    if "outdated" in issue_text or "slow" in issue_text or "low trust" in issue_text:
        return "Outdated Website"
    if "multilingual" in issue_text:
        return "No Multilingual Support"
    if "structure" in issue_text or "scan" in issue_text or "content" in issue_text:
        return "Poor Content Structure"
    return "Looks Good But Does Not Convert"


def score_lead(found: FoundLead, scraped: ScrapedWebsite, top_issue: str) -> int:
    has_contact_method = bool(scraped.email or scraped.phone or found.phone)
    has_valid_website = bool(scraped.website_url or found.website)
    has_clear_issue = bool(top_issue and top_issue.strip())

    score = 2
    if has_valid_website and has_contact_method and has_clear_issue:
        score = 3
    if scraped.email:
        score += 1
    if scraped.issue_signals:
        score += 1
    if scraped.booking_url == "":
        score += 1
    if found.review_count and found.review_count >= 50:
        score += 1
    if scraped.website_status == "failed to load":
        score -= 1
    return max(1, min(score, 5))


def audit_lead(found: FoundLead, scraped: ScrapedWebsite) -> AuditedLead:
    top_issue = _top_issue(scraped)
    offer = _recommended_offer(top_issue)
    angle_bucket = _angle_bucket(top_issue, scraped)
    score = score_lead(found, scraped, top_issue)
    notes = [
        f"Website status: {scraped.website_status}",
        f"HTTPS active: {'yes' if scraped.https_active else 'no'}",
        f"Mobile-friendly basic layout: {scraped.mobile_friendly}",
        f"PageSpeed Score: {scraped.pagespeed_score if scraped.pagespeed_score is not None else 'null'}",
        *scraped.technical_notes,
    ]

    outreach_angle = (
        "Position the redesign as a patient-conversion system that simplifies booking, improves trust, "
        "and turns more website visitors into consultations."
    )

    return AuditedLead(
        google_place_id=found.google_place_id,
        business_name=scraped.business_name or found.business_name,
        niche="Dental clinic",
        city=found.city,
        website=scraped.website_url or found.website,
        domain=scraped.domain,
        email=scraped.email,
        phone=scraped.phone or found.phone,
        address=found.address,
        google_maps_url=found.google_maps_url,
        rating=found.rating,
        review_count=found.review_count,
        top_issue=top_issue,
        outreach_angle=outreach_angle,
        angle_bucket=angle_bucket,
        recommended_offer=offer,
        lead_quality_score=score,
        website_status=scraped.website_status,
        source=found.source,
        scrape_notes="\n".join(notes),
        contact_page_url=scraped.contact_page_url,
        booking_url=scraped.booking_url,
        languages=", ".join(scraped.languages),
        services=", ".join(scraped.services),
    )
