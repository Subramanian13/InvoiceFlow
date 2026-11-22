import type { InvoiceDetail } from '../types/invoices'

export function visibleValidationResults(detail: InvoiceDetail) {
  if (detail.status === 'BLOCKED') return detail.validation_results.filter(rule => rule.status === 'BLOCK' && rule.rule_code !== 'VAL-014')
  if (detail.status === 'PROCESSING_FAILED') return detail.validation_results.filter(rule => rule.status === 'TECHNICAL_ERROR')
  return detail.validation_results
}

export function matchedPurchaseOrderLabel(detail: InvoiceDetail) {
  const match = detail.matching?.purchase_order
  const selected = match?.candidates?.find(candidate => candidate.po_id === match.matched_po_id)
  return selected?.po_number ?? detail.po_reference ?? 'Not provided'
}

export function shouldShowPOCandidates(detail: InvoiceDetail) {
  return !detail.matching?.purchase_order?.matched_po_id
}
