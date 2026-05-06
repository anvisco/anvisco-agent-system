# Outreach Ops

This runbook documents the current Anvis outreach workflow using the scripts already in this repo. It reflects the current checkpoint:

- Gmail OAuth scopes fixed
- Email copy and safety fixed
- Gmail draft redraft tool exists
- CASL backfill tool exists
- approved Gmail draft sender works
- sent messages get `Anvis/Leads` label after send
- stale and non-active draft reconciliation exists
- reply checker handles stale Gmail threads cleanly
- Notion views are cleaned
- canonical Notion field alignment Phase 1 is done

## 1. System Overview

- `agents/run_lead_scraper.py` finds leads for one active city at a time and writes qualified records to Notion.
- `agents/validate_outreach_notion.py` checks Notion readiness before drafting or sending.
- `agents/generate_drafts_from_notion.py --mode email1` generates first-touch Gmail drafts and updates Notion draft state.
- `agents/redraft_existing_gmail_drafts.py` repairs stale or invalid draft bodies without changing the outreach strategy.
- `agents/backfill_casl_basis.py` classifies CASL basis and marks manual review vs rule-sendable records.
- `agents/reconcile_gmail_drafts_with_notion.py` reconciles stale or non-active drafts before send.
- `agents/send_approved_gmail_drafts.py` performs dry-run or live gated sending.
- `agents/check_gmail_replies.py` checks Gmail threads for real replies and marks Notion replied only when appropriate.
- `agents/generate_drafts_from_notion.py --mode followups` handles due follow-up draft generation.

Canonical Notion fields are the primary source of truth:

- `Lead Status`
- `Gmail Sent Status`
- `Gmail Match Status`
- `CASL Basis`
- `Duplicate Status`
- `Send Mode`
- `Top Issue`
- `Outreach Angle`
- `Last Outreach Date`
- `Next Follow-up Date`

Legacy compatibility fields are still accepted where the scripts support them:

- `Outreach Status`
- `Reply Status`
- `Sequence Step`
- `Last Email Sent At`

## 2. Daily Operator Checklist

1. Pick one active city only.
2. Run the city scraper.
3. Validate the Notion queue.
4. Generate drafts for Email 1.
5. Inspect the draft batch.
6. Redraft any stale or weak drafts.
7. Backfill CASL basis.
8. Dry-run the send step.
9. Reconcile if dry-run shows stale or non-active drafts.
10. Run live send in batches of 10 or 20 only when the dry-run is clean.
11. Run the reply checker after sends.
12. Queue follow-up drafts when they become due.

## 3. City Queue Workflow

- Keep `ONE_CITY_PER_RUN=true`.
- Keep `ACTIVE_CITY` and `ACTIVE_PROVINCE` pointed at the one city you are working.
- Do not mix multiple active cities in one scraping session.
- Finish the current city queue before moving on.
- Use the scraper logs to confirm the active city and the city saturation metrics before widening the queue.

## 4. Lead Scrape Workflow

- Run the lead scraper only for the active city.
- Stay within Canada.
- Avoid creating drafts or sending anything during scrape.
- Let the scraper write only the lead records and audit fields it already owns.
- Use the scraper to populate the outreach foundation fields, including `Top Issue` and `Outreach Angle`.

## 5. Validation Workflow

- Validate the queue before draft generation or live send.
- Use validation to catch missing required fields, duplicate groups, and records that are not ready for outreach.
- Do not try to rescue records that are obviously blocked by `not_fit`, `archived`, `paid_client`, or `Do Not Contact`.

## 6. Draft Generation Workflow

- Run `agents/generate_drafts_from_notion.py --mode email1` for first-touch drafting.
- Use `--mode followups` only for due follow-up drafts.
- Draft generation should never auto-send.
- Draft generation should respect `Lead Status`, `Gmail Sent Status`, `Gmail Match Status`, `CASL Basis`, `Duplicate Status`, and `Send Mode`.
- Treat `CASL Basis = manual_research_needed` as not auto-sendable.
- Treat `CASL Basis = conspicuously_published_business_email` as rule-sendable if every other gate passes.

