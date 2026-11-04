import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { useDebounced, useResource } from '../hooks.js'
import { explainProblem, formatDate, formatNumber, nextAction, STAGES, STEP_TEXT } from '../lib.js'
import { NextIcon, PrevIcon, ProblemIcon, SearchIcon } from './icons.jsx'
import { Empty, Skeleton, StatusChip, StepDots } from './ui.jsx'

const PAGE_SIZE = 25
const SORTS = {
  newest: { sort: 'updated', order: 'desc', label: 'Newest first' },
  oldest: { sort: 'updated', order: 'asc', label: 'Oldest first' },
  number: { sort: 'id', order: 'asc', label: 'Job number' }
}

export function Jobs({ state, update, facets, refreshKey, onOpen, problemsOnly = false }) {
  const [search, setSearch] = useState(state.q)
  const [sortKey, setSortKey] = useState('newest')
  const debounced = useDebounced(search)

  useEffect(() => setSearch(state.q), [state.q])
  useEffect(() => {
    if (debounced !== state.q) update({ q: debounced, page: 1 })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debounced])

  const flagged = problemsOnly || state.flagged
  const { data, error, loading, reload } = useResource(
    signal =>
      api.board(
        { q: state.q, stage: state.stage, owner: state.owner, status: state.status, flagged, ...SORTS[sortKey], page: state.page, pageSize: PAGE_SIZE },
        signal
      ),
    [state.q, state.stage, state.owner, state.status, flagged, state.page, sortKey, refreshKey]
  )

  const total = data?.total ?? 0
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE))
  const filtering = state.q || state.stage || state.owner || state.status || (!problemsOnly && state.flagged)
  const clear = () => {
    setSearch('')
    update({ q: '', stage: '', owner: '', status: '', flagged: false, page: 1 }, { push: true })
  }

  return (
    <>
      <div className="filters" role="search">
        <div className="field grow">
          <label htmlFor="q">Search</label>
          <div className="searchbox">
            <SearchIcon />
            <input
              id="q"
              className="input"
              type="search"
              name="q"
              autoComplete="off"
              spellCheck={false}
              placeholder="A store name, a person, or a job number"
              value={search}
              onChange={e => setSearch(e.target.value)}
            />
          </div>
        </div>
        <div className="field">
          <label htmlFor="f-stage">Next step</label>
          <select id="f-stage" className="select" value={state.stage} onChange={e => update({ stage: e.target.value, page: 1 })}>
            <option value="">Any step</option>
            {STAGES.map((s, i) => (
              <option key={s} value={s}>
                {i + 1}. {STEP_TEXT[s].name}
              </option>
            ))}
            <option value="Done">Finished</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="f-owner">Who needs to act</label>
          <select id="f-owner" className="select" value={state.owner} onChange={e => update({ owner: e.target.value, page: 1 })}>
            <option value="">Anyone</option>
            {facets?.owners.map(o => (
              <option key={o}>{o}</option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="f-status">Status</label>
          <select id="f-status" className="select" value={state.status} onChange={e => update({ status: e.target.value, page: 1 })}>
            <option value="">Any status</option>
            {facets?.statuses.map(s => (
              <option key={s}>{s}</option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="f-sort">Show first</label>
          <select id="f-sort" className="select" value={sortKey} onChange={e => setSortKey(e.target.value)}>
            {Object.entries(SORTS).map(([k, v]) => (
              <option key={k} value={k}>
                {v.label}
              </option>
            ))}
          </select>
        </div>
      </div>
      {!problemsOnly && (
        <label className="check">
          <input type="checkbox" checked={state.flagged} onChange={e => update({ flagged: e.target.checked, page: 1 })} />
          Only show jobs that need a look
        </label>
      )}

      <p className="result-line" aria-live="polite">
        {loading && !data ? (
          'Loading…'
        ) : (
          <span>
            <b>{formatNumber(total)}</b> {total === 1 ? 'job' : 'jobs'}
            {filtering ? ' match' : ''}
          </span>
        )}
        {filtering && (
          <button type="button" className="link" onClick={clear}>
            Clear all filters
          </button>
        )}
      </p>

      {error && (
        <div className="notice" data-tone="red" role="alert">
          <div>
            <strong>The list couldn’t be loaded.</strong> {error.message}{' '}
            <button type="button" className="link" onClick={reload}>
              Try again
            </button>
          </div>
        </div>
      )}

      {loading && !data ? (
        <Skeleton rows={5} />
      ) : data && data.items.length === 0 ? (
        <Empty
          title={problemsOnly && !filtering ? 'Nothing needs a look. Nice.' : filtering ? 'No jobs match what you picked' : 'There are no jobs yet'}
          action={
            filtering ? (
              <button type="button" className="btn" onClick={clear}>
                Clear all filters
              </button>
            ) : null
          }
        >
          {filtering ? 'Try fewer filters, or a different word.' : problemsOnly ? 'Every Closed or Resolved job has its paperwork.' : 'Press Update Now to bring jobs in from FieldServe.'}
        </Empty>
      ) : (
        <ul className="jobs" aria-busy={loading}>
          {data?.items.map(job => {
            const problems = job.integrity.map(explainProblem)
            return (
              <li key={job.id} className="job" data-problem={problems.length > 0} data-done={job.stage === 'Done'}>
                <a
                  className="job-link"
                  href={`?ticket=${job.id}`}
                  onClick={e => {
                    if (e.metaKey || e.ctrlKey || e.shiftKey || e.button === 1) return
                    e.preventDefault()
                    onOpen(job.id)
                  }}
                >
                  <span className="job-top">
                    <span className="job-id" translate="no">
                      Job #{job.id}
                    </span>
                    <StatusChip status={job.status} />
                    {job.unsynced?.length > 0 && <span className="chip" data-tone="amber">Change not sent yet</span>}
                    <span className="job-date">Changed {formatDate(job.updatedAt)}</span>
                  </span>
                  <span className="job-title">{job.subject}</span>
                  <span className="job-meta">
                    {[job.store && `Store: ${job.store}`, job.storeCode && `Code ${job.storeCode}`, job.jobType && `${job.jobType} job`].filter(Boolean).join('  ·  ')}
                  </span>
                  <span className="job-next">{nextAction(job)}</span>
                  <StepDots stage={job.stage} />
                  {problems.slice(0, 2).map(p => (
                    <span key={p.title} className="job-problem">
                      <ProblemIcon size={16} />
                      {p.title}
                    </span>
                  ))}
                  {problems.length > 2 && <span className="job-problem more">and {problems.length - 2} more</span>}
                </a>
              </li>
            )
          })}
        </ul>
      )}

      {total > PAGE_SIZE && (
        <nav className="pager" aria-label="More jobs">
          <button type="button" className="btn" disabled={state.page <= 1} onClick={() => update({ page: state.page - 1 }, { push: true })}>
            <PrevIcon /> Previous
          </button>
          <span>
            Page {state.page} of {pages}
          </span>
          <button type="button" className="btn" disabled={state.page >= pages} onClick={() => update({ page: state.page + 1 }, { push: true })}>
            Next <NextIcon />
          </button>
        </nav>
      )}
    </>
  )
}
