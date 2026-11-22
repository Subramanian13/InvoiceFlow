from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models.entities import ActorType, Invoice, InvoiceEvent, InvoiceLine, InvoiceRun, InvoiceStatus, RunStatus, ValidationResult, ValidationStatus
from app.services.extraction import ExtractionProvider, ExtractionProviderError
from app.services.normalization import normalize_charge_type, normalize_extraction, normalize_tax_identifier
from app.services.po_matching import match_purchase_order
from app.services.vendor_matching import match_vendor
from app.services.validation import AllocationConflict, commit_allocation, final_eligibility, validate_invoice
from app.services.review import sync_review_cases


def now() -> datetime:
    return datetime.now(timezone.utc)


def add_event(db: Session, invoice_id: int, run_id: int, stage: str, status: str, message: str, details: dict | None = None) -> None:
    db.add(InvoiceEvent(invoice_id=invoice_id, run_id=run_id, event_type="PIPELINE_STAGE", stage=stage,
        status=status, actor_type=ActorType.SYSTEM, actor_name=None, message=message, details_json=details))
    db.commit()


def sanitize_extraction(payload: Any) -> Any:
    if isinstance(payload, dict):
        result = {}
        for key, value in payload.items():
            if key in {"vendor_tax_identifier", "tax_identifier", "tax_id"}:
                normalized = normalize_tax_identifier(str(value)) if value else None
                result[key] = {"present": bool(normalized), "last4": normalized[-4:] if normalized else None, "redacted": True}
            else:
                result[key] = sanitize_extraction(value)
        return result
    if isinstance(payload, list):
        return [sanitize_extraction(item) for item in payload]
    return payload


