# Anvis Workflow

Last updated: 2026-04-29

## Operating Principle

Notion is the source of truth. Gmail is only used for drafts. Brian reviews and sends manually.

Do not build a full admin dashboard yet. Keep the system simple, local, and easy to inspect.

## System Roles

The future system can use five specialist agents, but they should work through one orchestrator and shared Notion records.

1. Lead Gen + Website Audit Agent
2. UX / Conversion Agent
3. Copywriting + Email Agent
4. Sales / Deal Assistant Agent
5. Client Delivery Agent

The agents do not run independently. Each one updates the same Notion record and passes it to the next step through status changes.

## Daily Lead Workflow

Goal: find and prepare 10-20 quality dental leads per day.

Flow:

1. Find dental clinics using rotated Toronto-area locations and query variations.
2. De-duplicate against Notion by website, email, phone, and practice name.
3. Visit the clinic website.
4. Extract useful public information.
5. Audit the website for conversion opportunities.
6. Score and tier the lead.
7. Create or update the Notion lead record.
8. Generate outreach email draft.
9. Create Gmail draft.
10. Set Notion status to Draft Ready.

Never send automatically.

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
- CDCP mention
- Insurance mention
- Online booking
- High-value services
- Reviews / testimonials
- Website platform if visible
- Obvious conversion issue
- Multilingual opportunity

Look for:

- Broken or expired testimonial widgets
- Old COVID messaging
- Old copyright year
- Missing or weak booking path
- Too many CTAs
- Repeated forms
- Content-heavy sections
- Confusing service organization
- Multiple-location confusion
- High-value services not framed clearly
- No website translation in a multilingual area

## Lead Scoring

HOT:

- Broken site, no website, severe outdated content, broken trust section, or high-value clinic with obvious conversion issue

WARM:

- Functional but dated, weak booking flow, poor mobile experience, missing online booking, or strong multilingual opportunity

COOL:

- Decent site with one fixable issue

NURTURE:

- Acceptable site, needs more research

SKIP:

- Modern, recently maintained, or not worth pitching right now

## Outreach Draft Workflow

Default subject:

Web design services to improve conversion

Email structure:

Hello [Practice Name],

I build websites that run, grow, and optimize your business.

You can check out some of my work here: https://anvisco.com

I took a quick look at your website and you already have a solid foundation. [Mention what works.]

One thing I noticed is [specific issue or opportunity]. [Explain why it matters for trust, booking, or patient conversion.]

I also see room to make the website cleaner, faster, easier to navigate, and more conversion-focused. [Mention multilingual translation if relevant.]

If you’re looking to improve how your website performs, I’d be happy to share how I’d approach it.

Rules:

- No signature
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

Sales stages:

- Replied
- Interested
- Call Booked
- Discovery Completed
- Proposal Needed
- Proposal Sent
- Deposit Pending
- Closed Won
- Closed Lost
- Nurture

Discovery call structure:

1. Understand what they want more of: calls, bookings, consultations, or specific services.
2. Show the specific website issue and how it affects patients.
3. Recommend the right package and next step.

## Client Delivery Workflow

When a deal closes:

1. Move the lead to Client.
2. Create or update client/project record in Notion.
3. Track package, deposit, remaining balance, and portal access details.
4. Send onboarding draft through Gmail.
5. Track assets received.
6. Move through project stages.
7. Draft client updates when needed.
8. Track final payment.
9. Launch and hand over.
10. Offer Care Plan after launch.

Client project stages:

1. Deposit Pending
2. Project Confirmed
3. Onboarding
4. Build in Progress
5. Review
6. Final Payment
7. Launched
8. Care Plan Offered
9. Care Plan Active

## Payment / Package Workflow

After package selection:

- Essentials: $600 deposit, $600 remaining
- Standard: $1,100 deposit, $1,100 remaining
- Premium: $1,900 deposit, $1,900 remaining

Live payment entry point:

- Stripe Checkout

Do not use manual payment links in live prospect copy.

The project should not launch until final payment is marked paid.

## Manual Review Points

Brian should manually review:

- New lead quality
- Audit-ready leads before Email 1
- Outreach email before sending
- Follow-up emails before sending
- Replies before response
- Package recommendation before proposal
- Pricing before sharing
- Checkout links before sharing
- Deposit status before project confirmation
- Final payment before launch
- Test-client deletes before removal
- Offer copy before publishing changes

Admin safeguards:

- Drafts only by default
- No manual payment links in live prospect copy
- No bulk campaigns without explicit review
- Prospect copy must pass safety validation before draft creation
- Allowed exceptions: `anvisco.com` and `brian@anvisco.com`
