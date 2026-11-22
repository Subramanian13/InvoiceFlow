import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../App'
import ValidationEvidence from '../components/ValidationEvidence'
import { ResolutionChecklist } from '../pages/InvoiceDetailPage'
import type { InvoiceDetail } from '../types/invoices'
import { matchedPurchaseOrderLabel, shouldShowPOCandidates, visibleValidationResults } from '../utils/invoicePresentation'

const json = (body: unknown) => Promise.resolve(new Response(JSON.stringify(body), {status: 200, headers: {'Content-Type':'application/json'}}))

describe('M2 enterprise UI', () => {
  beforeEach(() => { vi.restoreAllMocks() })

  it('shows only decisive blockers for a blocked invoice', () => {
    const validation = (id:number,status:string,code:string) => ({id,rule_code:code,rule_name:code,status,severity:'CONTROL',message:code,expected_json:null,actual_json:null,difference_json:null,evidence_json:null,required:true,created_at:new Date().toISOString()})
    const detail = {status:'BLOCKED',validation_results:[
      validation(1,'BLOCK','VAL-003'), validation(2,'REVIEW_REQUIRED','VAL-009'), validation(3,'REVIEW_REQUIRED','VAL-012'), validation(4,'BLOCK','VAL-014'),
    ]} as unknown as InvoiceDetail
    expect(visibleValidationResults(detail).map(rule => rule.rule_code)).toEqual(['VAL-003'])
  })

  it('shows the analyst-confirmed PO and removes stale candidate prompts', () => {
    const detail = {po_reference:null,matching:{purchase_order:{matched_po_id:10,match_method:'ANALYST_CONFIRMED_PO',automatic_match_permitted:true,evidence:[],conflict_codes:[],candidates:[
      {po_id:11,po_number:'PO-20011'},{po_id:10,po_number:'PO-20010'},
    ]}}} as unknown as InvoiceDetail
    expect(matchedPurchaseOrderLabel(detail)).toBe('PO-20010')
    expect(shouldShowPOCandidates(detail)).toBe(false)
  })

  it('navigates directly to the restored purchase-order and supplier screen', async () => {
    window.history.pushState({}, '', '/purchase-orders')
    vi.spyOn(globalThis, 'fetch').mockImplementation(input => {
      const url = String(input)
      if (url.endsWith('/purchase-orders')) return json([])
      if (url.endsWith('/vendors')) return json([])
      return json([])
    })
    render(<App/>)
    expect(await screen.findByRole('heading', {name:'Purchase orders and suppliers'})).toBeVisible()
    expect(screen.getByText('Approved supplier master')).toBeVisible()
    expect(screen.getByRole('link', {name:/Dashboard/})).toBeVisible()
    expect(screen.getByRole('link', {name:/Review queue/})).toBeVisible()
    expect(screen.getByRole('link', {name:/Audit trail/})).toBeVisible()
  })

  it('shows an honest empty invoice inbox state', async () => {
    window.history.pushState({}, '', '/invoices')
    vi.spyOn(globalThis, 'fetch').mockImplementation(() => json([]))
    render(<App/>)
    expect(await screen.findByText('No invoices have been uploaded.')).toBeVisible()
  })

  it('renders human-readable evidence without exposing technical JSON', () => {
    render(<ValidationEvidence rule={{id:1,rule_code:'VAL-012',rule_name:'PO financial capacity',status:'REVIEW_REQUIRED',severity:'CONTROL',message:'The invoice exceeds authorization.',expected_json:null,actual_json:null,difference_json:null,evidence_json:null,required:true,created_at:new Date().toISOString(),presentation:{group:'Financial checks',outcome:'REVIEW_REQUIRED',explanation:'The invoice exceeds the remaining authorized balance by $300.',expected:[{label:'Available authorization',value:'$2,300.00',format:'currency'}],actual:[{label:'Invoice amount',value:'$2,600.00',format:'currency'}],difference:[{label:'Shortfall',value:'$300.00',format:'currency'}],evidence:[],recommended_action:'Obtain an authorized PO amendment.',technical_details:{authorization_shortfall:'300.00'}}}}/>)
    expect(screen.getByText('$2,300.00')).toBeVisible()
    expect(screen.getByText('$2,600.00')).toBeVisible()
    expect(screen.getByText('$300.00')).toBeVisible()
    expect(screen.getByText('Obtain an authorized PO amendment.')).toBeVisible()
    expect(screen.queryByText(/authorization_shortfall/)).not.toBeInTheDocument()
    expect(screen.queryByText('Technical details')).not.toBeInTheDocument()
  })

  it('explains independent authorization issues without financial amendment controls', () => {
    const value = (label:string, amount:string) => ({label,value:amount,format:'currency'})
    const base = {state:'UNRESOLVED',actual:value('Required','$2,600.00'),authorized:value('Available','$2,300.00'),shortfall:value('Shortfall','$300.00'),existing_authorization:value('Existing','$2,300.00'),minimum_new_total:value('New total','$2,600.00'),resulting_remaining:value('Remaining','$0.00'),responsible_role:'Procurement',review_case_id:1,resolved_at:null}
    const detail = {resolution_checklist:[
      {...base,code:'VAL-012',title:'Purchase order limit exceeded',why:'PO capacity is short.',required_action:'Procurement must review this in the purchasing system.',action_type:null,action_label:null},
      {...base,code:'VAL-010-ALLOWANCE',title:'Detention allowance exceeded',why:'Detention allowance is short.',required_action:'Procurement must review this externally.',action_type:null,action_label:null},
    ]} as unknown as InvoiceDetail
    render(<ResolutionChecklist detail={detail}/>)
    expect(screen.getByText('Review the issues preventing automatic approval')).toBeVisible()
    expect(screen.getByText('Purchase order limit exceeded')).toBeVisible()
    expect(screen.getByText('Detention allowance exceeded')).toBeVisible()
    expect(screen.queryByRole('button',{name:/Amend PO/})).not.toBeInTheDocument()
    expect(screen.queryByRole('button',{name:/Amend detention/})).not.toBeInTheDocument()
  })
})
