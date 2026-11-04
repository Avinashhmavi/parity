import { api } from '../api.js'
import { useResource } from '../hooks.js'
import { formatTime } from '../lib.js'
import { Empty, Skeleton } from './ui.jsx'

const TABS = [
  { key: 'sent', label: 'Changes sent', blurb: 'What was sent to FieldServe, and anything FieldServe turned down.' },
  { key: 'clashes', label: 'Changes that clashed', blurb: 'Someone changed the same thing here and in FieldServe. FieldServe’s version was kept; yours is shown so you can re-enter it if you still want it.' },
  { key: 'ignored', label: 'Ignored emails', blurb: 'Spam and automatic alerts are kept out of the job list. Check nothing real is in here.' }
]
const KIND = {
  pushed: ['Sent', 'green'],
  rejected: ['Turned down', 'red'],
  error: ['Will retry', 'amber'],
  held: ['Kept your edit', 'blue'],
  added: ['New jobs', 'blue'],
  removed: ['Removed', 'amber'],
  noise: ['Ignored', 'grey'],
  ignored: ['Skipped', 'grey'],
  warning: ['Heads up', 'amber'],
  conflict: ['Clash', 'amber']
}

export function History({ tab, onTab, refreshKey, onOpen }) {
  const loader = { sent: api.activity, clashes: api.conflicts, ignored: api.noise }[tab] ?? api.activity
  const { data, error, loading } = useResource(signal => loader(signal), [tab, refreshKey])
  const current = TABS.find(t => t.key === tab) ?? TABS[0]

  return (
    <>
      <h1>History</h1>
      <div className="seg" role="tablist" aria-label="History">
        {TABS.map(t => (
          <button key={t.key} type="button" role="tab" id={`tab-${t.key}`} aria-selected={tab === t.key} aria-controls="hist-panel" onClick={() => onTab(t.key)}>
            {t.label}
          </button>
        ))}
      </div>
      <p className="muted">{current.blurb}</p>
      <div id="hist-panel" role="tabpanel" aria-labelledby={`tab-${current.key}`}>
        {error && <p className="error" role="alert">{error.message}</p>}
        {loading && !data ? (
          <Skeleton rows={4} />
        ) : !data?.length ? (
          <Empty title={{ sent: 'Nothing has been sent yet', clashes: 'No clashes. Good.', ignored: 'No emails were ignored' }[current.key]} />
        ) : (
          <ul className="feed">
            {tab === 'sent' &&
              data.map((a, i) => {
                const [label, tone] = KIND[a.kind] ?? [a.kind, 'grey']
                return (
                  <li key={i}>
                    <span className="when">{formatTime(a.time)}</span>
                    <span className="chip" data-tone={tone}>{label}</span>
                    <span className="what">
                      {a.ticket_id && (
                        <button type="button" className="link" onClick={() => onOpen(a.ticket_id)}>
                          Job #{a.ticket_id}
                        </button>
                      )}{' '}
                      {a.message}
                    </span>
                  </li>
                )
              })}
            {tab === 'clashes' &&
              data.map((c, i) => (
                <li key={i} className="clash">
                  <span className="when">{formatTime(c.time)}</span>
                  <span className="what">
                    <button type="button" className="link" onClick={() => onOpen(c.ticket_id)}>
                      Job #{c.ticket_id}
                    </button>{' '}
                    <b>{c.field}</b>
                    <span className="versions">
                      <span>
                        <small>What you had</small>
                        <code>{c.sheet || '(blank)'}</code>
                      </span>
                      <span className={c.winner === 'api' ? 'kept' : ''}>
                        <small>What FieldServe had{c.winner === 'api' ? ' (kept)' : ''}</small>
                        <code>{c.api || '(blank)'}</code>
                      </span>
                    </span>
                  </span>
                </li>
              ))}
            {tab === 'ignored' &&
              data.map(n => (
                <li key={n.id}>
                  <span className="when">Job #{n.id}</span>
                  <span className="what">
                    <b>{n.subject}</b>
                    <br />
                    <span className="muted">
                      From {n.requester}. Why it was ignored: {n.reason}
                    </span>
                  </span>
                </li>
              ))}
          </ul>
        )}
      </div>
    </>
  )
}
