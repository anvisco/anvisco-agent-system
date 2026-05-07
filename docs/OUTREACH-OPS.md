# Outreach Ops

This runbook documents the current Anvis outreach workflow using the scripts already in this repo. It reflects the current checkpoint:

- Ops Status is the workflow source of truth
- `Blocker Reason` explains why a record is blocked
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

## Do Not Use As Approval Gate

- `Lead Status`
- `Outreach Status`
- `Auto-Send Eligible`
- `Sequence Step`
- `Reply Status`

These fields may remain for history, reporting, or compatibility, but they do not approve draft or send actions when Ops Status exists.

Legacy fields are scheduled for deletion and should not be treated as operating inputs:

- `Lead Status`
- `Outreach Status`
- `Auto-Send Eligible`
- `Admin Approved`
- `Send Mode`
- `Reply Status`

## 1. System Overview

- `agents/run_lead_scraper.py` finds leads for one active city at a time and writes qualified records to Notion.
- `agents/update_outreach_ops_status.py` refreshes `Ops Status` and `Blocker Reason`.
- `agents/validate_outreach_notion.py` checks Notion readiness before drafting or sending.
- `agents/generate_drafts_from_notion.py --mode email1` generates first-touch Gmail drafts only when `Ops Status = ready_to_draft`.
- `agents/redraft_existing_gmail_drafts.py` repairs stale or invalid draft bodies without changing the outreach strategy.
- `agents/backfill_casl_basis.py` classifies CASL basis and marks manual review vs rule-sendable records.
- `agents/reconcile_gmail_drafts_with_notion.py` reconciles stale or non-active drafts before send.
- `agents/send_approved_gmail_drafts.py` performs dry-run or live gated sending only when `Ops Status = ready_to_send`.
- `agents/check_gmail_replies.py` checks Gmail threads for real replies and marks Notion replied only when appropriate.
- `agents/generate_drafts_from_notion.py --mode followups` handles due follow-up draft generation.

Canonical Notion fields remain useful inputs, but they are not the approval gate when Ops Status exists:

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

## Safe Operating Order

1. Scrape or intake leads.
2. Run `agents/update_outreach_ops_status.py`.
3. Run `agents/outreach_health_check.py`.
4. Run `agents/generate_drafts_from_notion.py --mode email1`.
5. Run `agents/update_outreach_ops_status.py` again if draft state changed.
6. Send only records with `Ops Status = ready_to_send`.
7. Run `agents/reconcile_gmail_drafts_with_notion.py` for stale or non-active drafts.
8. Run `agents/check_gmail_replies.py`.
9. Run `agents/outreach_health_check.py` again.

## 2. Weekly Operator Checklist

1. Sunday: pick one active city only.
2. Sunday: run the city scraper.
3. Sunday: refresh Ops Status.
4. Sunday: check the health report.
5. Sunday: generate drafts for Email 1 only for `ready_to_draft`.
6. Sunday: inspect the draft batch.
7. Sunday: redraft any stale or weak drafts.
8. Sunday: backfill CASL basis.
9. Monday 8:00 AM ET: dry-run the send step before the first live run.
10. Monday 8:00 AM ET: reconcile if the dry-run shows stale or non-active drafts.
11. Monday 8:00 AM ET: live send only records that are `ready_to_send`.
12. Monday 8:00 AM ET: no send cap is applied in the scheduled send workflow.
13. Monday 8:00 AM ET: run the reply checker after sends.
14. Monday 8:00 AM ET: queue follow-up drafts when they become due.

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
- Draft generation should respect `Ops Status`, `Gmail Sent Status`, `Gmail Match Status`, `CASL Basis`, `Duplicate Status`, and `Send Mode`.
- Draft generation requires `Ops Status = ready_to_draft`.
- Treat `CASL Basis = manual_research_needed` as not auto-sendable.
- Treat `CASL Basis = conspicuously_published_business_email` as rule-sendable only if every other gate passes.

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
- Never live send until the dry-run is clean and `Ops Status = ready_to_send`.

## 11. Live Send Workflow

- Live send is gated.
- Send in the Monday 8:00 AM ET scheduled workflow.
- No send cap is applied in the scheduled workflow.
- Send only approved records that pass all safety checks and have `Ops Status = ready_to_send`.
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