def process_invoice(run_id: int, session_factory: sessionmaker, provider_factory: Callable[[], ExtractionProvider]) -> None:
    with session_factory() as db:
        run = db.get(InvoiceRun, run_id)
        if run is None:
            return
        invoice = db.get(Invoice, run.invoice_id)
        if invoice is None:
            return
        run.status = RunStatus.RUNNING
        run.started_at = now()
        invoice.status = InvoiceStatus.PROCESSING
        db.commit()
        current_stage = "EXTRACTING"
        try:
            add_event(db, invoice.id, run.id, "EXTRACTING", "STARTED", "Gemini document extraction started.")
            pdf_bytes = Path(invoice.pdf_storage_key).read_bytes()
            provider = provider_factory()
            result = provider.extract(pdf_bytes)
            invoice.extraction_provider = result.provider
            invoice.extraction_model = result.model
            invoice.extraction_duration_ms = result.duration_ms
            raw_data = result.data.model_dump(mode="json")
            invoice.extraction_json = {
                "raw_extraction": sanitize_extraction(raw_data),
                "raw_provider_response": sanitize_extraction(result.raw_response),
                "normalization_changes": [],
                "missing_fields": result.data.missing_fields,
                "uncertain_fields": result.data.uncertain_fields,
                "warnings": result.data.warnings,
                "source_references": result.data.source_references,
            }
            db.commit()
            add_event(db, invoice.id, run.id, "EXTRACTING", "COMPLETED", "Structured extraction completed.",
                {"provider": result.provider, "model": result.model, "duration_ms": result.duration_ms})

            current_stage = "NORMALIZING"
            add_event(db, invoice.id, run.id, "NORMALIZING", "STARTED", "Deterministic normalization started.")
            normalized, changes, exceptions = normalize_extraction(result.data)
            invoice.invoice_number = normalized["invoice_number"]
            invoice.invoice_number_normalized = normalized["invoice_number_normalized"]
            invoice.vendor_name_raw = normalized["vendor_name"] or ""
            tax_normalized = normalize_tax_identifier(result.data.vendor_tax_identifier)
            invoice.tax_id_last4_raw = tax_normalized[-4:] if tax_normalized else None
            invoice.po_reference_raw = normalized["po_reference"]
            invoice.shipment_ref = normalized["shipment_reference"]
            invoice.invoice_date = normalized["invoice_date"]
            invoice.due_date = normalized["due_date"]
            invoice.currency = normalized["currency"]
            invoice.subtotal = normalized["subtotal"]
            invoice.tax_amount = normalized["tax"]
            invoice.total_amount = normalized["total_amount"]
            invoice.extraction_json = {**(invoice.extraction_json or {}), "normalization_changes": changes}
            invoice.lines.clear()
            for index, line in enumerate(result.data.lines, 1):
                invoice.lines.append(InvoiceLine(
                    line_number=index, description=line.description, charge_type=normalize_charge_type(line.charge_type).value,
                    quantity=line.quantity, unit_price=line.unit_price, amount=line.line_amount,
                    shipment_ref=line.shipment_reference, extraction_confidence=None,
                    raw_json=sanitize_extraction(line.model_dump(mode="json")),
                ))
            db.commit()
            add_event(db, invoice.id, run.id, "NORMALIZING", "COMPLETED", "Extracted values normalized without guessing missing data.",
                {"change_count": len(changes), "exception_count": len(exceptions)})

            current_stage = "VENDOR_MATCHING"
            add_event(db, invoice.id, run.id, "VENDOR_MATCHING", "STARTED", "Vendor-master matching started.")
            vendor_result = match_vendor(db, result.data.vendor_name, result.data.vendor_tax_identifier)
            invoice.vendor_id = vendor_result.matched_vendor_id
            if vendor_result.conflict_codes:
                exceptions.extend({"code": code, "field": "vendor", "message": "Vendor identity requires review."} for code in vendor_result.conflict_codes)
            db.commit()
            add_event(db, invoice.id, run.id, "VENDOR_MATCHING", "COMPLETED", "Vendor matching completed.", vendor_result.model_dump(mode="json"))

            current_stage = "PO_MATCHING"
            add_event(db, invoice.id, run.id, "PO_MATCHING", "STARTED", "Purchase-order matching started.")
            po_result = match_purchase_order(db, vendor_result.matched_vendor_id, result.data.po_reference,
                result.data.shipment_reference, [line.description for line in result.data.lines])
            invoice.matched_po_id = po_result.matched_po_id
            if po_result.conflict_codes:
                exceptions.extend({"code": code, "field": "purchase_order", "message": "Purchase-order matching requires review."} for code in po_result.conflict_codes)
            invoice.matching_json = {"vendor": vendor_result.model_dump(mode="json"), "purchase_order": po_result.model_dump(mode="json")}
            invoice.exceptions_json = exceptions
            db.commit()
            add_event(db, invoice.id, run.id, "PO_MATCHING", "COMPLETED", "Purchase-order matching completed.", po_result.model_dump(mode="json"))

            exact_match = vendor_result.automatic_match_permitted and po_result.automatic_match_permitted and not exceptions
            invoice.status = InvoiceStatus.READY_FOR_VALIDATION if exact_match else InvoiceStatus.NEEDS_REVIEW
            invoice.decision_reason = "Vendor and PO matching completed; deterministic financial validation is next." if exact_match else "Matching completed with business exceptions; dependent financial controls will fail closed."
            db.commit()
            add_event(db, invoice.id, run.id, "MATCHING_COMPLETE", "COMPLETED",
                "Technical matching stage completed.",
                {"business_outcome": "READY_FOR_VALIDATION" if exact_match else "NEEDS_REVIEW",
                 "ready_for_financial_validation": exact_match})

            current_stage = "VALIDATING"
            def validation_stage(stage: str, status: str, message: str, details: dict | None) -> None:
                add_event(db, invoice.id, run.id, stage, status, message, details)

            validation_results = validate_invoice(db, invoice, run.id, validation_stage)
            db.commit()
            current_stage = "DECIDING"
            add_event(db, invoice.id, run.id, "DECIDING", "STARTED", "Deterministic decision precedence started.")
            eligibility = final_eligibility(validation_results)
            eligibility.persist(db, run.id)
            db.commit()

            if eligibility.outcome == ValidationStatus.BLOCK:
                invoice.status = InvoiceStatus.BLOCKED
                invoice.decision_reason = eligibility.explanation
            elif eligibility.outcome != ValidationStatus.PASS:
                invoice.status = InvoiceStatus.NEEDS_REVIEW
                invoice.decision_reason = eligibility.explanation
            else:
                current_stage = "COMMITTING_ALLOCATION"
                add_event(db, invoice.id, run.id, "COMMITTING_ALLOCATION", "STARTED",
                          "Final controls are being rechecked under a serialized database transaction.")
                try:
                    commit_allocation(db, invoice.id, run.id)
                    return
                except AllocationConflict as exc:
                    db.rollback()
                    invoice = db.get(Invoice, invoice.id)
                    invoice.status = InvoiceStatus.NEEDS_REVIEW
                    invoice.decision_reason = str(exc)
                    eligibility.outcome = ValidationStatus.REVIEW_REQUIRED
                    row = db.query(ValidationResult).filter_by(run_id=run.id, rule_code="VAL-014").first()
                    if row:
                        row.status = ValidationStatus.REVIEW_REQUIRED
                        row.message = f"Final transactional recheck prevented approval: {exc}"
                    db.commit()
                    add_event(db, invoice.id, run.id, "COMMITTING_ALLOCATION", "FAILED",
                              "Allocation was rolled back because a final control changed.", {"reason": str(exc)})

            add_event(db, invoice.id, run.id, "DECIDING", "COMPLETED", "Business decision completed.",
                      {"business_outcome": invoice.status.value})
            run.status = RunStatus.COMPLETED
            run.completed_at = now()
            sync_review_cases(db, invoice, run.id)
            db.commit()
            add_event(db, invoice.id, run.id, "DECISION_COMPLETE", "COMPLETED",
                      "Financial validation run completed.", {"business_outcome": invoice.status.value})
        except ExtractionProviderError as exc:
            fail_run(db, invoice, run, current_stage, exc.code, str(exc))
        except Exception:
            fail_run(db, invoice, run, current_stage, "PIPELINE_UNEXPECTED_ERROR", "Processing failed unexpectedly. Review server logs for the internal exception.")


def fail_run(db: Session, invoice: Invoice, run: InvoiceRun, stage: str, code: str, message: str) -> None:
    invoice.status = InvoiceStatus.PROCESSING_FAILED
    invoice.decision_reason = message
    invoice.exceptions_json = [*(invoice.exceptions_json or []), {"code": code, "field": stage, "message": message}]
    run.status = RunStatus.FAILED
    run.error_code = code
    run.completed_at = now()
    db.commit()
    add_event(db, invoice.id, run.id, stage, "FAILED", message, {"error_code": code})

