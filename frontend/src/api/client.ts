import type { PurchaseOrder, Vendor } from '../types/catalog'
import type { AuditRecord, Dashboard, InvoiceDetail, InvoiceSummary, ReviewCase, Run, UploadResult } from '../types/invoices'
export const baseUrl = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api'
async function parseError(response: Response) { try { const body = await response.json(); return body.detail?.message ?? body.detail?.code ?? `Request failed (${response.status})` } catch { return `Request failed (${response.status})` } }
async function get<T>(path: string): Promise<T> { const response = await fetch(`${baseUrl}${path}`); if (!response.ok) throw new Error(await parseError(response)); return response.json() }
export const fetchVendors = () => get<Vendor[]>('/vendors')
export const fetchPurchaseOrders = () => get<PurchaseOrder[]>('/purchase-orders')
export const fetchInvoices = (query = '') => get<InvoiceSummary[]>(`/invoices${query ? `?${query}` : ''}`)
export const fetchInvoice = (id: number) => get<InvoiceDetail>(`/invoices/${id}`)
export const fetchRun = (id: number) => get<Run>(`/runs/${id}`)
export const documentUrl = (id: number) => `${baseUrl}/invoices/${id}/document`
export const fetchDashboard = () => get<Dashboard>('/dashboard/summary')
export const fetchReviews = (category = '') => get<ReviewCase[]>(`/reviews${category ? `?category=${encodeURIComponent(category)}` : ''}`)
export const fetchAudit = () => get<AuditRecord[]>('/audit')
export const fetchPODetail = (id: number) => get<Record<string, unknown>>(`/purchase-orders/${id}/detail`)
export async function uploadInvoice(file: File): Promise<UploadResult> { const form = new FormData(); form.append('file', file); const response = await fetch(`${baseUrl}/invoices/upload`, { method: 'POST', body: form }); if (!response.ok) throw new Error(await parseError(response)); return response.json() }
async function post<T>(path: string, body: unknown, username: string, password: string): Promise<T> { const response = await fetch(`${baseUrl}${path}`, { method: 'POST', headers: {'Content-Type':'application/json', Authorization:`Basic ${btoa(`${username}:${password}`)}`}, body: JSON.stringify(body) }); if (!response.ok) throw new Error(await parseError(response)); return response.json() }
export const confirmPO = (invoiceId:number, payload:unknown, user:string, password:string) => post<UploadResult>(`/invoices/${invoiceId}/review/confirm-po`, payload, user, password)
export const correctField = (invoiceId:number, payload:unknown, user:string, password:string) => post<UploadResult>(`/invoices/${invoiceId}/review/correct-field`, payload, user, password)
export const correctFields = (invoiceId:number, payload:unknown, user:string, password:string) => post<UploadResult>(`/invoices/${invoiceId}/review/correct-fields`, payload, user, password)

