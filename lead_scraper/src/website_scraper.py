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
    keywords = ("contact", "about", "team", "doctor", "dentist", "service")
    links: list[str] = []
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        text = f"{href} {anchor.get_text(' ', strip=True)}".lower()
        if any(keyword in text for keyword in keywords):
            absolute = urljoin(base_url, href)
            if normalize_domain(absolute) == normalize_domain(base_url):
                links.append(absolute)
    unique: list[str] = []
    for link in links:
        if link not in unique:
            unique.append(link)
    return unique[:4]


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

    for link in _candidate_links(final_url, soup):
        page_html, _, page_url = _fetch(link)
        if page_html:
            pages.append((page_url, BeautifulSoup(page_html, "html.parser")))

    all_text = "\n".join(page_soup.get_text(" ", strip=True) for _, page_soup in pages)
    all_html_text = "\n".join(str(page_soup) for _, page_soup in pages)

    emails = [email for email in EMAIL_RE.findall(all_text) if not email.lower().endswith((".png", ".jpg"))]
    phones = PHONE_RE.findall(all_text)
    scraped.email = emails[0] if emails else ""
    scraped.phone = display_phone(phones[0]) if phones and not scraped.phone else scraped.phone
    scraped.contact_page_url = next((url for url, _ in pages if "contact" in url.lower()), "")
    scraped.booking_url = next((_extract_booking_url(url, page_soup) for url, page_soup in pages if _extract_booking_url(url, page_soup)), "")
    scraped.social_links = _extract_social_links(soup)
    scraped.mobile_friendly = "yes" if soup.find("meta", attrs={"name": "viewport"}) else "partial"
    scraped.languages = sorted({keyword.title() for keyword in LANGUAGE_KEYWORDS if keyword in all_text.lower()})
    scraped.services = sorted({keyword.title() for keyword in SERVICE_KEYWORDS if keyword in all_text.lower()})
    scraped.issue_signals = _detect_issue_signals(all_text, soup, scraped.booking_url)

    return scraped
