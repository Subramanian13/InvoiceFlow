from decimal import Decimal

from sqlalchemy import func, select

from app.api.routes import settings
from app.models.entities import (
    FieldCorrection, Invoice, InvoicePOAllocation, InvoiceRun, POAmendment,
    POConfirmation, PurchaseOrder, ReviewAction, ReviewCase, ReviewCaseStatus,
    ValidationResult,
)
from app.schemas.extraction import ChargeType, ExtractedLine
from app.tests.test_m1b import invoice_data, rule, upload

D = Decimal


def auth_headers(user="ap-analyst", password="ap-secret"):
    import base64
    encoded = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {encoded}"}


def enable_demo_auth():
    settings.demo_ap_password = "ap-secret"


def pacific_missing_po():
    line = ExtractedLine(description="Regional drayage standard service SH-7777", quantity=D("1"),
        unit_of_measure="TRIP", unit_price=D("1000"), line_amount=D("1000"),
        charge_type=ChargeType.BASE_FREIGHT, shipment_reference="SH-7777")
    return invoice_data(vendor_name="Pacific Freight Inc.", vendor_tax_identifier="98-7658821",
        invoice_number="INV-777", invoice_date="2026-11-05", due_date=None, po_reference=None,
        shipment_reference="SH-7777", subtotal=D("1000"), total_amount=D("1000"), lines=[line])


def detention_overage():
    return invoice_data(invoice_number="INV-505", po_reference="PO-10055", shipment_reference="SH-8895",
        lines=[
            ExtractedLine(description="Base freight SH-8895", quantity=D("1"), unit_of_measure="TRIP", unit_price=D("2000"), line_amount=D("2000"), charge_type=ChargeType.BASE_FREIGHT, shipment_reference="SH-8895"),
            ExtractedLine(description="Detention 3 hours", quantity=D("3"), unit_of_measure="HR", unit_price=D("200"), line_amount=D("600"), charge_type=ChargeType.DETENTION, shipment_reference="SH-8895"),
        ])


def test_dashboard_filters_review_cases_and_human_presentations(client, db):
    detail = upload(client, pacific_missing_po(), "pacific-inv-777-no-po.pdf")
    assert detail["status"] == "NEEDS_REVIEW"
    dashboard = client.get("/api/dashboard/summary").json()
    assert dashboard["total_invoices"] == 2  # historical seed plus upload
    assert dashboard["needs_review"] == 1
    reviews = client.get("/api/reviews").json()
    assert reviews and any(item["invoice_id"] == detail["id"] for item in reviews)
    assert len({item["invoice_id"] for item in reviews}) == len(reviews)
    review = next(item for item in reviews if item["invoice_id"] == detail["id"])
    assert review["issue_count"] == 1
    filtered = client.get("/api/invoices", params={"search": "777", "status": "NEEDS_REVIEW"}).json()
    assert [item["id"] for item in filtered] == [detail["id"]]
    capacity = rule(detail, "VAL-012")
    assert capacity["presentation"]["actual"]
    assert all("{" not in item["value"] for item in capacity["presentation"]["actual"])
    assert detail["decision_summary"]["reasons"]


def test_checklist_shows_root_causes_not_cascading_po_failures(client):
    detail = upload(client, invoice_data(
        vendor_name=None, vendor_tax_identifier=None, po_reference=None,
        subtotal=None, total_amount=None,
    ), "pacific-inv-777-no-po.pdf")
    codes = {item["code"] for item in detail["resolution_checklist"] if item["state"] == "UNRESOLVED"}
    assert codes == {"EXTRACTION_ISSUES"}
    assert codes.isdisjoint({"VAL-004", "VAL-006", "VAL-007", "VAL-008", "VAL-009", "VAL-012", "VAL-013"})
    extraction = detail["resolution_checklist"][0]
    assert extraction["title"] == "Extraction needs correction"
    assert "Supplier name" in extraction["details"]
    assert "Purchase order reference" in extraction["details"]


