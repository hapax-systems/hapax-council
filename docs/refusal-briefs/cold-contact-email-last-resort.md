# Refusal Brief: Cold Email Last-Resort

**Slug:** `cold-contact-email-last-resort`
**Date Refused:** 2026-04-25

## Refusal Rationale

This surface has been permanently refused. The operator's verbatim rationale is:

> "Operator-approval gate is constitutionally incompatible with full-automation-or-nothing directive (2026-04-25 16:55Z). Drop 2 §1 explicit 'contraindicated' verdict (Columbia/Barracuda 2025: >50% spam-attribution; 47% B2B reply-likelihood drop)."

## Constitutional Basis

The design for this cold email surface required an operator-approval gate before each email could be sent. This directly violates the `feedback_full_automation_or_no_engagement` constitutional directive, which requires all engagement surfaces to be fully autonomous with no operator-in-the-loop gating.

## Research Basis

The underlying mechanic of AI-authored direct cold email was found to be explicitly contraindicated per Research Drop 2 §1. Studies (Columbia/Barracuda 2025) demonstrate a >50% spam-attribution rate and a 47% drop in B2B reply likelihood for such communications.

## Resolution

No `email_sender.py` or SMTP client will be implemented. The outreach mechanic is instead fully replaced by the citation-graph touch (`cold-contact-zenodo-iscitedby-touch`), which provides a daemon-tractable and constitutionally compatible engagement surface.
