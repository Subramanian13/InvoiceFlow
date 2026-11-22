from datetime import datetime
from decimal import Decimal
import hashlib
from pathlib import Path
from uuid import uuid4

import secrets
from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.responses import FileResponse
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, selectinload

from app.db.session import get_db
from app.core.config import get_settings
from app.models.entities import ActorType, AllocationStatus, FieldCorrection, Invoice, InvoiceEvent, InvoiceLine, InvoicePOAllocation, InvoiceRun, InvoiceStatus, POAmendment, POConfirmation, PurchaseOrder, ReviewCase, ReviewCaseStatus, RunStatus, ValidationResult, Vendor, utcnow
from app.schemas.catalog import HealthOut, PurchaseOrderOut, VendorOut
from app.schemas.extraction import EventOut, InvoiceDetailOut, InvoiceSummaryOut, RunOut, UploadOut
from app.schemas.m2 import ConfirmPOIn, CorrectionBatchIn, CorrectionIn, DashboardOut, ReviewInvoiceOut, RunStartedOut
from app.services.pdf_documents import PDFValidationError, validate_pdf
from app.services.pipeline import process_invoice
from app.services.presentation import authorization_history, decision_summary, resolution_checklist, validation_presentation
from app.services.review import confirm_po, correct_field, correct_fields


router = APIRouter(prefix="/api")
settings = get_settings()
security = HTTPBasic(auto_error=False)


def require_ap(credentials: HTTPBasicCredentials | None = Depends(security)) -> str:
    if not settings.demo_ap_password:
        raise HTTPException(status_code=503, detail={"code": "DEMO_AUTH_NOT_CONFIGURED", "message": "Configure the AP analyst demo credential before using this action."})
    if not credentials or not secrets.compare_digest(credentials.username, settings.demo_ap_username) or not secrets.compare_digest(credentials.password, settings.demo_ap_password):
        raise HTTPException(status_code=401, detail={"code": "INVALID_DEMO_CREDENTIAL", "message": "Valid AP analyst demo credentials are required."}, headers={"WWW-Authenticate": "Basic"})
    return credentials.username
@router.get("/health", response_model=HealthOut)
def health(db: Session = Depends(get_db)) -> HealthOut:
    db.execute(text("SELECT 1"))
    return HealthOut(status="ok", database="reachable")


@router.get("/vendors", response_model=list[VendorOut])
def list_vendors(db: Session = Depends(get_db)):
    return db.scalars(select(Vendor).options(selectinload(Vendor.aliases)).order_by(Vendor.vendor_code)).all()


def po_response(po: PurchaseOrder, committed: Decimal) -> PurchaseOrderOut:
    remaining = po.authorized_total - committed
    return PurchaseOrderOut(
        id=po.id, po_number=po.po_number, vendor_id=po.vendor_id,
        vendor_name=po.vendor.display_name, status=po.status, currency=po.currency,
        authorized_total=po.authorized_total, committed_total=committed,
        remaining_total=remaining, issue_date=po.issue_date, valid_from=po.valid_from,
        valid_to=po.valid_to, description=po.description, lines=po.lines,
        charge_policies=po.charge_policies,
    )


def load_po_query():
    return select(PurchaseOrder).options(
        selectinload(PurchaseOrder.vendor), selectinload(PurchaseOrder.lines),
        selectinload(PurchaseOrder.charge_policies),
    )


def committed_by_po(db: Session) -> dict[int, Decimal]:
    rows = db.execute(
        select(InvoicePOAllocation.po_id, func.coalesce(func.sum(InvoicePOAllocation.amount), 0))
        .where(InvoicePOAllocation.status == AllocationStatus.COMMITTED)
        .group_by(InvoicePOAllocation.po_id)
    ).all()
    return {po_id: Decimal(total) for po_id, total in rows}


@router.get("/purchase-orders", response_model=list[PurchaseOrderOut])
def list_purchase_orders(db: Session = Depends(get_db)):
    committed = committed_by_po(db)
    orders = db.scalars(load_po_query().order_by(PurchaseOrder.po_number)).all()
    return [po_response(po, committed.get(po.id, Decimal("0.00"))) for po in orders]


