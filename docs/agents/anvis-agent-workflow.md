# Anvis Agent Workflow

## Purpose

This document defines the current automatic agent workflow for Anvis.
It is the operating architecture for lead capture, outreach, client handoff, and post-sale coordination across Notion, Gmail, Supabase, Stripe, and the client portal.

## Brand And Scope

- Brand: Anvis
- Domain: https://anvisco.com
- Email: brian@anvisco.com
- Positioning: websites that run, grow, and optimize local businesses
- Primary targets: local service businesses, especially dental and other local clinics
- Tone: premium, dark, direct, operational, conversion-focused, no generic agency language

## System Overview

The system is organized around one lead-to-client pipeline:

1. Capture leads from scraping and manual inputs.
2. Generate a website audit and outreach angle.
3. Draft personalized outreach in Gmail.
4. Track reply and follow-up state in CRM records.
5. Hand off paying clients through Stripe Checkout and Supabase.
6. Move the client into the portal with magic-link login.
7. Keep admin review and test-client management separate from production client data.

Notion remains the working CRM for outreach-stage tracking.
Supabase becomes the source of truth for paid clients, package records, portal access, and payment state.
Gmail is draft-only for human-reviewed communication.

## Lead Capture

Lead capture can come from:

- Automated lead scraping
- Manual lead entry
- Imported prospects from research or referrals

Capture data should include at minimum:

- Business name
- Website
- Email or contact route
- Location
- Source
- Current status

Lead capture records stay in Notion until the lead is qualified or moved into the paid-client flow.

## Audit Generation

The audit layer turns a raw lead into a pitchable opportunity.
It should extract only public signals and focus on conversion issues, not broad design opinions.

Audit outputs should include:

- Top website issue
- Conversion angle
- Lead quality or priority score
- Service fit notes
- Booking or contact friction
- Mobile or trust issues
- Multilingual opportunity when relevant

The audit output feeds outreach, follow-up logic, and CRM status updates.

## Outreach Draft Generation

Outreach drafts are generated from the lead record and the audit result.
The system should produce short, specific, plain-language copy that:

- Opens with a direct observation
- Names one clear issue or opportunity
- Connects the issue to bookings, trust, or conversion
- Avoids fake claims and generic agency language
- Avoids signatures unless explicitly needed

Drafts are created in Gmail for manual review, not sent automatically.

## Follow-Up Sequencing

Follow-up sequencing should support a small, controlled sequence per lead.
The sequence should:

- Track whether the first draft was created
- Track whether a reply arrived
- Track whether a follow-up draft is due
- Stop when the lead replies, books, closes, or is marked out of scope

Follow-up generation should only use leads that are still active and eligible.
It should not generate duplicate drafts for the same sequence step.

## CRM, Notion, Gmail, And Supabase Update Points

### Notion

Use Notion for:

- Lead intake
- Lead status
- Audit fields
- Draft readiness
- Reply tracking
- Follow-up scheduling
- Admin review notes where needed

### Gmail

Use Gmail for:

- Draft creation
- Reply detection
- Follow-up draft preparation

Gmail should remain draft-only for outreach unless the workflow explicitly changes later.

### Supabase

Use Supabase for:

- Paid client records
- Package and payment state
- Portal access records
- Client-user linking
- Test-client management

Supabase is the handoff layer after payment confirmation, not the outreach CRM.

### Stripe

Stripe Checkout is the payment entry point for buyers.
The automation should rely on webhook confirmation, not on manual payment-link tracking.

## Checkout And Client Handoff

The public site should route users into one of three paths:

- Free Audit
- Checkout or offers
- Client Login

Prospect-facing handoff wording:

After checkout, you'll receive access to your client portal. Use the same email you used during checkout. From there, you'll be able to view your package, project stage, payment details, and updates.

The paid-client handoff should work as follows:

1. User checks out through Stripe Checkout.
2. Stripe webhook confirms payment.
3. Supabase client, package, and payment records are created or updated.
4. Welcome email is sent through Resend.
5. Client logs into the portal with a Supabase magic link.
6. The client must use the same email used at checkout.
7. Portal auth links the user to the client record through `public.client_users`.

This flow replaces any older manual payment-link assumptions for the live path.

## Admin Review Queue

Admin review should stay separate from automated execution.
The review queue should cover:

- Lead quality exceptions
- New leads
- Audit-ready leads
- Drafted emails
- Replies needing action
- Checkout-started leads
- Paid clients
- Draft review before any human send
- Reply handling exceptions
- Checkout or webhook mismatches
- Portal access issues
- Test-client cleanup
- Automation errors

Admin review checkpoints should happen before:

- Sending first outreach
- Sending follow-ups
- Sending pricing
- Sending checkout links
- Moving a lead to paid_client manually
- Deleting test clients
- Updating offer copy
- Sending bulk campaigns

Admin tools must support viewing, managing, and deleting test clients without affecting live client records.

## Safety Checks

The workflow should enforce these constraints:

- Brand must stay Anvis in prospect-facing copy, except for the allowed domain and sender email references.
- Do not send outreach emails automatically.
- Do not create duplicate drafts for the same lead and sequence step.
- Do not move a lead into client records without confirmed payment.
- Do not bypass webhook confirmation for paid-client creation.
- Do not use a client email different from the checkout email for portal access.
- If portal access fails, first check whether the checkout email and portal login email match.
- Do not treat test-client data as production data.
- Do not invent pricing or package details in automation logic.
- Do not overwrite manual review fields unless the workflow explicitly allows it.
- Do not let prospect-facing copy mention stale brand wording, manual payment links, backend tool names, guarantees, or secret-like tokens.

## Operating State Model

Suggested lifecycle:

1. Lead captured
2. Website audited
3. Outreach drafted
4. Sent manually
5. Replied
6. Qualified
7. Checkout completed
8. Client created in Supabase
9. Portal access granted
10. Delivery and admin review

This is the only state model the automation should depend on until a future revision adds more detail.

## Non-Goals

- No implementation code in this document
- No pricing definition
- No new dashboard design
- No replacement of the current CRM split between Notion and Supabase
