from __future__ import annotations

import enum
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, Index, Integer, JSON, Numeric, String, Text, UniqueConstraint, text as sql_text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


MONEY = Numeric(14, 2)
QUANTITY = Numeric(14, 4)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class StrEnum(str, enum.Enum):
    pass


class VendorStatus(StrEnum): ACTIVE = "ACTIVE"; INACTIVE = "INACTIVE"
class POStatus(StrEnum): OPEN = "OPEN"; CLOSED = "CLOSED"; CANCELLED = "CANCELLED"
class RateType(StrEnum): PER_HOUR = "PER_HOUR"; PERCENT_BASE = "PERCENT_BASE"; FIXED = "FIXED"
class InvoiceStatus(StrEnum): RECEIVED = "RECEIVED"; PROCESSING = "PROCESSING"; READY_FOR_VALIDATION = "READY_FOR_VALIDATION"; APPROVED = "APPROVED"; NEEDS_REVIEW = "NEEDS_REVIEW"; BLOCKED = "BLOCKED"; DISPUTED = "DISPUTED"; PROCESSING_FAILED = "PROCESSING_FAILED"; VOID = "VOID"
class AllocationStatus(StrEnum): COMMITTED = "COMMITTED"; RELEASED = "RELEASED"
class RunStatus(StrEnum): QUEUED = "QUEUED"; RUNNING = "RUNNING"; COMPLETED = "COMPLETED"; FAILED = "FAILED"
class ValidationStatus(StrEnum): PASS = "PASS"; FAIL = "FAIL"; REVIEW_REQUIRED = "REVIEW_REQUIRED"; BLOCK = "BLOCK"; NOT_APPLICABLE = "NOT_APPLICABLE"; TECHNICAL_ERROR = "TECHNICAL_ERROR"
class ActorType(StrEnum): SYSTEM = "SYSTEM"; AP_ANALYST = "AP_ANALYST"; PROCUREMENT = "PROCUREMENT"
class ReviewActionType(StrEnum): CONFIRM_PO = "CONFIRM_PO"; CORRECT_EXTRACTION = "CORRECT_EXTRACTION"; REQUEST_EVIDENCE = "REQUEST_EVIDENCE"; RECORD_PO_AMENDMENT = "RECORD_PO_AMENDMENT"; REVALIDATE = "REVALIDATE"; MARK_DISPUTED = "MARK_DISPUTED"
class ReviewCaseStatus(StrEnum): OPEN = "OPEN"; RESOLVED = "RESOLVED"; CANCELLED = "CANCELLED"; SUPERSEDED = "SUPERSEDED"


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class Vendor(TimestampMixin, Base):
    __tablename__ = "vendors"
    id: Mapped[int] = mapped_column(primary_key=True)
    vendor_code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    legal_name: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(255))
    status: Mapped[VendorStatus] = mapped_column(Enum(VendorStatus))
    tax_id_fingerprint: Mapped[str | None] = mapped_column(String(128), unique=True)
    tax_id_last4: Mapped[str | None] = mapped_column(String(4))
    tax_id_verified_in_master: Mapped[bool] = mapped_column(Boolean, default=False)
    aliases: Mapped[list[VendorAlias]] = relationship(back_populates="vendor", cascade="all, delete-orphan")
    purchase_orders: Mapped[list[PurchaseOrder]] = relationship(back_populates="vendor")


class VendorAlias(Base):
    __tablename__ = "vendor_aliases"
    __table_args__ = (UniqueConstraint("vendor_id", "alias_normalized"), Index("ix_vendor_aliases_alias_normalized", "alias_normalized"))
    id: Mapped[int] = mapped_column(primary_key=True)
    vendor_id: Mapped[int] = mapped_column(ForeignKey("vendors.id", ondelete="CASCADE"))
    alias_normalized: Mapped[str] = mapped_column(String(255))
    source: Mapped[str] = mapped_column(String(32), default="MASTER_APPROVED")
    vendor: Mapped[Vendor] = relationship(back_populates="aliases")


