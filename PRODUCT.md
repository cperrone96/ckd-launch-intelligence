# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

delegated: Dash on top of the versioned offline FastAPI response contracts; the dashboard must remain runnable without external data access.

## Users

Primary users are portfolio reviewers, hiring managers, and analytics leaders evaluating whether this project demonstrates defensible CKD launch-intelligence analysis. They arrive for a fast, decision-oriented review rather than patient care or beneficiary-level operations.

## Product Purpose

The dashboard makes the committed public-data CKD analytics legible as a sequence of business decisions: what population-level need is observed, how an educational screening-opportunity model performs, what source-specific care and prescribing signals exist, what trial activity is registered, and which conclusions remain scenario-only. Success is accurate interpretation with evidence boundaries visible within seconds.

## Positioning

Its differentiator is evidence-aware decision framing: every view carries source population, grain, denominator, uncertainty, evidence type, provenance, and limitations while refusing patient-level linkage and incompatible geographic composites.

## Operating Context

Reviewers scan the summary first, then move through patient need, patient finding, care and prescribing, trials, opportunity, and synthetic journeys. The application reads only committed local API/artifact responses and is evaluated on desktop and mobile web viewports.

## Capabilities and Constraints

- The dashboard must consume versioned API response models only; it must not read business data, credentials, live external sources, or raw patient/beneficiary/study identifiers.
- Pages must include loading, empty, error, and responsive states, with accessible chart alternatives and keyboard-visible focus.
- The synthetic journey view must say CMS synthetic data and that it is not representative of Medicare beneficiaries.
- The patient-finding view must say the score is not a clinical diagnostic tool.
- Opportunity geography remains source-specific and scenario-only; no mixed-state leaderboard may be implied.
- Visual direction and dashboard copy remain open assumptions for this delegated build and must not invent outcomes beyond the artifacts.

## Evidence on Hand

Committed verified artifacts under `data/processed`, their manifests and checksum sidecars under `data/manifests` and `data/processed`, the versioned API in `api/`, and the scientific methods in `src/ckd_intelligence`. No customer, business, or beneficiary-level data is available or permitted.

## Product Principles

- Lead with the decision and immediately show what evidence supports it.
- Keep source populations and denominators attached to every number.
- Make uncertainty and limitations part of the result, not footnotes.
- Separate observed public evidence, synthetic demonstrations, and scenario-only illustrations.
- Prefer accessible, reproducible explanations over decorative complexity.

## Accessibility & Inclusion

Use semantic landmarks, keyboard-accessible controls, visible focus, sufficient contrast, chart tables or text summaries, responsive layout, and non-color-only status communication. The dashboard should remain understandable with charts unavailable or disabled.
