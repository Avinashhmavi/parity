import { ArrowsClockwise, Pulse, Scales, ShieldWarning, Stack } from './icons.jsx'
import { formatNumber, relativeTime } from '../lib.js'

const NAV = [
  { view: 'board', label: 'Board', Icon: Stack },
  { view: 'workload', label: 'Workload', Icon: Scales },
  { view: 'integrity', label: 'Integrity', Icon: ShieldWarning },
  { view: 'activity', label: 'Activity', Icon: Pulse }
]

export function Rail({ view, href, onNavigate, health, syncing, onSync, summary }) {
  const last = health?.lastSync
  const state = syncing ? 'syncing' : !last ? 'never' : last.ok ? 'ok' : 'failed'
  const label = syncing
    ? 'Syncing…'
    : !last
      ? 'Never synced'
      : last.ok
        ? `Synced ${relativeTime(last.finished_at)}`
        : 'Last sync failed'

  return (
    <aside className="rail">
      <a className="brand" href={href('board')} onClick={e => onNavigate(e, 'board')}>
        <span className="brand-mark" aria-hidden="true">
          <Stack size={18} />
        </span>
        <span>
          <span className="brand-name" translate="no">
            Ticket Board
          </span>
          <span className="brand-sub" translate="no">
            FieldServe
          </span>
        </span>
      </a>

      <nav className="nav" aria-label="Primary">
        {NAV.map(({ view: v, label: text, Icon }) => (
          <a key={v} href={href(v)} onClick={e => onNavigate(e, v)} aria-current={view === v ? 'page' : undefined}>
            <Icon size={18} />
            {text}
            {v === 'integrity' && summary?.totals.flagged > 0 && <span className="count num">{formatNumber(summary.totals.flagged)}</span>}
          </a>
        ))}
      </nav>

      <div className="syncbox">
        <div className="row" aria-live="polite">
          <span className="dot" data-state={state} aria-hidden="true" />
          <strong>{label}</strong>
        </div>
        <div className="detail">
          {last?.ok && (
            <span>
              <span className="num">{formatNumber(last.operational)}</span> on board, <span className="num">{formatNumber(last.noise)}</span> noise,{' '}
              <span className="num">{formatNumber(last.requests)}</span> requests
            </span>
          )}
          {last && !last.ok && <span>{last.error}</span>}
          {health && !health.canSync && <span>Read-only: no API key configured.</span>}
          {health?.canSync && (
            <span>
              Conflicts: <b>{health.conflictPolicy === 'api' ? 'server wins' : 'sheet wins'}</b>
            </span>
          )}
        </div>
        <button type="button" className="btn btn-primary" onClick={onSync} disabled={syncing || !health?.canSync}>
          <ArrowsClockwise size={16} className={syncing ? 'spin' : undefined} />
          {syncing ? 'Syncing…' : 'Sync Now'}
        </button>
      </div>
    </aside>
  )
}