def test_supplier_typo_explains_exact_match_requirement_and_keeps_po_visible(client):
    detail = upload(client, invoice_data(
        vendor_name="Pacific Frieght Inc.", vendor_tax_identifier=None,
        po_reference=None, subtotal=None, total_amount=None,
    ), "pacific-inv-777-no-po.pdf")
    extraction = next(item for item in detail["resolution_checklist"]
                      if item["code"] == "EXTRACTION_ISSUES")
    assert "Pacific Frieght Inc." in extraction["why"]
    assert "Pacific Freight Inc." in extraction["why"]
    assert "automatic fuzzy matching is not permitted" in extraction["why"]
    assert "Purchase order reference" in extraction["details"]


def test_missing_po_confirmation_is_audited_and_revalidates_to_approval(client, db):
    enable_demo_auth()
    detail = upload(client, pacific_missing_po(), "pacific-inv-777-no-po.pdf")
    unresolved = [item for item in detail["resolution_checklist"] if item["state"] == "UNRESOLVED"]
    assert [item["code"] for item in unresolved] == ["VAL-004"]
    po = db.scalar(select(PurchaseOrder).where(PurchaseOrder.po_number == "PO-20010"))
    response = client.post(f"/api/invoices/{detail['id']}/review/confirm-po",
        json={"po_id": po.id, "reason": "Rate and shipment match the standard-service PO.", "idempotency_key": "confirm-777"},
        headers=auth_headers())
    assert response.status_code == 200, response.text
    updated = client.get(f"/api/invoices/{detail['id']}").json()
    assert updated["status"] == "APPROVED"
    assert updated["po_reference"] == "PO-20010"
    assert updated["po_reference_raw"] is None
    summary = next(item for item in client.get("/api/invoices").json() if item["id"] == detail["id"])
    assert summary["po_reference"] == "PO-20010"
    assert summary["po_reference_raw"] is None
    assert updated["allocations"][0]["amount"] == "1000.00"
    assert db.scalar(select(func.count()).select_from(POConfirmation).where(POConfirmation.invoice_id == detail["id"])) == 1
    assert db.scalar(select(func.count()).select_from(InvoiceRun).where(InvoiceRun.invoice_id == detail["id"])) == 2
    assert db.scalar(select(func.count()).select_from(ValidationResult).join(InvoiceRun).where(InvoiceRun.invoice_id == detail["id"])) > len(updated["validation_results"])
    assert all(case.status == ReviewCaseStatus.RESOLVED for case in db.scalars(select(ReviewCase).where(ReviewCase.invoice_id == detail["id"])).all())


def test_invalid_and_cross_vendor_po_confirmation_are_rejected(client, db):
    enable_demo_auth()
    detail = upload(client, pacific_missing_po(), "pacific-inv-777-no-po.pdf")
    atlas_po = db.scalar(select(PurchaseOrder).where(PurchaseOrder.po_number == "PO-10045"))
    response = client.post(f"/api/invoices/{detail['id']}/review/confirm-po",
        json={"po_id": atlas_po.id, "reason": "Invalid cross-vendor attempt."}, headers=auth_headers())
    assert response.status_code == 422
    assert "different vendor" in response.json()["detail"]["message"]
    assert db.scalar(select(func.count()).select_from(InvoicePOAllocation).where(InvoicePOAllocation.invoice_id == detail["id"])) == 0


def test_field_correction_preserves_history_and_revalidates(client, db):
    enable_demo_auth()
    detail = upload(client, invoice_data(invoice_number=None))
    assert detail["status"] == "NEEDS_REVIEW"
    response = client.post(f"/api/invoices/{detail['id']}/review/correct-field",
        json={"field_path": "invoice_number", "corrected_value": "INV-CORRECTED-1",
              "reason": "Verified against the original PDF.", "idempotency_key": "correct-number-1"},
        headers=auth_headers())
    assert response.status_code == 200, response.text
    updated = client.get(f"/api/invoices/{detail['id']}").json()
    assert updated["invoice_number"] == "INV-CORRECTED-1"
    assert updated["status"] == "APPROVED"
    correction = db.scalar(select(FieldCorrection).where(FieldCorrection.invoice_id == detail["id"]))
    assert correction.original_value_json == {"value": None}
    assert correction.corrected_value_json == {"value": "INV-CORRECTED-1"}


