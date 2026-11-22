from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class AliasOut(ORMModel):
    alias_normalized: str
    source: str


class VendorOut(ORMModel):
    id: int
    vendor_code: str
    legal_name: str
    display_name: str
    status: str
    tax_id_last4: str | None
    tax_id_verified_in_master: bool
    aliases: list[AliasOut]


class POLineOut(ORMModel):
    id: int
    line_number: int
    service_code: str
    description: str
    shipment_ref: str | None
    ordered_quantity: Decimal
    unit_of_measure: str
    unit_price: Decimal
    authorized_line_total: Decimal


class ChargePolicyOut(ORMModel):
    id: int
    charge_type: str
    rate_type: str
    rate: Decimal
    free_hours: Decimal | None
    max_total_allowance: Decimal
    requires_evidence: bool
    policy_notes: str


class PurchaseOrderOut(ORMModel):
    id: int
    po_number: str
    vendor_id: int
    vendor_name: str
    status: str
    currency: str
    authorized_total: Decimal
    committed_total: Decimal
    remaining_total: Decimal
    issue_date: date
    valid_from: date | None
    valid_to: date | None
    description: str
    lines: list[POLineOut]
    charge_policies: list[ChargePolicyOut]


class HealthOut(BaseModel):
    status: str
    database: str

