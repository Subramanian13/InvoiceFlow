# InvoiceFlow — Project Specification

**Version:** 1.0  
**Case study:** PS-4 — Invoice processing: from PDF to decision  
**Client:** GlobalFreight Inc. (fictional US logistics and freight enterprise)  
**Primary user:** Accounts Payable (AP) analyst  
**Implementation priority:** Working, explainable end-to-end demo in approximately 48 hours

> **Status:** This document is the implementation contract for Codex. Where it says **MUST**, implement and test that behavior. Where it says **OPTIONAL**, do not jeopardize the working MVP to implement it. The fictional data, policies and architecture below are our design choices, not requirements imposed by the candidate guide.

## 1. Source requirements and success criteria

The Zamp AI Solutions Analyst/Associate Candidate Guide (2026), PS-4, asks for a process that takes an invoice PDF and produces a clear, reasoned decision with intermediate reasoning visible. The fictional client is a US logistics enterprise with messy PDF invoices, procurement POs, approved vendors, tolerance rules, partial invoicing, surcharges and duplicate risks.

**Required for submission:**
- A **live, runnable** process accepting a **real PDF** and producing a real persisted decision; no simulated runs or mock-only dashboards.
- Visible stages of the real execution, including inputs, matched records, checks and final rationale.
- **2–4 deliberately designed edge cases**, handled gracefully.
- An intuitive AP-analyst UI, **live run view**, and dashboard of history, statuses and outputs.
- A publicly reachable process link for the reviewer (if hosting requires credentials, provide appropriate access).
- A **five-minute-or-shorter edited video**, with the candidate **on camera**, narrating in their **own voice**, pitching to an enterprise buyer; show happy path and 2–3 edge cases. No AI voiceover, no slide-only pitch.
- Prepared, repeatable live demo in follow-up interview.
- Do not use Zamp or Pace tools to build this.

**Our stricter success criterion:** Upload each supplied test PDF through the UI, execute the real pipeline, see correct decisions, resolve a real exception, and refresh the page without losing history. Tests must pass. All demos should work from a clean seeded state.

## 2. Product statement

InvoiceFlow is an AI-assisted AP invoice decisioning application. It extracts structured fields from vendor PDFs, identifies the supplier and PO, validates charges and available authorization, detects duplicates, and either **approves for downstream AP processing**, **holds for review**, or **blocks automatic approval**. Every decision includes evidence, checks and an audit trail.

**Do not claim:** That InvoiceFlow pays suppliers, posts to an actual ERP, verifies EINs against the IRS, reads real carrier gate logs, or provides production-grade controls. It is a realistic, fully functional case-study prototype with synthetic procurement/operations data.

**Business boundaries:** One vendor and one PO per invoice in MVP; a single PO may have many invoices. Amounts in USD. Multi-PO allocations, complex tax jurisdiction logic, actual payment execution and ERP integration are out of scope.

## 3. Guiding principles

1. **AI extracts; code decides.** Use a genuine PDF-to-structured-data extraction pipeline (prefer a vision-capable LLM API for scanned PDFs), Pydantic schema validation, and deterministic matching/financial rules.
2. **Fail closed.** Missing fields, ambiguous identity, uncertain extraction or absent evidence must never be treated as passing.
3. **Identity before PO matching.** Similar names are not sufficient. Vendor ID is an internal master-data key; optional tax identifier is only compared to previously verified vendor-master data, not externally validated.
4. **Authorization is distinct from factual correctness.** A detention charge may be evidenced and mathematically correct yet exceed the PO's approved allowance.
5. **Never invent evidence.** Only validate waiting time if an actual seeded shipment record exists; show `NOT_VERIFIED` otherwise.
6. **No double spending.** Approved invoice allocations must consume PO capacity atomically. Held and blocked invoices do not consume it.
7. **Audit everything.** Record run stage, rule code, evidence, human action and timestamp.
8. **Reproducible demos.** Deterministic seed and reset command; no hidden manual DB edits required to demonstrate outcomes.
9. **Scope discipline.** Complete happy path before edge cases. Keep UI functional and polished, not sprawling.

## 4. Target architecture

```text
React + TypeScript + Vite + Tailwind UI
   | REST + polling (or SSE if easy)
FastAPI (Python) backend
   |-- PDF upload/storage + MIME/size validation
   |-- PDF parsing/rendering (PyMuPDF or equivalent)
   |-- Real AI extractor (vision-capable model API; structured JSON)
   |-- Pydantic validation + normalization
   |-- Vendor resolver and PO candidate matcher
   |-- Deterministic validation/decision engine
   |-- Review and revalidation service
   |-- Event logger and reporting API
   +-- SQLAlchemy ORM + SQLite locally
          (PostgreSQL in deployment if SQLite persistence is unreliable)
```

