from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from app.models.entities import ChargePolicy, Invoice, InvoiceEvent, InvoiceStatus, PurchaseOrder, ReviewCase, ReviewCaseStatus, ValidationResult, ValidationStatus
from app.schemas.m2 import AuthorizationHistoryOut, DecisionSummaryOut, DisplayValue, ResolutionChecklistItemOut, ValidationPresentationOut


GROUPS = {
    "VAL-001": "Identity and document", "VAL-002": "Identity and document",
    "VAL-003": "Identity and document", "VAL-013": "Identity and document",
    "VAL-004": "Purchase order matching", "VAL-006": "Purchase order matching",
    "VAL-007": "Purchase order matching", "VAL-008": "Purchase order matching",
    "VAL-009": "Purchase order matching", "VAL-005": "Financial checks",
    "VAL-011": "Financial checks", "VAL-012": "Financial checks",
    "VAL-010-EVIDENCE": "Detention", "VAL-010-ALLOWANCE": "Detention",
    "VAL-014": "Final decision",
}

ACTIONS = {
    "VAL-001": "Correct the extracted field or obtain a corrected invoice.",
    "VAL-002": "Resolve the vendor identity conflict with approved master data.",
    "VAL-003": "Review the existing invoice; do not create a second payment request.",
    "VAL-004": "Confirm an eligible purchase order using supporting evidence.",
    "VAL-005": "Request a corrected invoice or correct a verified extraction error.",
    "VAL-006": "Obtain a currency-corrected invoice; automatic FX conversion is unavailable.",
    "VAL-007": "Resolve the PO line mapping before approval.",
    "VAL-008": "Obtain an authorized rate or request a corrected invoice.",
    "VAL-009": "Obtain additional quantity authorization or request a corrected invoice.",
    "VAL-010-EVIDENCE": "Obtain verified shipment evidence or dispute the charge.",
    "VAL-010-ALLOWANCE": "Obtain an authorized detention allowance amendment or dispute the excess.",
    "VAL-011": "Obtain an applicable charge policy or remove the unsupported charge.",
    "VAL-012": "Obtain an authorized PO amendment or request a corrected invoice.",
    "VAL-013": "Resolve the invoice/service date conflict with procurement.",
}

LABELS = {
    "remaining_authorization": "Available authorization", "invoice_total": "Invoice amount",
    "authorization_shortfall": "Shortfall", "committed_total": "Previously committed",
    "remaining_allowance": "Authorized remaining allowance", "claimed": "Amount claimed",
    "shortfall": "Excess charge", "expected": "Expected amount", "actual": "Actual amount",
    "difference": "Difference", "remaining_quantity": "Authorized remaining quantity",
    "requested_quantity": "Requested quantity", "po_currency": "PO currency",
    "invoice_currency": "Invoice currency", "vendor_status": "Vendor status",
    "po_owner_matches": "PO belongs to vendor", "duplicate": "Duplicate found",
    "linked_invoice_id": "Existing invoice record", "missing_or_ambiguous": "Missing or ambiguous fields",
    "status": "PO status", "match_method": "Match method", "vendor_owned": "PO belongs to vendor",
    "tolerance": "Rounding tolerance", "line_sum": "Invoice line total", "subtotal": "Subtotal",
    "tax": "Tax", "total": "Invoice total", "valid_from": "PO valid from", "valid_to": "PO valid to",
    "invoice_date": "Invoice date", "waiting_hours": "Waiting time", "free_hours": "Free time",
    "billable_hours": "Billable time", "shipment_reference": "Shipment reference",
}

MONEY_KEYS = {"remaining_authorization", "invoice_total", "authorization_shortfall", "committed_total",
              "remaining_allowance", "claimed", "shortfall", "expected", "actual", "difference",
              "line_sum", "subtotal", "tax", "total", "previous_total", "new_total"}
QUANTITY_KEYS = {"remaining_quantity", "requested_quantity", "waiting_hours", "free_hours", "billable_hours"}


