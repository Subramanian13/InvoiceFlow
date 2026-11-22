import io
import os
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError
from pypdf import PdfReader, PdfWriter
from sqlalchemy import select

from app.main import app
from app.core.config import get_settings
from app.models.entities import Invoice, InvoiceRun, InvoiceStatus, RunStatus
from app.schemas.extraction import ChargeType, ExtractedInvoice, ExtractedLine, ExtractionResult
from app.services.extraction import ExtractionProviderError, GeminiExtractionProvider, generate_content_schema
from app.services.po_matching import match_purchase_order
from app.services.vendor_matching import match_vendor


FIXTURE = Path(__file__).resolve().parents[3] / "demo" / "fixtures" / "atlas-inv-504.pdf"


def extracted(vendor="Atlas Transport LLC", tax_id="12-3454107", po="PO-10045"):
    return ExtractedInvoice(
        vendor_name=vendor, vendor_tax_identifier=tax_id, invoice_number="INV-504", invoice_date="2026-11-01",
        due_date="2026-12-01", po_reference=po, shipment_reference="SH-8891", currency="USD",
        subtotal=Decimal("2600.00"), tax=Decimal("0.00"), total_amount=Decimal("2600.00"),
        lines=[
            ExtractedLine(description="Base freight SH-8891", quantity=Decimal("1"), unit_of_measure="TRIP", unit_price=Decimal("2000"), line_amount=Decimal("2000"), charge_type=ChargeType.BASE_FREIGHT, shipment_reference="SH-8891"),
            ExtractedLine(description="Detention 3 hours", quantity=Decimal("3"), unit_of_measure="HR", unit_price=Decimal("200"), line_amount=Decimal("600"), charge_type=ChargeType.DETENTION, shipment_reference="SH-8891"),
        ], missing_fields=[], uncertain_fields=[], warnings=[], source_references=["Page 1"],
    )


class FakeProvider:
    def extract(self, _pdf_bytes):
        data = extracted()
        return ExtractionResult(data=data, provider="test-provider", model="deterministic-test", duration_ms=12, raw_response=data.model_dump(mode="json"))


class FailingProvider:
    def extract(self, _pdf_bytes):
        raise ExtractionProviderError("GEMINI_RATE_LIMIT", "Gemini request failed (GEMINI_RATE_LIMIT).")


@pytest.fixture(autouse=True)
def provider_override():
    app.state.provider_factory = FakeProvider
    yield


def upload(client, path=FIXTURE):
    with path.open("rb") as stream:
        return client.post("/api/invoices/upload", files={"file": (path.name, stream, "application/pdf")})


def test_valid_pdf_upload_persists_extraction_matching_and_events(client, db):
    response = upload(client)
    assert response.status_code == 202
    invoice_id = response.json()["invoice_id"]
    detail = client.get(f"/api/invoices/{invoice_id}").json()
    assert detail["status"] == "APPROVED"
    assert detail["invoice_number"] == "INV-504"
    assert detail["matching"]["vendor"]["match_method"] == "VERIFIED_MASTER_TAX_ID"
    assert detail["matching"]["purchase_order"]["match_method"] == "EXACT_PO_REFERENCE"
    assert detail["extraction"]["raw_extraction"]["vendor_tax_identifier"]["redacted"] is True
    assert "12-3454107" not in response.text and "12-3454107" not in str(detail)
    assert len(detail["lines"]) == 2
    assert client.get(f"/api/invoices/{invoice_id}/document").content.startswith(b"%PDF-")
    stages = [event["stage"] for event in detail["events"]]
    assert stages[:10] == ["RECEIVED", "EXTRACTING", "EXTRACTING", "NORMALIZING", "NORMALIZING", "VENDOR_MATCHING", "VENDOR_MATCHING", "PO_MATCHING", "PO_MATCHING", "MATCHING_COMPLETE"]
    assert stages[-1] == "DECISION_COMPLETE"
    assert db.get(Invoice, invoice_id).status == InvoiceStatus.APPROVED
    assert detail["allocations"][0]["amount"] == "2600.00"


def test_invalid_file_type(client):
    response = client.post("/api/invoices/upload", files={"file": ("invoice.txt", b"not pdf", "text/plain")})
    assert response.status_code == 415
    assert response.json()["detail"]["code"] == "INVALID_FILE_TYPE"


def test_corrupt_pdf(client):
    response = client.post("/api/invoices/upload", files={"file": ("bad.pdf", b"%PDF-1.7 broken", "application/pdf")})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "MALFORMED_PDF"


def test_oversized_pdf(client):
    from app.api.routes import settings
    old = settings.upload_max_bytes; settings.upload_max_bytes = 20
    try:
        response = upload(client)
        assert response.status_code == 413
        assert response.json()["detail"]["code"] == "PDF_TOO_LARGE"
    finally:
        settings.upload_max_bytes = old