@router.get("/purchase-orders/{po_id}", response_model=PurchaseOrderOut)
def get_purchase_order(po_id: int, db: Session = Depends(get_db)):
    po = db.scalar(load_po_query().where(PurchaseOrder.id == po_id))
    if po is None:
        raise HTTPException(status_code=404, detail={"code": "PO_NOT_FOUND", "message": "Purchase order not found"})
    return po_response(po, committed_by_po(db).get(po.id, Decimal("0.00")))


@router.post("/invoices/upload", response_model=UploadOut, status_code=202)
async def upload_invoice(request: Request, background_tasks: BackgroundTasks, file: UploadFile = File(...), db: Session = Depends(get_db)):
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=415, detail={"code": "INVALID_FILE_TYPE", "message": "Only application/pdf uploads are accepted."})
    data = await file.read(settings.upload_max_bytes + 1)
    try:
        metadata = validate_pdf(data, settings.upload_max_bytes, settings.upload_max_pages)
    except PDFValidationError as exc:
        status_code = 413 if exc.code in {"PDF_TOO_LARGE", "PDF_PAGE_LIMIT"} else 422
        raise HTTPException(status_code=status_code, detail={"code": exc.code, "message": str(exc)}) from exc
    storage_dir = settings.invoice_storage_dir.resolve()
    storage_dir.mkdir(parents=True, exist_ok=True)
    stored_path = storage_dir / f"{uuid4().hex}.pdf"
    stored_path.write_bytes(data)
    invoice = Invoice(
        vendor_name_raw="", currency="USD", pdf_storage_key=str(stored_path),
        pdf_sha256=hashlib.sha256(data).hexdigest(), extraction_json=None,
        status=InvoiceStatus.RECEIVED, decision_reason="Awaiting extraction and matching.",
    )
    db.add(invoice); db.flush()
    run = InvoiceRun(invoice_id=invoice.id, run_number=1, status=RunStatus.QUEUED)
    db.add(run); db.flush()
    db.add(InvoiceEvent(invoice_id=invoice.id, run_id=run.id, event_type="PIPELINE_STAGE", stage="RECEIVED",
        status="COMPLETED", actor_type=ActorType.SYSTEM, actor_name=None,
        message="PDF received, validated, hashed, and stored.",
        details_json={"page_count": metadata.page_count, "size_bytes": len(data), "sha256": invoice.pdf_sha256}))
    db.commit()
    background_tasks.add_task(process_invoice, run.id, request.app.state.session_factory, request.app.state.provider_factory)
    return UploadOut(invoice_id=invoice.id, run_id=run.id, status=run.status.value)


def latest_run_id(db: Session, invoice_id: int) -> int | None:
    return db.scalar(select(InvoiceRun.id).where(InvoiceRun.invoice_id == invoice_id).order_by(InvoiceRun.run_number.desc()).limit(1))


def display_supplier(invoice: Invoice, vendor: Vendor | None) -> str:
    return vendor.legal_name if vendor else invoice.vendor_name_raw or (
        "Not extracted" if invoice.status == InvoiceStatus.PROCESSING_FAILED else "Pending extraction")


def display_po(invoice: Invoice, po: PurchaseOrder | None) -> str | None:
    return po.po_number if po else invoice.po_reference_raw