def _human(key: str) -> str:
    return LABELS.get(key, key.replace("_", " ").capitalize())


def _format(key: str, value: Any) -> tuple[str, str]:
    if value is None:
        return "Not provided", "missing"
    if isinstance(value, bool):
        return ("Yes" if value else "No"), "boolean"
    if isinstance(value, list):
        if not value:
            return "None", "text"
        if all(not isinstance(item, dict) for item in value):
            return ", ".join(str(item).replace("_", " ") for item in value), "text"
        return f"{len(value)} issue{'s' if len(value) != 1 else ''}", "text"
    if key in MONEY_KEYS:
        try:
            return f"${Decimal(str(value)):,.2f}", "currency"
        except InvalidOperation:
            pass
    if key in QUANTITY_KEYS:
        return f"{value} hours" if "hours" in key else str(value), "quantity"
    return str(value).replace("_", " "), "text"


def _values(payload: dict[str, Any] | None) -> list[DisplayValue]:
    output: list[DisplayValue] = []
    for key, value in (payload or {}).items():
        if key == "issues" and isinstance(value, list):
            for index, issue in enumerate(value, 1):
                if isinstance(issue, dict):
                    for issue_key, issue_value in issue.items():
                        formatted, kind = _format(issue_key, issue_value)
                        output.append(DisplayValue(label=f"Issue {index}: {_human(issue_key)}", value=formatted, format=kind))
            continue
        formatted, kind = _format(key, value)
        output.append(DisplayValue(label=_human(key), value=formatted, format=kind))
    return output


def validation_presentation(row: ValidationResult) -> ValidationPresentationOut:
    action = ACTIONS.get(row.rule_code) if row.status not in {ValidationStatus.PASS, ValidationStatus.NOT_APPLICABLE} else None
    if row.rule_code == "VAL-005" and row.status == ValidationStatus.REVIEW_REQUIRED \
            and (row.actual_json or {}).get("tax") is None:
        action = ("Enter $0.00 only when the PDF explicitly states zero or no tax. Otherwise obtain supplier clarification "
                  "or a corrected invoice; do not infer zero from a matching total.")
    return ValidationPresentationOut(
        group=GROUPS.get(row.rule_code, "Other controls"), outcome=row.status.value,
        explanation=row.message, expected=_values(row.expected_json), actual=_values(row.actual_json),
        difference=_values(row.difference_json), evidence=_values(row.evidence_json),
        recommended_action=action,
        technical_details={"expected": row.expected_json, "actual": row.actual_json,
                           "difference": row.difference_json, "evidence": row.evidence_json},
    )


