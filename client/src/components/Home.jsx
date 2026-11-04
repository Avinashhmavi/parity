import { formatNumber, ROLE_TEXT, STAGES, STEP_TEXT } from '../lib.js'
import { Empty, Skeleton } from './ui.jsx'

export function Home({ summary, onGo }) {
  if (!summary) return <Skeleton rows={4} />
  const { totals, stages, workload } = summary

  if (totals.tickets === 0) {
    return (
      <Empty title="There are no jobs here yet">
        Press <b>Update Now</b> at the top to bring in the jobs from FieldServe.
      </Empty>
    )
  }

  const busiest = workload.filter(p => p.pending > 0).sort((a, b) => b.pending - a.pending).slice(0, 6)
  const most = Math.max(1, ...busiest.map(p => p.pending))
  const maxStage = Math.max(1, ...STAGES.map(s => stages[s] ?? 0))

  return (
    <>
      <section className="hero" aria-labelledby="hero-h">
        <h1 id="hero-h">Here is where things stand</h1>
        <p className="lead">
          <b>{formatNumber(totals.pending)}</b> of <b>{formatNumber(totals.tickets)}</b> jobs are waiting for someone to act.
          {totals.flagged > 0 && (
            <>
              {' '}
              <b>{formatNumber(totals.flagged)}</b> need a closer look.
            </>
          )}
        </p>
      </section>

      <div className="tiles">
        <button type="button" className="tile" data-tone="amber" onClick={() => onGo({ view: 'jobs' })}>
          <span className="tile-n">{formatNumber(totals.pending)}</span>
          <span className="tile-t">Waiting for someone</span>
          <span className="tile-d">Jobs with a step still to do. See them all.</span>
        </button>
        <button type="button" className="tile" data-tone="red" onClick={() => onGo({ view: 'problems' })}>
          <span className="tile-n">{formatNumber(totals.flagged)}</span>
          <span className="tile-t">Need a look</span>
          <span className="tile-d">Something doesn’t add up, such as a Closed job with paperwork missing.</span>
        </button>
        <button type="button" className="tile" data-tone="green" onClick={() => onGo({ view: 'jobs', stage: 'Done' })}>
          <span className="tile-n">{formatNumber(totals.done)}</span>
          <span className="tile-t">Finished</span>
          <span className="tile-d">All six steps are complete.</span>
        </button>
      </div>

      <section className="block" aria-labelledby="busy-h">
        <div className="block-head">
          <h2 id="busy-h">Who has the most waiting</h2>
          <button type="button" className="link" onClick={() => onGo({ view: 'people' })}>
            See everyone
          </button>
        </div>
        <ul className="bars">
          {busiest.map(p => (
            <li key={p.person}>
              <button type="button" className="bar-row" onClick={() => onGo({ view: 'jobs', owner: p.person })}>
                <span className="bar-name">
                  {p.person}
                  <small>{ROLE_TEXT[p.role]?.title ?? p.role}</small>
                </span>
                <span className="bar" aria-hidden="true">
                  <span style={{ width: `${(p.pending / most) * 100}%` }} />
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

      <section className="block" aria-labelledby="steps-h">
        <div className="block-head">
          <h2 id="steps-h">The six steps every job goes through</h2>
        </div>
        <p className="muted">A job can only move on when the step before it is finished. Press a step to see the jobs stuck there.</p>
        <ol className="step-list">
          {STAGES.map((stage, i) => {
            const n = stages[stage] ?? 0
            return (
              <li key={stage}>
                <button type="button" className="step-row" onClick={() => onGo({ view: 'jobs', stage })}>
                  <span className="step-num" aria-hidden="true">
                    {i + 1}
                  </span>
                  <span className="step-text">
                    <b>{STEP_TEXT[stage].name}</b>
                    <small>{STEP_TEXT[stage].about}</small>
                  </span>
                  <span className="step-bar" aria-hidden="true">
                    <span style={{ width: `${(n / maxStage) * 100}%` }} />
                  </span>
                  <span className="step-n">
                    {formatNumber(n)}
                    <small> jobs here</small>
                  </span>
                </button>
              </li>
            )
          })}
        </ol>
      </section>

      {totals.noise > 0 && (
        <p className="muted foot-note">
          {formatNumber(totals.noise)} emails (spam and automatic alerts) were left out of the list.{' '}
          <button type="button" className="link" onClick={() => onGo({ view: 'history', tab: 'ignored' })}>
            See which ones
          </button>
        </p>
      )}
    </>
  )
}
