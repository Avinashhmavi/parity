import { formatNumber, ROLE_TEXT } from '../lib.js'
import { Empty, Skeleton } from './ui.jsx'

const ORDER = ['Coordinator', 'Manager', 'Engineer', 'Finance', 'Unlisted']

export function People({ summary, onPick }) {
  if (!summary) return <Skeleton rows={4} />
  if (summary.totals.tickets === 0) return <Empty title="Nothing to count yet">Press Update Now to bring in jobs, then this page shows who has work waiting.</Empty>

  const max = Math.max(1, ...summary.workload.map(p => p.pending))
  const groups = ORDER.map(role => ({ role, people: summary.workload.filter(p => p.role === role) })).filter(g => g.people.length)

  return (
    <>
      <h1>People</h1>
      <p className="lead">How many jobs are waiting on each person right now. Press a name to see their jobs.</p>
      {groups.map(({ role, people }) => (
        <section key={role} className="block" aria-labelledby={`g-${role}`}>
          <div className="block-head">
            <div>
              <h2 id={`g-${role}`}>{ROLE_TEXT[role]?.title ?? role}</h2>
              <p className="muted">{ROLE_TEXT[role]?.about}</p>
            </div>
            <span className="muted">
              <b>{formatNumber(people.reduce((a, p) => a + p.pending, 0))}</b> waiting
            </span>
          </div>
          <ul className="bars">
            {people.map(p => (
              <li key={p.person}>
                <button type="button" className="bar-row" onClick={() => onPick(p.person)} aria-label={`${p.person}: ${p.pending} jobs waiting. Show their jobs`}>
                  <span className="bar-name">
                    {p.person}
                    {p.flagged > 0 && <small className="warn">{formatNumber(p.flagged)} need a look</small>}
                  </span>
                  <span className="bar" aria-hidden="true">
                    <span style={{ width: `${(p.pending / max) * 100}%` }} />
                  </span>
                  <span className="bar-n">
                    {formatNumber(p.pending)}
                    <small> waiting</small>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </>
  )
}
