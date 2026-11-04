import { STAGES, stageIndex, stepLabel, STATUS_TEXT } from '../lib.js'

const STATUS_TONE = { Open: 'blue', Pending: 'amber', Resolved: 'green', Closed: 'grey' }
export function StatusChip({ status }) {
  if (!status) return null
  return (
    <span className="chip" data-tone={STATUS_TONE[status] ?? 'grey'} title={STATUS_TEXT[status] ?? status}>
      {status}
    </span>
  )
}

/** Six dots, one per step: done, current, still to come. */
export function StepDots({ stage, withLabel = true }) {
  const at = stageIndex(stage)
  return (
    <span className="steps-inline">
      <span className="dots" role="img" aria-label={stepLabel(stage)}>
        {STAGES.map((name, i) => (
          <i key={name} data-s={i < at ? 'done' : i === at ? 'now' : 'todo'} />
        ))}
      </span>
      {withLabel && <span className="steps-label">{stepLabel(stage)}</span>}
    </span>
  )
}

const DOC_TEXT = {
  url: { tone: 'green', label: 'Link added' },
  waived: { tone: 'green', label: 'Not needed' },
  junk: { tone: 'red', label: 'Not a link' },
  empty: { tone: 'grey', label: 'Missing' }
}
export function DocChip({ state }) {
  const d = DOC_TEXT[state] ?? DOC_TEXT.empty
  return (
    <span className="chip" data-tone={d.tone}>
      {d.label}
    </span>
  )
}

export function Empty({ title, children, action }) {
  return (
    <div className="empty" role="status">
      <strong>{title}</strong>
      {children && <p>{children}</p>}
      {action}
    </div>
  )
}

export function Skeleton({ rows = 5 }) {
  return (
    <div className="skeletons" aria-hidden="true">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="skeleton" />
      ))}
    </div>
  )
}

export function Notice({ tone = 'blue', title, children, icon }) {
  return (
    <div className="notice" data-tone={tone} role={tone === 'red' ? 'alert' : 'status'}>
      {icon}
      <div>
        {title && <strong>{title}</strong>}
        {children && <div>{children}</div>}
      </div>
    </div>
  )
}
