# Anvis Agent Workflow

This document summarizes the current controlled outreach workflow for internal use.

## Defaults

- Brand: Anvis
- Domain: https://anvisco.com
- Email: brian@anvisco.com
- Default mode: Auto-Draft + Label
- Gated mode: Auto-Send
- Default label: `Anvis/Leads`

## Operating Rules

1. Draft before send is the default.
2. Auto-send is only allowed when all required checks pass.
3. Outreach copy must stay prospect-facing and avoid backend internals.
4. Gmail send-as alias verification must pass before auto-send.
5. Canada-only scraping with one active city per run.
6. Weekend-only scraping through GitHub Actions.

## Review Checkpoints

- Review first outreach before sending
- Review follow-ups before sending
- Review pricing and checkout links before sending
- Review any manual status change to paid client
- Review test-client deletions
- Review offer copy updates

## Labels and Records

- Apply `Anvis/Leads` to generated drafts and sent outreach where supported
- Use Notion as the source of truth
- Keep dedupe checks on website, email, phone, and name/location

## Safety

- Do not use manual payment links
- Do not expose Supabase, Stripe, Resend, webhooks, or secrets in prospect copy
- Do not promise rankings, bookings, revenue, SEO rankings, or guaranteed growth