def decision_summary(invoice: Invoice, validations: list[ValidationResult], po_number: str | None,
                     po_authorized: Decimal | None, po_committed: Decimal | None,
                     po_remaining: Decimal | None) -> DecisionSummaryOut:
    issues = [row for row in validations if row.status in {
        ValidationStatus.FAIL, ValidationStatus.REVIEW_REQUIRED, ValidationStatus.BLOCK, ValidationStatus.TECHNICAL_ERROR}]
    codes = {row.rule_code for row in issues}
    if "VAL-003" in codes:
        issues = [row for row in issues if row.rule_code == "VAL-003"]
    elif "VAL-004" in codes:
        # PO-dependent controls fail closed too, but the missing/ambiguous PO is the root action.
        issues = [row for row in issues if row.rule_code in {"VAL-001", "VAL-002", "VAL-004"}]
        if any(row.rule_code == "VAL-004" for row in issues):
            issues = [row for row in issues if row.rule_code != "VAL-001"]
        vendor = next((row for row in issues if row.rule_code == "VAL-002"), None)
        vendor_actual = (vendor.actual_json or {}) if vendor else {}
        if (vendor_actual.get("vendor_id") and vendor_actual.get("vendor_status") == "ACTIVE"
                and not vendor_actual.get("identity_conflicts")):
            issues = [row for row in issues if row.rule_code != "VAL-002"]
    elif "VAL-002" in codes:
        issues = [row for row in issues if row.rule_code in {"VAL-001", "VAL-002"}]
    reasons = [row.message for row in issues if row.rule_code != "VAL-014"]
    if invoice.vendor_id is None and any(row.rule_code in {"VAL-001", "VAL-002", "VAL-005"} for row in issues):
        reasons = ["Required invoice information was not reliably extracted and must be checked against the PDF."]
    linked = None
    duplicate = next((row for row in validations if row.rule_code == "VAL-003"), None)
    if duplicate:
        linked = (duplicate.actual_json or {}).get("linked_invoice_id")
    metrics: list[DisplayValue] = []
    allocation = next((item for item in invoice.allocations if item.status.value == "COMMITTED"), None)
    if invoice.total_amount is not None:
        metrics.append(DisplayValue(label="Invoice total", value=f"${invoice.total_amount:,.2f}", format="currency"))
    if po_number:
        metrics.append(DisplayValue(label="Purchase order", value=po_number, format="identifier"))
    if allocation:
        before = (po_remaining or Decimal("0")) + allocation.amount
        metrics.extend([
            DisplayValue(label="Previous available balance", value=f"${before:,.2f}", format="currency"),
            DisplayValue(label="Amount committed", value=f"${allocation.amount:,.2f}", format="currency"),
            DisplayValue(label="Remaining balance", value=f"${po_remaining or Decimal('0'):,.2f}", format="currency"),
        ])
    elif po_remaining is not None:
        metrics.append(DisplayValue(label="Remaining PO authorization", value=f"${po_remaining:,.2f}", format="currency"))
    number = invoice.invoice_number or f"Upload #{invoice.id}"
    if invoice.status == InvoiceStatus.APPROVED:
        summary = "All required controls passed and the PO allocation committed successfully."
        next_action = "Ready for downstream processing. No payment or ERP posting has occurred."
    elif invoice.status == InvoiceStatus.BLOCKED:
        metrics = [item for item in metrics if item.label == "Invoice total"]
        summary = "A definitive control prevents automatic approval."
        next_action = ACTIONS["VAL-003"] if linked else "Review the blocking control before further action."
    elif invoice.status == InvoiceStatus.PROCESSING_FAILED:
        summary = "A technical error prevented processing from completing."
        next_action = "Resolve the reported technical issue, then retry safely."
    elif invoice.status == InvoiceStatus.NEEDS_REVIEW:
        issue_codes = {row.rule_code for row in issues if row.rule_code != "VAL-014"}
        if issue_codes and issue_codes.issubset({"VAL-009", "VAL-012"}):
            summary = f"{len(reasons)} purchase-order authorization issue{'s' if len(reasons) != 1 else ''} require review."
        else:
            summary = f"{len(reasons)} issue{'s' if len(reasons) != 1 else ''} require analyst attention."
        next_action = next((ACTIONS.get(row.rule_code) for row in issues if ACTIONS.get(row.rule_code)), "Review the evidence and resolve each open exception.")
    else:
        summary = "Processing is still in progress."
        next_action = "Wait for the current run to complete."
    return DecisionSummaryOut(headline=f"Invoice {number} - {invoice.status.value.replace('_', ' ')}",
        outcome=invoice.status.value, summary=summary, reasons=reasons, metrics=metrics,
        next_action=next_action, linked_invoice_id=linked)