- `Lead Status`: historical/classification field; do not use as the approval gate when `Ops Status` exists.
- `Gmail Sent Status`: whether an outbound Gmail send has actually occurred.
- `Gmail Match Status`: whether Gmail state matches the expected outreach state.
- `CASL Basis`: compliance basis for email eligibility.
- `Duplicate Status`: duplicate-control state.
- `Send Mode`: historical/classification field; do not use as the approval gate when `Ops Status` exists.
- `Top Issue`: the main problem the outreach message should mention.
- `Outreach Angle`: the framing used in the email copy.
- `Last Outreach Date`: the last send date used by draft and reply logic.
- `Next Follow-up Date`: the next scheduled follow-up date.

Legacy compatibility fields:

- `Outreach Status`: accepted by older scripts when canonical `Lead Status` is missing.
- `Reply Status`: legacy reply marker used by older flows.
- `Sequence Step`: legacy sequence marker used by older flows.
- `Last Email Sent At`: legacy date field accepted by some scripts.

## 15b. Ops Status Overlay

- `Ops Status` is the operational classifier output used to route a record to the next human or automated step.
- `Blocker Reason` stores the machine-readable blocker codes that explain why a record is not ready.
- Treat `Ops Status` as the source of truth for draft/send readiness.
- The ops classifier is dry-run by default and should only update these fields after you review the preview output.
- Do not use `Lead Status`, `Outreach Status`, `Auto-Send Eligible`, `Sequence Step`, or `Reply Status` as approval gates.
- Do not use `Ops Status` to overwrite `Lead Status`, `CASL Basis`, `Gmail Sent Status`, or `Gmail Match Status`.

## 16. Gmail Label Behavior

- Sent messages get the `Anvis/Leads` label after send.
- Reconciled or rebuilt drafts keep the outreach label behavior consistent where supported.
- Do not depend on labels as the only source of truth.
- Ops Status remains the operational source of truth for draft and send state.

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

## Preserve Email Copy

- `src/email_writer.py` is the source of outbound email copy.
- Do not rewrite the copy during ops cleanup.
- Keep wording changes separate from workflow or safety cleanup.

## 19. Exact PowerShell Commands

Use the repo venv:

```powershell
.\.venv\Scripts\python.exe agents\validate_outreach_notion.py

$env:DRY_RUN="true"
$env:ACTIVE_CITY="Toronto"
$env:ACTIVE_PROVINCE="Ontario"
$env:ONE_CITY_PER_RUN="true"
.\.venv\Scripts\python.exe agents\run_lead_scraper.py

$env:MAX_DRAFTS_PER_RUN="150"
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

$env:DRY_RUN="true"
$env:SEND_DRY_RUN="true"
$env:SEND_APPROVED_DRAFTS="true"
$env:ALLOW_RULE_BASED_APPROVAL="true"
$env:ALLOW_LEGACY_STATUS_FALLBACK="false"
.\.venv\Scripts\python.exe agents\send_approved_gmail_drafts.py

$env:DRY_RUN="false"
$env:SEND_DRY_RUN="false"
$env:SEND_APPROVED_DRAFTS="true"
$env:ALLOW_RULE_BASED_APPROVAL="true"
$env:ALLOW_LEGACY_STATUS_FALLBACK="false"
.\.venv\Scripts\python.exe agents\send_approved_gmail_drafts.py

$env:DRY_RUN="true"
.\.venv\Scripts\python.exe agents\check_gmail_replies.py

.\.venv\Scripts\python.exe agents\generate_drafts_from_notion.py --mode followups
```

Suggested weekly operating order for a normal session:

1. Sunday: validate.
2. Sunday: scrape one city.
3. Sunday: refresh Ops Status.
4. Sunday: generate drafts.
5. Sunday: inspect and redraft.
6. Sunday: backfill CASL basis.
7. Monday 8:00 AM ET: dry-run send.
8. Monday 8:00 AM ET: reconcile if needed.
9. Monday 8:00 AM ET: live send all ready_to_send records.
10. Monday 8:00 AM ET: check replies.
11. Monday 8:00 AM ET: queue follow-ups when due.
