# Anvis Lead Scraper

This package finds local Canadian leads, scrapes their websites, audits conversion basics, deduplicates against Notion, and writes qualified leads into the Outreach Tracker with `Outreach Status = New Lead`.

It does not create Gmail drafts and does not send email.

## Setup

Add these values to `.env`:

```bash
NOTION_API_KEY=
NOTION_DATABASE_ID=
GOOGLE_PLACES_API_KEY=
PAGESPEED_API_KEY=
OPENAI_API_KEY=
COUNTRY_SCOPE=Canada
ACTIVE_PROVINCE=Ontario
ACTIVE_CITY=Toronto
ONE_CITY_PER_RUN=true
LEAD_SCRAPER_NICHE=dental clinic
LEAD_SCRAPER_LOCATIONS=Toronto
LEAD_SCRAPER_QUERIES=dental clinic, dentist, cosmetic dentist, family dentist, dental office
MAX_NEW_LEADS_PER_RUN=15
MAX_PLACES_RESULTS_PER_LOCATION=20
MAX_TOTAL_CANDIDATES=60
SCRAPER_REQUEST_TIMEOUT_SECONDS=12
FILTER_FRANCHISES=true
MIN_LEAD_SCORE=3
DRY_RUN=true
CITY_DUPLICATE_RATE_LIMIT=0.70
CITY_MIN_USABLE_EMAIL_RATE=0.15
CITY_WEAK_BATCH_LIMIT=3
CITY_TARGET_USABLE_LEADS=300
MAX_DAILY_PLACES_REQUESTS=1000
MAX_WEEKLY_PLACES_REQUESTS=3000
MAX_MONTHLY_PLACES_REQUESTS=10000
MAX_WEEKLY_RAW_PLACE_RESULTS=1000
MAX_WEEKLY_PLACE_DETAILS_CALLS=750
MAX_WEEKLY_UNIQUE_LEADS=300
MAX_WEEKLY_GMAIL_DRAFTS=75
```

`PAGESPEED_API_KEY` and `OPENAI_API_KEY` are optional. PageSpeed is not required for a run; when it is not configured the scraper records `PageSpeed not checked`.

Install dependencies:

```bash
pip install -r requirements.txt
```

Run:

```bash
python agents/run_lead_scraper.py
```

## Flow

1. Search Google Places using the active city only.
2. Stay within Canada.
3. Skip records with no website.
4. Normalize domains for deduplication.
5. Check existing Notion records by place ID, domain, phone, and name plus city.
6. Skip contacted or closed duplicates.
7. Enrich early-stage duplicates when new data is better.
8. Scrape homepage and likely contact/about/team/services pages.
9. Visit the homepage plus common contact/about pages to extract email, phone, booking URL, services, languages, and social links.
10. Generate `Top Issue`, `Outreach Angle`, `Recommended Offer`, and `Lead Quality Score`.
11. Continue processing until `MAX_NEW_LEADS_PER_RUN` accepted leads are inserted/enriched, `MAX_TOTAL_CANDIDATES` is reached, or the candidate pool is exhausted.
12. Write qualified leads with `Outreach Status = New Lead`.
13. Write a daily log to `logs/lead_scraper_YYYY-MM-DD.log`.

## Notion Fields

The writer uses existing Notion fields only. It skips fields that do not exist and never changes the Notion schema.

Expected fields:

- Business Name
- Country
- Province
- Niche
- City
- Website
- Domain
- Email
- Phone
- Address
- Google Maps URL
- Rating
- Review Count
- Top Issue
- Outreach Angle
- Recommended Offer
- Lead Quality Score
- Website Status
- Source
- Last Scraped Date
- Scrape Notes
- Outreach Status
