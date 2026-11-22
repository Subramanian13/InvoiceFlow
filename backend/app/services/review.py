from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models.entities import (
    ActorType, ChargePolicy, FieldCorrection, Invoice, InvoiceEvent, InvoiceRun,
    InvoiceStatus, POAmendment, POConfirmation, POStatus, PurchaseOrder,
    ReviewAction, ReviewActionType, ReviewCase, ReviewCaseStatus, RunStatus,
    ValidationResult, ValidationStatus,
)
from app.services.normalization import normalize_invoice_number, normalize_po_reference, normalize_shipment_reference
from app.services.po_matching import match_purchase_order
from app.services.validation import AllocationConflict, commit_allocation, final_eligibility, validate_invoice
from app.services.vendor_matching import match_vendor


def now() -> datetime:
    return datetime.now(timezone.utc)


CATEGORIES = {
    "VAL-001": "MISSING_INVOICE_FIELD", "VAL-002": "VENDOR_IDENTITY",
    "VAL-003": "DUPLICATE", "VAL-004": "MISSING_OR_AMBIGUOUS_PO",
    "VAL-005": "ARITHMETIC", "VAL-006": "CURRENCY",
    "VAL-007": "PO_LINE_MATCH", "VAL-008": "RATE_DISCREPANCY",
    "VAL-009": "QUANTITY_EXCEEDED", "VAL-010-EVIDENCE": "DETENTION_EVIDENCE",
    "VAL-010-ALLOWANCE": "DETENTION_AUTHORIZATION", "VAL-011": "UNSUPPORTED_CHARGE",
    "VAL-012": "PO_CAPACITY_EXCEEDED", "VAL-013": "PO_DATE_APPLICABILITY",
    "VAL-014": "FINAL_ELIGIBILITY",
}


def add_event(db: Session, invoice: Invoice, run_id: int | None, stage: str, status: str,
              message: str, actor_type: ActorType = ActorType.SYSTEM,
              actor_name: str | None = None, details: dict[str, Any] | None = None) -> None:
    db.add(InvoiceEvent(invoice_id=invoice.id, run_id=run_id, event_type="REVIEW_WORKFLOW",
        stage=stage, status=status, actor_type=actor_type, actor_name=actor_name,
        message=message, details_json=details))


def sync_review_cases(db: Session, invoice: Invoice, run_id: int) -> None:
    rows = db.scalars(select(ValidationResult).where(ValidationResult.run_id == run_id)).all()
    active = {
        row.rule_code: row for row in rows
        if row.status in {ValidationStatus.FAIL, ValidationStatus.REVIEW_REQUIRED, ValidationStatus.BLOCK, ValidationStatus.TECHNICAL_ERROR}
        or (row.required and row.status == ValidationStatus.NOT_APPLICABLE)
    }
    open_cases = db.scalars(select(ReviewCase).where(
        ReviewCase.invoice_id == invoice.id, ReviewCase.status == ReviewCaseStatus.OPEN)).all()
    existing = {case.exception_code: case for case in open_cases}
    for code, row in active.items():
        if code == "VAL-014":
            continue
        if code not in existing:
            db.add(ReviewCase(invoice_id=invoice.id, validation_result_id=row.id,
                exception_code=code, category=CATEGORIES.get(code, "OTHER"), summary=row.message,
                status=ReviewCaseStatus.OPEN))
        else:
            existing[code].validation_result_id = row.id
            existing[code].summary = row.message
    for code, case in existing.items():
        if code not in active:
            case.status = ReviewCaseStatus.RESOLVED
            case.resolution_type = "REVALIDATION_PASSED"
            case.resolution_details = {"run_id": run_id}
            case.resolved_at = now()


def _next_run(db: Session, invoice: Invoice) -> InvoiceRun:
    number = db.scalar(select(func.coalesce(func.max(InvoiceRun.run_number), 0)).where(
        InvoiceRun.invoice_id == invoice.id)) or 0
    run = InvoiceRun(invoice_id=invoice.id, run_number=int(number) + 1,
                     status=RunStatus.RUNNING, started_at=now())
    db.add(run); db.flush()
    return run