## 7. Draft Inspection Checklist

- Confirm the subject line matches the lead and the city.
- Confirm the opening sentence is specific and not generic.
- Confirm the body references the clinic’s actual site or booking context.
- Confirm no disallowed claims were introduced.
- Confirm the draft is still addressed to the correct lead email.
- Confirm the draft is not for a blocked record.
- Confirm the draft is suitable for the current stage before redraft or send.

## 8. Redraft Workflow

- Use `agents/redraft_existing_gmail_drafts.py` when an existing draft is stale, broken, or no longer matches the lead state.
- Redraft does not replace the outreach logic with a new campaign.
- Redraft should preserve the existing record relationship and thread intent.
- Do not manually delete `Gmail Draft ID` from Notion to force a rebuild.
- Let reconciliation and redraft scripts handle stale draft IDs.

## 9. CASL Backfill Workflow

- Use `agents/backfill_casl_basis.py` to classify outreach compliance basis.
- `CASL Basis = conspicuously_published_business_email` is the automated rule-sendable path.
- `CASL Basis = manual_research_needed` means the record needs human review and should not be auto-sent.
- Do not force-send records that remain manual.
- Keep `Do Not Contact`, `archived`, `paid_client`, and `not_fit` records blocked.

## 10. Send Dry-Run Workflow

- Always dry-run before live send.
- The dry-run should show which records would be sent without creating outbound mail.
- Use the dry-run result to identify stale or non-active drafts.
- If the dry-run shows stale or non-active drafts, run reconciliation before sending.
- Never live send until the dry-run is clean.

## 11. Live Send Workflow

- Live send is gated.
- Send in batches of 10 or 20.
- Do not exceed the batch cap in one run.
- Send only approved records that pass all safety checks.
- Do not auto-send during scrape or draft generation.
- Do not bulk edit sent, replied, archived, paid_client, or do-not-contact records.

## 12. Reconciliation Workflow

- Run reconciliation when draft IDs are stale, missing, or no longer active.
- Reconciliation is the repair step before send.
- Reconciliation may rebuild draft state and align Notion with the active Gmail draft.
- Do not manually clear or delete `Gmail Draft ID` in Notion.
- If reconciliation finds a stale draft path, fix that before attempting live send.

## 13. Reply Check Workflow

- Run `agents/check_gmail_replies.py` after sends.
- If the reply checker is being tested, set `DRY_RUN=true`.
- The checker must not treat stale Gmail thread IDs as replies.
- The checker must skip stale Gmail thread IDs cleanly.
- The checker should update Notion only when a real reply is found.
- The checker should not clear `Gmail Thread ID`.
- The checker should preserve reply protection for `replied`, `closed`, `call booked`, `not interested`, `do not contact`, `archived`, `paid_client`, and `not_fit`.

## 14. Follow-up Workflow Placeholder

- Follow-up drafting already exists in `agents/generate_drafts_from_notion.py --mode followups`.
- Use the follow-up queue only after the first-touch batch and reply check flow are settled.
- Keep follow-ups tied to `Next Follow-up Date` and the current outreach state.
- Do not turn follow-up handling into an auto-send step without an explicit gate.

## 15. Notion Field Meanings

- `Lead Status`: canonical lead state; primary gate for outreach progression.
- `Gmail Sent Status`: whether an outbound Gmail send has actually occurred.
- `Gmail Match Status`: whether Gmail state matches the expected outreach state.
- `CASL Basis`: compliance basis for email eligibility.
- `Duplicate Status`: duplicate-control state.
- `Send Mode`: whether the record is draft-only, rule-gated, or auto-send-gated.
- `Top Issue`: the main problem the outreach message should mention.
- `Outreach Angle`: the framing used in the email copy.
- `Last Outreach Date`: the last send date used by draft and reply logic.
- `Next Follow-up Date`: the next scheduled follow-up date.