def test_bulk_extraction_correction_runs_validation_once(client, db):
    enable_demo_auth()
    detail = upload(client, invoice_data(invoice_number=None, due_date=None))
    before_runs = db.scalar(select(func.count()).select_from(InvoiceRun).where(InvoiceRun.invoice_id == detail["id"]))
    response = client.post(f"/api/invoices/{detail['id']}/review/correct-fields", json={
        "corrections": [
            {"field_path": "invoice_number", "corrected_value": "INV-BULK-1"},
            {"field_path": "due_date", "corrected_value": "2026-12-01"},
        ],
        "reason": "Both values were verified against the original PDF.",
        "idempotency_key": "bulk-correction-1",
    }, headers=auth_headers())
    assert response.status_code == 200, response.text
    assert db.scalar(select(func.count()).select_from(InvoiceRun).where(InvoiceRun.invoice_id == detail["id"])) == before_runs + 1
    corrections = db.scalars(select(FieldCorrection).where(FieldCorrection.invoice_id == detail["id"])).all()
    assert {item.field_path for item in corrections} == {"invoice_number", "due_date"}


def test_financial_amendment_route_is_not_exposed(client, db):
    detail = upload(client, detention_overage(), "atlas-inv-505-detention-overage.pdf")
    po = db.scalar(select(PurchaseOrder).where(PurchaseOrder.po_number == "PO-10055"))
    payload = {"invoice_id": detail["id"], "amendment_scope": "PO_TOTAL",
               "new_authorized_total": "2600.00", "charge_type": "DETENTION",
               "new_allowance": "300.00", "approval_reference": "PROC-2026-001",
               "reason": "Procurement approved PO total only.", "explicit_confirmation": True,
               "idempotency_key": "amend-total-only"}
    response = client.post(f"/api/purchase-orders/{po.id}/amendments", json=payload,
        headers=auth_headers("procurement", "proc-secret"))
    assert response.status_code == 404
    held = client.get(f"/api/invoices/{detail['id']}").json()
    assert held["status"] == "NEEDS_REVIEW"
    assert rule(held, "VAL-010-ALLOWANCE")["status"] == "REVIEW_REQUIRED"
    assert len(db.scalars(select(POAmendment).where(POAmendment.invoice_id == detail["id"])).all()) == 0
    assert held["allocations"] == []


def test_m22_explains_independent_shortfalls_without_amendment_actions(client):
    detail = upload(client, detention_overage(), "atlas-inv-505-detention-overage.pdf")
    checklist = {item["code"]: item for item in detail["resolution_checklist"]}
    capacity = checklist["VAL-012"]
    detention = checklist["VAL-010-ALLOWANCE"]
    assert capacity["title"] == "Purchase order limit exceeded"
    assert capacity["shortfall"]["value"] == "$300.00"
    assert capacity["action_type"] is None
    assert detention["title"] == "Detention allowance exceeded"
    assert detention["shortfall"]["value"] == "$300.00"
    assert detention["action_type"] is None
    assert "purchasing system" in capacity["required_action"]
    assert "InvoiceFlow cannot change" in detention["required_action"]


def test_review_action_idempotency_and_audit_endpoint(client, db):
    enable_demo_auth()
    detail = upload(client, pacific_missing_po(), "pacific-inv-777-no-po.pdf")
    po = db.scalar(select(PurchaseOrder).where(PurchaseOrder.po_number == "PO-20010"))
    payload = {"po_id": po.id, "reason": "Confirmed with shipment and rate evidence.", "idempotency_key": "same-confirm-key"}
    first = client.post(f"/api/invoices/{detail['id']}/review/confirm-po", json=payload, headers=auth_headers())
    second = client.post(f"/api/invoices/{detail['id']}/review/confirm-po", json=payload, headers=auth_headers())
    assert first.status_code == 200 and second.status_code == 200
    assert db.scalar(select(func.count()).select_from(ReviewAction).where(ReviewAction.idempotency_key == "same-confirm-key")) == 1
    audit = client.get("/api/audit", params={"invoice_id": detail["id"]}).json()
    assert any(item["stage"] == "PO_CONFIRMED" for item in audit)
