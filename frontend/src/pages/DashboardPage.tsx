import { useEffect, useState, type ReactNode } from 'react'
import { CheckCircle2, CircleDollarSign, Files, ShieldAlert, UploadCloud } from 'lucide-react'
import { Link } from 'react-router-dom'
import { fetchDashboard, fetchInvoices, fetchReviews } from '../api/client'
import type { Dashboard, InvoiceSummary, ReviewCase } from '../types/invoices'
import { ErrorNotice, money, PageTitle, StatusChip } from '../components/Common'

export default function DashboardPage() {
  const [summary,setSummary] = useState<Dashboard|null>(null), [invoices,setInvoices] = useState<InvoiceSummary[]>([]), [reviews,setReviews] = useState<ReviewCase[]>([]), [error,setError] = useState('')
  useEffect(() => { Promise.all([fetchDashboard(),fetchInvoices(),fetchReviews()]).then(([a,b,c]) => { setSummary(a); setInvoices(b.slice(0,6)); setReviews(c.slice(0,5)) }).catch(e => setError(e.message)) }, [])
  return <main className="route-page">
    <PageTitle eyebrow="OPERATIONS OVERVIEW" title="Accounts payable dashboard" description="Monitor invoice processing, approvals, and exceptions." action={<Link className="primary-action" to="/invoices"><UploadCloud/>Upload invoice</Link>}/>
    <ErrorNotice message={error}/>
    <div className="kpi-grid"><KPI icon={<Files/>} label="Invoices processed" value={summary?.total_invoices ?? '—'}/><KPI icon={<CheckCircle2/>} label="Approved" value={summary?.approved ?? '—'}/><KPI icon={<ShieldAlert/>} label="Needs review / blocked" value={summary ? summary.needs_review + summary.blocked : '—'}/><KPI icon={<CircleDollarSign/>} label="Approved value" value={summary ? money.format(Number(summary.total_approved_value)) : '—'}/></div>
    <div className="dashboard-grid"><section className="panel"><div className="panel-heading"><div><p className="eyebrow">RECENT ACTIVITY</p><h2>Recent invoices</h2></div><Link to="/invoices">View inbox</Link></div><InvoiceTable invoices={invoices}/></section>
      <section className="panel"><div className="panel-heading"><div><p className="eyebrow">ACTION REQUIRED</p><h2>Open exceptions</h2></div><Link to="/reviews">Review queue</Link></div><div className="attention-list">{reviews.length ? reviews.map(item => <Link to={`/invoices/${item.invoice_id}`} key={item.invoice_id}><StatusChip status={item.status}/><div><b>{item.invoice_number ?? `Upload #${item.invoice_id}`}</b><span>{item.vendor_name} · {item.issues[0] ?? 'Review required'}{item.amount ? ` · ${money.format(Number(item.amount))}` : ''}</span></div></Link>) : <p className="empty-state">No invoices currently require review.</p>}</div></section></div>
    <section className="panel exception-breakdown"><div className="panel-heading"><div><p className="eyebrow">OPEN EXCEPTIONS</p><h2>Exception breakdown</h2></div></div><div>{summary && Object.keys(summary.exception_breakdown).length ? Object.entries(summary.exception_breakdown).map(([key,value]) => <article key={key}><span>{key}</span><strong>{value}</strong></article>) : <p className="empty-state">No open exception categories.</p>}</div></section>
  </main>
}

function KPI({icon,label,value}:{icon:ReactNode;label:string;value:string|number}) { return <article className="kpi-card"><span>{icon}</span><small>{label}</small><strong>{value}</strong></article> }
export function InvoiceTable({invoices}:{invoices:InvoiceSummary[]}) { return invoices.length ? <div className="table-wrap"><table><thead><tr><th>Invoice</th><th>Supplier</th><th>Purchase order</th><th>Amount</th><th>Status</th><th>Processed date</th></tr></thead><tbody>{invoices.map(item => <tr key={item.id} className="clickable"><td><Link to={`/invoices/${item.id}`}><b>{item.invoice_number ?? `Upload #${item.id}`}</b></Link></td><td>{item.vendor_name}</td><td>{item.po_reference ?? '—'}</td><td>{item.total_amount ? money.format(Number(item.total_amount)) : 'Not extracted'}</td><td><StatusChip status={item.status}/></td><td>{new Date(item.created_at).toLocaleString()}</td></tr>)}</tbody></table></div> : <p className="empty-state">No invoices have been uploaded.</p> }