Legacy compatibility fields:

- `Outreach Status`: accepted by older scripts when canonical `Lead Status` is missing.
- `Reply Status`: legacy reply marker used by older flows.
- `Sequence Step`: legacy sequence marker used by older flows.
- `Last Email Sent At`: legacy date field accepted by some scripts.

## 16. Gmail Label Behavior

- Sent messages get the `Anvis/Leads` label after send.
- Reconciled or rebuilt drafts keep the outreach label behavior consistent where supported.
- Do not depend on labels as the only source of truth.
- Notion remains the operational source of truth for lead state and send state.

## 17. Troubleshooting

- If the scraper is noisy, confirm the active city is correct and only one city is enabled.
- If draft generation skips too much, validate Notion fields first.
- If send dry-run shows stale drafts, run reconciliation before live send.
- If CASL backfill marks many records manual, do not override that to force send.
- If reply checking shows stale Gmail thread IDs, that should now be counted separately and skipped.
- If a record is blocked by `Do Not Contact`, `archived`, `paid_client`, or `not_fit`, leave it alone.

## 18. Safe Stop Rules

- Stop if the active city is wrong.
- Stop if validation shows the queue is not ready.
- Stop if draft inspection reveals generic or unsafe copy.
- Stop if reconciliation shows stale or non-active drafts that still need repair.
- Stop if CASL basis is `manual_research_needed`.
- Stop if the dry-run is not clean.
- Stop if a record is sent, replied, archived, paid_client, or do-not-contact.
- Stop if a script asks for a manual gate you have not completed yet.

## 19. Exact PowerShell Commands

Use the repo venv:

```powershell
.\.venv\Scripts\python.exe agents\validate_outreach_notion.py

$env:DRY_RUN="true"
$env:ACTIVE_CITY="Toronto"
$env:ACTIVE_PROVINCE="Ontario"
$env:ONE_CITY_PER_RUN="true"
.\.venv\Scripts\python.exe agents\run_lead_scraper.py

$env:MAX_DRAFTS_PER_RUN="20"
.\.venv\Scripts\python.exe agents\generate_drafts_from_notion.py --mode email1

$env:REDRAFT_DRY_RUN="true"
$env:MAX_REDRAFTS_PER_RUN="5"
.\.venv\Scripts\python.exe agents\redraft_existing_gmail_drafts.py

$env:CASL_BACKFILL_DRY_RUN="true"
$env:MAX_CASL_BACKFILL="25"
.\.venv\Scripts\python.exe agents\backfill_casl_basis.py

$env:RECONCILE_DRY_RUN="true"
$env:MAX_RECONCILE_DRAFTS="20"
.\.venv\Scripts\python.exe agents\reconcile_gmail_drafts_with_notion.py

$env:SEND_DRY_RUN="true"
$env:SEND_APPROVED_DRAFTS="false"
$env:MAX_SENDS_PER_RUN="10"
.\.venv\Scripts\python.exe agents\send_approved_gmail_drafts.py

$env:SEND_DRY_RUN="false"
$env:SEND_APPROVED_DRAFTS="true"
$env:MAX_SENDS_PER_RUN="10"
.\.venv\Scripts\python.exe agents\send_approved_gmail_drafts.py

$env:DRY_RUN="true"
.\.venv\Scripts\python.exe agents\check_gmail_replies.py

.\.venv\Scripts\python.exe agents\generate_drafts_from_notion.py --mode followups
```

Suggested operating order for a normal session:

1. Validate.
2. Scrape one city.
3. Generate drafts.
4. Inspect and redraft.
5. Backfill CASL basis.
6. Dry-run send.
7. Reconcile if needed.
8. Live send in a capped batch.
9. Check replies.
10. Queue follow-ups when due.
