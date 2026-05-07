# Anvis Workflow

Last updated: 2026-05-05

## Operating Principle

Ops Status is the workflow source of truth. Gmail is used for drafts and reply detection. Brian reviews and sends manually unless the gated send path is explicitly enabled.

Keep the system simple, inspectable, and draft-first by default.

## Do Not Use As Approval Gate

- `Lead Status`
- `Outreach Status`
- `Auto-Send Eligible`
- `Sequence Step`
- `Reply Status`

These are historical, reporting, or compatibility inputs only when Ops Status exists.

Legacy workflow fields are deprecated and scheduled for deletion:

- `Lead Status`
- `Outreach Status`
- `Auto-Send Eligible`
- `Admin Approved`
- `Send Mode`
- `Reply Status`

## Safe Operating Order

1. Sunday: scrape or intake leads.
2. Sunday: run `agents/update_outreach_ops_status.py`.
3. Sunday: run `agents/generate_drafts_from_notion.py`.
4. Sunday: run the health check.
5. Monday 8:00 AM ET: run `agents/update_outreach_ops_status.py` again.
6. Monday 8:00 AM ET: send only records with `Ops Status = ready_to_send`.
7. Monday 8:00 AM ET: run `agents/update_outreach_ops_status.py` again after send.
8. Monday 8:00 AM ET: run reconciliation for stale drafts or mismatched Gmail state if needed.
9. Monday 8:00 AM ET: run reply checking.
10. Monday 8:00 AM ET: run the health check again.

## Operating Modes

### Mode 1: Auto-Draft + Label

Default mode.

Flow:

1. Scrape Canadian leads.
2. Dedupe against Notion and Gmail records.
3. Audit the website.
4. Generate the first outreach email in HTML.
5. Create a Gmail draft from the verified Anvis sender alias when possible.
6. Apply the `Anvis/Leads` label.
7. Brian reviews and sends manually.

### Mode 2: Auto-Send

Gated mode only.

Auto-send is allowed only when all required checks pass, including:

- `AUTO_SEND_FIRST_EMAILS=true`
- Admin approval is true
- Country is Canada
- Duplicate status is Unique
- Do Not Contact is false
- CASL Basis is filled
- Email exists
- No prior Gmail draft or sent thread exists
- Subject angle exists
- Clinic strengths have enough real content
- Safety validation passes
- Sender alias is verified
- `Ops Status = ready_to_send`

If any of those checks fail, the system falls back to draft mode.

## Weekly Intake Workflow

1. Sunday intake finds Canadian dental and local service leads using the active city only.
2. Dedupe against Notion by website, email, phone, and practice name.
3. Visit the clinic website.
4. Extract useful public information.
5. Audit the website for conversion opportunities, trust signals, local discovery, mobile experience, and booking flow.
6. Score and tier the lead.
7. Create or update the Notion lead record.
8. Refresh Ops Status and Blocker Reason.
9. Generate the outreach email draft when `Ops Status = ready_to_draft`.
10. Set Ops Status to reflect the next valid step.

Monday sends are automatic only for `Ops Status = ready_to_send`.

## Website Audit Workflow

Capture:

- Practice name
- Website
- Email
- Phone
- Address
- Doctors / decision makers
- Services
- Languages
- Online booking
- High-value services
- Reviews / testimonials
- Website platform if visible
- Obvious conversion issue

Look for:

- Booking flow clarity
- CTA clarity
- Mobile experience
- Trust signals
- Service structure
- Local discovery
- Google, Maps, and AI readiness
- Speed and performance
- Content hierarchy
- FAQ and schema readiness where relevant

## Lead Scoring

HOT:

- Broken site, obvious trust failure, outdated content, or high-value clinic with obvious conversion issues

WARM:

- Functional but dated, weak booking flow, poor mobile experience, or missing multilingual support

COOL:

- Decent site with one fixable issue

NURTURE:

- Acceptable site, needs more research

SKIP:

- Modern, recently maintained, or not worth pitching right now

## Outreach Draft Workflow

Default subject:

Use a personalized curiosity subject tied to the clinic's strongest missed signal.

Email structure:

Hello [Practice Name],

I build websites that run, grow, and get discovered.

You can check out some of my work here: https://anvisco.com

I took a quick look at your website and you already have a solid foundation. [Mention what works.]

One thing I noticed is [specific issue or opportunity]. [Explain why it matters for trust, booking, or patient conversion.]

I also see room to make the website cleaner, faster, easier to navigate, and more conversion-focused. [Mention multilingual support if relevant.]

If you are looking to improve how your website performs, I would be happy to share how I would approach it.

Rules:

- No signature unless the approved HTML signature block is already part of the template
- No em dashes
- Short and specific
- Compliment first
- One main issue per email
- Do not invent facts
- Do not mention Loom unless available
- Do not rewrite copy during ops cleanup. `src/email_writer.py` is the source of outbound copy.

## Sales Reply Workflow

When a lead replies:

1. Update Ops Status to `replied`.
2. Summarize what they are asking or objecting to.
3. Recommend the next action: answer, book call, send proposal, nurture, or close lost.
4. Draft a Gmail reply.
5. Brian reviews and sends manually.
6. Update Ops Status and reply tracking fields.

## Client Delivery Workflow

When a deal closes:

1. Move the lead to client.
2. Create or update client/project record in Notion.
3. Track package, deposit, remaining balance, and portal access.
4. Send the onboarding draft through Gmail.
5. Track assets received.
6. Move through project stages.
7. Draft client updates when needed.
8. Track final payment.
9. Launch and hand over.
10. Offer Care Plan after launch.

## Payment / Portal Workflow

After package selection:

- Checkout routes to `/checkout`
- After payment, portal access routes to `/portal`
- The client must use the same email address used during checkout

Do not use manual payment links.

## Manual Review Points

Brian should manually review:

- New lead quality
- Outreach email before sending
- Replies before response
- Follow-ups before sending
- Package recommendation before proposal
- Deposit status before project confirmation
- Final payment before launch
- Any manual client status change

## Weekly Automation

- Sunday intake: scraper -> Ops refresh -> drafts -> health check
- Monday 8:00 AM ET: Ops refresh -> send ready_to_send -> Ops refresh -> reply check -> health check
- No send cap is applied in the Monday scheduled send workflow
- `src/email_writer.py` remains the preserved outbound copy source
