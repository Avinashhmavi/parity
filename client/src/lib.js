// Pure helpers, kept free of React so they can be unit-tested.

export const STAGES = [
  'Assign Manager',
  'Assign Engineer',
  'Purchase Order',
  'Delivery Note',
  'Work Report',
  'Invoice'
]

const number = new Intl.NumberFormat()
export const formatNumber = n => number.format(n ?? 0)

const dateTime = new Intl.DateTimeFormat(undefined, {
  day: 'numeric',
  month: 'short',
  hour: 'numeric',
  minute: '2-digit'
})

export function formatTime(value) {
  if (!value) return '—'
  const d = new Date(value)
  return Number.isNaN(d.getTime()) ? String(value) : dateTime.format(d)
}

const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' })
export function relativeTime(value, now = Date.now()) {
  const d = new Date(value)
  if (!value || Number.isNaN(d.getTime())) return ''
  const seconds = Math.round((d.getTime() - now) / 1000)
  const abs = Math.abs(seconds)
  if (abs < 45) return rtf.format(0, 'second')
  if (abs < 3600) return rtf.format(Math.round(seconds / 60), 'minute')
  if (abs < 86400) return rtf.format(Math.round(seconds / 3600), 'hour')
  return rtf.format(Math.round(seconds / 86400), 'day')
}

/** Index of the stage in the six-step flow; 6 means Done. */
export function stageIndex(stage) {
  if (stage === 'Done') return STAGES.length
  const i = STAGES.indexOf(stage)
  return i < 0 ? 0 : i
}

/** Which of the editable fields differ between a draft and the saved ticket. */
export function changedFields(saved, draft) {
  const out = {}
  for (const key of Object.keys(draft)) {
    if ((saved[key] ?? '') !== (draft[key] ?? '')) out[key] = draft[key]
  }
  return out
}

export function draftFrom(ticket) {
  return {
    status: ticket.status ?? '',
    engineer: ticket.engineer ?? '',
    manager: ticket.manager ?? '',
    purchase_order: ticket.documents.purchase_order.value,
    delivery_note: ticket.documents.delivery_note.value,
    work_report: ticket.documents.work_report.value,
    invoice: ticket.documents.invoice.value
  }
}

/** Read URL state from a query string, with defaults. */
export function parseQuery(search) {
  const p = new URLSearchParams(search)
  return {
    view: p.get('view') || 'board',
    q: p.get('q') || '',
    stage: p.get('stage') || '',
    owner: p.get('owner') || '',
    status: p.get('status') || '',
    flagged: p.get('flagged') === '1',
    page: Math.max(1, Number(p.get('page')) || 1),
    ticket: p.get('ticket') ? Number(p.get('ticket')) : null,
    tab: p.get('tab') || 'conflicts'
  }
}

export function buildQuery(state) {
  const p = new URLSearchParams()
  if (state.view && state.view !== 'board') p.set('view', state.view)
  if (state.q) p.set('q', state.q)
  if (state.stage) p.set('stage', state.stage)
  if (state.owner) p.set('owner', state.owner)
  if (state.status) p.set('status', state.status)
  if (state.flagged) p.set('flagged', '1')
  if (state.page > 1) p.set('page', String(state.page))
  if (state.ticket) p.set('ticket', String(state.ticket))
  if (state.view === 'activity' && state.tab !== 'conflicts') p.set('tab', state.tab)
  const s = p.toString()
  return s ? `?${s}` : ''
}