**Preferred stack:** React, TypeScript, Vite, Tailwind, FastAPI, Pydantic, SQLAlchemy, Alembic (if manageable), pytest, SQLite locally; PostgreSQL on deployment if needed. Use Python `Decimal` and database `NUMERIC` for currency, never binary floats. Store UTC timestamps. Use environment variables for API credentials. Do not expose AI API keys in frontend. Keep provider integration behind a single adapter to swap models.

**Hosting:** Choose a viable frontend/backend host after verifying its current free/paid plan and persistent storage constraints. If using ephemeral storage, do not pretend history survives redeployment. Provide deployment instructions and a smoke test against the public URL.

## 5. End-to-end run pipeline

1. **UPLOAD_RECEIVED:** User submits actual PDF (single file); backend validates file type, max size (e.g. 10 MB), stores it, creates invoice/run IDs and event.
2. **EXTRACTING:** Extract PDF text and/or render pages to images. Invoke real AI extraction with structured schema. Record provider, processing duration and any errors. Do not simulate processing progress.
3. **NORMALIZING:** Normalize dates, USD amounts, invoice numbers, vendor name, PO reference, shipment references, line items, charge types. Preserve raw extraction JSON and uncertainties.
4. **IDENTIFYING_VENDOR:** Match against verified vendor master and aliases/identifiers; collect evidence and candidates.
5. **MATCHING_PO:** Exact PO reference first; if missing, rank eligible candidate POs using vendor + shipment + service/date. Never silently choose an ambiguous candidate. Verify PO belongs to resolved vendor and is open.
6. **VALIDATING:** Execute all applicable mandatory checks; persist each result and evidence.
7. **DECIDING:** Apply deterministic precedence: technical failure, blocking controls, review conditions, otherwise approve.
8. **COMMITTING:** If approved, atomically recheck PO balance/line quantities/charge allowances and commit allocation. If another invoice consumed capacity, change outcome to review. Persist decision and events.
9. **COMPLETE:** Return invoice details, check results, explanations, recommended next action, status, and links to the stored PDF.

Run stages must reflect actual backend events. UI may poll `GET /api/runs/{id}` every ~1 second. A failure must be displayed as failure, not as a completed green stage.

## 6. Relational data model

Implement with real foreign keys, uniqueness constraints and indexes. These are logical field definitions; adapt column types as needed while preserving semantics.

### 6.1 `vendors`
- `id` UUID or integer PK; `vendor_code` unique (`VEN-001`)
- `legal_name`; `display_name`; `status` (`ACTIVE`, `INACTIVE`)
- `tax_id_fingerprint` nullable, for equality comparison only (synthetic test values); `tax_id_last4` nullable for display; `tax_id_verified_in_master` boolean
- `created_at`, `updated_at`
- **Security:** Never log or show complete tax IDs. Do not claim a tax-ID match means live government verification. Fictional identifiers only.

### 6.2 `vendor_aliases`
- `id`; `vendor_id` FK; `alias_normalized`; `source` (`MASTER_APPROVED`); unique normalized alias per vendor
- Only **preapproved** aliases permit automatic identity resolution. Fuzzy-name matches produce suggestions, not identity confirmation.

### 6.3 `purchase_orders`
- `id`; `po_number` unique; `vendor_id` FK; `status` (`OPEN`, `CLOSED`, `CANCELLED`)
- `currency` (USD); `authorized_total` NUMERIC; `issue_date`; `valid_from`/`valid_to` optional; `description`; `version` integer for optimistic concurrency if useful
- The PO total includes its base-service commitments and explicit surcharge allowances in seeded examples; do not count allowances twice.

### 6.4 `po_lines`
- `id`; `po_id` FK; `line_number`; `service_code` (`FREIGHT`, `WAREHOUSING`, etc.); `description`; `shipment_ref` nullable
- `ordered_quantity` NUMERIC; `unit_of_measure` (`CONTAINER`, `TRIP`, etc.); `unit_price` NUMERIC; `authorized_line_total` NUMERIC
- Unique `(po_id, line_number)`.

### 6.5 `charge_policies`
- `id`; `po_id` FK; `charge_type` (`DETENTION`, `FUEL_SURCHARGE`, etc.)
- `rate_type` (`PER_HOUR`, `PERCENT_BASE`, `FIXED`); `rate` NUMERIC; `free_hours` NUMERIC nullable; `max_total_allowance` NUMERIC
- `requires_evidence` boolean; `policy_notes`; unique `(po_id, charge_type)` for MVP.
- An allowed **rate** does not by itself mean unlimited authorization; both allowance and overall PO total must pass.