@router.get("/invoices", response_model=list[InvoiceSummaryOut])
def list_invoices(search: str | None = None, status: str | None = None, vendor_id: int | None = None,
                  sort: str = Query("desc", pattern="^(asc|desc)$"), db: Session = Depends(get_db)):
    query = select(Invoice)
    if search:
        query = query.where(Invoice.invoice_number.ilike(f"%{search.strip()}%"))
    if status:
        try: query = query.where(Invoice.status == InvoiceStatus(status))
        except ValueError: raise HTTPException(status_code=422, detail={"code": "INVALID_STATUS", "message": "Unknown invoice status."})
    if vendor_id is not None:
        query = query.where(Invoice.vendor_id == vendor_id)
    query = query.order_by(Invoice.created_at.asc() if sort == "asc" else Invoice.created_at.desc())
    invoices = db.scalars(query).all()
    po_ids = {item.matched_po_id for item in invoices if item.matched_po_id}
    vendor_ids = {item.vendor_id for item in invoices if item.vendor_id}
    pos = {item.id: item for item in db.scalars(select(PurchaseOrder).where(PurchaseOrder.id.in_(po_ids))).all()} if po_ids else {}
    vendors = {item.id: item for item in db.scalars(select(Vendor).where(Vendor.id.in_(vendor_ids))).all()} if vendor_ids else {}
    return [InvoiceSummaryOut(id=item.id, invoice_number=item.invoice_number,
        vendor_name=display_supplier(item, vendors.get(item.vendor_id)), vendor_name_raw=item.vendor_name_raw or None,
        po_reference=display_po(item, pos.get(item.matched_po_id)), po_reference_raw=item.po_reference_raw,
        total_amount=item.total_amount, currency=item.currency, status=item.status,
        created_at=item.created_at, latest_run_id=latest_run_id(db, item.id)) for item in invoices]


def event_outputs(db: Session, invoice_id: int, run_id: int | None = None):
    query = select(InvoiceEvent).where(InvoiceEvent.invoice_id == invoice_id)
    if run_id is not None:
        query = query.where(InvoiceEvent.run_id == run_id)
    return db.scalars(query.order_by(InvoiceEvent.created_at, InvoiceEvent.id)).all()


@router.get("/invoices/{invoice_id}", response_model=InvoiceDetailOut)
def get_invoice(invoice_id: int, db: Session = Depends(get_db)):
    invoice = db.scalar(select(Invoice).options(selectinload(Invoice.lines), selectinload(Invoice.allocations)).where(Invoice.id == invoice_id))
    if invoice is None:
        raise HTTPException(status_code=404, detail={"code": "INVOICE_NOT_FOUND", "message": "Invoice not found"})
    latest_id = latest_run_id(db, invoice.id)
    validation_results = db.scalars(select(ValidationResult).where(ValidationResult.run_id == latest_id)
        .order_by(ValidationResult.created_at, ValidationResult.id)).all() if latest_id else []
    po = db.get(PurchaseOrder, invoice.matched_po_id) if invoice.matched_po_id else None
    vendor = db.get(Vendor, invoice.vendor_id) if invoice.vendor_id else None
    committed = committed_by_po(db).get(po.id, Decimal("0.00")) if po else None
    events = event_outputs(db, invoice.id)
    review_cases = db.scalars(select(ReviewCase).where(ReviewCase.invoice_id == invoice.id).order_by(ReviewCase.created_at)).all()
    detention_policy = next((item for item in po.charge_policies if item.charge_type == "DETENTION"), None) if po else None
    return InvoiceDetailOut(
        id=invoice.id, invoice_number=invoice.invoice_number, vendor_name=display_supplier(invoice, vendor),
        vendor_name_raw=invoice.vendor_name_raw or None,
        po_reference=display_po(invoice, po), po_reference_raw=invoice.po_reference_raw,
        total_amount=invoice.total_amount, currency=invoice.currency,
        status=invoice.status, created_at=invoice.created_at, latest_run_id=latest_id,
        invoice_date=invoice.invoice_date, due_date=invoice.due_date, shipment_reference=invoice.shipment_ref,
        subtotal=invoice.subtotal, tax_amount=invoice.tax_amount, pdf_sha256=invoice.pdf_sha256,
        extraction_provider=invoice.extraction_provider, extraction_model=invoice.extraction_model,
        extraction_duration_ms=invoice.extraction_duration_ms, extraction=invoice.extraction_json,
        matching=invoice.matching_json, exceptions=invoice.exceptions_json or [], decision_reason=invoice.decision_reason,
        lines=invoice.lines, events=events,
        validation_results=[{**{
            "id": row.id, "rule_code": row.rule_code, "rule_name": "Invoice totals and line amounts" if row.rule_code == "VAL-005" else row.rule_name,
            "status": row.status, "severity": row.severity, "message": row.message,
            "expected_json": row.expected_json, "actual_json": row.actual_json,
            "difference_json": row.difference_json, "evidence_json": row.evidence_json,
            "required": row.required, "created_at": row.created_at,
        }, "presentation": validation_presentation(row)} for row in validation_results], allocations=invoice.allocations,
        po_authorized_total=po.authorized_total if po else None,
        po_committed_total=committed,
        po_remaining_total=po.authorized_total - committed if po and committed is not None else None,
        decision_summary=decision_summary(invoice, validation_results, po.po_number if po else None,
            po.authorized_total if po else None, committed,
            po.authorized_total - committed if po and committed is not None else None),
        resolution_checklist=resolution_checklist(invoice, validation_results, review_cases, po, detention_policy),
        authorization_history=authorization_history(invoice, events, po),
    )


