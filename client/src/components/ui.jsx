import { stageIndex, STAGES } from '../lib.js'

export function Chip({ tone, children }) {
  return (
    <span className="chip" data-tone={tone}>
      {children}
    </span>
  )
}

const STATUS_TONE = { Open: 'accent', Pending: 'warn', Resolved: 'ok', Closed: '' }
export function StatusChip({ status }) {
  if (!status) return <span className="muted">{'—'}</span>
  return <Chip tone={STATUS_TONE[status]}>{status}</Chip>
}

/** Six segments, one per workflow step: done, current, not reached. */
export function Progress({ stage }) {
  const at = stageIndex(stage)
  return (
    <span className="progress" role="img" aria-label={stage === 'Done' ? 'All six steps complete' : `Step ${at + 1} of 6: ${stage}`}>
      {STAGES.map((name, i) => (
        <i key={name} data-s={i < at ? 'done' : i === at ? 'now' : 'todo'} />
      ))}
    </span>
  )
}

const DOC_TONE = { url: 'ok', waived: 'ok', junk: 'bad', empty: '' }
const DOC_LABEL = { url: 'Link', waived: 'Waived', junk: 'Not a link', empty: 'Missing' }
export function DocChip({ state }) {
  return <Chip tone={DOC_TONE[state]}>{DOC_LABEL[state] ?? state}</Chip>
}

export function Empty({ title, children }) {
  return (
    <div className="empty" role="status">
      <strong>{title}</strong>
      <span>{children}</span>
    </div>
  )
}

export function Skeleton({ rows = 8 }) {
  return (
    <div aria-hidden="true" style={{ display: 'grid', gap: '0.6rem', padding: '1rem' }}>
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="skeleton" style={{ height: '2.4rem', opacity: 1 - i * 0.08 }} />
      ))}
    </div>
  )
}
