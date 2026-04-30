from __future__ import annotations

import re
import time
from typing import Iterable, List, Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from .config import settings
from .models import FoundLead, ScrapedWebsite
from .utils import clean_phone, display_phone, normalize_domain


EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
PHONE_RE = re.compile(r"(?:\+?1[\s.-]?)?(?:\(?\d{3}\)?[\s.-]?)\d{3}[\s.-]?\d{4}")
LANGUAGE_KEYWORDS = ("english", "french", "spanish", "mandarin", "cantonese", "farsi", "arabic", "hindi", "urdu", "tagalog")
SERVICE_KEYWORDS = ("implant", "invisalign", "orthodont", "cosmetic", "emergency", "cleaning", "whitening", "root canal", "denture")
COMMON_EMAIL_PATHS = ("/contact", "/contact-us", "/about", "/team", "/new-patients")
PREFERRED_EMAIL_PREFIXES = ("info", "admin", "reception", "hello", "appointments")
BAD_EMAIL_LOCAL_TOKENS = ("no-reply", "noreply", "donotreply", "do-not-reply", "privacy")
BAD_EMAIL_LOCALS = ("example", "test")
WEBSITE_BUILDER_DOMAINS = (
    "wix.com",
    "wixpress.com",
    "squarespace.com",
    "wordpress.com",
    "weebly.com",
    "godaddy.com",
    "webflow.com",
    "shopify.com",
)


def _ensure_url(url: str) -> str:
    if not url:
        return ""
    return url if url.startswith(("http://", "https://")) else f"https://{url}"


def _fetch(url: str) -> tuple[Optional[str], float, str]:
    start = time.monotonic()
    try:
        response = requests.get(
            url,
            timeout=settings.request_timeout_seconds,
            headers={"User-Agent": "Mozilla/5.0 AnviscoLeadScraper/1.0"},
        )
        elapsed = time.monotonic() - start
        response.raise_for_status()
        return response.text, elapsed, response.url
    except requests.RequestException:
        return None, time.monotonic() - start, url


def _candidate_links(base_url: str, soup: BeautifulSoup) -> list[str]:
    keywords = ("contact", "about", "team", "doctor", "dentist", "service", "new-patient")
    links: list[str] = []
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        if href.lower().startswith("mailto:"):
            continue
        text = f"{href} {anchor.get_text(' ', strip=True)}".lower()
        if any(keyword in text for keyword in keywords):
            absolute = urljoin(base_url, href)
            if normalize_domain(absolute) == normalize_domain(base_url):
                links.append(absolute)
    unique: list[str] = []
    for link in links:
        if link not in unique:
            unique.append(link)
    return unique[:6]


def _common_page_links(base_url: str) -> list[str]:
    return [urljoin(base_url, path) for path in COMMON_EMAIL_PATHS]


def _clean_email(email: str) -> str:
    return email.strip().strip(".,;:()[]<>\"'").lower()


def _is_website_builder_domain(domain: str) -> bool:
    return any(domain == builder or domain.endswith(f".{builder}") for builder in WEBSITE_BUILDER_DOMAINS)


def _is_bad_email(email: str) -> bool:
    local, separator, domain = email.partition("@")
    if not separator or not local or not domain:
        return True
    if domain.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg")):
        return True
    if any(token in local for token in BAD_EMAIL_LOCAL_TOKENS):
        return True
    if local in BAD_EMAIL_LOCALS or domain.startswith(("example.", "test.")):
        return True
    if _is_website_builder_domain(domain):
        return True
    return False


def _emails_from_mailto(href: str) -> list[str]:
    if not href.lower().startswith("mailto:"):
        return []
    address_part = href.split(":", 1)[1].split("?", 1)[0]
    return EMAIL_RE.findall(address_part)


def _extract_emails_from_page(soup: BeautifulSoup) -> list[str]:
    emails = EMAIL_RE.findall(soup.get_text(" ", strip=True))
    for anchor in soup.find_all("a", href=True):
        emails.extend(_emails_from_mailto(anchor["href"]))
    return emails


def _email_preference_index(email: str) -> int:
    local = email.split("@", 1)[0]
    for index, prefix in enumerate(PREFERRED_EMAIL_PREFIXES):
        if local == prefix or local.startswith(f"{prefix}.") or local.startswith(f"{prefix}-"):
            return index
    return len(PREFERRED_EMAIL_PREFIXES)


