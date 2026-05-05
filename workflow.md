# Anvis Workflow

Last updated: 2026-05-05

## Operating Principle

Notion is the source of truth. Gmail is used for drafts and reply detection. Brian reviews and sends manually unless the gated auto-send mode is explicitly turned on.

Keep the system simple, inspectable, and draft-first by default.

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

If any of those checks fail, the system falls back to draft mode.

## Daily Lead Workflow

1. Find Canadian dental and local service leads using the active city only.
2. Dedupe against Notion by website, email, phone, and practice name.
3. Visit the clinic website.
4. Extract useful public information.
5. Audit the website for conversion opportunities, trust signals, local discovery, mobile experience, and booking flow.
6. Score and tier the lead.
7. Create or update the Notion lead record.
8. Generate the outreach email draft.
9. Create the Gmail draft and label it `Anvis/Leads`.
10. Set Notion status to Draft Ready.

Never send automatically unless the gated mode is explicitly enabled.

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

## Sales Reply Workflow

When a lead replies:

1. Update Notion status to Replied.
2. Summarize what they are asking or objecting to.
3. Recommend the next action: answer, book call, send proposal, nurture, or close lost.
4. Draft a Gmail reply.
5. Brian reviews and sends manually.
6. Update Notion status.

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