def test_encrypted_pdf(client, tmp_path):
    reader = PdfReader(FIXTURE); writer = PdfWriter(); writer.append_pages_from_reader(reader); writer.encrypt("secret")
    encrypted = tmp_path / "encrypted.pdf"
    with encrypted.open("wb") as stream: writer.write(stream)
    response = upload(client, encrypted)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "ENCRYPTED_PDF"


def test_extraction_schema_rejects_invalid_amount():
    with pytest.raises(ValidationError):
        ExtractedInvoice.model_validate({"lines": [{"description": "Freight", "line_amount": "NaN"}]})


def test_extraction_schema_converts_model_null_sentinels():
    result = ExtractedInvoice.model_validate({"po_reference": "null", "due_date": "Not present"})
    assert result.po_reference is None
    assert result.due_date is None


def test_provider_error_is_persisted(client, db):
    app.state.provider_factory = FailingProvider
    response = upload(client)
    run = db.get(InvoiceRun, response.json()["run_id"])
    invoice = db.get(Invoice, response.json()["invoice_id"])
    db.refresh(run); db.refresh(invoice)
    assert run.status == RunStatus.FAILED
    assert run.error_code == "GEMINI_RATE_LIMIT"
    assert invoice.status == InvoiceStatus.PROCESSING_FAILED
    assert invoice.allocations == []


def test_gemini_provider_uses_generate_content_pdf_input(monkeypatch):
    calls = {}
    payload = extracted().model_dump(mode="json")

    class Response:
        status_code = 200
        def json(self):
            return {"candidates": [{"content": {"parts": [{"text": json.dumps(payload)}]}}]}

    def post(url, **kwargs):
        calls["url"] = url
        calls.update(kwargs)
        return Response()

    monkeypatch.setattr("app.services.extraction.requests.post", post)

    provider = GeminiExtractionProvider.__new__(GeminiExtractionProvider)
    provider.settings = get_settings()
    result = provider.extract(FIXTURE.read_bytes())
    assert calls["url"].endswith("/v1beta/models/gemini-3-flash-preview:generateContent")
    parts = calls["json"]["contents"][0]["parts"]
    assert "Never infer or invent" in parts[0]["text"]
    assert parts[1]["inline_data"]["mime_type"] == "application/pdf"
    assert calls["json"]["generationConfig"]["responseMimeType"] == "application/json"
    assert calls["json"]["generationConfig"]["maxOutputTokens"] == 8192
    assert "thinkingConfig" not in calls["json"]["generationConfig"]
    assert calls["timeout"] == (10, 60)
    assert result.data.invoice_number == "INV-504"


def test_gemini_schema_requires_explicit_values_or_nulls_for_every_field():
    schema = generate_content_schema()
    assert set(schema["required"]) == set(schema["properties"])
    assert schema["properties"]["vendor_name"]["nullable"] is True
    assert schema["properties"]["total_amount"]["nullable"] is True
    line = schema["properties"]["lines"]["items"]
    assert set(line["required"]) == set(line["properties"])


def test_exact_alias_and_tax_identifier_conflict(db):
    alias = match_vendor(db, "Atlas Transportation LLC", None)
    assert alias.automatic_match_permitted and alias.match_method == "APPROVED_ALIAS"
    mismatch = match_vendor(db, "Atlas Transport LLC", "55-5559999")
    assert mismatch.matched_vendor_id is None
    assert "TAX_IDENTIFIER_MISMATCH" in mismatch.conflict_codes
    conflicting_name = match_vendor(db, "Atlas Investments LLC", "12-3454107")
    assert conflicting_name.matched_vendor_id is None
    assert "TAX_NAME_CONFLICT" in conflicting_name.conflict_codes


def test_po_matching_exact_wrong_vendor_and_missing_ambiguous(db):
    atlas = match_vendor(db, "Atlas Transport LLC", None)
    pacific = match_vendor(db, "Pacific Freight Inc.", None)
    exact = match_purchase_order(db, atlas.matched_vendor_id, "PO-10045", "SH-8891", ["Base freight"])
    assert exact.automatic_match_permitted
    wrong = match_purchase_order(db, pacific.matched_vendor_id, "PO-10045", "SH-8891", ["Freight"])
    assert "PO_VENDOR_MISMATCH" in wrong.conflict_codes
    missing = match_purchase_order(db, pacific.matched_vendor_id, None, "SH-7777", ["Regional drayage"])
    assert "AMBIGUOUS_PO_MATCH" in missing.conflict_codes
    assert len(missing.candidates) == 2


@pytest.mark.skipif(
    not get_settings().gemini_api_key or os.getenv("RUN_GEMINI_INTEGRATION") != "1",
    reason="Set RUN_GEMINI_INTEGRATION=1 with GEMINI_API_KEY to run the live test",
)
def test_configured_gemini_integration():
    result = GeminiExtractionProvider().extract(FIXTURE.read_bytes())
    assert result.data.invoice_number == "INV-504"
    assert result.data.total_amount == Decimal("2600.00")
