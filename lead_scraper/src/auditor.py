from __future__ import annotations

from datetime import datetime, timezone

from .models import AuditedLead, FoundLead, ScrapedWebsite
from src.lead_pipeline import intent_level_from_score


ISSUE_PRIORITY = {
    "no booking funnel": 10,
    "too many CTAs": 20,
    "weak mobile layout": 30,
    "slow website experience": 35,
    "weak trust signals": 40,
    "https trust signal is weak": 42,
    "weak local discovery signals": 45,
    "faq/schema readiness is missing": 50,
    "too much content without structure": 60,
    "high-value services could be framed more clearly": 70,
    "no multilingual support mentioned": 80,
    "contact path is buried or missing": 90,
    "outdated COVID messaging": 100,
}

ISSUE_LABELS = {
    "no booking funnel": "No clear booking path",
    "too many CTAs": "Too many competing CTAs",
    "weak mobile layout": "Weak mobile experience",
    "slow website experience": "Speed and performance need work",
    "weak trust signals": "Trust signals are thin",
    "https trust signal is weak": "HTTPS trust signal is weak",
    "weak local discovery signals": "Local discovery signals are thin",
    "faq/schema readiness is missing": "FAQ/schema readiness is missing",
    "too much content without structure": "Content hierarchy needs cleanup",
    "high-value services could be framed more clearly": "Service hierarchy needs clearer framing",
    "no multilingual support mentioned": "Multilingual support is missing",
    "contact path is buried or missing": "Contact path is buried",
    "outdated COVID messaging": "Messaging feels outdated",
}


def _top_issue_text(scraped: ScrapedWebsite) -> str:
    if scraped.website_status == "failed to load":
        return "The website is not loading reliably enough to support a clear patient journey."
    if scraped.website_status == "slow":
        return "The website feels slow enough to create friction before the booking step."
    signals = scraped.issue_signals
    if "no booking funnel" in signals:
        return "The site does not lead visitors to one clear booking path."
    if "too many CTAs" in signals:
        return "The site has too many competing calls to action."
    if "weak mobile layout" in signals:
        return "The mobile experience feels weak and can make the next step harder to reach."
    if "slow website experience" in signals:
        return "The site may feel slow enough to create friction before the booking step."
    if "weak trust signals" in signals:
        return "The site does not surface enough trust proof for a quick local comparison."
    if "https trust signal is weak" in signals:
        return "The site is missing a simple trust signal that can affect confidence."
    if "weak local discovery signals" in signals:
        return "Local discovery signals are thin, so the site is not doing enough for nearby searchers."
    if "faq/schema readiness is missing" in signals:
        return "FAQ/schema readiness is missing, which leaves structured context on the table."
    if "too much content without structure" in signals:
        return "The content hierarchy needs cleanup so visitors can scan it faster."
    if "high-value services could be framed more clearly" in signals:
        return "High-value services are present, but they need clearer framing."
    if "no multilingual support mentioned" in signals:
        return "Multilingual support is not visible, which may narrow the local audience."
    if "contact path is buried or missing" in signals:
        return "The contact path is buried, so ready visitors may not reach the next step."
    if "outdated COVID messaging" in signals:
        return "Some messaging feels outdated and can weaken trust quickly."
    if signals:
        return f"The website shows a fixable conversion issue: {signals[0]}."
    return "The website has room to make the patient journey clearer and easier to act on."


def _issue_candidates(found: FoundLead, scraped: ScrapedWebsite) -> list[str]:
    candidates: list[tuple[int, str]] = []
    seen: set[str] = set()

    def add(signal: str) -> None:
        if signal in seen:
            return
        label = ISSUE_LABELS.get(signal)
        if not label:
            return
        seen.add(signal)
        candidates.append((ISSUE_PRIORITY.get(signal, 999), label))

    for signal in scraped.issue_signals:
        add(signal)

    if not found.review_count:
        add("weak local discovery signals")
    elif found.review_count < 10:
        add("weak trust signals")
    elif found.review_count < 25:
        add("weak local discovery signals")

    if not scraped.https_active:
        add("https trust signal is weak")

    if scraped.website_status == "failed to load":
        candidates.insert(0, (1, "Website reliability is a problem"))

    if not candidates:
        return ["No clear blocker found yet"]

    candidates.sort(key=lambda item: (item[0], item[1]))
    return [label for _, label in candidates[:3]]