def revalidate_invoice(db: Session, invoice_id: int, actor_name: str, reason: str,
                       idempotency_key: str | None = None) -> InvoiceRun:
    invoice = db.scalar(select(Invoice).options(selectinload(Invoice.lines)).where(Invoice.id == invoice_id))
    if invoice is None:
        raise ValueError("Invoice not found.")
    if invoice.status == InvoiceStatus.APPROVED:
        raise ValueError("Approved invoices cannot be revalidated into another commitment.")
    if idempotency_key:
        prior = db.scalar(select(ReviewAction).where(ReviewAction.idempotency_key == idempotency_key))
        if prior:
            return db.scalar(select(InvoiceRun).where(InvoiceRun.invoice_id == invoice.id).order_by(InvoiceRun.run_number.desc()))
    action = ReviewAction(invoice_id=invoice.id, actor_name=actor_name, actor_role="AP_ANALYST",
        action_type=ReviewActionType.REVALIDATE, reason=reason,
        payload_json=None, idempotency_key=idempotency_key)
    db.add(action)
    run = _next_run(db, invoice)
    invoice.status = InvoiceStatus.PROCESSING
    add_event(db, invoice, run.id, "REVALIDATION", "STARTED", "Deterministic revalidation started.",
              ActorType.AP_ANALYST, actor_name, {"reason": reason})

    confirmation = db.scalar(select(POConfirmation).where(POConfirmation.invoice_id == invoice.id)
                             .order_by(POConfirmation.created_at.desc(), POConfirmation.id.desc()))
    if confirmation:
        po = db.get(PurchaseOrder, confirmation.po_id)
        po_result = {
            "matched_po_id": po.id, "match_method": "ANALYST_CONFIRMED_PO",
            "automatic_match_permitted": True,
            "evidence": [f"{actor_name} confirmed {po.po_number}; backend verified OPEN status and vendor ownership."],
            "conflict_codes": [], "candidates": ((invoice.matching_json or {}).get("purchase_order") or {}).get("candidates", []),
        }
        invoice.matched_po_id = po.id
    else:
        matched = match_purchase_order(db, invoice.vendor_id, invoice.po_reference_raw,
            invoice.shipment_ref, [line.description for line in invoice.lines])
        po_result = matched.model_dump(mode="json")
        invoice.matched_po_id = matched.matched_po_id
    invoice.matching_json = {**(invoice.matching_json or {}), "purchase_order": po_result}
    db.flush()

    def stage(name: str, status: str, message: str, details: dict[str, Any] | None) -> None:
        add_event(db, invoice, run.id, name, status, message, details=details)
        db.flush()

    results = validate_invoice(db, invoice, run.id, stage)
    eligibility = final_eligibility(results)
    eligibility.persist(db, run.id)
    db.flush()
    if eligibility.outcome == ValidationStatus.BLOCK:
        invoice.status = InvoiceStatus.BLOCKED
        invoice.decision_reason = eligibility.explanation
    elif eligibility.outcome != ValidationStatus.PASS:
        invoice.status = InvoiceStatus.NEEDS_REVIEW
        invoice.decision_reason = eligibility.explanation
    else:
        db.commit()
        try:
            commit_allocation(db, invoice.id, run.id)
            invoice = db.get(Invoice, invoice.id)
            sync_review_cases(db, invoice, run.id)
            db.commit()
            return run
        except AllocationConflict as exc:
            db.rollback()
            invoice = db.get(Invoice, invoice.id)
            run = db.get(InvoiceRun, run.id)
            invoice.status = InvoiceStatus.NEEDS_REVIEW
            invoice.decision_reason = str(exc)
    run.status = RunStatus.COMPLETED
    run.completed_at = now()
    add_event(db, invoice, run.id, "DECISION_COMPLETE", "COMPLETED", "Revalidation decision completed.",
              details={"business_outcome": invoice.status.value})
    sync_review_cases(db, invoice, run.id)
    db.commit()
    return run


def confirm_po(db: Session, invoice_id: int, po_id: int, actor_name: str, reason: str,
               idempotency_key: str | None = None) -> InvoiceRun:
    invoice = db.get(Invoice, invoice_id)
    po = db.get(PurchaseOrder, po_id)
    if not invoice or not po:
        raise ValueError("Invoice or purchase order not found.")
    if not invoice.vendor_id:
        raise ValueError("A verified vendor is required before PO confirmation.")
    if po.vendor_id != invoice.vendor_id:
        raise ValueError("The selected PO belongs to a different vendor.")
    if po.status != POStatus.OPEN:
        raise ValueError("Only an OPEN purchase order can be confirmed.")
    if idempotency_key:
        prior = db.scalar(select(ReviewAction).where(ReviewAction.idempotency_key == idempotency_key))
        if prior:
            return db.scalar(select(InvoiceRun).where(InvoiceRun.invoice_id == invoice_id).order_by(InvoiceRun.run_number.desc()))
    action = ReviewAction(invoice_id=invoice.id, actor_name=actor_name, actor_role="AP_ANALYST",
        action_type=ReviewActionType.CONFIRM_PO, reason=reason,
        payload_json={"po_id": po.id, "po_number": po.po_number}, idempotency_key=idempotency_key)
    db.add(action); db.flush()
    db.add(POConfirmation(invoice_id=invoice.id, po_id=po.id, review_action_id=action.id,
        actor_name=actor_name, reason=reason))
    add_event(db, invoice, None, "PO_CONFIRMED", "COMPLETED", f"{po.po_number} confirmed for revalidation.",
              ActorType.AP_ANALYST, actor_name, {"po_id": po.id, "reason": reason})
    db.commit()
    return revalidate_invoice(db, invoice.id, actor_name, "Revalidate after PO confirmation.")


