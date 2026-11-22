import { BrowserRouter, Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import DashboardPage from './pages/DashboardPage'
import InboxPage from './pages/InboxPage'
import InvoiceDetailPage from './pages/InvoiceDetailPage'
import ReviewsPage from './pages/ReviewsPage'
import PurchaseOrdersPage from './pages/PurchaseOrdersPage'
import AuditPage from './pages/AuditPage'

export default function App() { return <BrowserRouter><Routes><Route element={<Layout/>}><Route index element={<DashboardPage/>}/><Route path="invoices" element={<InboxPage/>}/><Route path="invoices/:id" element={<InvoiceDetailPage/>}/><Route path="reviews" element={<ReviewsPage/>}/><Route path="purchase-orders" element={<PurchaseOrdersPage/>}/><Route path="audit" element={<AuditPage/>}/></Route></Routes></BrowserRouter> }
