import hashlib
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.entities import (
    AllocationStatus, ChargePolicy, Invoice, InvoiceLine, InvoiceLineAllocation,
    InvoicePOAllocation, InvoiceStatus, POLine, POStatus, PurchaseOrder, RateType,
    ShipmentEvidence, Vendor, VendorAlias, VendorStatus,
)


D = Decimal


def add_po(session: Session, vendor: Vendor, number: str, total: str, description: str,
           shipment: str, quantity: str, unit_price: str, uom: str = "TRIP",
           currency: str = "USD") -> PurchaseOrder:
    po = PurchaseOrder(
        po_number=number, vendor=vendor, status=POStatus.OPEN, currency=currency,
        authorized_total=D(total), issue_date=date(2026, 10, 1), valid_from=date(2026, 10, 1),
        valid_to=date(2026, 12, 31), description=description,
    )
    po.lines.append(POLine(
        line_number=1, service_code="FREIGHT", description=description, shipment_ref=shipment,
        ordered_quantity=D(quantity), unit_of_measure=uom, unit_price=D(unit_price),
        authorized_line_total=D(quantity) * D(unit_price),
    ))
    session.add(po)
    return po


def seed(session: Session) -> None:
    if session.scalar(select(Vendor.id).limit(1)) is not None:
        atlas = session.scalar(select(Vendor).where(Vendor.vendor_code == "VEN-001"))
        pacific = session.scalar(select(Vendor).where(Vendor.vendor_code == "VEN-002"))
        if atlas:
            atlas.tax_id_fingerprint = hashlib.sha256(b"123454107").hexdigest()
            atlas.tax_id_last4 = "4107"
        if pacific:
            pacific.tax_id_fingerprint = hashlib.sha256(b"987658821").hexdigest()
            pacific.tax_id_last4 = "8821"
        session.commit()
        print("Demo data already exists; reconciled synthetic vendor fingerprints.")
        return
    atlas = Vendor(
        vendor_code="VEN-001", legal_name="Atlas Transport LLC", display_name="Atlas Transport",
        status=VendorStatus.ACTIVE, tax_id_fingerprint=hashlib.sha256(b"123454107").hexdigest(),
        tax_id_last4="4107", tax_id_verified_in_master=True,
        aliases=[VendorAlias(alias_normalized="atlas transportation llc", source="MASTER_APPROVED")],
    )
    pacific = Vendor(
        vendor_code="VEN-002", legal_name="Pacific Freight Inc.", display_name="Pacific Freight",
        status=VendorStatus.ACTIVE, tax_id_fingerprint=hashlib.sha256(b"987658821").hexdigest(),
        tax_id_last4="8821", tax_id_verified_in_master=True,
        aliases=[VendorAlias(alias_normalized="pacific freight inc", source="MASTER_APPROVED")],
    )
    northstar = Vendor(
        vendor_code="VEN-003", legal_name="Northstar Logistics Co.", display_name="Northstar Logistics",
        status=VendorStatus.ACTIVE, tax_id_fingerprint=hashlib.sha256(b"364918205").hexdigest(),
        tax_id_last4="8205", tax_id_verified_in_master=True,
        aliases=[VendorAlias(alias_normalized="northstar logistics", source="MASTER_APPROVED")],
    )
    harbor = Vendor(
        vendor_code="VEN-004", legal_name="Harbor Cold Chain LLC", display_name="Harbor Cold Chain",
        status=VendorStatus.ACTIVE, tax_id_fingerprint=hashlib.sha256(b"824617390").hexdigest(),
        tax_id_last4="7390", tax_id_verified_in_master=True,
        aliases=[VendorAlias(alias_normalized="harbor cold chain", source="MASTER_APPROVED")],
    )
    summit = Vendor(
        vendor_code="VEN-005", legal_name="Summit Air Cargo Inc.", display_name="Summit Air Cargo",
        status=VendorStatus.ACTIVE, tax_id_fingerprint=hashlib.sha256(b"458203176").hexdigest(),
        tax_id_last4="3176", tax_id_verified_in_master=True,
        aliases=[VendorAlias(alias_normalized="summit air cargo", source="MASTER_APPROVED")],
    )
    bluepeak = Vendor(
        vendor_code="VEN-006", legal_name="BluePeak Distribution Ltd.", display_name="BluePeak Distribution",
        status=VendorStatus.ACTIVE, tax_id_fingerprint=hashlib.sha256(b"719305284").hexdigest(),
        tax_id_last4="5284", tax_id_verified_in_master=True,
        aliases=[VendorAlias(alias_normalized="bluepeak distribution", source="MASTER_APPROVED")],
    )
    redwood = Vendor(
        vendor_code="VEN-007", legal_name="Redwood Haulage Corp.", display_name="Redwood Haulage",
        status=VendorStatus.INACTIVE, tax_id_fingerprint=hashlib.sha256(b"936142870").hexdigest(),
        tax_id_last4="2870", tax_id_verified_in_master=True,
        aliases=[VendorAlias(alias_normalized="redwood haulage", source="MASTER_APPROVED")],
    )
    metro = Vendor(
        vendor_code="VEN-008", legal_name="MetroLine Courier Services LLC", display_name="MetroLine Courier",
        status=VendorStatus.ACTIVE, tax_id_fingerprint=hashlib.sha256(b"602847315").hexdigest(),
        tax_id_last4="7315", tax_id_verified_in_master=True,
        aliases=[VendorAlias(alias_normalized="metroline courier", source="MASTER_APPROVED")],
    )
    session.add_all([atlas, pacific, northstar, harbor, summit, bluepeak, redwood, metro]); session.flush()
    po_a = add_po(session, atlas, "PO-10045", "3000.00", "Port-to-warehouse freight for SH-8891", "SH-8891", "1", "2000.00")
    po_c = add_po(session, atlas, "PO-10055", "2300.00", "Port-to-warehouse freight for SH-8895", "SH-8895", "1", "2000.00")
    po_d1 = add_po(session, pacific, "PO-20010", "2000.00", "Regional drayage, standard service", "SH-7777", "2", "1000.00")
    po_d2 = add_po(session, pacific, "PO-20011", "1800.00", "Regional drayage, expedited service", "SH-7777", "2", "900.00")
    po_e = add_po(session, atlas, "PO-30010", "10000.00", "Ten scheduled line-haul trips", "SH-3000", "10", "1000.00")
    po_n1 = add_po(session, northstar, "PO-40010", "5000.00", "Dedicated local delivery runs", "SH-8100", "2", "1450.00")
    add_po(session, northstar, "PO-40011", "3600.00", "Airport transfer service", "SH-8110", "3", "1200.00")
    po_h1 = add_po(session, harbor, "PO-50010", "5000.00", "Refrigerated full-truckload service", "SH-9200", "1", "3200.00")
    add_po(session, harbor, "PO-50011", "4200.00", "Cold-storage shuttle service", "SH-9210", "2", "1800.00")
    po_s1 = add_po(session, summit, "PO-60010", "4000.00", "Domestic air cargo movement", "AWB-6100", "2", "1800.00", uom="LOAD")
    po_b1 = add_po(session, bluepeak, "PO-70010", "5000.00", "Regional distribution route", "SH-7100", "3", "1200.00")
    add_po(session, redwood, "PO-80010", "2500.00", "Heavy haul service", "SH-9900", "1", "2000.00")
    add_po(session, metro, "PO-90010", "2400.00", "Same-day city courier route", "SH-9300", "4", "500.00")
    add_po(session, metro, "PO-90011", "2400.00", "Next-day city courier route", "SH-9300", "4", "500.00")
    session.flush()
    for po, allowance in [(po_a, "1000.00"), (po_c, "300.00")]:
        po.charge_policies.append(ChargePolicy(
            charge_type="DETENTION", rate_type=RateType.PER_HOUR, rate=D("200.00"),
            free_hours=D("2"), max_total_allowance=D(allowance), requires_evidence=True,
            policy_notes="One-hour billing increments; verified warehouse gate log required.",
        ))
    session.add_all([
        ShipmentEvidence(shipment_ref="SH-8891", vendor_id=atlas.id, po_id=po_a.id,
            arrival_at=datetime(2026, 11, 1, 9, tzinfo=timezone.utc), departure_at=datetime(2026, 11, 1, 14, tzinfo=timezone.utc),
            source="WAREHOUSE_GATE_LOG", verified=True, notes="Synthetic North Harbor gate record."),
        ShipmentEvidence(shipment_ref="SH-8895", vendor_id=atlas.id, po_id=po_c.id,
            arrival_at=datetime(2026, 11, 3, 9, tzinfo=timezone.utc), departure_at=datetime(2026, 11, 3, 14, tzinfo=timezone.utc),
            source="WAREHOUSE_GATE_LOG", verified=True, notes="Synthetic East Distribution Center gate record."),
        ShipmentEvidence(shipment_ref="SH-7777", vendor_id=pacific.id, po_id=None,
            arrival_at=datetime(2026, 11, 5, 10, tzinfo=timezone.utc), departure_at=datetime(2026, 11, 5, 11, tzinfo=timezone.utc),
            source="WAREHOUSE_GATE_LOG", verified=True, notes="Evidence intentionally does not disambiguate two eligible POs."),
        ShipmentEvidence(shipment_ref="SH-8100", vendor_id=northstar.id, po_id=po_n1.id,
            arrival_at=datetime(2026, 11, 7, 8, tzinfo=timezone.utc), departure_at=datetime(2026, 11, 7, 9, tzinfo=timezone.utc),
            source="DRIVER_DELIVERY_LOG", verified=True, notes="Synthetic Northstar delivery record."),
        ShipmentEvidence(shipment_ref="SH-9200", vendor_id=harbor.id, po_id=po_h1.id,
            arrival_at=datetime(2026, 11, 8, 6, tzinfo=timezone.utc), departure_at=datetime(2026, 11, 8, 8, tzinfo=timezone.utc),
            source="COLD_STORAGE_GATE_LOG", verified=True, notes="Synthetic refrigerated-dock record."),
        ShipmentEvidence(shipment_ref="AWB-6100", vendor_id=summit.id, po_id=po_s1.id,
            arrival_at=datetime(2026, 11, 9, 12, tzinfo=timezone.utc), departure_at=datetime(2026, 11, 9, 13, tzinfo=timezone.utc),
            source="AIR_WAYBILL_EVENT", verified=True, notes="Synthetic air-cargo movement event."),
        ShipmentEvidence(shipment_ref="SH-7100", vendor_id=bluepeak.id, po_id=po_b1.id,
            arrival_at=datetime(2026, 11, 10, 10, tzinfo=timezone.utc), departure_at=datetime(2026, 11, 10, 11, tzinfo=timezone.utc),
            source="DISTRIBUTION_SCAN", verified=True, notes="Synthetic distribution scan event."),
    ])
    prior = Invoice(
        invoice_number="INV-3001", invoice_number_normalized="INV-3001", vendor_id=atlas.id,
        vendor_name_raw="Atlas Transport LLC", po_reference_raw="PO-30010", matched_po_id=po_e.id,
        shipment_ref="SH-3000", invoice_date=date(2026, 10, 20), currency="USD",
        subtotal=D("7000.00"), tax_amount=D("0.00"), total_amount=D("7000.00"),
        pdf_storage_key="seed://historical/INV-3001", pdf_sha256=hashlib.sha256(b"historical-inv-3001").hexdigest(),
        extraction_json={"source": "seeded historical commitment"}, extraction_provider=None,
        status=InvoiceStatus.APPROVED, decision_reason="Historical committed invoice seeded for capacity testing.",
    )
    line = InvoiceLine(line_number=1, description="Seven scheduled trips", charge_type="FREIGHT",
        quantity=D("7"), unit_price=D("1000.00"), amount=D("7000.00"), shipment_ref="SH-3000", matched_po_line_id=po_e.lines[0].id)
    prior.lines.append(line); session.add(prior); session.flush()
    allocation = InvoicePOAllocation(invoice_id=prior.id, po_id=po_e.id, amount=D("7000.00"), status=AllocationStatus.COMMITTED)
    session.add(allocation); session.flush()
    session.add(InvoiceLineAllocation(allocation_id=allocation.id, invoice_line_id=line.id, po_line_id=po_e.lines[0].id,
        charge_policy_id=None, allocated_quantity=D("7"), allocated_amount=D("7000.00")))
    session.commit()
    print("Seeded 8 vendors, 14 POs, 7 evidence records, and 1 historical committed invoice.")


if __name__ == "__main__":
    with SessionLocal() as db:
        seed(db)