### 6.6 `shipment_evidence`
- `id`; `shipment_ref` unique for MVP; `vendor_id` FK; `po_id` FK nullable
- `arrival_at` timestamp; `departure_at` timestamp; `source` (`WAREHOUSE_GATE_LOG`); `verified` boolean
- Optional `notes`; times must use compatible time zones.
- This is a seeded operational record, not data extracted from the invoice. Never accept invoice-stated waiting hours as independent verification.

### 6.7 `invoices`
- `id`; `invoice_number` nullable; `invoice_number_normalized` nullable; `vendor_id` nullable FK; `vendor_name_raw`; `tax_id_last4_raw` nullable
- `po_reference_raw` nullable; `matched_po_id` nullable FK; `shipment_ref` nullable
- `invoice_date` nullable; `currency`; `subtotal`, `tax_amount`, `total_amount` NUMERIC nullable
- `pdf_storage_key`; `pdf_sha256`; `extraction_json` JSON; `extraction_provider` nullable; `status`; `decision_reason`; `created_at`, `updated_at`
- Distinguish invoice **document record** from each processing **run**. Do not enforce a uniqueness constraint that prevents saving a duplicate submission for inspection; enforce duplicate blocking through the decision engine.

### 6.8 `invoice_lines`
- `id`; `invoice_id` FK; `line_number`; `description`; `charge_type`; `quantity` NUMERIC nullable; `unit_price` NUMERIC nullable; `amount` NUMERIC
- `shipment_ref` nullable; `matched_po_line_id` nullable FK; `extraction_confidence` nullable; `raw_json` JSON optional

### 6.9 `invoice_po_allocations`
- `id`; `invoice_id` FK; `po_id` FK; `amount` NUMERIC; `status` (`COMMITTED`, `RELEASED`); `created_at`
- For MVP one committed allocation per invoice, one PO per invoice. Many invoices can commit against one PO.
- For line-level quantity and surcharge usage, additionally implement `invoice_line_allocations` or equivalent fields linking invoice lines to PO lines and charge policy types. This is **necessary** to avoid allowing a PO-total pass while individual service quantity or detention allowance is exceeded.
- On approval, compute available capacity from active committed allocations; do not use a separately mutable `used_amount` as the only source of truth.

### 6.10 `invoice_runs`
- `id`; `invoice_id` FK; `run_number`; `status` (`QUEUED`, `RUNNING`, `COMPLETED`, `FAILED`); `started_at`, `completed_at`; `error_code` nullable
- Each revalidation creates a new run, preserving previous outcomes.

### 6.11 `validation_results`
- `id`; `run_id` FK; `rule_code`; `status` (`PASS`, `FAIL`, `REVIEW_REQUIRED`, `BLOCK`, `NOT_APPLICABLE`, `TECHNICAL_ERROR`)
- `severity`; `message`; `expected_json`; `actual_json`; `evidence_json`; `created_at`
- Do not treat `NOT_APPLICABLE` as success for a required rule. Store whether the rule was required.

### 6.12 `invoice_events`
- `id`; `invoice_id` FK; `run_id` nullable FK; `event_type`; `stage`; `status`; `actor_type` (`SYSTEM`, `AP_ANALYST`, `PROCUREMENT`); `actor_name` nullable; `message`; `details_json`; `created_at`
- Append-only timeline in the application.

### 6.13 `review_actions`
- `id`; `invoice_id` FK; `actor_name`; `actor_role`; `action_type` (`CONFIRM_PO`, `CORRECT_EXTRACTION`, `REQUEST_EVIDENCE`, `RECORD_PO_AMENDMENT`, `REVALIDATE`, `MARK_DISPUTED`); `reason`; `payload_json`; `created_at`
- Case-study identity is a **clearly labeled demo role selector**, not real authentication. Do not imply secure role enforcement without auth.

### 6.14 `po_amendments` (recommended for detention demo)
- `id`; `po_id` FK; `previous_authorized_total`; `new_authorized_total`; `charge_type`; `previous_allowance`; `new_allowance`; `approved_by`; `approval_reference`; `reason`; `created_at`
- An authorized procurement action modifies the PO and/or allowance with immutable amendment history. Revalidation is separate; no direct status override.

**Index suggestions:** `vendors.vendor_code`, normalized aliases, `purchase_orders.po_number`, `invoices(vendor_id, invoice_number_normalized)`, `invoices.pdf_sha256`, `shipment_evidence.shipment_ref`, `invoice_events.invoice_id`, `invoice_po_allocations.po_id`.

## 7. Vendor identification rules

