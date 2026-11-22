from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models.entities import (
    ActorType, AllocationStatus, ChargePolicy, Invoice, InvoiceEvent, InvoiceLine, InvoiceLineAllocation,
    InvoicePOAllocation, InvoiceRun, InvoiceStatus, POLine, POStatus, PurchaseOrder, ReviewCase, ReviewCaseStatus, RunStatus,
    ShipmentEvidence, ValidationResult, ValidationStatus, Vendor, VendorStatus,
)

D = Decimal
CENT = D("0.01")
ACTIVE_DUPLICATE_STATUSES = {
    InvoiceStatus.RECEIVED, InvoiceStatus.PROCESSING, InvoiceStatus.READY_FOR_VALIDATION,
    InvoiceStatus.APPROVED, InvoiceStatus.NEEDS_REVIEW, InvoiceStatus.BLOCKED,
    InvoiceStatus.DISPUTED,
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def money(value: Decimal | None) -> str | None:
    return None if value is None else f"{value.quantize(CENT):.2f}"


@dataclass
class RuleResult:
    code: str
    name: str
    outcome: ValidationStatus
    explanation: str
    expected: dict[str, Any] | None = None
    actual: dict[str, Any] | None = None
    difference: dict[str, Any] | None = None
    evidence: dict[str, Any] | None = None
    required: bool = True
    severity: str = "CONTROL"
    timestamp: datetime = field(default_factory=utcnow)

    def persist(self, db: Session, run_id: int) -> ValidationResult:
        row = ValidationResult(
            run_id=run_id, rule_code=self.code, rule_name=self.name,
            status=self.outcome, severity=self.severity, message=self.explanation,
            expected_json=self.expected, actual_json=self.actual,
            difference_json=self.difference, evidence_json=self.evidence,
            required=self.required, created_at=self.timestamp,
        )
        db.add(row)
        return row


def result(code: str, name: str, outcome: ValidationStatus, explanation: str, **kwargs: Any) -> RuleResult:
    return RuleResult(code, name, outcome, explanation, **kwargs)


def committed_po_total(db: Session, po_id: int) -> Decimal:
    value = db.scalar(select(func.coalesce(func.sum(InvoicePOAllocation.amount), 0)).where(
        InvoicePOAllocation.po_id == po_id,
        InvoicePOAllocation.status == AllocationStatus.COMMITTED,
    ))
    return D(value or 0)


def committed_line_quantity(db: Session, po_line_id: int) -> Decimal:
    value = db.scalar(select(func.coalesce(func.sum(InvoiceLineAllocation.allocated_quantity), 0))
        .join(InvoicePOAllocation, InvoiceLineAllocation.allocation_id == InvoicePOAllocation.id)
        .where(InvoiceLineAllocation.po_line_id == po_line_id,
               InvoicePOAllocation.status == AllocationStatus.COMMITTED))
    return D(value or 0)


def committed_charge_total(db: Session, policy_id: int) -> Decimal:
    value = db.scalar(select(func.coalesce(func.sum(InvoiceLineAllocation.allocated_amount), 0))
        .join(InvoicePOAllocation, InvoiceLineAllocation.allocation_id == InvoicePOAllocation.id)
        .where(InvoiceLineAllocation.charge_policy_id == policy_id,
               InvoicePOAllocation.status == AllocationStatus.COMMITTED))
    return D(value or 0)


def find_duplicate(db: Session, invoice: Invoice) -> Invoice | None:
    if invoice.vendor_id is None or not invoice.invoice_number_normalized:
        return None
    return db.scalar(select(Invoice).where(
        Invoice.id != invoice.id,
        Invoice.vendor_id == invoice.vendor_id,
        Invoice.invoice_number_normalized == invoice.invoice_number_normalized,
        Invoice.status.in_(ACTIVE_DUPLICATE_STATUSES),
    ).order_by(Invoice.created_at, Invoice.id).limit(1))


def _raw_uom(line: InvoiceLine) -> str | None:
    value = (line.raw_json or {}).get("unit_of_measure")
    return str(value).strip().upper() if value else None


def _base_lines(invoice: Invoice) -> list[InvoiceLine]:
    return [line for line in invoice.lines if line.charge_type in {"BASE_FREIGHT", "FREIGHT"}]


def _charge_lines(invoice: Invoice) -> list[InvoiceLine]:
    return [line for line in invoice.lines if line.charge_type not in {"BASE_FREIGHT", "FREIGHT"}]


def validate_invoice(
    db: Session, invoice: Invoice, run_id: int,
    stage: Callable[[str, str, str, dict[str, Any] | None], None] | None = None,
) -> list[RuleResult]:
    """Evaluate every safe deterministic M1B control and persist its evidence."""
    db.query(ValidationResult).filter(ValidationResult.run_id == run_id).delete()
    results: list[RuleResult] = []
    matching = invoice.matching_json or {}
    vendor_match = matching.get("vendor") or {}
    po_match = matching.get("purchase_order") or {}

    missing: list[str] = []
    for label, value in {
        "vendor identity": invoice.vendor_id, "invoice number": invoice.invoice_number_normalized,
        "invoice date": invoice.invoice_date, "currency": invoice.currency,
        "invoice total": invoice.total_amount, "line items": invoice.lines,
    }.items():
        if value is None or value == "" or value == []:
            missing.append(label)
    authorized_po_match = bool(po_match.get("automatic_match_permitted") and po_match.get("match_method") in {
        "EXACT_PO_REFERENCE", "ANALYST_CONFIRMED_PO",
    })
    if not authorized_po_match:
        missing.append("confirmed PO match")
    insufficient_lines = [line.line_number for line in invoice.lines if line.amount is None or not line.description]
    if insufficient_lines:
        missing.append("required line-item information")
    results.append(result("VAL-001", "Required invoice fields",
        ValidationStatus.PASS if not missing else ValidationStatus.REVIEW_REQUIRED,
        "All mandatory invoice fields are present." if not missing else "Mandatory information is missing or ambiguous.",
        expected={"mandatory_fields": "present and unambiguous"},
        actual={"missing_or_ambiguous": missing, "insufficient_line_numbers": insufficient_lines}))

    vendor = db.get(Vendor, invoice.vendor_id) if invoice.vendor_id else None
    vendor_conflicts = vendor_match.get("conflict_codes") or []
    vendor_ok = bool(vendor and vendor.status == VendorStatus.ACTIVE and vendor_match.get("automatic_match_permitted") and not vendor_conflicts)
    po = db.scalar(select(PurchaseOrder).options(
        selectinload(PurchaseOrder.lines), selectinload(PurchaseOrder.charge_policies)
    ).where(PurchaseOrder.id == invoice.matched_po_id)) if invoice.matched_po_id else None
    ownership_ok = bool(po and vendor and po.vendor_id == vendor.id)
    results.append(result("VAL-002", "Vendor authorization",
        ValidationStatus.PASS if vendor_ok and ownership_ok else ValidationStatus.REVIEW_REQUIRED,
        "Vendor is active, verified, conflict-free, and owns the matched PO." if vendor_ok and ownership_ok else "Vendor authorization is unresolved or conflicts with PO ownership.",
        expected={"vendor_status": "ACTIVE", "identity_conflicts": [], "po_owner_matches": True},
        actual={"vendor_id": invoice.vendor_id, "vendor_status": vendor.status.value if vendor else None,
                "identity_conflicts": vendor_conflicts, "po_owner_matches": ownership_ok}))

    if stage:
        stage("VALIDATING_DUPLICATES", "STARTED", "Business-key and document duplicate controls started.", None)
    duplicate = find_duplicate(db, invoice)
    results.append(result("VAL-003", "Duplicate invoice detection",
        ValidationStatus.BLOCK if duplicate else ValidationStatus.PASS,
        "An active invoice with the same verified supplier and invoice number already exists." if duplicate else "No active invoice has the same verified vendor and normalized invoice number.",
        expected={"duplicate": False},
        actual={"duplicate": bool(duplicate), "linked_invoice_id": duplicate.id if duplicate else None,
                "same_document_hash": bool(duplicate and duplicate.pdf_sha256 == invoice.pdf_sha256)},
        evidence={"business_key": [invoice.vendor_id, invoice.invoice_number_normalized]}))
    if stage:
        stage("VALIDATING_DUPLICATES", "COMPLETED", "Duplicate controls completed.", {"duplicate_invoice_id": duplicate.id if duplicate else None})

    po_ok = bool(po and po.status == POStatus.OPEN and ownership_ok and po_match.get("automatic_match_permitted"))
    results.append(result("VAL-004", "Purchase-order authorization",
        ValidationStatus.PASS if po_ok else ValidationStatus.REVIEW_REQUIRED,
        "The explicitly referenced PO is OPEN and owned by the verified vendor." if po_ok else "The PO is missing, ambiguous, closed, or not owned by the verified vendor.",
        expected={"status": "OPEN", "explicit_or_authorized_confirmation": True, "vendor_owned": True},
        actual={"po_id": po.id if po else None, "status": po.status.value if po else None,
                "match_method": po_match.get("match_method"), "vendor_owned": ownership_ok}))

    if stage:
        stage("VALIDATING_ARITHMETIC", "STARTED", "Decimal invoice arithmetic validation started.", None)
    arithmetic_issues: list[dict[str, Any]] = []
    for line in invoice.lines:
        if line.quantity is not None and line.unit_price is not None:
            calculated = line.quantity * line.unit_price
            diff = line.amount - calculated
            if abs(diff) > CENT:
                arithmetic_issues.append({"line": line.line_number, "expected": money(calculated), "actual": money(line.amount), "difference": money(diff)})
    line_sum = sum((line.amount for line in invoice.lines), D("0.00"))
    if invoice.subtotal is None or abs(line_sum - invoice.subtotal) > CENT:
        arithmetic_issues.append({"field": "subtotal", "expected": money(line_sum), "actual": money(invoice.subtotal),
                                  "difference": money(invoice.subtotal - line_sum) if invoice.subtotal is not None else None})
    if invoice.tax_amount is None:
        arithmetic_issues.append({"field": "tax", "issue": "not explicitly represented"})
    elif invoice.subtotal is not None and invoice.total_amount is not None:
        expected_total = invoice.subtotal + invoice.tax_amount
        if abs(invoice.total_amount - expected_total) > CENT:
            arithmetic_issues.append({"field": "total", "expected": money(expected_total), "actual": money(invoice.total_amount),
                                      "difference": money(invoice.total_amount - expected_total)})
    elif invoice.total_amount is None:
        arithmetic_issues.append({"field": "total", "issue": "not extracted"})
    if arithmetic_issues and invoice.subtotal is None and invoice.tax_amount is None \
            and invoice.total_amount is not None and abs(invoice.total_amount - line_sum) <= CENT:
        arithmetic_message = (f"The invoice lines total ${line_sum:,.2f} and match the invoice total, but subtotal and tax "
                              "are not explicitly stated. Missing tax is unknown and cannot be assumed to be $0.00.")
    elif arithmetic_issues and invoice.tax_amount is None:
        arithmetic_message = "Tax is not explicitly stated on the invoice. Missing tax is unknown and cannot be assumed to be $0.00."
    else:
        arithmetic_message = "Invoice arithmetic is incomplete or does not reconcile."
    results.append(result("VAL-005", "Invoice totals and line amounts",
        ValidationStatus.PASS if not arithmetic_issues else ValidationStatus.REVIEW_REQUIRED,
        "Line extensions, subtotal, tax, and total reconcile within $0.01." if not arithmetic_issues else arithmetic_message,
        expected={"tolerance": "0.01", "line_sum": money(line_sum)},
        actual={"subtotal": money(invoice.subtotal), "tax": money(invoice.tax_amount), "total": money(invoice.total_amount)},
        difference={"issues": arithmetic_issues}))
    if stage:
        stage("VALIDATING_ARITHMETIC", "COMPLETED", "Invoice arithmetic validation completed.", {"issue_count": len(arithmetic_issues)})

    currency_ok = bool(po and invoice.currency and invoice.currency.upper() == po.currency.upper())
    results.append(result("VAL-006", "Currency",
        ValidationStatus.PASS if currency_ok else ValidationStatus.REVIEW_REQUIRED,
        "Invoice and PO currencies match." if currency_ok else "Currency is missing or differs from the PO; M1B performs no FX conversion.",
        expected={"po_currency": po.currency if po else None}, actual={"invoice_currency": invoice.currency}))

    if stage:
        stage("VALIDATING_PO_LINES", "STARTED", "PO service, rate, and remaining-quantity checks started.", None)
    base_lines = _base_lines(invoice)
    line_issues: list[dict[str, Any]] = []
    rate_issues: list[dict[str, Any]] = []
    quantity_issues: list[dict[str, Any]] = []
    if po:
        for line in base_lines:
            candidates = [pl for pl in po.lines
                if pl.service_code == "FREIGHT"
                and (not line.shipment_ref or not pl.shipment_ref or line.shipment_ref == pl.shipment_ref)]
            if len(candidates) != 1:
                line_issues.append({"invoice_line": line.line_number, "candidate_po_line_ids": [item.id for item in candidates]})
                line.matched_po_line_id = None
                continue
            pline = candidates[0]
            line.matched_po_line_id = pline.id
            uom = _raw_uom(line)
            if uom and uom != pline.unit_of_measure.upper():
                line_issues.append({"invoice_line": line.line_number, "uom": uom, "expected_uom": pline.unit_of_measure})
            if line.unit_price is None or line.unit_price != pline.unit_price:
                rate_issues.append({"invoice_line": line.line_number, "expected": money(pline.unit_price), "actual": money(line.unit_price),
                                    "difference": money(line.unit_price - pline.unit_price) if line.unit_price is not None else None})
            remaining_qty = pline.ordered_quantity - committed_line_quantity(db, pline.id)
            if line.quantity is None or line.quantity > remaining_qty:
                quantity_issues.append({"invoice_line": line.line_number, "remaining_quantity": str(remaining_qty),
                                        "requested_quantity": str(line.quantity) if line.quantity is not None else None})
    elif base_lines:
        line_issues.append({"issue": "No confirmed PO is available for line matching."})
    results.append(result("VAL-007", "PO line matching",
        ValidationStatus.PASS if base_lines and not line_issues else ValidationStatus.REVIEW_REQUIRED,
        "Each base-service line maps uniquely to an authorized PO line." if base_lines and not line_issues else "One or more base-service lines cannot be mapped unambiguously.",
        actual={"issues": line_issues}, evidence={"matched_po_line_ids": [line.matched_po_line_id for line in base_lines]}))
    results.append(result("VAL-008", "Rate validation",
        ValidationStatus.PASS if base_lines and not rate_issues and not line_issues else ValidationStatus.REVIEW_REQUIRED,
        "All mapped base-service rates equal PO rates." if base_lines and not rate_issues and not line_issues else "A rate is missing, ambiguous, or differs from the authorized PO rate.",
        actual={"issues": rate_issues}))
    results.append(result("VAL-009", "Quantity and partial invoicing",
        ValidationStatus.PASS if base_lines and not quantity_issues and not line_issues else ValidationStatus.REVIEW_REQUIRED,
        "Requested quantities fit remaining committed-line capacity." if base_lines and not quantity_issues and not line_issues else "A quantity is missing or exceeds remaining PO-line authorization.",
        actual={"issues": quantity_issues}))
    if stage:
        stage("VALIDATING_PO_LINES", "COMPLETED", "PO line controls completed.", {
            "line_match_issues": len(line_issues), "rate_issues": len(rate_issues), "quantity_issues": len(quantity_issues)})

    if stage:
        stage("VALIDATING_CHARGES", "STARTED", "Accessorial policy, evidence, and allowance checks started.", None)
    detention_lines = [line for line in invoice.lines if line.charge_type == "DETENTION"]
    detention_calc_issues: list[dict[str, Any]] = []
    detention_allowance_issues: list[dict[str, Any]] = []
    for line in detention_lines:
        policy = next((item for item in (po.charge_policies if po else []) if item.charge_type == "DETENTION"), None)
        evidence = db.scalar(select(ShipmentEvidence).where(ShipmentEvidence.shipment_ref == line.shipment_ref)) if line.shipment_ref else None
        if not policy or not evidence or not evidence.verified or not vendor or evidence.vendor_id != vendor.id or evidence.po_id != (po.id if po else None):
            detention_calc_issues.append({"line": line.line_number, "policy_found": bool(policy), "verified_evidence": bool(evidence and evidence.verified),
                                           "shipment_reference": line.shipment_ref})
            continue
        waiting_hours = D(str((evidence.departure_at - evidence.arrival_at).total_seconds())) / D("3600")
        billable_hours = max(D("0"), waiting_hours - D(policy.free_hours or 0))
        expected = billable_hours * policy.rate
        if line.amount != expected or line.unit_price != policy.rate or line.quantity != billable_hours:
            detention_calc_issues.append({"line": line.line_number, "waiting_hours": str(waiting_hours), "free_hours": str(policy.free_hours),
                                           "billable_hours": str(billable_hours), "expected": money(expected), "actual": money(line.amount)})
        remaining_allowance = policy.max_total_allowance - committed_charge_total(db, policy.id)
        if line.amount > remaining_allowance:
            detention_allowance_issues.append({"line": line.line_number, "remaining_allowance": money(remaining_allowance),
                                                "claimed": money(line.amount), "shortfall": money(line.amount - remaining_allowance)})
    results.append(result("VAL-010-EVIDENCE", "Detention evidence and calculation",
        ValidationStatus.NOT_APPLICABLE if not detention_lines else ValidationStatus.PASS if not detention_calc_issues else ValidationStatus.REVIEW_REQUIRED,
        "No detention charge is present." if not detention_lines else "Verified shipment evidence supports the claimed detention calculation." if not detention_calc_issues else "Detention evidence, duration, or contractual rate is missing or inconsistent.",
        actual={"issues": detention_calc_issues}, required=bool(detention_lines)))
    results.append(result("VAL-010-ALLOWANCE", "Detention authorization allowance",
        ValidationStatus.NOT_APPLICABLE if not detention_lines else ValidationStatus.PASS if not detention_allowance_issues else ValidationStatus.REVIEW_REQUIRED,
        "No detention charge is present." if not detention_lines else "The detention charge fits the remaining authorized allowance." if not detention_allowance_issues else "The evidenced detention charge exceeds remaining financial authorization.",
        actual={"issues": detention_allowance_issues}, required=bool(detention_lines)))

    other_charges = [line for line in _charge_lines(invoice) if line.charge_type != "DETENTION"]
    other_issues: list[dict[str, Any]] = []
    for line in other_charges:
        policy = next((item for item in (po.charge_policies if po else []) if item.charge_type == line.charge_type), None)
        if not policy:
            other_issues.append({"line": line.line_number, "charge_type": line.charge_type, "issue": "No applicable charge policy."})
    results.append(result("VAL-011", "Other additional charges",
        ValidationStatus.NOT_APPLICABLE if not other_charges else ValidationStatus.PASS if not other_issues else ValidationStatus.REVIEW_REQUIRED,
        "No other accessorial charges are present." if not other_charges else "Each additional charge has applicable authorized terms." if not other_issues else "An additional charge is unknown or lacks an applicable policy/evidence.",
        actual={"issues": other_issues}, required=bool(other_charges)))
    if stage:
        stage("VALIDATING_CHARGES", "COMPLETED", "Accessorial controls completed.", {
            "detention_calculation_issues": len(detention_calc_issues),
            "detention_allowance_issues": len(detention_allowance_issues),
            "other_charge_issues": len(other_issues)})

    if stage:
        stage("VALIDATING_PO_CAPACITY", "STARTED", "Committed allocations and remaining PO capacity are being recalculated.", None)
    committed = committed_po_total(db, po.id) if po else D("0")
    remaining = po.authorized_total - committed if po else None
    capacity_ok = bool(po and invoice.total_amount is not None and remaining is not None and invoice.total_amount <= remaining)
    shortfall = invoice.total_amount - remaining if invoice.total_amount is not None and remaining is not None and invoice.total_amount > remaining else D("0")
    results.append(result("VAL-012", "PO financial capacity",
        ValidationStatus.PASS if capacity_ok else ValidationStatus.REVIEW_REQUIRED,
        "The proposed commitment fits remaining PO authorization." if capacity_ok else "The invoice total is missing or exceeds remaining PO authorization.",
        expected={"remaining_authorization": money(remaining)}, actual={"invoice_total": money(invoice.total_amount), "committed_total": money(committed)},
        difference={"authorization_shortfall": money(shortfall)}))

    date_ok = bool(po and invoice.invoice_date and (po.valid_from is None or invoice.invoice_date >= po.valid_from)
                   and (po.valid_to is None or invoice.invoice_date <= po.valid_to))
    results.append(result("VAL-013", "Invoice date and PO applicability",
        ValidationStatus.PASS if date_ok else ValidationStatus.REVIEW_REQUIRED,
        "Invoice date falls within the configured PO validity window." if date_ok else "Invoice date is missing or conflicts with configured PO validity dates.",
        expected={"valid_from": str(po.valid_from) if po and po.valid_from else None, "valid_to": str(po.valid_to) if po and po.valid_to else None},
        actual={"invoice_date": str(invoice.invoice_date) if invoice.invoice_date else None}))
    if stage:
        stage("VALIDATING_PO_CAPACITY", "COMPLETED", "PO capacity and applicability controls completed.", {
            "committed_total": money(committed), "remaining_authorization": money(remaining), "shortfall": money(shortfall)})

    for item in results:
        item.persist(db, run_id)
    db.flush()
    return results


def final_eligibility(results: list[RuleResult]) -> RuleResult:
    blocked = [item.code for item in results if item.outcome == ValidationStatus.BLOCK]
    review = [item.code for item in results if item.outcome in {ValidationStatus.FAIL, ValidationStatus.REVIEW_REQUIRED, ValidationStatus.TECHNICAL_ERROR}
              or (item.required and item.outcome == ValidationStatus.NOT_APPLICABLE)]
    if blocked:
        outcome = ValidationStatus.BLOCK
        explanation = "A definitive blocking control prevents automatic approval."
    elif review:
        outcome = ValidationStatus.REVIEW_REQUIRED
        explanation = "One or more mandatory controls require analyst resolution."
    else:
        outcome = ValidationStatus.PASS
        explanation = "All mandatory applicable controls passed; transactional allocation may proceed."
    return result("VAL-014", "Final approval eligibility", outcome, explanation,
                  actual={"blocking_rules": blocked, "review_rules": review})


class AllocationConflict(RuntimeError):
    pass


def commit_allocation(db: Session, invoice_id: int, run_id: int | None = None) -> InvoicePOAllocation:
    """Serialize SQLite writers, recheck controls, and atomically create one commitment."""
    db.commit()
    if db.bind and db.bind.dialect.name == "sqlite":
        db.connection().exec_driver_sql("BEGIN IMMEDIATE")
    invoice = db.scalar(select(Invoice).options(selectinload(Invoice.lines)).where(Invoice.id == invoice_id))
    if invoice is None or invoice.status == InvoiceStatus.APPROVED:
        raise AllocationConflict("Invoice is missing or has already been approved.")
    if db.scalar(select(InvoicePOAllocation.id).where(InvoicePOAllocation.invoice_id == invoice_id)):
        raise AllocationConflict("An allocation already exists for this invoice.")
    duplicate = find_duplicate(db, invoice)
    if duplicate:
        raise AllocationConflict(f"Duplicate invoice {duplicate.id} became active before commit.")
    po = db.scalar(select(PurchaseOrder).options(selectinload(PurchaseOrder.lines), selectinload(PurchaseOrder.charge_policies))
                   .where(PurchaseOrder.id == invoice.matched_po_id)) if invoice.matched_po_id else None
    if not po or po.status != POStatus.OPEN or po.vendor_id != invoice.vendor_id or invoice.total_amount is None:
        raise AllocationConflict("PO ownership, status, or invoice total changed before commit.")
    remaining = po.authorized_total - committed_po_total(db, po.id)
    if invoice.total_amount > remaining:
        raise AllocationConflict("Remaining PO authorization changed before commit.")
    for line in invoice.lines:
        if line.matched_po_line_id:
            po_line = next((item for item in po.lines if item.id == line.matched_po_line_id), None)
            if not po_line or line.quantity is None or line.quantity > po_line.ordered_quantity - committed_line_quantity(db, po_line.id):
                raise AllocationConflict("Remaining PO line quantity changed before commit.")
        elif line.charge_type == "DETENTION":
            policy = next((item for item in po.charge_policies if item.charge_type == "DETENTION"), None)
            if not policy or line.amount > policy.max_total_allowance - committed_charge_total(db, policy.id):
                raise AllocationConflict("Remaining detention allowance changed before commit.")
    allocation = InvoicePOAllocation(invoice_id=invoice.id, po_id=po.id, amount=invoice.total_amount,
                                     status=AllocationStatus.COMMITTED)
    db.add(allocation)
    db.flush()
    for line in invoice.lines:
        policy = next((item for item in po.charge_policies if item.charge_type == line.charge_type), None)
        db.add(InvoiceLineAllocation(
            allocation_id=allocation.id, invoice_line_id=line.id,
            po_line_id=line.matched_po_line_id, charge_policy_id=policy.id if policy else None,
            allocated_quantity=line.quantity, allocated_amount=line.amount,
        ))
    invoice.status = InvoiceStatus.APPROVED
    invoice.decision_reason = "All mandatory deterministic controls passed and the PO allocation committed atomically."
    for review_case in db.scalars(select(ReviewCase).where(
        ReviewCase.invoice_id == invoice.id, ReviewCase.status == ReviewCaseStatus.OPEN)).all():
        review_case.status = ReviewCaseStatus.RESOLVED
        review_case.resolution_type = "APPROVED_AFTER_REVALIDATION"
        review_case.resolution_details = {"run_id": run_id, "allocation_id": allocation.id}
        review_case.resolved_at = utcnow()
    if run_id is not None:
        run = db.get(InvoiceRun, run_id)
        if run is None:
            raise AllocationConflict("Processing run disappeared before commit.")
        run.status = RunStatus.COMPLETED
        run.completed_at = utcnow()
        for stage, message, details in [
            ("COMMITTING_ALLOCATION", "PO allocation committed atomically.", {"allocation_id": allocation.id, "amount": money(allocation.amount)}),
            ("DECIDING", "Business decision completed.", {"business_outcome": "APPROVED"}),
            ("DECISION_COMPLETE", "Financial validation run completed.", {"business_outcome": "APPROVED"}),
        ]:
            db.add(InvoiceEvent(
                invoice_id=invoice.id, run_id=run_id, event_type="PIPELINE_STAGE", stage=stage,
                status="COMPLETED", actor_type=ActorType.SYSTEM, actor_name=None,
                message=message, details_json=details,
            ))
    db.commit()
    return allocation
