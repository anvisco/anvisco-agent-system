# Gmail Setup

1. Enable the Gmail API in Google Cloud.
2. Create OAuth Desktop App credentials.
3. Download the JSON credentials file.
4. Rename it to `gmail_credentials.json`.
5. Put it inside `credentials/`.
6. Run:

```bash
python agents/test_gmail_draft.py
```

If you need help locating and installing the OAuth JSON first, run:

```bash
python agents/setup_gmail_credentials.py
```

The first successful OAuth run creates `credentials/gmail_token.json`.

This system only creates Gmail drafts. It does not send emails automatically.

# Lead Scraper

Run the lead scraper with:

```bash
python agents/run_lead_scraper.py
```

Details are in `lead_scraper/README.md`.

# Daily Outreach Automation

Run the full daily workflow with:

```bash
npm run outreach:daily
```

This runs, in order:

1. Lead scraper
2. Notion validation
3. Email 1 draft creation
4. Gmail reply checker
5. Follow-up draft checker
6. Daily log writing under `logs/`

Dry run:

```bash
npm run outreach:daily -- --dry-run
```

Dry run sets `DRY_RUN=true` and `CREATE_GMAIL_DRAFTS=false`, so it prints what would happen without writing to Notion or Gmail.

Dry run with Notion writes but no Gmail drafts:

```bash
npm run outreach:daily -- --dry-run --write
```

Individual phases:

```bash
npm run scraper:daily
npm run drafts:create
npm run replies:check
npm run followups:check
```

The system never sends email automatically. Gmail is used only to create drafts and detect replies.

For GitHub Actions, add these repository secrets:

- `NOTION_API_KEY`
- `NOTION_DATABASE_ID`
- `GOOGLE_PLACES_API_KEY`
- `PAGESPEED_API_KEY` optional
- `OPENAI_API_KEY`
- `GMAIL_CLIENT_ID`
- `GMAIL_CLIENT_SECRET`
- `GMAIL_REFRESH_TOKEN`

The workflow file is `.github/workflows/outreach-daily.yml`. It runs once per weekday morning and can also be triggered manually.

Gmail OAuth for scheduled runs must include:

- `https://www.googleapis.com/auth/gmail.compose`
- `https://www.googleapis.com/auth/gmail.readonly`

If your existing local `credentials/gmail_token.json` was created before reply detection was added, delete it and rerun the Gmail setup so the token includes the readonly scope.
