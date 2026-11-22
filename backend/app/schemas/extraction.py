from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.schemas.m2 import AuthorizationHistoryOut, DecisionSummaryOut, ResolutionChecklistItemOut, ValidationPresentationOut


class ChargeType(str, Enum):
    BASE_FREIGHT = "BASE_FREIGHT"
    FUEL_SURCHARGE = "FUEL_SURCHARGE"
    DETENTION = "DETENTION"
    DEMURRAGE = "DEMURRAGE"
    STORAGE = "STORAGE"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


class ExtractedLine(BaseModel):
    description: str = Field(min_length=1, max_length=2000)
    quantity: Decimal | None = None
    unit_of_measure: str | None = Field(default=None, max_length=64)
    unit_price: Decimal | None = None
    line_amount: Decimal
    charge_type: ChargeType = ChargeType.UNKNOWN
    shipment_reference: str | None = Field(default=None, max_length=128)
    source_reference: str | None = Field(default=None, max_length=1000)

    @field_validator("quantity", "unit_price", "line_amount")
    @classmethod
    def finite_decimal(cls, value: Decimal | None):
        if value is not None and not value.is_finite():
            raise ValueError("numeric values must be finite")
        return value


class ExtractedInvoice(BaseModel):
    vendor_name: str | None = Field(default=None, max_length=500)
    vendor_tax_identifier: str | None = Field(default=None, max_length=128)
    invoice_number: str | None = Field(default=None, max_length=256)
    invoice_date: str | None = Field(default=None, max_length=64)
    due_date: str | None = Field(default=None, max_length=64)
    po_reference: str | None = Field(default=None, max_length=128)
    shipment_reference: str | None = Field(default=None, max_length=128)
    currency: str | None = Field(default=None, max_length=16)
    subtotal: Decimal | None = None
    tax: Decimal | None = None
    total_amount: Decimal | None = None
    lines: list[ExtractedLine] = Field(default_factory=list, max_length=200)
    missing_fields: list[str] = Field(default_factory=list, max_length=100)
    uncertain_fields: list[str] = Field(default_factory=list, max_length=100)
    warnings: list[str] = Field(default_factory=list, max_length=100)
    source_references: list[str] = Field(default_factory=list, max_length=100)

    @field_validator(
        "vendor_name", "vendor_tax_identifier", "invoice_number", "invoice_date", "due_date",
        "po_reference", "shipment_reference", "currency", mode="before",
    )
    @classmethod
    def null_sentinel_to_none(cls, value):
        if isinstance(value, str) and value.strip().casefold() in {"null", "none", "n/a", "not provided", "not present", "unknown"}:
            return None
        return value

    @field_validator("subtotal", "tax", "total_amount")
    @classmethod
    def finite_amount(cls, value: Decimal | None):
        if value is not None and not value.is_finite():
            raise ValueError("amounts must be finite")
        return value


class ExtractionResult(BaseModel):
    data: ExtractedInvoice
    provider: str
    model: str
    duration_ms: int
    raw_response: dict[str, Any]


class VendorCandidate(BaseModel):
    vendor_id: int
    vendor_code: str
    legal_name: str
    match_method: str
    evidence: list[str]
    automatic_match_permitted: bool
    similarity: float | None = None


class VendorMatchResult(BaseModel):
    matched_vendor_id: int | None = None
    match_method: str | None = None
    automatic_match_permitted: bool = False
    evidence: list[str] = Field(default_factory=list)
    conflict_codes: list[str] = Field(default_factory=list)
    candidates: list[VendorCandidate] = Field(default_factory=list)


class POCandidate(BaseModel):
    po_id: int
    po_number: str
    evidence: list[str]
    shipment_match: bool
    service_match: bool
    vendor_match: bool
    po_status: str
    analyst_confirmation_required: bool
    priority: int


class POMatchResult(BaseModel):
    matched_po_id: int | None = None
    match_method: str | None = None
    automatic_match_permitted: bool = False
    evidence: list[str] = Field(default_factory=list)
    conflict_codes: list[str] = Field(default_factory=list)
    candidates: list[POCandidate] = Field(default_factory=list)


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    stage: str
    status: str
    message: str
    details_json: dict[str, Any] | None
    created_at: datetime


class LineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    line_number: int
    description: str
    charge_type: str
    quantity: Decimal | None
    unit_price: Decimal | None
    amount: Decimal
    shipment_ref: str | None
    raw_json: dict[str, Any] | None


class ValidationResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    rule_code: str
    rule_name: str
    status: str
    severity: str
    message: str
    expected_json: dict[str, Any] | None
    actual_json: dict[str, Any] | None
    difference_json: dict[str, Any] | None
    evidence_json: dict[str, Any] | None
    required: bool
    created_at: datetime
    presentation: ValidationPresentationOut | None = None


class AllocationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    po_id: int
    amount: Decimal
    status: str
    created_at: datetime


class InvoiceSummaryOut(BaseModel):
    id: int
    invoice_number: str | None
    vendor_name: str
    vendor_name_raw: str | None = None
    po_reference: str | None
    po_reference_raw: str | None = None
    total_amount: Decimal | None
    currency: str
    status: str
    created_at: datetime
    latest_run_id: int | None


class InvoiceDetailOut(InvoiceSummaryOut):
    invoice_date: date | None
    due_date: date | None
    shipment_reference: str | None
    subtotal: Decimal | None
    tax_amount: Decimal | None
    pdf_sha256: str
    extraction_provider: str | None
    extraction_model: str | None
    extraction_duration_ms: int | None
    extraction: dict[str, Any] | None
    matching: dict[str, Any] | None
    exceptions: list[dict[str, Any]]
    decision_reason: str | None
    lines: list[LineOut]
    events: list[EventOut]
    validation_results: list[ValidationResultOut]
    allocations: list[AllocationOut]
    po_authorized_total: Decimal | None = None
    po_committed_total: Decimal | None = None
    po_remaining_total: Decimal | None = None
    decision_summary: DecisionSummaryOut | None = None
    resolution_checklist: list[ResolutionChecklistItemOut] = []
    authorization_history: list[AuthorizationHistoryOut] = []


class RunOut(BaseModel):
    id: int
    invoice_id: int
    status: str
    started_at: datetime | None
    completed_at: datetime | None
    error_code: str | None
    events: list[EventOut]


class UploadOut(BaseModel):
    invoice_id: int
    run_id: int
    status: str

