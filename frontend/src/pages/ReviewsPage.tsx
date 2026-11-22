import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { fetchReviews } from '../api/client'
import type { ReviewCase } from '../types/invoices'
import { ErrorNotice, money, PageTitle, StatusChip } from '../components/Common'

const filters = [['','All'],['PO','PO matching'],['FINANCIAL','Financial authorization'],['DUPLICATE','Duplicate'],['DOCUMENT','Document issues'],['CHARGE','Charge validation']] as const
function inCategory(item: ReviewCase, filter: string) {
  const values = item.categories.join(' ')
  if (!filter) return true
  if (filter === 'PO') return /PO_LINE|MISSING_OR_AMBIGUOUS_PO/.test(values)
  if (filter === 'FINANCIAL') return /CAPACITY|QUANTITY|RATE|CURRENCY/.test(values)
  if (filter === 'DUPLICATE') return values.includes('DUPLICATE')
  if (filter === 'DOCUMENT') return /MISSING_INVOICE|ARITHMETIC|VENDOR/.test(values)
  return /DETENTION|UNSUPPORTED_CHARGE/.test(values)
}

export default function ReviewsPage() {
  const [items,setItems] = useState<ReviewCase[]>([]), [filter,setFilter] = useState(''), [error,setError] = useState('')
  useEffect(() => { fetchReviews().then(setItems).catch(e => setError(e.message)) }, [])
  const visible = useMemo(() => items.filter(item => inCategory(item,filter)), [items,filter])
  return <main className="route-page">
    <PageTitle eyebrow="EXCEPTION WORKSPACE" title="Invoices requiring attention" description="Review invoices that could not be automatically approved."/>
    <ErrorNotice message={error}/>
    <section className="panel"><div className="filterbar"><b>{visible.length} invoice{visible.length === 1 ? '' : 's'} requiring review</b><select aria-label="Exception category" value={filter} onChange={e => setFilter(e.target.value)}>{filters.map(([value,label]) => <option value={value} key={value}>{label}</option>)}</select></div>
      <div className="review-list invoice-review-list">{visible.map(item => <article key={item.invoice_id}><div><StatusChip status={item.status}/><span>{item.issue_count} issue{item.issue_count === 1 ? '' : 's'}</span></div><h3>{item.invoice_number ?? `Upload #${item.invoice_id}`}</h3><p className="review-supplier">{item.vendor_name} · {item.po_reference ?? 'PO not matched'} · {item.amount ? money.format(Number(item.amount)) : 'Amount not extracted'}</p><ul>{item.issues.map(issue => <li key={issue}>{issue}</li>)}</ul><footer><span>Processed {new Date(item.created_at).toLocaleString()}</span><Link to={`/invoices/${item.invoice_id}`}>View invoice</Link></footer></article>)}{!visible.length && <p className="empty-state">No invoices currently require review.</p>}</div>
    </section>
  </main>
}