**Identity resolution priority:**
1. If an invoice carries a reliable buyer-issued vendor code and it matches an active master record, use it **only after checking for conflicting identity evidence**. Vendor codes are optional and not required on PDFs.
2. If a tax identifier is provided and matches a previously verified master record, use as strong evidence, **but reject conflicting vendor name/PO ownership signals for review**. In the US an EIN is not routinely present on invoices and this is not an IRS verification service.
3. Exact normalized legal name or an explicitly approved alias -> resolve if unambiguous and no conflicting identifier.
4. Similar/fuzzy name -> show ranked candidate(s) and **NEEDS_REVIEW**, never auto-approve on similarity alone.
5. No match, inactive vendor, or conflicting identifier -> **NEEDS_REVIEW** with specific reason.

Normalization: trim, case-fold, collapse whitespace, normalize punctuation; do **not** blindly strip legally significant words or assume all companies sharing a root name are identical. Approved aliases can cover `Atlas Transport LLC` vs `Atlas Transportation LLC`. `Atlas Investments LLC` must not match `Atlas Transport LLC` by shared word `Atlas`.

## 8. PO matching rules

**Primary:** Exact normalized `po_reference_raw` -> PO lookup. Verify PO status OPEN, vendor ownership, dates if configured, and relevant service/shipment. If PO number exists but belongs to another vendor, **do not fallback** to a different PO without explicit review; flag `PO_VENDOR_MISMATCH`.

**Missing PO reference:** Search OPEN POs for the **verified** vendor; rank by shipment_ref exact match, service/route match, invoice date within service window, and available capacity. Candidate ranking is explanatory, not approval authorization. Show top candidates and evidence. Even one candidate requires manual confirmation under MVP policy. Zero candidates -> request PO from supplier/procurement. Multiple candidates -> analyst selects and confirms.

**Line mapping:** Map `FREIGHT` invoice lines to PO service lines using service type and shipment reference, check quantity × unit price. Map `DETENTION` and other accessorial lines to charge policies. Unknown/bundled lines that cannot be safely allocated -> review. No invented split.

**Partial invoicing:** One PO may fund many distinct invoices; invoice numbers must be distinct per vendor. Compute used quantities, line amounts, surcharge allowances and PO total from committed allocations only.

## 9. Deterministic validation rules

Store each check with rule code, status, evidence and actionable explanation. Evaluate all safe checks even if another check fails, so the user sees the full picture. If prerequisites are missing, mark dependent checks `NOT_APPLICABLE`/`REVIEW_REQUIRED` with reason; never mark them PASS.

| Code | Condition | If unmet |
|---|---|---|
| `PDF_READABLE` | PDF can be parsed or visually extracted | REVIEW / technical failure if provider down |
| `REQUIRED_FIELDS` | Invoice number, date, vendor, total and adequate line/PO information present | NEEDS_REVIEW |
| `EXTRACTION_CONFIRMED` | No unresolved ambiguous critical fields | NEEDS_REVIEW |
| `VENDOR_ACTIVE` | Resolved, active vendor with no conflicting identifiers | NEEDS_REVIEW |
| `DUPLICATE_INVOICE` | No existing non-void invoice with same vendor + normalized invoice number | BLOCKED |
| `DUPLICATE_FILE` | Same PDF hash already received; warn/link record; avoid accidental repeat | BLOCKED or REVIEW depending on whether prior record was voided |
| `PO_MATCH` | Exact confirmed or human-confirmed PO, OPEN and owned by vendor | NEEDS_REVIEW |
| `CURRENCY_MATCH` | USD invoice vs USD PO | NEEDS_REVIEW |
| `INVOICE_ARITHMETIC` | Sum line amounts + separately represented tax = invoice total, within $0.01 | NEEDS_REVIEW |
| `LINE_MATCH` | Service, shipment, quantities and unit prices fit PO line remaining capacity | NEEDS_REVIEW |
| `CHARGE_POLICY` | Charge type authorized and charge calculation matches policy | NEEDS_REVIEW |
| `CHARGE_EVIDENCE` | Required independent shipment evidence exists and validates billed charge | NEEDS_REVIEW |
| `CHARGE_ALLOWANCE` | Charge fits remaining approved allowance | NEEDS_REVIEW |
| `PO_BALANCE` | Entire invoice fits remaining authorized PO total | NEEDS_REVIEW |

**Arithmetic convention:** `invoice_lines.amount` excludes tax when tax is shown separately; if tax is embedded, flag as included and don't add twice. No arbitrary sales-tax assumption for freight. Tax is validated arithmetically only in MVP, not legally.

**Detention calculation:** `billable_hours = max(0, (departure_at - arrival_at) in hours - free_hours)`; `expected_detention = billable_hours * policy.rate`. Define rounding to nearest permitted billing increment (MVP: exact decimal hours or 1-hour increments explicitly set in policy). Require verified gate-log record matching shipment and vendor. Example: 09:00–14:00, 2 free hours, $200/hour => $600. If invoice says $600 and remaining detention allowance is $300, `CHARGE_EVIDENCE` PASS but `CHARGE_ALLOWANCE` REVIEW_REQUIRED.