@router.get("/dashboard/summary", response_model=DashboardOut)
def dashboard_summary(db: Session = Depends(get_db)):
    processed_statuses = [InvoiceStatus.APPROVED, InvoiceStatus.NEEDS_REVIEW, InvoiceStatus.BLOCKED, InvoiceStatus.DISPUTED]
    total = db.scalar(select(func.count()).select_from(Invoice).where(Invoice.status.in_(processed_statuses))) or 0
    counts = dict(db.execute(select(Invoice.status, func.count()).group_by(Invoice.status)).all())
    approved_value = db.scalar(select(func.coalesce(func.sum(InvoicePOAllocation.amount), 0)).where(
        InvoicePOAllocation.status == AllocationStatus.COMMITTED)) or Decimal("0")
    category_groups = {
        "MISSING_OR_AMBIGUOUS_PO": "PO matching", "PO_LINE_MATCH": "PO matching",
        "PO_CAPACITY_EXCEEDED": "Financial authorization", "QUANTITY_EXCEEDED": "Financial authorization",
        "RATE_DISCREPANCY": "Financial authorization", "CURRENCY": "Financial authorization",
        "DUPLICATE": "Duplicate invoices", "MISSING_INVOICE_FIELD": "Document or extraction issues",
        "ARITHMETIC": "Document or extraction issues", "VENDOR_IDENTITY": "Document or extraction issues",
        "DETENTION_EVIDENCE": "Charge validation", "DETENTION_AUTHORIZATION": "Charge validation",
        "UNSUPPORTED_CHARGE": "Charge validation",
    }
    exception_rows = db.execute(select(ReviewCase.category, ReviewCase.invoice_id).where(
        ReviewCase.status == ReviewCaseStatus.OPEN)).all()
    grouped: dict[str, set[int]] = {}
    for category, invoice_id in exception_rows:
        label = category_groups.get(category, "Document or extraction issues")
        grouped.setdefault(label, set()).add(invoice_id)
    approved = counts.get(InvoiceStatus.APPROVED, 0)
    return DashboardOut(total_invoices=total, approved=approved,
        needs_review=counts.get(InvoiceStatus.NEEDS_REVIEW, 0), blocked=counts.get(InvoiceStatus.BLOCKED, 0),
        processing_failed=counts.get(InvoiceStatus.PROCESSING_FAILED, 0),
        total_approved_value=approved_value,
        approval_rate=(Decimal(approved) / Decimal(total) * 100).quantize(Decimal("0.01")) if total else Decimal("0"),
        exception_breakdown={key: len(value) for key, value in grouped.items()})


