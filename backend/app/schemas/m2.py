from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, model_validator


class DisplayValue(BaseModel):
    label: str
    value: str
    format: str = "text"


class DecisionSummaryOut(BaseModel):
    headline: str
    outcome: str
    summary: str
    reasons: list[str]
    metrics: list[DisplayValue]
    next_action: str
    linked_invoice_id: int | None = None


class ValidationPresentationOut(BaseModel):
    group: str
    outcome: str
    explanation: str
    expected: list[DisplayValue]
    actual: list[DisplayValue]
    difference: list[DisplayValue]
    evidence: list[DisplayValue]
    recommended_action: str | None
    technical_details: dict[str, Any]


class ResolutionChecklistItemOut(BaseModel):
    code: str
    title: str
    state: str
    why: str
    actual: DisplayValue | None
    authorized: DisplayValue | None
    shortfall: DisplayValue | None
    supporting_values: list[DisplayValue] = []
    existing_authorization: DisplayValue | None = None
    minimum_new_total: DisplayValue | None = None
    resulting_remaining: DisplayValue | None = None
    required_action: str
    responsible_role: str
    action_type: str | None
    action_label: str | None
    review_case_id: int | None = None
    resolved_at: datetime | None = None
    details: list[str] = []


class AuthorizationHistoryOut(BaseModel):
    id: int
    action: str
    actor: str
    actor_role: str
    timestamp: datetime
    context: str
    affected_record: str
    changes: list[DisplayValue]
    justification: str | None
    resulting_outcome: str | None


class ReviewCaseOut(BaseModel):
    id: int
    invoice_id: int
    invoice_number: str | None
    vendor_name: str
    amount: Decimal | None
    exception_code: str
    category: str
    summary: str
    status: str
    assigned_actor: str | None
    created_at: datetime
    resolved_at: datetime | None


class ReviewInvoiceOut(BaseModel):
    invoice_id: int
    invoice_number: str | None
    vendor_name: str
    po_reference: str | None = None
    amount: Decimal | None
    status: str
    issue_count: int
    issues: list[str]
    categories: list[str]
    created_at: datetime


class DashboardOut(BaseModel):
    total_invoices: int
    approved: int
    needs_review: int
    blocked: int
    processing_failed: int
    total_approved_value: Decimal
    approval_rate: Decimal
    exception_breakdown: dict[str, int]


class ConfirmPOIn(BaseModel):
    po_id: int
    reason: str
    idempotency_key: str | None = None


class CorrectionIn(BaseModel):
    field_path: str
    corrected_value: str
    reason: str
    idempotency_key: str | None = None


class CorrectionItemIn(BaseModel):
    field_path: str
    corrected_value: str


class CorrectionBatchIn(BaseModel):
    corrections: list[CorrectionItemIn]
    reason: str
    idempotency_key: str | None = None


class RevalidateIn(BaseModel):
    reason: str
    idempotency_key: str | None = None


class AmendmentIn(BaseModel):
    invoice_id: int
    amendment_scope: str
    new_authorized_total: Decimal | None = None
    charge_type: str = "DETENTION"
    new_allowance: Decimal | None = None
    approval_reference: str
    reason: str
    explicit_confirmation: bool
    idempotency_key: str | None = None

    @model_validator(mode="after")
    def validate_scope(self):
        allowed = {"PO_TOTAL", "CHARGE_ALLOWANCE", "BOTH"}
        if self.amendment_scope not in allowed:
            raise ValueError("amendment_scope must be PO_TOTAL, CHARGE_ALLOWANCE, or BOTH")
        if not self.explicit_confirmation:
            raise ValueError("Explicit confirmation of the new authorization is required")
        if self.amendment_scope in {"PO_TOTAL", "BOTH"} and self.new_authorized_total is None:
            raise ValueError("new_authorized_total is required for this amendment scope")
        if self.amendment_scope in {"CHARGE_ALLOWANCE", "BOTH"} and self.new_allowance is None:
            raise ValueError("new_allowance is required for this amendment scope")
        return self


class RecordActionIn(BaseModel):
    action_type: str
    reason: str
    idempotency_key: str | None = None


class RunStartedOut(BaseModel):
    invoice_id: int
    run_id: int
    status: str
