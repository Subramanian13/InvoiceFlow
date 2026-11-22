from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.models.entities import InvoicePOAllocation, PurchaseOrder, ShipmentEvidence, Vendor, VendorAlias


def test_seed_counts_and_relationships(db):
    assert db.scalar(select(func.count()).select_from(Vendor)) == 8
    assert db.scalar(select(func.count()).select_from(PurchaseOrder)) == 14
    assert db.scalar(select(func.count()).select_from(ShipmentEvidence)) == 7
    atlas = db.scalar(select(Vendor).where(Vendor.vendor_code == "VEN-001"))
    assert {po.po_number for po in atlas.purchase_orders} == {"PO-10045", "PO-10055", "PO-30010"}
    assert atlas.tax_id_last4 == "4107"
    assert len(atlas.tax_id_fingerprint) == 64


def test_partial_invoice_seed_uses_allocation_as_source_of_truth(db):
    po = db.scalar(select(PurchaseOrder).where(PurchaseOrder.po_number == "PO-30010"))
    committed = db.scalar(select(func.sum(InvoicePOAllocation.amount)).where(InvoicePOAllocation.po_id == po.id))
    assert committed == Decimal("7000.00")
    assert po.authorized_total - committed == Decimal("3000.00")
    assert po.allocations[0].line_allocations[0].allocated_quantity == Decimal("7.0000")


def test_air_cargo_po_uses_load_unit(db):
    po = db.scalar(select(PurchaseOrder).where(PurchaseOrder.po_number == "PO-60010"))
    assert po.lines[0].unit_of_measure == "LOAD"


def test_foreign_keys_and_alias_uniqueness_are_enforced(db):
    db.add(VendorAlias(vendor_id=99999, alias_normalized="not a vendor", source="MASTER_APPROVED"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()

