// Pure helpers, kept free of React so they can be unit-tested.
// Most of the "plain English" of the whole UI lives here.

export const STAGES = ['Assign Manager', 'Assign Engineer', 'Purchase Order', 'Delivery Note', 'Work Report', 'Invoice']

// How each step is described to someone who has never seen the system.
export const STEP_TEXT = {
  'Assign Manager': {
    name: 'Assign a manager',
    todo: 'assign a manager',
    done: 'A manager is in charge',
    about: 'The front desk gives every job a manager, so someone is responsible.'
  },
  'Assign Engineer': {
    name: 'Assign an engineer',
    todo: 'choose an engineer',
    done: 'An engineer is assigned',
    about: 'The manager picks which engineer goes to the store.'
  },
  'Purchase Order': {
    name: 'Purchase Order',
    todo: "get the customer's Purchase Order",
    done: 'Purchase Order received',
    about: 'The customer approves the job and the budget in writing.'
  },
  'Delivery Note': {
    name: 'Delivery Note',
    todo: 'add the Delivery Note',
    done: 'Delivery Note received',
    about: 'Proof that parts reached the store, or a note that nothing was delivered.',
    canSkip: true
  },
  'Work Report': {
    name: 'Work Report',
    todo: 'upload the Work Report',
    done: 'Work Report received',
    about: 'The engineer reports that the work is finished.'
  },
  Invoice: {
    name: 'Invoice',
    todo: 'add the Invoice',
    done: 'Invoice sent',
    about: 'The bill is sent to the customer, or marked as not needed.',
    canSkip: true
  }
}

export const STATUS_TEXT = {
  Open: 'Open: work still to be done',
  Pending: 'Pending: waiting on the customer',
  Resolved: 'Resolved: the work is done',
  Closed: 'Closed: everything is finished'
}

export const ROLE_TEXT = {
  Coordinator: { title: 'Front desk', about: 'Make sure every new job has a manager.' },
  Manager: { title: 'Managers', about: 'Choose the engineer and get the customer’s Purchase Order.' },
  Engineer: { title: 'Engineers', about: 'Visit the store and upload the Work Report.' },
  Finance: { title: 'Finance', about: 'Provide Delivery Notes and send Invoices.' },
  Unlisted: { title: 'Not on the team list', about: 'Names typed on a job that don’t match anyone on the team.' }
}

const number = new Intl.NumberFormat()
export const formatNumber = n => number.format(n ?? 0)

const dateTime = new Intl.DateTimeFormat(undefined, { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' })
const dateOnly = new Intl.DateTimeFormat(undefined, { day: 'numeric', month: 'short', year: 'numeric' })

export function formatTime(value) {
  if (!value) return '—'
  const d = new Date(value)
  return Number.isNaN(d.getTime()) ? String(value) : dateTime.format(d)
}

export function formatDate(value) {
  if (!value) return '—'
  const d = new Date(value)
  return Number.isNaN(d.getTime()) ? String(value) : dateOnly.format(d)
}

const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' })
export function relativeTime(value, now = Date.now()) {
  const d = new Date(value)
  if (!value || Number.isNaN(d.getTime())) return ''
  const seconds = Math.round((d.getTime() - now) / 1000)
  const abs = Math.abs(seconds)
  if (abs < 45) return 'just now'
  if (abs < 3600) return rtf.format(Math.round(seconds / 60), 'minute')
  if (abs < 86400) return rtf.format(Math.round(seconds / 3600), 'hour')
  return rtf.format(Math.round(seconds / 86400), 'day')
}

/** 0-based position of the stage in the six steps; 6 means finished. */
export function stageIndex(stage) {
  if (stage === 'Done') return STAGES.length
  const i = STAGES.indexOf(stage)
  return i < 0 ? 0 : i
}

/** "Step 3 of 6", or "Finished". */
export function stepLabel(stage) {
  return stage === 'Done' ? 'Finished' : `Step ${stageIndex(stage) + 1} of ${STAGES.length}`
}

/** One sentence saying what happens next and whose move it is. */
export function nextAction(job) {
  if (job.stage === 'Done') return 'Nothing left to do. All six steps are finished.'
  const who = job.actionOwner || 'Someone on the team'
  const step = STEP_TEXT[job.stage]
  return `${who} needs to ${step ? step.todo : job.stage.toLowerCase()}.`
}

/**
 * Turns one of the system's short problem flags into a title and a "what to do".
 * Unknown flags fall back to their own text so nothing is ever hidden.
 */
export function explainProblem(flag) {
  let m = flag.match(/^Closed but waiting on (.+)$/)
  if (m) {
    return {
      title: `Marked Closed, but “${m[1]}” is still missing`,
      help: 'Either finish that step, or change the status back so nobody thinks the job is complete.'
    }
  }
  if (flag === 'Resolved without Work Report') {
    return {
      title: 'Marked Resolved, but there is no Work Report',
      help: 'Resolved means the work is done. Add the engineer’s Work Report link, or change the status.'
    }
  }
  m = flag.match(/^(.+) is not a link$/)
  if (m) {
    return {
      title: `${m[1]} has text that is not a link`,
      help: 'Someone typed a note such as “ok” or “will upload”. Replace it with the real link.'
    }
  }
  m = flag.match(/^(.+) cannot be NA$/)
  if (m) {
    return { title: `${m[1]} is marked “not needed”, but it is always required`, help: 'Add a real link for it.' }
  }
  if (flag === 'Manager not on roster') {
    return { title: 'The manager’s name doesn’t match anyone on the team', help: 'Pick a manager from the list.' }
  }
  if (flag === 'Engineer not on roster') {
    return { title: 'The engineer isn’t on the team list', help: 'Choose an engineer from the list.' }
  }
  return { title: flag, help: '' }
}

/** Which of the editable fields differ between a draft and the saved job. */
export function changedFields(saved, draft) {
  const out = {}
  for (const key of Object.keys(draft)) {
    if ((saved[key] ?? '') !== (draft[key] ?? '')) out[key] = draft[key]
  }
  return out
}

export function draftFrom(job) {
  return {
    status: job.status ?? '',
    engineer: job.engineer ?? '',
    manager: job.manager ?? '',
    purchase_order: job.documents.purchase_order.value,
    delivery_note: job.documents.delivery_note.value,
    work_report: job.documents.work_report.value,
    invoice: job.documents.invoice.value
  }
}

/** Read URL state from a query string, with defaults. */
export function parseQuery(search) {
  const p = new URLSearchParams(search)
  return {
    view: p.get('view') || 'home',
    q: p.get('q') || '',
    stage: p.get('stage') || '',
    owner: p.get('owner') || '',
    status: p.get('status') || '',
    flagged: p.get('flagged') === '1',
    page: Math.max(1, Number(p.get('page')) || 1),
    ticket: p.get('ticket') ? Number(p.get('ticket')) : null,
    tab: p.get('tab') || 'sent'
  }
}

export function buildQuery(state) {
  const p = new URLSearchParams()
  if (state.view && state.view !== 'home') p.set('view', state.view)
  if (state.q) p.set('q', state.q)
  if (state.stage) p.set('stage', state.stage)
  if (state.owner) p.set('owner', state.owner)
  if (state.status) p.set('status', state.status)
  if (state.flagged) p.set('flagged', '1')
  if (state.page > 1) p.set('page', String(state.page))
  if (state.ticket) p.set('ticket', String(state.ticket))
  if (state.view === 'history' && state.tab !== 'sent') p.set('tab', state.tab)
  const s = p.toString()
  return s ? `?${s}` : ''
}
