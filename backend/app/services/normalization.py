import re
import unicodedata
from datetime import date, datetime
from decimal import Decimal

from app.schemas.extraction import ChargeType, ExtractedInvoice


def clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(value.strip().split())
    return cleaned or None


def normalize_vendor_name(value: str | None) -> str | None:
    value = clean_text(value)
    if not value:
        return None
    value = unicodedata.normalize("NFKC", value).casefold()
    value = re.sub(r"[^a-z0-9&]+", " ", value)
    return " ".join(value.split())


def normalize_reference(value: str | None) -> str | None:
    value = clean_text(value)
    if not value:
        return None
    return re.sub(r"[^A-Z0-9]+", "", unicodedata.normalize("NFKC", value).upper())


def normalize_invoice_number(value: str | None) -> str | None:
    return normalize_reference(value)


def normalize_po_reference(value: str | None) -> str | None:
    return normalize_reference(value)


def normalize_shipment_reference(value: str | None) -> str | None:
    return normalize_reference(value)


def normalize_date(value: str | None) -> date | None:
    value = clean_text(value)
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def normalize_currency(value: str | None) -> str:
    if not value:
        return "USD"
    normalized = value.strip().upper()
    return "USD" if normalized in {"$", "US$", "USD", "US DOLLAR", "US DOLLARS"} else normalized[:3]


CHARGE_ALIASES = {
    "FREIGHT": ChargeType.BASE_FREIGHT,
    "BASE": ChargeType.BASE_FREIGHT,
    "BASE_FREIGHT": ChargeType.BASE_FREIGHT,
    "FUEL": ChargeType.FUEL_SURCHARGE,
    "FUEL_SURCHARGE": ChargeType.FUEL_SURCHARGE,
    "DETENTION": ChargeType.DETENTION,
    "DEMURRAGE": ChargeType.DEMURRAGE,
    "STORAGE": ChargeType.STORAGE,
    "OTHER": ChargeType.OTHER,
    "UNKNOWN": ChargeType.UNKNOWN,
}


def normalize_charge_type(value: ChargeType | str) -> ChargeType:
    key = str(value.value if isinstance(value, ChargeType) else value).strip().upper().replace(" ", "_")
    return CHARGE_ALIASES.get(key, ChargeType.UNKNOWN)


def normalize_tax_identifier(value: str | None) -> str | None:
    if not value:
        return None
    normalized = re.sub(r"[^A-Za-z0-9]", "", value).upper()
    return normalized or None


def normalize_extraction(data: ExtractedInvoice) -> tuple[dict, list[dict], list[dict]]:
    changes: list[dict] = []
    exceptions: list[dict] = []

    def changed(field: str, raw, normalized):
        if raw is not None and str(raw) != str(normalized):
            changes.append({"field": field, "raw": str(raw), "normalized": str(normalized) if normalized is not None else None})

    invoice_date = normalize_date(data.invoice_date)
    due_date = normalize_date(data.due_date)
    changed("invoice_date", data.invoice_date, invoice_date)
    changed("due_date", data.due_date, due_date)
    if data.invoice_date and invoice_date is None:
        exceptions.append({"code": "INVALID_INVOICE_DATE", "field": "invoice_date", "message": "Invoice date could not be normalized safely."})
    if data.due_date and due_date is None:
        exceptions.append({"code": "INVALID_DUE_DATE", "field": "due_date", "message": "Due date could not be normalized safely."})
    normalized = {
        "vendor_name": clean_text(data.vendor_name),
        "vendor_name_normalized": normalize_vendor_name(data.vendor_name),
        "invoice_number": clean_text(data.invoice_number),
        "invoice_number_normalized": normalize_invoice_number(data.invoice_number),
        "invoice_date": invoice_date,
        "due_date": due_date,
        "po_reference": clean_text(data.po_reference),
        "po_reference_normalized": normalize_po_reference(data.po_reference),
        "shipment_reference": clean_text(data.shipment_reference),
        "shipment_reference_normalized": normalize_shipment_reference(data.shipment_reference),
        "currency": normalize_currency(data.currency),
        "subtotal": data.subtotal,
        "tax": data.tax,
        "total_amount": data.total_amount,
    }
    for field in ("vendor_name", "invoice_number", "invoice_date", "total_amount"):
        if normalized.get(field) is None:
            exceptions.append({"code": "MISSING_REQUIRED_FIELD", "field": field, "message": f"Required field {field} is missing."})
    for field in data.uncertain_fields:
        exceptions.append({"code": "UNCERTAIN_FIELD", "field": field, "message": f"Extraction marked {field} as uncertain."})
    return normalized, changes, exceptions

