from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.entities import POLine, POStatus, PurchaseOrder
from app.schemas.extraction import POCandidate, POMatchResult
from app.services.normalization import normalize_po_reference, normalize_shipment_reference


def match_purchase_order(db: Session, vendor_id: int | None, po_reference: str | None,
                         shipment_reference: str | None, line_descriptions: list[str]) -> POMatchResult:
    if vendor_id is None:
        return POMatchResult(conflict_codes=["PO_MATCH_REQUIRES_VERIFIED_VENDOR"], evidence=["PO matching was not attempted without a verified vendor."])
    orders = db.scalars(select(PurchaseOrder).options(selectinload(PurchaseOrder.lines)).order_by(PurchaseOrder.po_number)).all()
    normalized_po = normalize_po_reference(po_reference)
    if normalized_po:
        po = next((item for item in orders if normalize_po_reference(item.po_number) == normalized_po), None)
        if po is None:
            return POMatchResult(conflict_codes=["PO_NOT_FOUND"], evidence=[f"No purchase order matched reference {po_reference}."])
        candidate = po_candidate(po, shipment_reference, line_descriptions).model_copy(
            update={"analyst_confirmation_required": False, "priority": 1})
        if po.vendor_id != vendor_id:
            return POMatchResult(conflict_codes=["PO_VENDOR_MISMATCH"], candidates=[candidate], evidence=["Referenced PO belongs to a different vendor-master record."])
        if po.status != POStatus.OPEN:
            return POMatchResult(conflict_codes=["PO_NOT_OPEN"], candidates=[candidate], evidence=[f"Referenced PO status is {po.status.value}."])
        return POMatchResult(matched_po_id=po.id, match_method="EXACT_PO_REFERENCE", automatic_match_permitted=True,
            evidence=["Normalized PO reference matched an OPEN purchase order owned by the identified vendor."], candidates=[candidate])

    eligible = [po for po in orders if po.vendor_id == vendor_id and po.status == POStatus.OPEN]
    candidates = [po_candidate(po, shipment_reference, line_descriptions) for po in eligible]
    candidates.sort(key=lambda item: (item.shipment_match, item.service_match, item.po_number), reverse=True)
    candidates = [item.model_copy(update={"priority": index}) for index, item in enumerate(candidates, 1)]
    plausible = [item for item in candidates if item.shipment_match or item.service_match] or candidates
    code = "AMBIGUOUS_PO_MATCH" if len(plausible) > 1 else "MISSING_PO_REQUIRES_CONFIRMATION" if plausible else "NO_ELIGIBLE_PO"
    return POMatchResult(automatic_match_permitted=False, conflict_codes=[code], candidates=plausible,
        evidence=["Invoice has no PO reference; candidate ranking is explanatory and requires analyst confirmation."])


def po_candidate(po: PurchaseOrder, shipment_reference: str | None, descriptions: list[str]) -> POCandidate:
    normalized_shipment = normalize_shipment_reference(shipment_reference)
    shipment_match = bool(normalized_shipment and any(normalize_shipment_reference(line.shipment_ref) == normalized_shipment for line in po.lines))
    words = {word.casefold() for text in descriptions for word in text.split() if len(word) > 4}
    service_text = " ".join([po.description, *[line.description for line in po.lines]]).casefold()
    service_match = any(word in service_text for word in words)
    evidence = []
    if shipment_match: evidence.append(f"Shipment reference matches a line on {po.po_number}.")
    if service_match: evidence.append(f"Invoice service text overlaps {po.po_number} scope.")
    if not evidence: evidence.append(f"{po.po_number} is OPEN and belongs to the identified vendor.")
    evidence.append(f"Vendor ownership matched the identified vendor; PO status is {po.status.value}.")
    if not shipment_match and normalized_shipment:
        evidence.append(f"Shipment {normalized_shipment} does not match this PO's shipment scope.")
    return POCandidate(
        po_id=po.id, po_number=po.po_number, evidence=evidence,
        shipment_match=shipment_match, service_match=service_match,
        vendor_match=True, po_status=po.status.value,
        analyst_confirmation_required=True, priority=1,
    )