**PO total convention:** PO authorized total includes base and permitted charges. E.g. $2,000 freight + $1,000 detention allowance = $3,000 total. Do not subtract detention twice. Remaining = authorized_total − committed allocations. Independently check line quantities and charge allowance.

**Duplicate convention:** Key `(resolved_vendor_id, normalized_invoice_number)` across non-void invoices, not invoice number alone; same invoice number from different vendors is not necessarily duplicate. For uploads with unresolved vendor identity, exact file hash may detect re-upload; do not claim definitive vendor-based duplicate until identity resolved. Revalidation of the **same invoice record** is not a new duplicate.

**Concurrency:** Wrap final check and allocation insert in one DB transaction with appropriate locking/isolation (SQLite local serialized writes; PostgreSQL row lock in deployment). A precheck alone is insufficient.

## 10. Decision precedence and statuses

**Invoice business statuses:** `RECEIVED`, `PROCESSING`, `APPROVED`, `NEEDS_REVIEW`, `BLOCKED`, `DISPUTED`, `PROCESSING_FAILED`.

**Run statuses:** `QUEUED`, `RUNNING`, `COMPLETED`, `FAILED`.

Decision precedence:
1. Technical inability to complete -> `PROCESSING_FAILED`, safe retry offered; no allocation.
2. Definitive duplicate -> `BLOCKED`, show linked record; no allocation.
3. Missing/ambiguous fields, vendor/PO uncertainty, policy/amount/evidence mismatch -> `NEEDS_REVIEW`, explicit next action; no allocation.
4. All required checks passed -> transactionally recheck capacity and commit -> `APPROVED`.
5. User may mark a disputed invoice `DISPUTED` with reason; it is not approved.

`APPROVED` means **approved for simulated downstream AP processing**, **not paid or posted to an ERP**. An untrusted manual click cannot simply force APPROVED. A valid correction/amendment must change evidence/authorization and rerun rules.

## 11. Human review workflows

**Missing PO:** Analyst sees candidate list with evidence -> selects PO -> records reason -> rerun matching and all validations. Analyst confirmation is not permission to ignore vendor mismatch.

**Extraction correction:** Analyst edits wrongly extracted field, with before/after and reason -> rerun checks. Preserve original AI extraction and correction event.

**Detention authorization:** System confirms charge evidence and arithmetic but flags insufficient allowance -> procurement demo-role records approved PO amendment with approval reference and reason -> backend updates PO total/allowance and logs amendment -> analyst reruns validation -> if all checks pass, approve and commit. Never make approval contingent on fake, pre-scripted events.

**Supplier dispute:** Analyst records dispute and requests revised invoice; preserve history. No direct financial commitment.

**Demo permissions:** Clearly mark role selector as simulation; production role-based access is out of scope. Require explicit reason and approval reference for simulated procurement amendments.

## 12. Featured demo scenarios and exact seed fixtures

Prepare **four primary scenarios** plus optional vendor-identity mismatch. Make all fixture values internally consistent. Generate realistic PDF files with visibly different vendor layouts, including at least one scanned/image-only PDF if vision extraction works reliably.

### Scenario A — Happy path with valid detention
- Vendor `VEN-001`: Atlas Transport LLC (active); approved alias `Atlas Transportation LLC`.
- PO `PO-10045`: base freight $2,000 for shipment `SH-8891`, detention max $1,000 at $200/hour after 2 free hours, total authorization $3,000, no prior commitments.
- Verified gate log `SH-8891`: 09:00–14:00 same day, five hours total -> three billable hours -> $600.
- Invoice `INV-504`: freight $2,000 + detention $600 = $2,600; PO-10045; vendor Atlas Transport LLC.
- Expected `APPROVED`; committed $2,600; remaining PO total $400; detention allowance remaining $400. All checks PASS.

### Scenario B — Duplicate invoice
- Upload exact same `INV-504` PDF again after A (or a differently formatted PDF with same vendor and invoice number).
- Expected `BLOCKED`, reason `DUPLICATE_INVOICE` and link to original. No additional commitment. A revalidation of original is allowed and is not a duplicate.

### Scenario C — Verified detention but insufficient allowance, then amendment
- Separate PO `PO-10055` with $2,000 base freight and $300 detention allowance, total $2,300; shipment `SH-8895` with verified 09:00–14:00 gate log; detention rate $200/hour, 2 free hours.
- Invoice `INV-505` bills freight $2,000 + detention $600 = $2,600.
- Expected `NEEDS_REVIEW`: detention evidence/calculation PASS; `CHARGE_ALLOWANCE` fails by $300 and `PO_BALANCE` fails by $300.
- Procurement demo-role records amendment raising detention allowance to $600 and PO total to $2,600, with reason and approval reference.
- Revalidation on same invoice -> `APPROVED`; new allocation $2,600; old validation history retained.

