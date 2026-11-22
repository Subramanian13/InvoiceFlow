/* eslint-disable react-refresh/only-export-components */
import type { ReactNode } from 'react'

export const money = new Intl.NumberFormat('en-US', {style:'currency', currency:'USD'})
export function StatusChip({status}:{status:string}) { const label = status === 'REVIEW_REQUIRED' ? 'NEEDS REVIEW' : status === 'BLOCK' ? 'BLOCKED' : status.replaceAll('_',' '); return <span className={`status-chip status-${status.toLowerCase()}`}>{label}</span> }
export function PageTitle({eyebrow,title,description,action}:{eyebrow:string,title:string,description:string,action?:ReactNode}) { return <div className="page-title"><div><p className="eyebrow">{eyebrow}</p><h1>{title}</h1><p>{description}</p></div>{action}</div> }
export function Empty({children}:{children:ReactNode}) { return <div className="empty-state">{children}</div> }
export function ErrorNotice({message}:{message:string}) { return message ? <div className="notice error" role="alert">{message}</div> : null }
