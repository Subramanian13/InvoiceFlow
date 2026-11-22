import type { ValidationResult } from '../types/invoices'
import { StatusChip } from './Common'

export default function ValidationEvidence({rule}:{rule:ValidationResult & {presentation?: import('../types/invoices').ValidationPresentation | null}}) {
  const p = rule.presentation
  if (!p) return null
  const sections = [['Expected',p.expected],['Actual',p.actual],['Difference',p.difference],['Evidence',p.evidence]] as const
  return <article className="validation-card"><div className="validation-head"><div><small>{rule.rule_code}</small><h4>{rule.rule_name}</h4></div><StatusChip status={p.outcome}/></div><p>{p.explanation}</p><div className="evidence-values">{sections.map(([label,items]) => items.length > 0 && <section key={label}><b>{label}</b>{items.map((item,index) => <div key={`${item.label}-${index}`}><span>{item.label}</span><strong className={`value-${item.format}`}>{item.value}</strong></div>)}</section>)}</div>{p.recommended_action && <div className="recommended"><b>Required action</b><span>{p.recommended_action}</span></div>}</article>
}