### Scenario D — Missing and ambiguous PO
- Active vendor `VEN-002`: Pacific Freight Inc.
- Two OPEN POs `PO-20010` and `PO-20011` for same vendor, same shipment `SH-7777`, overlapping service descriptions, enough capacity.
- Invoice `INV-777` for $1,000 references `SH-7777` but no PO number.
- Expected `NEEDS_REVIEW` with **both** candidates, clear evidence and no automatic selection. Analyst chooses the correct PO, supplies reason, reruns validation, and can approve if line terms match. Make PO line terms distinct enough that selected PO can be verified against the invoice details.

### Scenario E — Partial invoicing / stateful capacity (fourth featured edge case)
- PO `PO-30010` for Atlas Transport LLC: 10 containers × $1,000 = $10,000, no accessorial charges.
- Prior seeded **committed** invoice `INV-3001`: 7 containers, $7,000.
- Upload `INV-3002`: 2.5 containers × $1,000 = $2,500 **only if fractional container quantities are allowed**. Prefer a less awkward fixture: PO 10 trips × $1,000, prior 7 trips ($7,000), new 2 trips ($2,000), remaining $1,000; then a final 1-trip invoice may pass, and a 2-trip invoice must be held. Use whole-number units consistently.
- Expected first new invoice `APPROVED`, PO remaining decreases; overage invoice `NEEDS_REVIEW`, no overcommit.

**Optional negative identity test:** `Atlas Investments LLC` invoice references Atlas Transport's PO. Similar name must not auto-resolve. Conflicting fictional tax-ID fingerprints -> `NEEDS_REVIEW`.

**Important demo isolation:** Seed scenarios must be independently runnable and repeatable; add a documented `reset_demo_data` CLI command for local tests. For a public demo, use a safe, access-controlled reset mechanism or separate fixture namespace; never expose an unrestricted destructive reset endpoint.

## 13. Extraction schema and model behavior

Return structured JSON validated by Pydantic:

```json
{
  "vendor_name": "Atlas Transport LLC",
  "vendor_code": null,
  "tax_id_last4": null,
  "invoice_number": "INV-504",
  "invoice_date": "2026-11-01",
  "po_reference": "PO-10045",
  "shipment_reference": "SH-8891",
  "currency": "USD",
  "subtotal": "2600.00",
  "tax_amount": "0.00",
  "total_amount": "2600.00",
  "lines": [
    {"description":"Freight SH-8891","charge_type":"FREIGHT","quantity":"1","unit_price":"2000.00","amount":"2000.00","shipment_reference":"SH-8891"},
    {"description":"Detention 3 billable hours","charge_type":"DETENTION","quantity":"3","unit_price":"200.00","amount":"600.00","shipment_reference":"SH-8891"}
  ],
  "uncertain_fields": [],
  "warnings": []
}
```

Extraction rules:
- Use actual PDF bytes on every new upload; never choose a hard-coded outcome based on filename or PDF hash.
- AI must **not** invent PO references, vendor IDs, tax identifiers, shipment evidence, or missing invoice numbers.
- Extract null for missing fields; preserve source text and warnings where possible.
- Normalize currencies, dates and amounts after extraction; reject invalid formats safely.
- Model output is untrusted; Pydantic checks required types, limits, amounts and line totals.
- If PDF text extraction is insufficient, render pages and invoke vision-capable extraction. Support at least one scanned fixture if time allows; otherwise explicitly document limitation.
- On provider errors, record technical failure and offer retry. No silently substituted fake extraction.
- Save model/provider metadata and extraction duration; never expose secret keys or full sensitive tax IDs.

## 14. API contract (suggested)

- `GET /api/health` — backend/DB health.
- `GET /api/vendors` — sanitized vendor list.
- `GET /api/purchase-orders` and `GET /api/purchase-orders/{id}` — POs, lines, allowances, committed/remaining balances.
- `POST /api/invoices/upload` — multipart PDF; create invoice/run and start real processing; returns IDs.
- `GET /api/runs/{run_id}` — current stage/status and actual events/checks.
- `GET /api/invoices` — paginated/filterable history.
- `GET /api/invoices/{invoice_id}` — extracted fields, matched PO, lines, checks, decision and actions.
- `GET /api/invoices/{invoice_id}/document` — securely serve stored PDF.
- `GET /api/invoices/{invoice_id}/events` — audit timeline.
- `GET /api/invoices/{invoice_id}/po-candidates` — ranked candidate POs with evidence.
- `POST /api/invoices/{invoice_id}/review/confirm-po` — analyst confirmation + reason.
- `POST /api/invoices/{invoice_id}/review/correct-field` — correction + reason.
- `POST /api/purchase-orders/{id}/amendments` — procurement demo-role amendment + reason/approval reference.
- `POST /api/invoices/{invoice_id}/revalidate` — rerun deterministic checks against corrected extraction/updated master data; new run ID.
- `GET /api/dashboard/summary` — status counts and recent activity.

