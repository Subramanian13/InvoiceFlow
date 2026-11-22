export interface Vendor { id: number; vendor_code: string; legal_name: string; display_name: string; status: string; tax_id_last4: string | null; tax_id_verified_in_master: boolean; aliases: {alias_normalized: string; source: string}[] }
export interface POLine { id: number; line_number: number; service_code: string; description: string; shipment_ref: string | null; ordered_quantity: string; unit_of_measure: string; unit_price: string; authorized_line_total: string }
export interface ChargePolicy { id: number; charge_type: string; rate_type: string; rate: string; free_hours: string | null; max_total_allowance: string; requires_evidence: boolean; policy_notes: string }
export interface PurchaseOrder { id: number; po_number: string; vendor_id: number; vendor_name: string; status: string; currency: string; authorized_total: string; committed_total: string; remaining_total: string; issue_date: string; description: string; lines: POLine[]; charge_policies: ChargePolicy[] }

