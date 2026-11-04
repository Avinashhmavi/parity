import { api } from '../api.js'
import { useResource } from '../hooks.js'
import { formatNumber, STAGES } from '../lib.js'
import { Empty, Skeleton } from './ui.jsx'

const ROLES = ['Coordinator', 'Manager', 'Engineer', 'Finance', 'Unlisted']

export function Workload({ summary, onPickOwner, onPickStage }) {
  if (!summary) return <Skeleton rows={6} />
  const max = Math.max(1, ...summary.workload.map(p => p.pending))
  const stageMax = Math.max(1, ...Object.values(summary.stages))
  const groups = ROLES.map(role => ({ role, people: summary.workload.filter(p => p.role === role) })).filter(g => g.people.length)

  if (summary.totals.tickets === 0) {
    return <Empty title="Nothing to count yet">Run a sync to pull tickets, then this page shows who each one is waiting on.</Empty>
  }

  return (
    <>
      <div className="funnel" role="group" aria-label="Tickets by stage">
        {[...STAGES, 'Done'].map(stage => {
          const n = summary.stages[stage] ?? 0
          return (
            <button key={stage} type="button" data-done={stage === 'Done'} onClick={() => onPickStage(stage)}>
              <span className="n">{formatNumber(n)}</span>
              <span className="l">{stage}</span>
              <span className="bar" style={{ transform: `scaleX(${n / stageMax})` }} aria-hidden="true" />
            </button>
          )
        })}
      </div>

      {groups.map(({ role, people }) => (
        <section key={role} aria-labelledby={`g-${role}`}>
          <h2 className="group-title" id={`g-${role}`}>
            {role === 'Finance' ? 'Finance' : `${role}s`}
            <span className="num muted">{formatNumber(people.reduce((a, p) => a + p.pending, 0))} waiting</span>
          </h2>
          <div className="people">
            {people.map(p => (
              <button key={p.person} type="button" className="person" onClick={() => onPickOwner(p.person)} aria-label={`${p.person}: ${p.pending} waiting. Show their tickets`}>
                <span className="name truncate">{p.person}</span>
                <span className="meter" aria-hidden="true">
                  <span style={{ transform: `scaleX(${p.pending / max})` }} />
                </span>
                <span className="pending">{formatNumber(p.pending)}</span>
                <span className="flagged">
                  {p.flagged > 0 ? (
                    <span className="flag num">{formatNumber(p.flagged)} flagged</span>
                  ) : (
                    <span className="muted">{'—'}</span>
                  )}
                </span>
              </button>
            ))}
          </div>
        </section>
      ))}
    </>
  )
}

export function useSummary(refreshKey) {
  return useResource(signal => api.summary(signal), [refreshKey])
}