def _business_impact(top_issues: list[str], found: FoundLead, scraped: ScrapedWebsite) -> str:
    issue_blob = " ".join(top_issues).lower()
    parts: list[str] = []

    if any(term in issue_blob for term in ("booking path", "competing ctas", "contact path")):
        parts.append("Visitors may not understand the next step quickly enough to move from interest to contact.")
    if any(term in issue_blob for term in ("reliability", "failed load", "broken")):
        parts.append("If the site is unreliable, visitors may leave before they can even evaluate the clinic.")
    if any(term in issue_blob for term in ("mobile", "speed", "performance")):
        parts.append("Mobile visitors can run into friction before they ever reach the booking step.")
    if any(term in issue_blob for term in ("trust", "local discovery", "https")) or not scraped.https_active:
        parts.append("The clinic can feel less established or easier to overlook in a local search comparison.")
    if any(term in issue_blob for term in ("content hierarchy", "schema", "services")):
        parts.append("Important services and answers are harder to scan, which slows decision-making.")
    if found.review_count is not None and found.review_count < 25:
        parts.append("Low review volume can make the clinic look less proven on Google Maps and in nearby search.")

    if not parts:
        parts.append("The site leaves room to make the patient journey clearer and easier to act on.")

    return " ".join(parts)


def _recommended_offer(top_issues: list[str], found: FoundLead, scraped: ScrapedWebsite, score: int) -> str:
    issue_blob = " ".join(top_issues).lower()

    if not top_issues or "no clear blocker found yet" in issue_blob or score <= 2:
        return "Free Audit"
    if scraped.website_status == "failed to load" or "messaging feels outdated" in issue_blob:
        return "Full Build"
    if any(term in issue_blob for term in ("trust signals", "local discovery", "faq/schema", "speed and performance")):
        return "Full Website Audit"
    if score >= 4 and scraped.website_status == "loads" and found.review_count and found.review_count >= 50:
        return "Care/Growth Plan"
    if len(top_issues) <= 2:
        return "Modules / Improvements"
    return "Full Website Audit"


def _recommended_fix(offer: str, top_issues: list[str]) -> str:
    primary = top_issues[0].lower() if top_issues else "the site"
    if offer == "Free Audit":
        return "Start with a short audit to confirm where the biggest opportunity is."
    if offer == "Modules / Improvements":
        return "Tighten the CTA stack, simplify the service section, and add a stronger trust block near the booking path."
    if offer == "Full Website Audit":
        return "Run a deeper ranked audit across booking flow, trust, mobile, local discovery, and content hierarchy."
    if offer == "Full Build":
        return "Rebuild the core pages around one clear booking path, stronger trust proof, and cleaner mobile structure."
    if offer == "Care/Growth Plan":
        return "Set up ongoing content, conversion, and support improvements to keep the site performing."
    return f"Tighten {primary} and remove the friction that is slowing the site down."


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


def _email_angle(offer: str, top_issues: list[str]) -> str:
    primary = top_issues[0].lower() if top_issues else "the website"
    if offer == "Free Audit":
        return "Open with a quick free audit and show the main friction points."
    if offer == "Modules / Improvements":
        return f"Focus on a few targeted fixes that make {primary} easier to resolve."
    if offer == "Full Website Audit":
        return "Position the work as a deeper audit of the site experience and booking path."
    if offer == "Full Build":
        return "Frame the site as needing a rebuild around booking, trust, and local discovery."
    if offer == "Care/Growth Plan":
        return "Position the work as ongoing optimization and support, not a one-time fix."
    return f"Show how {primary} can be cleaned up without overcomplicating the project."


def _loom_script(top_issues: list[str], business_impact: str, recommended_fix: str) -> str:
    issue_text = ", ".join(top_issues[:3]) if top_issues else "a few fixable issues"
    return (
        "Hey, Brian here. I took a quick look at your site and noticed "
        f"{issue_text}. {business_impact} "
        f"I would start by {recommended_fix.lower().rstrip('.')}. "
        "If helpful, I can walk you through the changes I would make."
    )


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
    top_issue = _top_issue_text(scraped)
    score = score_lead(found, scraped, top_issue)
    top_3_issues = _issue_candidates(found, scraped)
    business_impact = _business_impact(top_3_issues, found, scraped)
    recommended_offer = _recommended_offer(top_3_issues, found, scraped, score)
    recommended_fix = _recommended_fix(recommended_offer, top_3_issues)
    email_angle = _email_angle(recommended_offer, top_3_issues)
    angle_bucket = _angle_bucket(top_issue, scraped)
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
    updated_at = datetime.now(timezone.utc).isoformat()

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
        recommended_offer=recommended_offer,
        lead_quality_score=score,
        website_status=scraped.website_status,
        source=found.source,
        scrape_notes="\n".join(notes),
        contact_name=scraped.dentist_or_owner_name,
        website_url=scraped.website_url or found.website,
        industry="Dental",
        location=found.city,
        lead_source=found.source,
        lead_status="audit_ready",
        audit_status="complete",
        outreach_status="not_started",
        intent_level=intent_level_from_score(score),
        notes="\n".join(notes),
        updated_at=updated_at,
        contact_page_url=scraped.contact_page_url,
        booking_url=scraped.booking_url,
        languages=", ".join(scraped.languages),
        services=", ".join(scraped.services),
        top_3_issues=top_3_issues,
        business_impact=business_impact,
        recommended_fix=recommended_fix,
        email_angle=email_angle,
        loom_script=_loom_script(top_3_issues, business_impact, recommended_fix),
    )
