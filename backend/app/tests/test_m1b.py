from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.main import app
from app.models.entities import (
    AllocationStatus, Invoice, InvoicePOAllocation, InvoiceStatus, PurchaseOrder,
    ShipmentEvidence, ValidationResult, Vendor, VendorStatus,
)
from app.schemas.extraction import ChargeType, ExtractedInvoice, ExtractedLine, ExtractionResult
from app.services.validation import AllocationConflict, commit_allocation

FIXTURE_ROOT = Path(__file__).resolve().parents[3] / "demo" / "fixtures"
D = Decimal


def invoice_data(**overrides):
    values = dict(
        vendor_name="Atlas Transport LLC", vendor_tax_identifier="12-3454107",
        invoice_number="INV-504", invoice_date="2026-11-01", due_date="2026-12-01",
        po_reference="PO-10045", shipment_reference="SH-8891", currency="USD",
        subtotal=D("2600"), tax=D("0"), total_amount=D("2600"),
        lines=[
            ExtractedLine(description="Base freight SH-8891", quantity=D("1"), unit_of_measure="TRIP", unit_price=D("2000"), line_amount=D("2000"), charge_type=ChargeType.BASE_FREIGHT, shipment_reference="SH-8891"),
            ExtractedLine(description="Detention 3 hours", quantity=D("3"), unit_of_measure="HR", unit_price=D("200"), line_amount=D("600"), charge_type=ChargeType.DETENTION, shipment_reference="SH-8891"),
        ], missing_fields=[], uncertain_fields=[], warnings=[], source_references=["Page 1"],
    )
    values.update(overrides)
    return ExtractedInvoice(**values)


class Provider:
    def __init__(self, data): self.data = data
    def extract(self, _bytes):
        return ExtractionResult(data=self.data, provider="test", model="deterministic", duration_ms=1,
                                raw_response=self.data.model_dump(mode="json"))


def upload(client, data, fixture="atlas-inv-504.pdf"):
    app.state.provider_factory = lambda: Provider(data)
    with (FIXTURE_ROOT / fixture).open("rb") as stream:
        response = client.post("/api/invoices/upload", files={"file": (fixture, stream, "application/pdf")})
    assert response.status_code == 202
    return client.get(f"/api/invoices/{response.json()['invoice_id']}").json()


def rule(detail, code):
    return next(item for item in detail["validation_results"] if item["rule_code"] == code)


def test_clean_invoice_approves_and_commits_once(client, db):
    detail = upload(client, invoice_data())
    assert detail["status"] == "APPROVED"
    assert rule(detail, "VAL-014")["status"] == "PASS"
    assert detail["allocations"][0]["amount"] == "2600.00"
    assert detail["po_remaining_total"] == "400.00"
    assert db.scalar(select(func.count()).select_from(InvoicePOAllocation)) == 2  # includes historical seed


def test_duplicate_is_blocked_without_second_allocation(client):
    first = upload(client, invoice_data())
    second = upload(client, invoice_data(), "atlas-inv-504-scanned.pdf")
    assert first["status"] == "APPROVED"
    assert second["status"] == "BLOCKED"
    assert rule(second, "VAL-003")["status"] == "BLOCK"
    assert rule(second, "VAL-003")["actual_json"]["linked_invoice_id"] == first["id"]
    assert rule(second, "VAL-003")["message"] == "An active invoice with the same verified supplier and invoice number already exists."
    assert [item["code"] for item in second["resolution_checklist"] if item["state"] == "UNRESOLVED"] == ["VAL-003"]
    assert second["decision_summary"]["reasons"] == ["An active invoice with the same verified supplier and invoice number already exists."]
    assert [item["label"] for item in second["decision_summary"]["metrics"]] == ["Invoice total"]
    assert second["allocations"] == []


@pytest.mark.parametrize("change,code", [
    ({"total_amount": D("2601")}, "VAL-005"),
    ({"invoice_number": None}, "VAL-001"),
    ({"currency": "EUR"}, "VAL-006"),
])
def test_missing_arithmetic_and_currency_require_review(client, change, code):
    detail = upload(client, invoice_data(**change))
    assert detail["status"] == "NEEDS_REVIEW"
    assert rule(detail, code)["status"] == "REVIEW_REQUIRED"


def test_total_only_invoice_does_not_assume_missing_tax_is_zero(client):
    detail = upload(client, invoice_data(subtotal=None, tax=None, total_amount=D("2600")))
    arithmetic = rule(detail, "VAL-005")
    assert arithmetic["status"] == "REVIEW_REQUIRED"
    assert "match the invoice total" in arithmetic["message"]
    assert "cannot be assumed to be $0.00" in arithmetic["message"]
    assert "Enter $0.00 only when the PDF explicitly states" in arithmetic["presentation"]["recommended_action"]
    assert detail["allocations"] == []


def test_inactive_vendor_and_identity_mismatch_require_review(client, db):
    atlas = db.scalar(select(Vendor).where(Vendor.vendor_code == "VEN-001"))
    atlas.status = VendorStatus.INACTIVE; db.commit()
    inactive = upload(client, invoice_data())
    assert inactive["status"] == "NEEDS_REVIEW"
    assert rule(inactive, "VAL-002")["status"] == "REVIEW_REQUIRED"


def test_missing_po_explains_ranked_candidates_and_holds(client):
    detail = upload(client, invoice_data(invoice_number="INV-506", po_reference=None), "atlas-inv-506-no-po.pdf")
    assert detail["status"] == "NEEDS_REVIEW"
    candidates = detail["matching"]["purchase_order"]["candidates"]
    assert candidates and all(item["vendor_match"] and item["analyst_confirmation_required"] for item in candidates)
    assert rule(detail, "VAL-004")["status"] == "REVIEW_REQUIRED"


