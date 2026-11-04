import { api } from '../api.js'
import { useResource } from '../hooks.js'
import { formatTime } from '../lib.js'
import { Chip, Empty, Skeleton } from './ui.jsx'

const TABS = [
  { key: 'conflicts', label: 'Conflicts' },
  { key: 'activity', label: 'Sync Log' },
  { key: 'noise', label: 'Noise' }
]
const KIND_TONE = { conflict: 'warn', pushed: 'ok', rejected: 'bad', error: 'bad', held: 'accent', added: '', removed: 'warn', noise: '', ignored: '', warning: 'warn' }

export function ActivityView({ tab, onTab, refreshKey, onOpen }) {
  const loader = { conflicts: api.conflicts, activity: api.activity, noise: api.noise }[tab] ?? api.conflicts
  const { data, error, loading } = useResource(signal => loader(signal), [tab, refreshKey])

  return (
    <>
      <div className="tabs" role="tablist" aria-label="Activity">
        {TABS.map(t => (
          <button key={t.key} type="button" role="tab" id={`tab-${t.key}`} aria-selected={tab === t.key} aria-controls="activity-panel" onClick={() => onTab(t.key)}>
            {t.label}
          </button>
        ))}
      </div>
      <div id="activity-panel" role="tabpanel" aria-labelledby={`tab-${tab}`}>
        {error && <p className="error" role="alert">{error.message}</p>}
        {loading && !data ? (
          <Skeleton rows={5} />
        ) : !data?.length ? (
          <Empty title={{ conflicts: 'No conflicts', activity: 'Nothing logged yet', noise: 'No noise tickets' }[tab]}>
            {{
              conflicts: 'A conflict is logged whenever the sheet and the API both changed the same field since the last sync.',
              activity: 'Pushes, rejections and other sync events show up here.',
              noise: 'Spam and automated alerts are kept off the board and listed here with the reason.'
            }[tab]}
          </Empty>
        ) : (
          <ul className="feed">
            {tab === 'conflicts' &&
              data.map((c, i) => (
                <li key={i} style={{ gridTemplateColumns: '9rem minmax(0,1fr)' }}>
                  <span className="when num">{formatTime(c.time)}</span>
                  <div>
                    <button type="button" className="btn btn-ghost" style={{ minHeight: 0, padding: 0 }} onClick={() => onOpen(c.ticket_id)}>
                      <strong className="mono" translate="no">#{c.ticket_id}</strong>
                    </button>{' '}
                    <b>{c.field}</b> <span className="muted">{c.reason}</span>
                    <div className="conflict-grid">
                      <div>
                        <small>Last agreed</small>
                        <code>{c.base || '(empty)'}</code>
                      </div>
                      <div className={c.winner === 'sheet' ? 'win' : ''}>
                        <small>Sheet {c.winner === 'sheet' && '(kept)'}</small>
                        <code>{c.sheet || '(empty)'}</code>
                      </div>
                      <div className={c.winner === 'api' ? 'win' : ''}>
                        <small>Server {c.winner === 'api' && '(kept)'}</small>
                        <code>{c.api || '(empty)'}</code>
                      </div>
                    </div>
                  </div>
                </li>
              ))}
            {tab === 'activity' &&
              data.map((a, i) => (
                <li key={i}>
                  <span className="when num">{formatTime(a.time)}</span>
                  <span>
                    <Chip tone={KIND_TONE[a.kind]}>{a.kind}</Chip>
                  </span>
                  <span className="what">
                    {a.ticket_id && (
                      <button type="button" className="btn btn-ghost" style={{ minHeight: 0, padding: 0, marginRight: '0.4rem' }} onClick={() => onOpen(a.ticket_id)}>
                        <strong className="mono" translate="no">#{a.ticket_id}</strong>
                      </button>
                    )}
                    {a.message}
                  </span>
                </li>
              ))}
            {tab === 'noise' &&
              data.map(n => (
                <li key={n.id} style={{ gridTemplateColumns: '5rem minmax(0,1fr)' }}>
                  <span className="mono" translate="no">#{n.id}</span>
                  <span className="what">
                    <strong>{n.subject}</strong>
                    <br />
                    <span className="muted">
                      {n.requester} {'·'} {n.reason}
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