HEADER_FIELDS: dict[str, tuple[str, Callable[[str], Any]]] = {
    "vendor_name": ("vendor_name_raw", lambda value: value.strip()),
    "invoice_number": ("invoice_number", lambda value: value.strip()),
    "invoice_date": ("invoice_date", date.fromisoformat),
    "due_date": ("due_date", date.fromisoformat),
    "currency": ("currency", lambda value: value.strip().upper()),
    "subtotal": ("subtotal", Decimal),
    "tax_amount": ("tax_amount", Decimal),
    "total_amount": ("total_amount", Decimal),
    "po_reference": ("po_reference_raw", lambda value: value.strip()),
    "shipment_reference": ("shipment_ref", lambda value: value.strip()),
}
LINE_FIELDS = {"description": str, "quantity": Decimal, "unit_price": Decimal, "line_amount": Decimal}


def correct_field(db: Session, invoice_id: int, field_path: str, value: str, actor_name: str,
                  reason: str, idempotency_key: str | None = None) -> InvoiceRun:
    return correct_fields(db, invoice_id, [(field_path, value)], actor_name, reason, idempotency_key)


def correct_fields(db: Session, invoice_id: int, corrections: list[tuple[str, str]], actor_name: str,
                   reason: str, idempotency_key: str | None = None) -> InvoiceRun:
    invoice = db.scalar(select(Invoice).options(selectinload(Invoice.lines)).where(Invoice.id == invoice_id))
    if not invoice or invoice.status == InvoiceStatus.APPROVED:
        raise ValueError("Only unapproved invoices can be corrected.")
    if not corrections:
        raise ValueError("At least one changed field is required.")
    if idempotency_key:
        prior = db.scalar(select(ReviewAction).where(ReviewAction.idempotency_key == idempotency_key))
        if prior:
            return db.scalar(select(InvoiceRun).where(InvoiceRun.invoice_id == invoice_id).order_by(InvoiceRun.run_number.desc()))
    action = ReviewAction(invoice_id=invoice.id, actor_name=actor_name, actor_role="AP_ANALYST",
        action_type=ReviewActionType.CORRECT_EXTRACTION, reason=reason,
        payload_json={"field_paths": [path for path, _ in corrections]}, idempotency_key=idempotency_key)
    db.add(action); db.flush()
    changes = []
    for field_path, value in corrections:
        target: Any = invoice
        if field_path in HEADER_FIELDS:
            attribute, converter = HEADER_FIELDS[field_path]
        elif field_path.startswith("lines."):
            parts = field_path.split(".")
            if len(parts) != 3 or parts[2] not in LINE_FIELDS:
                raise ValueError("Unsupported line correction path.")
            target = next((line for line in invoice.lines if line.line_number == int(parts[1])), None)
            if target is None:
                raise ValueError("Invoice line not found.")
            attribute = "amount" if parts[2] == "line_amount" else parts[2]
            converter = LINE_FIELDS[parts[2]]
        else:
            raise ValueError("Unsupported correction field.")
        try:
            corrected = converter(value)
        except (ValueError, InvalidOperation) as exc:
            raise ValueError(f"Corrected value for {field_path} has an invalid format.") from exc
        original = getattr(target, attribute)
        if original == corrected:
            continue
        db.add(FieldCorrection(invoice_id=invoice.id, review_action_id=action.id, field_path=field_path,
            original_value_json={"value": str(original) if original is not None else None},
            corrected_value_json={"value": str(corrected)}, reason=reason, actor_name=actor_name))
        setattr(target, attribute, corrected)
        changes.append({"field_path": field_path, "before": str(original) if original is not None else None, "after": str(corrected)})
        if field_path == "vendor_name":
            vendor_result = match_vendor(db, invoice.vendor_name_raw, None)
            invoice.vendor_id = vendor_result.matched_vendor_id
            invoice.matched_po_id = None
            invoice.matching_json = {**(invoice.matching_json or {}), "vendor": vendor_result.model_dump(mode="json")}
        elif field_path == "invoice_number":
            invoice.invoice_number_normalized = normalize_invoice_number(corrected)
        elif field_path == "po_reference":
            invoice.matched_po_id = None
        elif field_path == "shipment_reference":
            invoice.shipment_ref = corrected
    if not changes:
        raise ValueError("No extracted values changed.")
    add_event(db, invoice, None, "FIELD_CORRECTED", "COMPLETED", f"Corrected {len(changes)} extracted field(s) and queued revalidation.",
              ActorType.AP_ANALYST, actor_name, {"changes": changes, "reason": reason})
    db.commit()
    return revalidate_invoice(db, invoice.id, actor_name, "Revalidate after correcting extracted information.")