@router.get("/reviews", response_model=list[ReviewInvoiceOut])
def list_reviews(category: str | None = None, status: str = "OPEN", db: Session = Depends(get_db)):
    query = select(ReviewCase, Invoice).join(Invoice, ReviewCase.invoice_id == Invoice.id)
    try: query = query.where(ReviewCase.status == ReviewCaseStatus(status))
    except ValueError: raise HTTPException(status_code=422, detail={"code": "INVALID_REVIEW_STATUS", "message": "Unknown review status."})
    if category:
        query = query.where(ReviewCase.category == category)
    rows = db.execute(query.order_by(Invoice.created_at.desc(), ReviewCase.created_at)).all()
    grouped: dict[int, tuple[Invoice, list[ReviewCase]]] = {}
    for case, invoice in rows:
        grouped.setdefault(invoice.id, (invoice, []))[1].append(case)
    output = []
    for invoice, cases in grouped.values():
        latest_id = latest_run_id(db, invoice.id)
        validations = db.scalars(select(ValidationResult).where(ValidationResult.run_id == latest_id)).all() if latest_id else []
        po = db.get(PurchaseOrder, invoice.matched_po_id) if invoice.matched_po_id else None
        vendor = db.get(Vendor, invoice.vendor_id) if invoice.vendor_id else None
        detention = next((item for item in po.charge_policies if item.charge_type == "DETENTION"), None) if po else None
        items = [item for item in resolution_checklist(invoice, validations, cases, po, detention) if item.state == "UNRESOLVED"]
        output.append(ReviewInvoiceOut(invoice_id=invoice.id, invoice_number=invoice.invoice_number,
            vendor_name=display_supplier(invoice, vendor), po_reference=display_po(invoice, po), amount=invoice.total_amount,
            status=invoice.status.value, issue_count=len(items), issues=[item.title for item in items[:3]],
            categories=sorted({case.category for case in cases}), created_at=invoice.created_at))
    return output


@router.get("/audit")
def audit_trail(invoice_id: int | None = None, event_type: str | None = None,
                date_from: str | None = None, date_to: str | None = None, db: Session = Depends(get_db)):
    query = select(InvoiceEvent, Invoice).join(Invoice, InvoiceEvent.invoice_id == Invoice.id)
    if invoice_id is not None: query = query.where(InvoiceEvent.invoice_id == invoice_id)
    if event_type: query = query.where(InvoiceEvent.event_type == event_type)
    if date_from: query = query.where(InvoiceEvent.created_at >= datetime.fromisoformat(date_from))
    if date_to: query = query.where(InvoiceEvent.created_at <= datetime.fromisoformat(date_to))
    rows = db.execute(query.order_by(InvoiceEvent.created_at.desc(), InvoiceEvent.id.desc()).limit(500)).all()
    return [{"id": event.id, "invoice_id": invoice.id, "invoice_number": invoice.invoice_number,
             "event_type": event.event_type, "stage": event.stage, "status": event.status,
             "actor_type": event.actor_type.value, "actor_name": event.actor_name,
             "message": event.message, "details": event.details_json, "created_at": event.created_at}
            for event, invoice in rows]


@router.get("/purchase-orders/{po_id}/detail")
def purchase_order_detail(po_id: int, db: Session = Depends(get_db)):
    po = db.scalar(load_po_query().where(PurchaseOrder.id == po_id))
    if not po: raise HTTPException(status_code=404, detail={"code": "PO_NOT_FOUND", "message": "Purchase order not found"})
    committed = committed_by_po(db).get(po.id, Decimal("0"))
    invoices = db.scalars(select(Invoice).where(Invoice.matched_po_id == po.id).order_by(Invoice.created_at.desc())).all()
    amendments = db.scalars(select(POAmendment).where(POAmendment.po_id == po.id).order_by(POAmendment.created_at.desc())).all()
    return {"purchase_order": po_response(po, committed),
            "related_invoices": [{"id": item.id, "invoice_number": item.invoice_number, "amount": item.total_amount, "status": item.status.value} for item in invoices],
            "amendments": [{"id": item.id, "invoice_id": item.invoice_id, "previous_total": item.previous_authorized_total,
                "new_total": item.new_authorized_total, "charge_type": item.charge_type,
                "previous_allowance": item.previous_allowance, "new_allowance": item.new_allowance,
                "approved_by": item.approved_by, "approval_reference": item.approval_reference,
                "reason": item.reason, "created_at": item.created_at} for item in amendments]}


