from __future__ import annotations

from .config import settings
from .models import AuditedLead, FoundLead, ScrapedWebsite


def _top_issue(scraped: ScrapedWebsite) -> str:
    signals = scraped.issue_signals
    if "no booking funnel" in signals:
        return "The website has no clear booking funnel, so visitors are pushed toward phone or email instead of a guided patient flow."
    if "too many CTAs" in signals:
        return "The website has too many competing calls to action, so visitors may not know which next step matters."
    if "trust signals are thin" in signals:
        return "The website does not surface enough trust signals early, which can make patients hesitate before booking."
    if "weak trust signals" in signals:
        return "The website does not surface enough trust proof early, which can make patients hesitate before booking."
    if "local discovery signals are thin" in signals:
        return "The website does not clearly support local discovery, so nearby patients may not immediately see why this clinic is relevant."
    if "weak local discovery signals" in signals:
        return "The website does not clearly support local discovery, so nearby patients may not immediately see why this clinic is relevant."
    if "faq/schema readiness is not obvious" in signals:
        return "The website does not make FAQ or schema readiness obvious, which can weaken scanability and search clarity."
    if "faq/schema readiness is missing" in signals:
        return "The website does not make FAQ or schema readiness obvious, which can weaken scanability and search clarity."
    if "weak mobile layout" in signals:
        return "The website appears to have a weak mobile layout, which can make it harder for patients to take action from their phone."
    if "slow website experience" in signals:
        return "The website feels slow enough to create friction before a patient reaches the booking step."
    if "too much content without structure" in signals:
        return "The website has a lot of content without enough structure, which can make services and next steps harder to scan."
    if "high-value services could be framed more clearly" in signals:
        return "High-value services are present, but they could be framed more clearly around patient trust and booking intent."
    if "no multilingual support mentioned" in signals:
        return "The website does not clearly mention multilingual support, which may matter for patients in the local area."
    if "https trust signal is weak" in signals:
        return "The website is missing a simple HTTPS trust signal that can affect confidence."
    if "contact path is buried or missing" in signals:
        return "The contact path is buried or missing, so ready visitors may not reach the next step."
    if "outdated COVID messaging" in signals:
        return "The website still carries outdated COVID messaging, which can weaken trust quickly."
    if signals:
        return f"The website shows a fixable conversion issue: {signals[0]}."
    return "The website has room to make the patient journey clearer and easier to act on."


def _recommended_offer(top_issue: str) -> str:
    lower = top_issue.lower()
    if any(keyword in lower for keyword in ("broken", "outdated", "low trust", "failed", "slow")):
        return "Full Build"
    if any(keyword in lower for keyword in ("booking", "patient flow", "cta", "structure", "services", "faq", "mobile", "local discovery", "trust signals", "trust proof", "https trust", "contact path")):
        return "Modules / Improvements"
    if any(keyword in lower for keyword in ("multilingual", "translation")):
        return "Full Website Audit"
    return "Free Audit"


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
    if "trust signals" in issue_text:
        return "Looks Good But Does Not Convert"
    if "local discovery" in issue_text or "faq/schema" in issue_text:
        return "Poor Content Structure"
    if "structure" in issue_text or "scan" in issue_text or "content" in issue_text:
        return "Poor Content Structure"
    return "Looks Good But Does Not Convert"


def _strengths(found: FoundLead, scraped: ScrapedWebsite) -> list[str]:
    strengths: list[str] = []
    if found.review_count and found.review_count >= 50:
        strengths.append(f"solid review profile with {found.review_count} reviews")
    if found.rating and found.rating >= 4.4:
        strengths.append(f"strong rating around {found.rating}")
    if scraped.booking_url:
        strengths.append("an obvious booking path")
    if scraped.contact_page_url:
        strengths.append("a clear contact page")
    if scraped.languages:
        strengths.append(f"multilingual support in {', '.join(scraped.languages[:2])}")
    if scraped.services:
        strengths.append(f"services like {', '.join(scraped.services[:3])}")
    if scraped.https_active:
        strengths.append("HTTPS security is active")
    if scraped.mobile_friendly != "unknown":
        strengths.append(f"a basic mobile layout signal ({scraped.mobile_friendly})")
    if scraped.issue_signals:
        strengths.append("enough content to work with")
    deduped: list[str] = []
    seen: set[str] = set()
    for item in strengths:
        key = item.lower()
        if key not in seen:
            seen.add(key)
            deduped.append(item)
    return deduped[:7]


def _subject_angle(found: FoundLead, scraped: ScrapedWebsite, angle_bucket: str) -> str:
    if scraped.booking_url:
        return f"Is {found.business_name}'s booking path clear enough?"
    if found.review_count and found.review_count >= 50:
        return f"Is {found.business_name}'s review advantage clear enough?"
    if "No Multilingual Support" == angle_bucket:
        return f"Is {found.business_name}'s multilingual advantage clear enough?"
    return f"Is {found.business_name} making it easy enough to choose you?"


def _patient_type_location_angle(found: FoundLead, scraped: ScrapedWebsite) -> str:
    if scraped.languages:
        return f"{found.city} patients looking for multilingual care"
    if scraped.services:
        return f"{found.city} patients comparing services like {', '.join(scraped.services[:2])}"
    return f"patients comparing clinics in {found.city}"