def resolution_checklist(invoice: Invoice, validations: list[ValidationResult], cases: list[ReviewCase],
                         po: PurchaseOrder | None, detention_policy: ChargePolicy | None) -> list[ResolutionChecklistItemOut]:
    by_code = {row.rule_code: row for row in validations}
    case_by_code = {case.exception_code: case for case in cases}
    active_codes = [row.rule_code for row in validations if row.status in {
        ValidationStatus.FAIL, ValidationStatus.REVIEW_REQUIRED, ValidationStatus.BLOCK, ValidationStatus.TECHNICAL_ERROR
    } and row.rule_code != "VAL-014"]
    # A definitive blocker takes precedence over remediable review findings.
    # The full run remains persisted for audit, but lower-priority findings are
    # not presented as work the analyst should perform on a blocked invoice.
    blocking_codes = [row.rule_code for row in validations
                      if row.status == ValidationStatus.BLOCK and row.rule_code != "VAL-014"]
    if blocking_codes:
        active_codes = blocking_codes
    # Persist all rule results, but expose only actionable root causes. Rules that
    # depend on an identified vendor or selected PO cannot yet be resolved.
    if invoice.vendor_id is None:
        dependent = {"VAL-004", "VAL-006", "VAL-007", "VAL-008", "VAL-009", "VAL-010-EVIDENCE", "VAL-010-ALLOWANCE", "VAL-011", "VAL-012", "VAL-013"}
        active_codes = [code for code in active_codes if code not in dependent]
    elif invoice.matched_po_id is None:
        dependent = {"VAL-006", "VAL-007", "VAL-008", "VAL-009", "VAL-010-EVIDENCE", "VAL-010-ALLOWANCE", "VAL-011", "VAL-012", "VAL-013"}
        active_codes = [code for code in active_codes if code not in dependent]
        required = (by_code.get("VAL-001").actual_json or {}).get("missing_or_ambiguous", []) if by_code.get("VAL-001") else []
        if required == ["confirmed PO match"]:
            active_codes = [code for code in active_codes if code != "VAL-001"]
        vendor = by_code.get("VAL-002")
        vendor_actual = (vendor.actual_json or {}) if vendor else {}
        if (vendor_actual.get("vendor_id") and vendor_actual.get("vendor_status") == "ACTIVE"
                and not vendor_actual.get("identity_conflicts")):
            active_codes = [code for code in active_codes if code != "VAL-002"]
    elif invoice.total_amount is None:
        active_codes = [code for code in active_codes if code != "VAL-012"]
    historical_resolved = [] if blocking_codes else [case.exception_code for case in cases if case.status == ReviewCaseStatus.RESOLVED]
    codes = list(dict.fromkeys([*active_codes, *historical_resolved]))
    items: list[ResolutionChecklistItemOut] = []
    for code in codes:
        row = by_code.get(code)
        case = case_by_code.get(code)
        state = "RESOLVED" if case and case.status == ReviewCaseStatus.RESOLVED and code not in active_codes else "UNRESOLVED"
        actual = authorized = shortfall = None
        supporting_values: list[DisplayValue] = []
        existing_authorization = minimum_new_total = resulting_remaining = None
        action_type = action_label = None
        role = "AP analyst"
        why = row.message if row else (case.summary if case else "This exception was recorded on an earlier validation run.")
        required = ACTIONS.get(code, "Review the supporting evidence and resolve the exception.")
        title = row.rule_name if row else code.replace("VAL-", "Control ")
        if code == "VAL-012":
            expected = row.expected_json or {} if row else {}
            observed = row.actual_json or {} if row else {}
            difference = row.difference_json or {} if row else {}
            available = expected.get("remaining_authorization")
            invoice_total = observed.get("invoice_total") or (f"{invoice.total_amount:.2f}" if invoice.total_amount is not None else None)
            gap = difference.get("authorization_shortfall")
            title = "Purchase order limit exceeded"
            why = f"The invoice amount exceeds the remaining PO authorization{f' by ${Decimal(str(gap)):,.2f}' if gap not in {None, '0.00'} else ''}." if state == "UNRESOLVED" else "The purchase-order capacity exception was resolved and revalidated."
            actual = DisplayValue(label="Invoice amount required", value=f"${Decimal(str(invoice_total)):,.2f}" if invoice_total is not None else "Not provided", format="currency")
            authorized = DisplayValue(label="Available PO authorization", value=f"${Decimal(str(available)):,.2f}" if available is not None else "Not provided", format="currency")
            shortfall = DisplayValue(label="Additional PO capacity required", value=f"${Decimal(str(gap)):,.2f}" if gap is not None else "$0.00", format="currency")
            if po:
                minimum = po.authorized_total + Decimal(str(gap or "0"))
                remaining_after = minimum - Decimal(str(observed.get("committed_total") or "0")) - (invoice.total_amount or Decimal("0"))
                existing_authorization = DisplayValue(label="Existing PO authorized total", value=f"${po.authorized_total:,.2f}", format="currency")
                minimum_new_total = DisplayValue(label="Minimum new PO total", value=f"${minimum:,.2f}", format="currency")
                resulting_remaining = DisplayValue(label="Resulting PO balance after this invoice", value=f"${remaining_after:,.2f}", format="currency")
            required = "Procurement must increase the authorized PO value in the purchasing system, or the supplier must issue a corrected invoice. InvoiceFlow cannot change this authorization."
            role, action_type, action_label = "Procurement (external)", None, None
        elif code == "VAL-010-ALLOWANCE":
            issues = ((row.actual_json or {}).get("issues") or []) if row else []
            issue = issues[0] if issues else {}
            claimed = issue.get("claimed")
            available = issue.get("remaining_allowance")
            gap = issue.get("shortfall")
            if state == "RESOLVED" and detention_policy:
                claimed_line = next((line for line in invoice.lines if line.charge_type == "DETENTION"), None)
                claimed = f"{claimed_line.amount:.2f}" if claimed_line else claimed
                available = f"{detention_policy.max_total_allowance:.2f}"
                gap = "0.00"
            title = "Detention allowance exceeded"
            why = f"The detention charge exceeds the remaining detention allowance{f' by ${Decimal(str(gap)):,.2f}' if gap not in {None, '0.00'} else ''}." if state == "UNRESOLVED" else "The detention allowance exception was resolved and revalidated."
            actual = DisplayValue(label="Detention charge required", value=f"${Decimal(str(claimed)):,.2f}" if claimed is not None else "Not provided", format="currency")
            authorized = DisplayValue(label="Authorized detention allowance", value=f"${Decimal(str(available)):,.2f}" if available is not None else "Not provided", format="currency")
            shortfall = DisplayValue(label="Additional detention allowance required", value=f"${Decimal(str(gap)):,.2f}" if gap is not None else "$0.00", format="currency")
            if detention_policy:
                minimum = detention_policy.max_total_allowance + Decimal(str(gap or "0"))
                existing_authorization = DisplayValue(label="Existing detention allowance total", value=f"${detention_policy.max_total_allowance:,.2f}", format="currency")
                minimum_new_total = DisplayValue(label="Minimum new detention allowance", value=f"${minimum:,.2f}", format="currency")
                resulting_remaining = DisplayValue(label="Resulting detention allowance after this charge", value="$0.00", format="currency")
            required = "Procurement must review the additional detention charge in the purchasing system, or AP must dispute the excess. InvoiceFlow cannot change this allowance."
            role, action_type, action_label = "Procurement (external)", None, None
        elif code == "VAL-009":
            issues = ((row.actual_json or {}).get("issues") or []) if row else []
            issue = issues[0] if issues else {}
            remaining = Decimal(str(issue["remaining_quantity"])) if issue.get("remaining_quantity") is not None else None
            requested = Decimal(str(issue["requested_quantity"])) if issue.get("requested_quantity") is not None else None
            excess = max(Decimal("0"), requested - remaining) if requested is not None and remaining is not None else None
            invoice_line = next((line for line in invoice.lines if line.line_number == issue.get("invoice_line")), None)
            po_line = next((line for line in (po.lines if po else [])
                            if invoice_line and line.id == invoice_line.matched_po_line_id), None)
            unit = po_line.unit_of_measure if po_line else "units"
            def quantity_text(value: Decimal) -> str:
                return format(value.normalize(), "f")
            if po_line and remaining is not None:
                previously_invoiced = po_line.ordered_quantity - remaining
                supporting_values = [
                    DisplayValue(label="Original PO quantity", value=f"{quantity_text(po_line.ordered_quantity)} {unit}", format="quantity"),
                    DisplayValue(label="Previously invoiced", value=f"{quantity_text(previously_invoiced)} {unit}", format="quantity"),
                ]
            title = "Purchase order quantity exceeded"
            why = (f"The invoice requests {quantity_text(requested)} {unit}, but only {quantity_text(remaining)} {unit} remain authorized."
                   if requested is not None and remaining is not None else row.message)
            actual = DisplayValue(label="Invoice requests", value=f"{quantity_text(requested)} {unit}" if requested is not None else "Not provided", format="quantity")
            authorized = DisplayValue(label="Remaining authorized quantity", value=f"{quantity_text(remaining)} {unit}" if remaining is not None else "Not provided", format="quantity")
            shortfall = DisplayValue(label="Excess quantity", value=f"{quantity_text(excess)} {unit}" if excess is not None else "Not provided", format="quantity")
            required = "Procurement must increase the authorized PO-line quantity, or the supplier must issue a corrected invoice. InvoiceFlow cannot change this authorization."
            role, action_type, action_label = "Procurement (external)", None, None
        elif code == "VAL-003":
            title = "Duplicate invoice"
            why = "An active invoice with the same verified supplier and invoice number already exists."
            required = "Open the existing invoice and verify that this upload is the same supplier invoice. Do not create a second payment request."
            action_type, action_label = None, None
        elif code == "VAL-004":
            title = "Confirm the purchase-order match"
            po_match = (invoice.matching_json or {}).get("purchase_order") or {}
            if "PO_NOT_FOUND" in (po_match.get("conflict_codes") or []):
                title = "Correct the purchase-order reference"
                required = "Check the PO number printed on the PDF and restore the complete reference. Do not enter an invoice amount or rate."
                action_type, action_label = "CORRECT_FIELD", "Correct PO reference from PDF"
            else:
                required = "AP must confirm which existing OPEN PO matches the invoice. Confirmation verifies identity only and adds no financial authorization."
                action_type, action_label = "CONFIRM_PO", "Confirm PO match only"
        elif code == "VAL-001":
            title = "Complete missing invoice fields"
            action_type, action_label = "CORRECT_FIELD", "Check missing fields against PDF"
        elif code == "VAL-002":
            title = "Verify the supplier identity"
            action_type, action_label = "CORRECT_FIELD", "Check supplier name against PDF"
        elif code == "VAL-005":
            title = "Invoice totals and line amounts"
            action_type, action_label = "CORRECT_FIELD", "Check invoice totals against PDF"
        elif code == "VAL-007":
            action_type, action_label = "CORRECT_FIELD", "Review PO line details"
        elif code == "VAL-008":
            action_type, action_label = "CORRECT_FIELD", "Check extracted rate"
        elif code == "VAL-009":
            action_type, action_label = "CORRECT_FIELD", "Check extracted quantity"
        items.append(ResolutionChecklistItemOut(code=code, title=title, state=state, why=why,
            actual=actual, authorized=authorized, shortfall=shortfall, supporting_values=supporting_values,
            required_action=required,
            existing_authorization=existing_authorization, minimum_new_total=minimum_new_total,
            resulting_remaining=resulting_remaining,
            responsible_role=role, action_type=action_type if state == "UNRESOLVED" else None,
            action_label=action_label if state == "UNRESOLVED" else None,
            review_case_id=case.id if case else None, resolved_at=case.resolved_at if case else None))
    extraction_codes = {"VAL-001", "VAL-002", "VAL-005"}
    extraction_items = [item for item in items if item.state == "UNRESOLVED" and item.code in extraction_codes]
    if any(item.code in {"VAL-001", "VAL-002"} for item in extraction_items):
        fields: list[str] = []
        required_row = by_code.get("VAL-001")
        for field in ((required_row.actual_json or {}).get("missing_or_ambiguous", []) if required_row else []):
            # A missing PO is resolved in the matching workflow, not by inventing
            # extracted data. It still belongs in the analyst's affected-field
            # summary so it does not disappear while vendor identity is unresolved.
            fields.append("purchase order reference" if field == "confirmed PO match" else str(field))
        arithmetic = by_code.get("VAL-005")
        for issue in ((arithmetic.difference_json or {}).get("issues", []) if arithmetic else []):
            if issue.get("field"):
                fields.append(str(issue["field"]))
        if "VAL-002" in {item.code for item in extraction_items} and "supplier identity" not in fields:
            fields.append("supplier identity")
        labels = {"vendor identity": "Supplier name", "supplier identity": "Supplier name",
                  "purchase order reference": "Purchase order reference",
                  "invoice total": "Total", "line items": "Line items", "subtotal": "Subtotal",
                  "tax": "Tax", "total": "Total", "currency": "Currency",
                  "invoice number": "Invoice number", "invoice date": "Invoice date"}
        details = list(dict.fromkeys(labels.get(field, field.replace("_", " ").title()) for field in fields))
        vendor_match = (invoice.matching_json or {}).get("vendor") or {}
        vendor_candidates = vendor_match.get("candidates") or []
        candidate_name = vendor_candidates[0].get("legal_name") if vendor_candidates else None
        if "VAL-002" in {item.code for item in extraction_items} and candidate_name:
            why = (f'“{invoice.vendor_name_raw}” is not an exact approved supplier name or alias. '
                   f'The closest master-data candidate is “{candidate_name}”; automatic fuzzy matching is not permitted.')
        else:
            why = "One or more values could not be reliably extracted from the invoice."
        items = [item for item in items if item not in extraction_items]
        items.append(ResolutionChecklistItemOut(code="EXTRACTION_ISSUES", title="Extraction needs correction",
            state="UNRESOLVED", why=why,
            actual=None, authorized=None, shortfall=None,
            required_action="Compare the highlighted fields with the PDF, correct only the values shown on the document, then save once to revalidate the invoice.",
            responsible_role="AP analyst", action_type="CORRECT_FIELD", action_label="Edit extracted information",
            details=details))
    return sorted(items, key=lambda item: (item.state == "RESOLVED", item.code))