@router.post("/invoices/{invoice_id}/review/confirm-po", response_model=RunStartedOut)
def confirm_invoice_po(invoice_id: int, payload: ConfirmPOIn, actor: str = Depends(require_ap), db: Session = Depends(get_db)):
    try: run = confirm_po(db, invoice_id, payload.po_id, actor, payload.reason, payload.idempotency_key)
    except ValueError as exc: raise HTTPException(status_code=422, detail={"code": "INVALID_PO_CONFIRMATION", "message": str(exc)})
    return RunStartedOut(invoice_id=invoice_id, run_id=run.id, status=run.status.value)


@router.post("/invoices/{invoice_id}/review/correct-field", response_model=RunStartedOut)
def correct_invoice_field(invoice_id: int, payload: CorrectionIn, actor: str = Depends(require_ap), db: Session = Depends(get_db)):
    try: run = correct_field(db, invoice_id, payload.field_path, payload.corrected_value, actor, payload.reason, payload.idempotency_key)
    except ValueError as exc: raise HTTPException(status_code=422, detail={"code": "INVALID_FIELD_CORRECTION", "message": str(exc)})
    return RunStartedOut(invoice_id=invoice_id, run_id=run.id, status=run.status.value)


@router.post("/invoices/{invoice_id}/review/correct-fields", response_model=RunStartedOut)
def correct_invoice_fields(invoice_id: int, payload: CorrectionBatchIn, actor: str = Depends(require_ap), db: Session = Depends(get_db)):
    try: run = correct_fields(db, invoice_id, [(item.field_path, item.corrected_value) for item in payload.corrections], actor, payload.reason, payload.idempotency_key)
    except ValueError as exc: raise HTTPException(status_code=422, detail={"code": "INVALID_FIELD_CORRECTION", "message": str(exc)})
    return RunStartedOut(invoice_id=invoice_id, run_id=run.id, status=run.status.value)


@router.get("/invoices/{invoice_id}/events", response_model=list[EventOut])
def get_invoice_events(invoice_id: int, db: Session = Depends(get_db)):
    if db.get(Invoice, invoice_id) is None:
        raise HTTPException(status_code=404, detail={"code": "INVOICE_NOT_FOUND", "message": "Invoice not found"})
    return event_outputs(db, invoice_id)


@router.get("/invoices/{invoice_id}/po-candidates")
def get_po_candidates(invoice_id: int, db: Session = Depends(get_db)):
    invoice = db.get(Invoice, invoice_id)
    if invoice is None:
        raise HTTPException(status_code=404, detail={"code": "INVOICE_NOT_FOUND", "message": "Invoice not found"})
    return ((invoice.matching_json or {}).get("purchase_order") or {}).get("candidates", [])


@router.get("/runs/{run_id}", response_model=RunOut)
def get_run(run_id: int, db: Session = Depends(get_db)):
    run = db.get(InvoiceRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail={"code": "RUN_NOT_FOUND", "message": "Processing run not found"})
    return RunOut(id=run.id, invoice_id=run.invoice_id, status=run.status, started_at=run.started_at,
        completed_at=run.completed_at, error_code=run.error_code, events=event_outputs(db, run.invoice_id, run.id))


@router.get("/invoices/{invoice_id}/document")
def get_invoice_document(invoice_id: int, db: Session = Depends(get_db)):
    invoice = db.get(Invoice, invoice_id)
    if invoice is None:
        raise HTTPException(status_code=404, detail={"code": "INVOICE_NOT_FOUND", "message": "Invoice not found"})
    path = Path(invoice.pdf_storage_key).resolve()
    storage_dir = settings.invoice_storage_dir.resolve()
    if storage_dir not in path.parents or not path.is_file():
        raise HTTPException(status_code=404, detail={"code": "DOCUMENT_NOT_FOUND", "message": "Stored document is unavailable"})
    return FileResponse(path, media_type="application/pdf", filename=f"invoice-{invoice.id}.pdf", content_disposition_type="inline")