Use consistent error JSON and typed response models. All writes validate inputs. Avoid open CORS wildcard in deployment if possible. Use server-side document paths, not user-supplied filesystem paths.

## 15. Frontend UX specification

**Design direction:** Modern enterprise operations UI; light background, restrained accent color, clear typography, generous whitespace, readable tables, meaningful status chips, loading and error states. No flashy animations that hide logic. Responsive desktop-first.

### 15.1 Dashboard
- KPI cards: processed, approved, needs review, blocked, processing failures (real DB counts).
- Recent invoices table: invoice #, vendor, PO, amount, created time, status, actionable next step.
- Filters/search by status, vendor, invoice #.
- Primary `Upload invoice` CTA.

### 15.2 Upload and live run
- Drag/drop or file chooser; validate PDF/size before sending.
- Progress based on real backend stages; stage timestamps and status.
- Real extraction fields, vendor match evidence, PO candidates, checks and final decision.
- If failure, show precise reason and retry/review path. No staged artificial delays.

### 15.3 Invoice detail/review
- Original PDF preview (browser PDF viewer acceptable) alongside extracted fields and PO summary.
- Line-level comparison (billed vs authorized/remaining), including detention calculation and evidence.
- Validation results grouped PASS / REVIEW / BLOCK; readable explanations and values.
- Recommended next action; review controls for missing PO, corrections and authorization amendments.
- Revalidate button; reflect new run and status without refreshing.

### 15.4 History and audit
- Invoice list persists across refreshes.
- Timeline: upload, extraction, identity, PO matching, validation, decision, analyst correction, amendment, revalidation.
- Show who/what changed, why, and before/after where relevant.

**Accessibility:** Label inputs, keyboard-friendly controls, high contrast, meaningful errors, no color-only status distinctions.

## 16. Tests and acceptance criteria

### Backend unit tests
- Exact PO + vendor ownership match passes; PO of another vendor fails.
- Approved alias resolves; fuzzy `Atlas Investments` does not.
- Missing PO returns candidate list and review.
- Duplicate `(vendor, invoice_number)` blocked; same invoice number for different vendors not automatically duplicate.
- Revalidation of same invoice not treated as duplicate.
- Arithmetic with Decimal and tax inclusion rules.
- Base line quantity/rate and remaining quantity checks.
- Detention expected amount from independent gate logs.
- Detention charge within allowance passes; evidenced charge above allowance held.
- Overall PO total remaining calculated from committed allocations.
- Partial invoices consume correct quantities/amounts.
- Concurrent approval cannot overcommit (at least transaction-level test).
- Technical extraction failure persists failure without approving.
- Amendment and revalidation retain old run events and approve only when checks pass.

### End-to-end manual tests
1. Upload clean happy-path PDF -> real stages -> `APPROVED` -> PO balance decreases -> history survives refresh.
2. Upload duplicate -> `BLOCKED`, linked original, unchanged PO balance.
3. Upload detention overage -> `NEEDS_REVIEW`, evidence PASS but allowance FAIL -> procurement amendment -> revalidate -> `APPROVED`.
4. Upload missing-PO PDF -> two candidates -> analyst confirms -> revalidate -> decision reflects selected PO.
5. Upload partial invoice -> correct PO balance update -> subsequent overage held.
6. Upload malformed/unreadable PDF -> honest review/failure, no invented values.
7. Stop AI API/network temporarily -> real error shown, no false success.
8. Verify public deployed URL, API connectivity, persistent data and sample PDFs before recording.

**Acceptance:** Every featured case produces the expected persisted decision without manual database editing, and all user-facing progress corresponds to actual backend work.

## 17. Seed data and fixture generation

Create `backend/scripts/seed_demo.py`, `backend/scripts/reset_demo.py`, and `backend/scripts/generate_invoices.py` (or equivalent). Use a PDF library to create actual vendor invoice PDFs, not JSON pretending to be PDFs. Vary fonts, headers, line arrangements and tax presentation. At least one test invoice should omit PO reference, and one should show freight plus detention. Add a scanned/image-only PDF if reliably supported.

Document fixture matrix and exact expected results in `docs/DEMO_SCENARIOS.md`. Use clear fixture names, but processing logic must never branch on filenames. Ensure each scenario's invoice number and PO are isolated or that run order is documented.

## 18. Implementation milestones for Codex