def test_rate_quantity_and_capacity_fail_closed(client):
    rate_line = ExtractedLine(description="Base freight", quantity=D("1"), unit_of_measure="TRIP", unit_price=D("2100"), line_amount=D("2100"), charge_type=ChargeType.BASE_FREIGHT, shipment_reference="SH-8891")
    detail = upload(client, invoice_data(subtotal=D("2100"), total_amount=D("2100"), lines=[rate_line]))
    assert detail["status"] == "NEEDS_REVIEW"
    assert rule(detail, "VAL-008")["status"] == "REVIEW_REQUIRED"


def test_detention_evidence_can_pass_while_allowance_and_capacity_fail(client):
    data = invoice_data(invoice_number="INV-505", po_reference="PO-10055", shipment_reference="SH-8895",
        lines=[
            ExtractedLine(description="Base freight SH-8895", quantity=D("1"), unit_of_measure="TRIP", unit_price=D("2000"), line_amount=D("2000"), charge_type=ChargeType.BASE_FREIGHT, shipment_reference="SH-8895"),
            ExtractedLine(description="Detention 3 hours", quantity=D("3"), unit_of_measure="HR", unit_price=D("200"), line_amount=D("600"), charge_type=ChargeType.DETENTION, shipment_reference="SH-8895"),
        ])
    detail = upload(client, data, "atlas-inv-505-detention-overage.pdf")
    assert rule(detail, "VAL-010-EVIDENCE")["status"] == "PASS"
    assert rule(detail, "VAL-010-ALLOWANCE")["status"] == "REVIEW_REQUIRED"
    assert rule(detail, "VAL-010-ALLOWANCE")["actual_json"]["issues"][0]["shortfall"] == "300.00"
    assert rule(detail, "VAL-012")["status"] == "REVIEW_REQUIRED"
    assert detail["allocations"] == []


def test_missing_detention_evidence_and_unsupported_charge_hold(client, db):
    evidence = db.scalar(select(ShipmentEvidence).where(ShipmentEvidence.shipment_ref == "SH-8891"))
    db.delete(evidence); db.commit()
    missing = upload(client, invoice_data())
    assert rule(missing, "VAL-010-EVIDENCE")["status"] == "REVIEW_REQUIRED"


def test_partial_invoice_then_over_capacity(client):
    partial_line = ExtractedLine(description="Scheduled trips SH-3000", quantity=D("2.5"), unit_of_measure="TRIP", unit_price=D("1000"), line_amount=D("2500"), charge_type=ChargeType.BASE_FREIGHT, shipment_reference="SH-3000")
    partial = upload(client, invoice_data(invoice_number="INV-3002", po_reference="PO-30010", shipment_reference="SH-3000", subtotal=D("2500"), total_amount=D("2500"), lines=[partial_line]), "atlas-inv-3002-partial.pdf")
    assert partial["status"] == "APPROVED"
    assert partial["po_remaining_total"] == "500.00"
    over_line = ExtractedLine(description="Scheduled trip SH-3000", quantity=D("1"), unit_of_measure="TRIP", unit_price=D("1000"), line_amount=D("1000"), charge_type=ChargeType.BASE_FREIGHT, shipment_reference="SH-3000")
    over = upload(client, invoice_data(invoice_number="INV-3003", po_reference="PO-30010", shipment_reference="SH-3000", subtotal=D("1000"), total_amount=D("1000"), lines=[over_line]), "atlas-inv-3003-over-capacity.pdf")
    assert over["status"] == "NEEDS_REVIEW"
    assert rule(over, "VAL-009")["status"] == "REVIEW_REQUIRED"
    assert rule(over, "VAL-012")["difference_json"]["authorization_shortfall"] == "500.00"
    quantity = next(item for item in over["resolution_checklist"] if item["code"] == "VAL-009")
    assert quantity["title"] == "Purchase order quantity exceeded"
    assert quantity["supporting_values"] == [
        {"label": "Original PO quantity", "value": "10 TRIP", "format": "quantity"},
        {"label": "Previously invoiced", "value": "9.5 TRIP", "format": "quantity"},
    ]
    assert quantity["authorized"]["value"] == "0.5 TRIP"
    assert quantity["actual"]["value"] == "1 TRIP"
    assert quantity["shortfall"]["value"] == "0.5 TRIP"
    assert over["decision_summary"]["summary"] == "2 purchase-order authorization issues require review."
    assert over["allocations"] == []


def test_allocation_idempotency_and_concurrent_capacity(db):
    po = db.scalar(select(PurchaseOrder).where(PurchaseOrder.po_number == "PO-10045"))
    atlas = db.scalar(select(Vendor).where(Vendor.vendor_code == "VEN-001"))
    created = []
    for number in ["RACE-1", "RACE-2"]:
        inv = Invoice(invoice_number=number, invoice_number_normalized=number, vendor_id=atlas.id,
            vendor_name_raw=atlas.legal_name, po_reference_raw=po.po_number, matched_po_id=po.id,
            shipment_ref="SH-8891", currency="USD", total_amount=D("2000"), subtotal=D("2000"), tax_amount=D("0"),
            pdf_storage_key=f"test://{number}", pdf_sha256=number.ljust(64, "0"), status=InvoiceStatus.READY_FOR_VALIDATION)
        db.add(inv); db.flush(); created.append(inv.id)
    db.commit()
    Session = db.info["session_factory"]
    def attempt(invoice_id):
        with Session() as session:
            try:
                commit_allocation(session, invoice_id)
                return "approved"
            except AllocationConflict:
                session.rollback()
                return "held"
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(attempt, created))
    assert sorted(outcomes) == ["approved", "held"]
    with pytest.raises(AllocationConflict):
        commit_allocation(db, created[outcomes.index("approved")])