def _rank_emails(emails: Iterable[str], website_domain: str) -> list[str]:
    unique: list[str] = []
    for email in emails:
        cleaned = _clean_email(email)
        if cleaned and cleaned not in unique and not _is_bad_email(cleaned):
            unique.append(cleaned)

    def sort_key(email: str) -> tuple[int, int, int]:
        email_domain = email.split("@", 1)[1]
        is_same_domain = email_domain == website_domain or email_domain.endswith(f".{website_domain}")
        preference = _email_preference_index(email)
        return (preference, 0 if is_same_domain else 1, unique.index(email))

    return sorted(unique, key=sort_key)


def _extract_booking_url(base_url: str, soup: BeautifulSoup) -> str:
    for anchor in soup.find_all("a", href=True):
        text = f"{anchor.get_text(' ', strip=True)} {anchor['href']}".lower()
        if any(keyword in text for keyword in ("book", "appointment", "schedule", "request")):
            return urljoin(base_url, anchor["href"])
    return ""


def _extract_social_links(soup: BeautifulSoup) -> list[str]:
    links: list[str] = []
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        if any(host in href.lower() for host in ("facebook.com", "instagram.com", "linkedin.com", "youtube.com")):
            links.append(href)
    return sorted(set(links))


def _detect_issue_signals(text: str, soup: BeautifulSoup, booking_url: str) -> list[str]:
    lower = text.lower()
    cta_words = sum(lower.count(word) for word in ("book", "call", "contact", "request", "schedule"))
    signals: list[str] = []

    if not booking_url:
        signals.append("no booking funnel")
    if cta_words > 12:
        signals.append("too many CTAs")
    if len(text) > 9000:
        signals.append("too much content without structure")
    if "covid" in lower:
        signals.append("outdated COVID messaging")
    if "implant" in lower or "invisalign" in lower:
        signals.append("high-value services could be framed more clearly")
    if not soup.find("meta", attrs={"name": "viewport"}):
        signals.append("weak mobile layout")
    if not any(keyword in lower for keyword in LANGUAGE_KEYWORDS):
        signals.append("no multilingual support mentioned")
    if "contact" not in lower and not booking_url:
        signals.append("contact path is buried or missing")

    return signals


def scrape_website(found: FoundLead) -> ScrapedWebsite:
    website = _ensure_url(found.website)
    domain = normalize_domain(website)
    scraped = ScrapedWebsite(
        website_url=website,
        domain=domain,
        business_name=found.business_name,
        phone=found.phone,
        https_active=website.startswith("https://"),
        pagespeed_score=None,
        technical_notes=["PageSpeed not checked"],
    )

    html, elapsed, final_url = _fetch(website)
    if not html:
        scraped.website_status = "failed to load"
        scraped.technical_notes.append("Website failed to load")
        return scraped

    scraped.website_status = "slow" if elapsed > 4 else "loads"
    scraped.website_url = final_url
    soup = BeautifulSoup(html, "html.parser")
    pages = [(final_url, soup)]

    page_links: list[str] = []
    for link in [*_common_page_links(final_url), *_candidate_links(final_url, soup)]:
        if link not in page_links:
            page_links.append(link)

    for link in page_links:
        page_html, _, page_url = _fetch(link)
        if page_html:
            pages.append((page_url, BeautifulSoup(page_html, "html.parser")))

    all_text = "\n".join(page_soup.get_text(" ", strip=True) for _, page_soup in pages)

    emails = _rank_emails((email for _, page_soup in pages for email in _extract_emails_from_page(page_soup)), domain)
    phones = PHONE_RE.findall(all_text)
    scraped.found_emails = emails
    scraped.email = emails[0] if emails else ""
    if emails:
        scraped.technical_notes.append(f"Emails found on website: {', '.join(emails)}")
    else:
        scraped.technical_notes.append("No email found on website")
    scraped.phone = display_phone(phones[0]) if phones and not scraped.phone else scraped.phone
    scraped.contact_page_url = next((url for url, _ in pages if "contact" in url.lower()), "")
    scraped.booking_url = next((_extract_booking_url(url, page_soup) for url, page_soup in pages if _extract_booking_url(url, page_soup)), "")
    scraped.social_links = _extract_social_links(soup)
    scraped.mobile_friendly = "yes" if soup.find("meta", attrs={"name": "viewport"}) else "partial"
    scraped.languages = sorted({keyword.title() for keyword in LANGUAGE_KEYWORDS if keyword in all_text.lower()})
    scraped.services = sorted({keyword.title() for keyword in SERVICE_KEYWORDS if keyword in all_text.lower()})
    scraped.issue_signals = _detect_issue_signals(all_text, soup, scraped.booking_url)

    return scraped
