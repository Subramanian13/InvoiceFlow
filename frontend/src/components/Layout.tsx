import { FileCheck2, Files, LayoutDashboard, ListChecks, ScrollText, ShoppingCart } from 'lucide-react'
import { NavLink, Outlet } from 'react-router-dom'

const links = [
  ['/', 'Dashboard', LayoutDashboard], ['/invoices', 'Invoice inbox', Files],
  ['/reviews', 'Review queue', ListChecks], ['/purchase-orders', 'Purchase orders', ShoppingCart],
  ['/audit', 'Audit trail', ScrollText],
] as const

export default function Layout() {
  return <div className="enterprise-shell"><aside className="sidebar"><div className="side-brand"><span><FileCheck2/></span><div><strong>InvoiceFlow</strong><small>GlobalFreight AP</small></div></div><nav aria-label="Primary navigation">{links.map(([to,label,Icon]) => <NavLink key={to} to={to} end={to === '/'}><Icon/>{label}</NavLink>)}</nav><div className="side-foot"><b>Local Demo</b><span>Invoice operations</span></div></aside><div className="page-shell"><header className="topbar"><div><b>Invoice operations</b><span>AI extracts. Deterministic controls decide.</span></div><span className="environment">LOCAL DEMO</span></header><Outlet/></div></div>
}