class PurchaseOrder(TimestampMixin, Base):
    __tablename__ = "purchase_orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    po_number: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    vendor_id: Mapped[int] = mapped_column(ForeignKey("vendors.id"), index=True)
    status: Mapped[POStatus] = mapped_column(Enum(POStatus))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    authorized_total: Mapped[Decimal] = mapped_column(MONEY)
    issue_date: Mapped[date] = mapped_column(Date)
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    description: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1)
    vendor: Mapped[Vendor] = relationship(back_populates="purchase_orders")
    lines: Mapped[list[POLine]] = relationship(back_populates="purchase_order", cascade="all, delete-orphan")
    charge_policies: Mapped[list[ChargePolicy]] = relationship(back_populates="purchase_order", cascade="all, delete-orphan")
    allocations: Mapped[list[InvoicePOAllocation]] = relationship(back_populates="purchase_order")


class POLine(Base):
    __tablename__ = "po_lines"
    __table_args__ = (UniqueConstraint("po_id", "line_number"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    po_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id", ondelete="CASCADE"))
    line_number: Mapped[int]
    service_code: Mapped[str] = mapped_column(String(32))
    description: Mapped[str] = mapped_column(Text)
    shipment_ref: Mapped[str | None] = mapped_column(String(64))
    ordered_quantity: Mapped[Decimal] = mapped_column(QUANTITY)
    unit_of_measure: Mapped[str] = mapped_column(String(32))
    unit_price: Mapped[Decimal] = mapped_column(MONEY)
    authorized_line_total: Mapped[Decimal] = mapped_column(MONEY)
    purchase_order: Mapped[PurchaseOrder] = relationship(back_populates="lines")


class ChargePolicy(Base):
    __tablename__ = "charge_policies"
    __table_args__ = (UniqueConstraint("po_id", "charge_type"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    po_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id", ondelete="CASCADE"))
    charge_type: Mapped[str] = mapped_column(String(32))
    rate_type: Mapped[RateType] = mapped_column(Enum(RateType))
    rate: Mapped[Decimal] = mapped_column(MONEY)
    free_hours: Mapped[Decimal | None] = mapped_column(QUANTITY)
    max_total_allowance: Mapped[Decimal] = mapped_column(MONEY)
    requires_evidence: Mapped[bool] = mapped_column(Boolean)
    policy_notes: Mapped[str] = mapped_column(Text)
    purchase_order: Mapped[PurchaseOrder] = relationship(back_populates="charge_policies")


class ShipmentEvidence(Base):
    __tablename__ = "shipment_evidence"
    id: Mapped[int] = mapped_column(primary_key=True)
    shipment_ref: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    vendor_id: Mapped[int] = mapped_column(ForeignKey("vendors.id"))
    po_id: Mapped[int | None] = mapped_column(ForeignKey("purchase_orders.id"))
    arrival_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    departure_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(64))
    verified: Mapped[bool] = mapped_column(Boolean)
    notes: Mapped[str | None] = mapped_column(Text)


class Invoice(TimestampMixin, Base):
    __tablename__ = "invoices"
    __table_args__ = (Index("ix_invoices_vendor_number", "vendor_id", "invoice_number_normalized"), Index("ix_invoices_pdf_sha256", "pdf_sha256"))
    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_number: Mapped[str | None] = mapped_column(String(128))
    invoice_number_normalized: Mapped[str | None] = mapped_column(String(128))
    vendor_id: Mapped[int | None] = mapped_column(ForeignKey("vendors.id"))
    vendor_name_raw: Mapped[str] = mapped_column(String(255))
    tax_id_last4_raw: Mapped[str | None] = mapped_column(String(4))
    po_reference_raw: Mapped[str | None] = mapped_column(String(64))
    matched_po_id: Mapped[int | None] = mapped_column(ForeignKey("purchase_orders.id"))
    shipment_ref: Mapped[str | None] = mapped_column(String(64))
    invoice_date: Mapped[date | None] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(Date)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    subtotal: Mapped[Decimal | None] = mapped_column(MONEY)
    tax_amount: Mapped[Decimal | None] = mapped_column(MONEY)
    total_amount: Mapped[Decimal | None] = mapped_column(MONEY)
    pdf_storage_key: Mapped[str] = mapped_column(String(512))
    pdf_sha256: Mapped[str] = mapped_column(String(64))
    extraction_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    extraction_provider: Mapped[str | None] = mapped_column(String(64))
    extraction_model: Mapped[str | None] = mapped_column(String(128))
    extraction_duration_ms: Mapped[int | None] = mapped_column(Integer)
    matching_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    exceptions_json: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)
    status: Mapped[InvoiceStatus] = mapped_column(Enum(InvoiceStatus))
    decision_reason: Mapped[str | None] = mapped_column(Text)
    lines: Mapped[list[InvoiceLine]] = relationship(back_populates="invoice", cascade="all, delete-orphan")
    allocations: Mapped[list[InvoicePOAllocation]] = relationship(back_populates="invoice")
    runs: Mapped[list[InvoiceRun]] = relationship(back_populates="invoice")


class InvoiceLine(Base):
    __tablename__ = "invoice_lines"
    __table_args__ = (UniqueConstraint("invoice_id", "line_number"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"))
    line_number: Mapped[int]
    description: Mapped[str] = mapped_column(Text)
    charge_type: Mapped[str] = mapped_column(String(32))
    quantity: Mapped[Decimal | None] = mapped_column(QUANTITY)
    unit_price: Mapped[Decimal | None] = mapped_column(MONEY)
    amount: Mapped[Decimal] = mapped_column(MONEY)
    shipment_ref: Mapped[str | None] = mapped_column(String(64))
    matched_po_line_id: Mapped[int | None] = mapped_column(ForeignKey("po_lines.id"))
    extraction_confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    raw_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    invoice: Mapped[Invoice] = relationship(back_populates="lines")


class InvoicePOAllocation(Base):
    __tablename__ = "invoice_po_allocations"
    __table_args__ = (
        Index("ix_invoice_po_allocations_po_id", "po_id"),
        UniqueConstraint("invoice_id", name="uq_invoice_po_allocations_invoice_id"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"))
    po_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id"))
    amount: Mapped[Decimal] = mapped_column(MONEY)
    status: Mapped[AllocationStatus] = mapped_column(Enum(AllocationStatus))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    invoice: Mapped[Invoice] = relationship(back_populates="allocations")
    purchase_order: Mapped[PurchaseOrder] = relationship(back_populates="allocations")
    line_allocations: Mapped[list[InvoiceLineAllocation]] = relationship(back_populates="allocation", cascade="all, delete-orphan")


class InvoiceLineAllocation(Base):
    __tablename__ = "invoice_line_allocations"
    id: Mapped[int] = mapped_column(primary_key=True)
    allocation_id: Mapped[int] = mapped_column(ForeignKey("invoice_po_allocations.id", ondelete="CASCADE"))
    invoice_line_id: Mapped[int] = mapped_column(ForeignKey("invoice_lines.id"))
    po_line_id: Mapped[int | None] = mapped_column(ForeignKey("po_lines.id"))
    charge_policy_id: Mapped[int | None] = mapped_column(ForeignKey("charge_policies.id"))
    allocated_quantity: Mapped[Decimal | None] = mapped_column(QUANTITY)
    allocated_amount: Mapped[Decimal] = mapped_column(MONEY)
    allocation: Mapped[InvoicePOAllocation] = relationship(back_populates="line_allocations")


class InvoiceRun(Base):
    __tablename__ = "invoice_runs"
    __table_args__ = (UniqueConstraint("invoice_id", "run_number"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"))
    run_number: Mapped[int]
    status: Mapped[RunStatus] = mapped_column(Enum(RunStatus))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(64))
    invoice: Mapped[Invoice] = relationship(back_populates="runs")


class ValidationResult(Base):
    __tablename__ = "validation_results"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("invoice_runs.id", ondelete="CASCADE"))
    rule_code: Mapped[str] = mapped_column(String(64))
    rule_name: Mapped[str] = mapped_column(String(160), default="Validation rule")
    status: Mapped[ValidationStatus] = mapped_column(Enum(ValidationStatus))
    severity: Mapped[str] = mapped_column(String(32))
    message: Mapped[str] = mapped_column(Text)
    expected_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    actual_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    difference_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    evidence_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    required: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class InvoiceEvent(Base):
    __tablename__ = "invoice_events"
    __table_args__ = (Index("ix_invoice_events_invoice_id", "invoice_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"))
    run_id: Mapped[int | None] = mapped_column(ForeignKey("invoice_runs.id"))
    event_type: Mapped[str] = mapped_column(String(64))
    stage: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32))
    actor_type: Mapped[ActorType] = mapped_column(Enum(ActorType))
    actor_name: Mapped[str | None] = mapped_column(String(128))
    message: Mapped[str] = mapped_column(Text)
    details_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReviewAction(Base):
    __tablename__ = "review_actions"
    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"))
    actor_name: Mapped[str] = mapped_column(String(128))
    actor_role: Mapped[str] = mapped_column(String(64))
    action_type: Mapped[ReviewActionType] = mapped_column(Enum(ReviewActionType))
    reason: Mapped[str] = mapped_column(Text)
    payload_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReviewCase(Base):
    __tablename__ = "review_cases"
    __table_args__ = (
        Index("ix_review_cases_invoice_status", "invoice_id", "status"),
        Index("uq_review_cases_open_issue", "invoice_id", "exception_code", unique=True,
              sqlite_where=sql_text("status = 'OPEN'"), postgresql_where=sql_text("status = 'OPEN'")),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"), index=True)
    validation_result_id: Mapped[int | None] = mapped_column(ForeignKey("validation_results.id"))
    exception_code: Mapped[str] = mapped_column(String(64), index=True)
    category: Mapped[str] = mapped_column(String(64), index=True)
    summary: Mapped[str] = mapped_column(Text)
    status: Mapped[ReviewCaseStatus] = mapped_column(Enum(ReviewCaseStatus), default=ReviewCaseStatus.OPEN)
    assigned_actor: Mapped[str | None] = mapped_column(String(128))
    resolution_type: Mapped[str | None] = mapped_column(String(64))
    resolution_details: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FieldCorrection(Base):
    __tablename__ = "field_corrections"
    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"), index=True)
    review_action_id: Mapped[int] = mapped_column(ForeignKey("review_actions.id"), index=True)
    field_path: Mapped[str] = mapped_column(String(128))
    original_value_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    corrected_value_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    reason: Mapped[str] = mapped_column(Text)
    actor_name: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class POConfirmation(Base):
    __tablename__ = "po_confirmations"
    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"), index=True)
    po_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id"))
    review_action_id: Mapped[int] = mapped_column(ForeignKey("review_actions.id"), unique=True)
    actor_name: Mapped[str] = mapped_column(String(128))
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class POAmendment(Base):
    __tablename__ = "po_amendments"
    id: Mapped[int] = mapped_column(primary_key=True)
    po_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id"))
    invoice_id: Mapped[int | None] = mapped_column(ForeignKey("invoices.id"))
    previous_authorized_total: Mapped[Decimal] = mapped_column(MONEY)
    new_authorized_total: Mapped[Decimal] = mapped_column(MONEY)
    charge_type: Mapped[str] = mapped_column(String(32))
    previous_allowance: Mapped[Decimal] = mapped_column(MONEY)
    new_allowance: Mapped[Decimal] = mapped_column(MONEY)
    approved_by: Mapped[str] = mapped_column(String(128))
    approval_reference: Mapped[str] = mapped_column(String(128))
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