def _top_3_issues(scraped: ScrapedWebsite) -> str:
    if not scraped.issue_signals:
        return ""
    return ", ".join(scraped.issue_signals[:3])


def _business_impact(found: FoundLead, top_issue: str, angle_bucket: str) -> str:
    city = found.city or "the area"
    if angle_bucket in {"No Booking Funnel", "Too Many CTAs"}:
        return f"For patients comparing clinics in {city}, unclear booking paths can lose attention before someone ever books."
    if angle_bucket == "Weak Mobile Experience":
        return f"Interested patients on mobile may drop off before calling if the experience feels clunky or hard to scan."
    if angle_bucket == "Outdated Website":
        return f"An outdated or low-trust experience can reduce confidence quickly for patients comparing options in {city}."
    if angle_bucket == "No Multilingual Support":
        return f"Patients in {city} who prefer another language may not feel fully comfortable moving forward."
    if angle_bucket == "Poor Content Structure":
        return f"If the site is hard to scan, the clinic can lose attention before visitors understand the strongest reasons to book."
    if "local discovery" in top_issue.lower():
        return f"Patients in {city} may not immediately see why the clinic is the relevant local choice when they search on Google or Maps."
    if "faq/schema" in top_issue.lower():
        return f"Without stronger structured answers, the clinic can miss opportunities to look clearer in search and AI-assisted discovery."
    if "trust proof" in top_issue.lower() or "trust signals" in top_issue.lower():
        return f"If trust proof is thin, patients comparing clinics in {city} may hesitate before they ever reach the booking step."
    return f"The site has room to make the patient journey clearer and easier to act on around {top_issue.lower()}."


def _recommended_fix(found: FoundLead, scraped: ScrapedWebsite, angle_bucket: str) -> str:
    if angle_bucket in {"No Booking Funnel", "Too Many CTAs"}:
        return "Clarify the booking path, reduce competing CTAs, and make the next step obvious."
    if angle_bucket == "Weak Mobile Experience":
        return "Tighten the mobile layout and make primary actions easier to tap."
    if angle_bucket == "Outdated Website":
        return "Refresh the trust signals, structure, and visual hierarchy so the site feels current."
    if angle_bucket == "No Multilingual Support":
        return "Make the key patient paths easier to understand for multilingual visitors."
    if angle_bucket == "Poor Content Structure":
        return "Restructure services, trust signals, and FAQs so the site scans faster."
    if "local discovery" in angle_bucket.lower():
        return "Surface the clinic's local presence more clearly with map, location, and nearby-search signals."
    if "trust" in angle_bucket.lower():
        return "Add clearer trust proof, reviews, and confidence signals near the main booking path."
    if "faq" in angle_bucket.lower() or "schema" in angle_bucket.lower():
        return "Add clearer FAQ structure and schema-friendly answers so the site is easier to scan."
    if scraped.services:
        return "Clarify the strongest services and make the booking flow easier to follow."
    return "Clean up the site structure so visitors can get to the right next step faster."


def _email_angle(found: FoundLead, angle_bucket: str) -> str:
    city = found.city or "their local market"
    if angle_bucket in {"No Booking Funnel", "Too Many CTAs"}:
        return f"For patients comparing clinics in {city}, the clearer the booking path, the less likely they are to keep comparing."
    if angle_bucket == "No Multilingual Support":
        return f"In {city}, a multilingual signal can matter for patients deciding who feels easiest to choose."
    if angle_bucket == "Poor Content Structure":
        return f"For patients comparing clinics in {city}, clearer structure can make the site easier to understand and act on."
    return f"For patients comparing clinics in {city}, clarity and trust can decide who gets picked first."


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
    strengths = _strengths(found, scraped)
    subject_angle = _subject_angle(found, scraped, angle_bucket)
    patient_type_location_angle = _patient_type_location_angle(found, scraped)
    top_3_issues = _top_3_issues(scraped)
    business_impact = _business_impact(found, top_issue, angle_bucket)
    recommended_fix = _recommended_fix(found, scraped, angle_bucket)
    email_angle = _email_angle(found, angle_bucket)
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
        country=getattr(settings, "country_scope", "Canada") or "Canada",
        province=getattr(settings, "active_province", ""),
        subject_angle=subject_angle,
        clinic_strengths=", ".join(strengths),
        strongest_advantage=strengths[0] if strengths else "",
        patient_type_location_angle=patient_type_location_angle,
        top_3_issues=top_3_issues,
        business_impact=business_impact,
        recommended_fix=recommended_fix,
        email_angle=email_angle,
        loom_link="",
        send_mode=getattr(settings, "send_mode", "auto_draft"),
        auto_send_eligible=False,
        duplicate_status="Unique",
        duplicate_reason="",
        gmail_match_status="",
        gmail_draft_id="",
        gmail_thread_id="",
        gmail_sent_status="",
        admin_approved=False,
        casl_basis="",
        contact_page_url=scraped.contact_page_url,
        booking_url=scraped.booking_url,
        languages=", ".join(scraped.languages),
        services=", ".join(scraped.services),
    )