**M0 — Project skeleton + DB (first Codex task)**
- Scaffold React/TS/Vite/Tailwind and FastAPI; DB models/migrations, seed script, health endpoint and read-only vendor/PO endpoints.
- Minimal frontend fetches real vendor/PO records.
- Tests for DB relations and seeds. **Stop and report** before proceeding.

**M1 — Happy-path PDF-to-decision**
- Real PDF upload, AI extraction, schema validation, exact vendor/PO match, arithmetic, line and charge validation, transactionally committed approval, persisted events.
- Minimal real live run view; one fixture completes end to end. **Stop and verify**.

**M2 — Exception logic**
- Duplicate blocking; missing/ambiguous PO candidates; detention allowance review; partial-invoice capacity and concurrency; optional vendor mismatch.
- Tests and fixture PDFs for each. **Stop and verify**.

**M3 — Human review + revalidation**
- Confirm PO, correct extraction, procurement amendment, revalidate same invoice, immutable event history. **Stop and verify**.

**M4 — Product polish + deployment**
- Dashboard, detail side-by-side view, filters, accessible states, error recovery, reliable persistence, deployment and smoke tests.

**M5 — Submission**
- Rehearse live happy path + 2–3 edge cases, record edited on-camera <=5-minute buyer pitch, upload video, submit working process URL and video URL to coordinator. Subject: `ASA Case Study | [Your Name] | PS-4`.

**Time protection:** If behind schedule, cut advanced fuzzy matching, multi-vendor fixtures, extra charge types and animations before cutting a real working end-to-end run, real history, or a functioning review path. Do not build all screens before testing the happy path.

## 19. Expected repository layout

```text
invoiceflow-zamp/
  PROJECT_SPEC.md
  README.md
  .env.example
  frontend/
    src/
      components/
      pages/
      api/
      types/
    package.json
  backend/
    app/
      main.py
      api/
      core/
      db/
      models/
      schemas/
      services/
        extraction.py
        vendor_matching.py
        po_matching.py
        validation.py
        decision.py
        review.py
      tests/
    scripts/
      seed_demo.py
      reset_demo.py
      generate_invoices.py
    requirements.txt
  fixtures/
    invoices/
  docs/
    DEMO_SCENARIOS.md
    ARCHITECTURE.md
    ASSUMPTIONS.md
```

## 20. Assumptions, limitations and buyer-trust narrative

**Assumptions:** Fictional US-based enterprise; USD; approved vendor/PO/operations data preloaded; single-PO invoice MVP; specific contract allowances; reviewer actions recorded under demo role, not actual SSO. PO balances represent committed approvals, not cash paid. Tax arithmetic checked but not jurisdictional tax legality.

**Limitations to state honestly:** No live ERP or bank integration; no external EIN validation; synthetic gate logs; no actual payment; model extraction accuracy may vary; demo role selector not production authentication; not all scanned layouts or bundled charges supported; no generalized multi-PO allocation.

**Enterprise buyer concerns and our answer:**
- **Trust:** Show original PDF, extracted fields and every validation result.
- **Control:** Rules, not LLM prose, govern authorization and balances.
- **Risk:** Ambiguity leads to review, duplicates blocked, no blind overrides.
- **Audit:** Immutable run/event history, reasoned amendments and revalidation.
- **Operational usability:** Review queue and clear next actions, not only AI output.
- **Integration path:** Replace seeded procurement tables with ERP adapters later; current prototype demonstrates decisions rather than integration claims.

## 21. Five-minute pitch outline (not a slide deck)

- **0:00–0:40 — Buyer pain:** Thousands of inconsistent logistics PDFs, manual PO matching, detention/fuel exceptions, duplicate risk.
- **0:40–1:15 — Buyer concerns:** Accuracy, unauthorized spending, auditability, AP workload, confidence in automation.
- **1:15–2:25 — Happy path live:** Upload actual PDF, watch extraction, vendor/PO match, detention evidence, approval and committed balance.
- **2:25–4:20 — Edge cases live:** Duplicate blocked; valid detention held for authorization and revalidated; ambiguous PO routed to analyst (choose 2–3 cases based on reliable timing).
- **4:20–5:00 — Why this design:** AI for unstructured extraction, deterministic rules for controls, humans for uncertainty, persistent audit and clear integration roadmap.

Keep candidate on camera, narrating in their own voice; edit tightly; never substitute slides for the working product.

## 22. Definition of done

InvoiceFlow is done for this case study when a reviewer can open the deployed application, upload realistic invoice PDFs, watch **real** stages execute, inspect vendor/PO/evidence checks, see a correct persisted decision, resolve a deliberately designed exception, revalidate it, and review history — and when the candidate can explain every design choice and limitation confidently in a live demo.
