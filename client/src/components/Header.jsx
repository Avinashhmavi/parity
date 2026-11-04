import { formatNumber, relativeTime } from '../lib.js'
import { HelpIcon, HistoryIcon, HomeIcon, JobsIcon, PeopleIcon, ProblemIcon, RefreshIcon } from './icons.jsx'

const NAV = [
  { view: 'home', label: 'Home', Icon: HomeIcon },
  { view: 'jobs', label: 'All Jobs', Icon: JobsIcon },
  { view: 'problems', label: 'Needs a Look', Icon: ProblemIcon },
  { view: 'people', label: 'People', Icon: PeopleIcon },
  { view: 'history', label: 'History', Icon: HistoryIcon }
]

export function Header({ view, href, onNavigate, health, syncing, onSync, onHelp, summary }) {
  const last = health?.lastSync
  let status = 'Not updated yet'
  let tone = 'grey'
  if (syncing) {
    status = 'Getting the latest from FieldServe…'
    tone = 'blue'
  } else if (last && last.ok) {
    status = `Updated ${relativeTime(last.finished_at)}`
    tone = 'green'
  } else if (last && !last.ok) {
    status = 'The last update didn’t work'
    tone = 'red'
  }

  return (
    <header className="top">
      <div className="top-inner">
        <a className="brand" href={href('home')} onClick={e => onNavigate(e, 'home')}>
          <span className="brand-mark" aria-hidden="true">
            F
          </span>
          <span>
            <span className="brand-name" translate="no">
              FieldServe Job Board
            </span>
            <span className="brand-sub">Who needs to do what, for every job</span>
          </span>
        </a>

        <div className="top-actions">
          <span className="update-status" data-tone={tone} aria-live="polite">
            <i aria-hidden="true" />
            {status}
          </span>
          <button
            type="button"
            className="btn btn-primary"
            onClick={onSync}
            disabled={syncing || !health?.canSync}
            title="Fetch the newest jobs from FieldServe and send them any changes you made here"
          >
            <RefreshIcon className={syncing ? 'spin' : undefined} />
            {syncing ? 'Updating…' : 'Update Now'}
          </button>
          <button type="button" className="btn btn-quiet" onClick={onHelp}>
            <HelpIcon />
            Help
          </button>
        </div>
      </div>

      <nav className="tabs" aria-label="Main">
        <ul>
          {NAV.map(({ view: v, label, Icon }) => (
            <li key={v}>
              <a href={href(v)} onClick={e => onNavigate(e, v)} aria-current={view === v ? 'page' : undefined}>
                <Icon />
                {label}
                {v === 'problems' && summary?.totals.flagged > 0 && <span className="badge">{formatNumber(summary.totals.flagged)}</span>}
              </a>
            </li>
          ))}
        </ul>
      </nav>
    </header>
  )
}
