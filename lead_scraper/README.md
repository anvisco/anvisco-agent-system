# Anvisco Lead Scraper

This package finds local dental clinic leads, scrapes their websites, audits the website basics, deduplicates against Notion, and writes qualified leads into the Outreach Tracker with `Outreach Status = New Lead`.

It does not create Gmail drafts and does not send email.

## Setup

Add these values to `.env`:

```bash
NOTION_API_KEY=
NOTION_DATABASE_ID=
GOOGLE_PLACES_API_KEY=
PAGESPEED_API_KEY=
OPENAI_API_KEY=
LEAD_SCRAPER_NICHE=dental clinic
LEAD_SCRAPER_LOCATIONS=Toronto, North York, Willowdale, Scarborough, Etobicoke, Markham, Vaughan, Richmond Hill, Thornhill, Mississauga, Brampton, East York, York, Leaside, Midtown Toronto, Downtown Toronto
LEAD_SCRAPER_QUERIES=dental clinic, dentist, cosmetic dentist, family dentist, dental office
MAX_NEW_LEADS_PER_RUN=15
MAX_PLACES_RESULTS_PER_LOCATION=20
MAX_TOTAL_CANDIDATES=60
SCRAPER_REQUEST_TIMEOUT_SECONDS=12
FILTER_FRANCHISES=true
MIN_LEAD_SCORE=3
DRY_RUN=true
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

1. Search Google Places using the configured location and query rotation.
2. Skip records with no website.
3. Normalize domains for deduplication.
4. Check existing Notion records by domain, email, phone, then business name plus city.
5. Skip contacted or closed duplicates.
6. Enrich early-stage duplicates when new data is better.
7. Scrape homepage and likely contact/about/team/services pages.
8. Extract email, phone, booking URL, services, languages, and social links.
9. Generate `Top Issue`, `Outreach Angle`, `Recommended Offer`, and `Lead Quality Score`.
10. Continue processing until `MAX_NEW_LEADS_PER_RUN` accepted leads are inserted/enriched, `MAX_TOTAL_CANDIDATES` is reached, or the candidate pool is exhausted.
11. Write qualified leads with `Outreach Status = New Lead`.
12. Write a daily log to `logs/lead_scraper_YYYY-MM-DD.log`.

`MAX_NEW_LEADS_PER_RUN` controls the target accepted lead count. `MAX_PLACES_RESULTS_PER_LOCATION` controls the Google Places search pool per location. `MAX_TOTAL_CANDIDATES` is the hard safety cap that prevents uncapped scraping.

## Notion Fields

The writer uses existing Notion fields only. It skips fields that do not exist and never changes the Notion schema.

Expected fields:

- Business Name
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
