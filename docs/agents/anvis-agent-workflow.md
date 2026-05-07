# Anvis Agent Workflow

This document summarizes the current controlled outreach workflow for internal use.

## Defaults

- Brand: Anvis
- Domain: https://anvisco.com
- Email: brian@anvisco.com
- Default mode: Auto-Draft + Label
- Gated mode: Auto-Send
- Default label: `Anvis/Leads`
- Workflow source of truth: `Ops Status`

## Operating Rules

1. Draft before send is the default.
2. Auto-send is only allowed when all required checks pass and `Ops Status = ready_to_send`.
3. Outreach copy must stay prospect-facing and avoid backend internals.
4. Gmail send-as alias verification must pass before auto-send.
5. Canada-only scraping with one active city per run.
6. Weekend-only scraping through GitHub Actions.

## Do Not Use As Approval Gate

- `Lead Status`
- `Outreach Status`
- `Auto-Send Eligible`
- `Sequence Step`
- `Reply Status`

These are historical or compatibility fields only.

Legacy fields are deprecated and should not be used as operating inputs:

- `Lead Status`
- `Outreach Status`
- `Auto-Send Eligible`
- `Admin Approved`
- `Send Mode`
- `Reply Status`

## Review Checkpoints

- Review first outreach before sending
- Review follow-ups before sending
- Review pricing and checkout links before sending
- Review any manual status change to paid client
- Review test-client deletions
- Review offer copy updates

## Labels and Records

- Apply `Anvis/Leads` to generated drafts and sent outreach where supported
- Use `Ops Status` as the source of truth for draft and send readiness
- Keep dedupe checks on website, email, phone, and name/location

## Safe Operating Order

1. Sunday: scrape or intake leads.
2. Sunday: refresh `Ops Status`.
3. Sunday: check the health report.
4. Sunday: generate drafts only for `ready_to_draft`.
5. Sunday: refresh `Ops Status` again after draft state changes.
6. Monday 8:00 AM ET: send only `ready_to_send`.
7. Monday 8:00 AM ET: reconcile stale drafts.
8. Monday 8:00 AM ET: check replies.
9. Monday 8:00 AM ET: re-run the health report.

## Safety

- Do not use manual payment links
- Do not expose Supabase, Stripe, Resend, webhooks, or secrets in prospect copy
- Do not promise rankings, bookings, revenue, SEO rankings, or guaranteed growth
- Scheduled sending exists now, but only for `Ops Status = ready_to_send`.
- Preserve outbound email copy in `src/email_writer.py`; do not rewrite it during workflow cleanup.