def authorization_history(invoice: Invoice, events: list[InvoiceEvent], po: PurchaseOrder | None) -> list[AuthorizationHistoryOut]:
    relevant = {"PO_CONFIRMED", "FIELD_CORRECTED", "AUTHORIZATION_AMENDED", "REQUEST_EVIDENCE",
                "REQUEST_CORRECTED_INVOICE", "MARK_DISPUTED", "REVALIDATION", "DECISION_COMPLETE"}
    output: list[AuthorizationHistoryOut] = []
    for event in events:
        if event.stage not in relevant:
            continue
        details = event.details_json or {}
        changes: list[DisplayValue] = []
        for key in ("po_total_before", "po_total_after", "allowance_before", "allowance_after",
                    "before", "after", "approval_reference", "business_outcome"):
            if key in details:
                formatted, kind = _format(key, details[key])
                changes.append(DisplayValue(label=_human(key), value=formatted, format=kind))
        affected = f"PO {po.po_number}" if event.stage in {"PO_CONFIRMED", "AUTHORIZATION_AMENDED"} and po else f"Invoice {invoice.invoice_number or invoice.id}"
        output.append(AuthorizationHistoryOut(id=event.id, action=event.stage.replace("_", " ").title(),
            actor=event.actor_name or "InvoiceFlow system", actor_role=event.actor_type.value.replace("_", " ").title(),
            timestamp=event.created_at, context=event.event_type.replace("_", " ").title(),
            affected_record=affected, changes=changes, justification=details.get("reason"),
            resulting_outcome=details.get("business_outcome")))
    return sorted(output, key=lambda item: item.timestamp, reverse=True)