def amend_authorization(db: Session, invoice_id: int, po_id: int, amendment_scope: str,
                        new_authorized_total: Decimal | None, charge_type: str,
                        new_allowance: Decimal | None, actor_name: str,
                        approval_reference: str, reason: str, idempotency_key: str | None = None) -> InvoiceRun:
    invoice = db.get(Invoice, invoice_id)
    po = db.scalar(select(PurchaseOrder).options(selectinload(PurchaseOrder.charge_policies)).where(PurchaseOrder.id == po_id))
    if not invoice or not po or invoice.matched_po_id != po.id:
        raise ValueError("Invoice and matched purchase order are required.")
    policy = next((item for item in po.charge_policies if item.charge_type == charge_type), None)
    if not policy:
        raise ValueError("The requested charge policy does not exist.")
    proposed_total = new_authorized_total if amendment_scope in {"PO_TOTAL", "BOTH"} else po.authorized_total
    proposed_allowance = new_allowance if amendment_scope in {"CHARGE_ALLOWANCE", "BOTH"} else policy.max_total_allowance
    if proposed_total is None or proposed_allowance is None:
        raise ValueError("The proposed authorization value is required for the selected amendment scope.")
    if proposed_total < po.authorized_total or proposed_allowance < policy.max_total_allowance:
        raise ValueError("M2 amendments cannot reduce existing authorization.")
    if not approval_reference.strip() or len(reason.strip()) < 8:
        raise ValueError("Approval reference and a meaningful justification are required.")
    if idempotency_key:
        prior = db.scalar(select(ReviewAction).where(ReviewAction.idempotency_key == idempotency_key))
        if prior:
            return db.scalar(select(InvoiceRun).where(InvoiceRun.invoice_id == invoice_id).order_by(InvoiceRun.run_number.desc()))
    previous_total, previous_allowance = po.authorized_total, policy.max_total_allowance
    po.authorized_total = proposed_total
    policy.max_total_allowance = proposed_allowance
    po.version += 1
    amendment = POAmendment(po_id=po.id, invoice_id=invoice.id,
        previous_authorized_total=previous_total, new_authorized_total=proposed_total,
        charge_type=charge_type, previous_allowance=previous_allowance, new_allowance=proposed_allowance,
        approved_by=actor_name, approval_reference=approval_reference, reason=reason)
    db.add(amendment)
    db.add(ReviewAction(invoice_id=invoice.id, actor_name=actor_name, actor_role="PROCUREMENT",
        action_type=ReviewActionType.RECORD_PO_AMENDMENT, reason=reason,
        payload_json={"po_id": po.id, "amendment_scope": amendment_scope,
                      "previous_total": str(previous_total), "new_total": str(proposed_total),
                      "charge_type": charge_type, "previous_allowance": str(previous_allowance), "new_allowance": str(proposed_allowance),
                      "approval_reference": approval_reference}, idempotency_key=idempotency_key))
    add_event(db, invoice, None, "AUTHORIZATION_AMENDED", "COMPLETED", "Authorized PO and charge-policy amendment recorded.",
              ActorType.PROCUREMENT, actor_name, {"po_id": po.id, "approval_reference": approval_reference,
              "amendment_scope": amendment_scope,
              "po_total_before": str(previous_total), "po_total_after": str(proposed_total),
              "allowance_before": str(previous_allowance), "allowance_after": str(proposed_allowance), "reason": reason})
    db.commit()
    return revalidate_invoice(db, invoice.id, actor_name, "Revalidate after authorized procurement amendment.")
