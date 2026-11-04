import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { useDebounced, useResource } from '../hooks.js'
import { formatNumber, STAGES } from '../lib.js'
import { Close, MagnifyingGlass, Next, Prev, Sort, Warning } from './icons.jsx'
import { Empty, Progress, Skeleton, StatusChip } from './ui.jsx'

const PAGE_SIZE = 100

export function Board({ state, update, facets, refreshKey, onOpen, summary }) {
  const [search, setSearch] = useState(state.q)
  const debounced = useDebounced(search)
  const [sort, setSort] = useState({ key: 'id', order: 'asc' })

  // Keep the box in step with back/forward navigation.
  useEffect(() => setSearch(state.q), [state.q])
  useEffect(() => {
    if (debounced !== state.q) update({ q: debounced, page: 1 })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debounced])

  const { data, error, loading, reload } = useResource(
    signal =>
      api.board(
        { q: state.q, stage: state.stage, owner: state.owner, status: state.status, flagged: state.flagged, sort: sort.key, order: sort.order, page: state.page, pageSize: PAGE_SIZE },
        signal
      ),
    [state.q, state.stage, state.owner, state.status, state.flagged, state.page, sort.key, sort.order, refreshKey]
  )

  const total = data?.total ?? 0
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE))
  const filtered = state.q || state.stage || state.owner || state.status || state.flagged

  const toggleSort = key => setSort(s => (s.key === key ? { key, order: s.order === 'asc' ? 'desc' : 'asc' } : { key, order: 'asc' }))
  const th = (key, label) => (
    <th scope="col" aria-sort={sort.key === key ? (sort.order === 'asc' ? 'ascending' : 'descending') : 'none'}>
      <button type="button" onClick={() => toggleSort(key)}>
        {label}
        <Sort size={12} />
      </button>
    </th>
  )

  const clear = () => {
    setSearch('')
    update({ q: '', stage: '', owner: '', status: '', flagged: false, page: 1 }, { push: true })
  }

  return (
    <>
      <div className="toolbar" role="search">
        <div className="field searchbox" style={{ flex: '1 1 18rem' }}>
          <label className="sr-only" htmlFor="q">
            Search tickets
          </label>
          <MagnifyingGlass size={16} />
          <input
            id="q"
            className="input"
            type="search"
            name="q"
            autoComplete="off"
            spellCheck={false}
            placeholder="Search id, subject, store code, person…"
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="owner">Waiting on</label>
          <select id="owner" name="owner" className="select" value={state.owner} onChange={e => update({ owner: e.target.value, page: 1 })}>
            <option value="">Anyone</option>
            {facets?.owners.map(o => (
              <option key={o}>{o}</option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="status">Status</label>
          <select id="status" name="status" className="select" value={state.status} onChange={e => update({ status: e.target.value, page: 1 })}>
            <option value="">Any status</option>
            {facets?.statuses.map(s => (
              <option key={s}>{s}</option>
            ))}
          </select>
        </div>
        <label className="toggle">
          <input type="checkbox" name="flagged" checked={state.flagged} onChange={e => update({ flagged: e.target.checked, page: 1 })} />
          Integrity issues only
        </label>
        {filtered && (
          <button type="button" className="btn btn-ghost" onClick={clear}>
            <Close size={14} />
            Clear Filters
          </button>
        )}
      </div>

      <div className="stagebar" role="group" aria-label="Filter by stage">
        <button type="button" className="chipbtn" aria-pressed={!state.stage} onClick={() => update({ stage: '', page: 1 })}>
          All Stages
          {summary && <span className="num">{formatNumber(summary.totals.tickets)}</span>}
        </button>
        {[...STAGES, 'Done'].map(stage => (
          <button key={stage} type="button" className="chipbtn" aria-pressed={state.stage === stage} onClick={() => update({ stage: state.stage === stage ? '' : stage, page: 1 })}>
            {stage}
            {summary && <span className="num">{formatNumber(summary.stages[stage] ?? 0)}</span>}
          </button>
        ))}
      </div>

      {error && (
        <div className="banner" role="alert">
          <Warning size={18} />
          <div>
            <strong>Could not load the board.</strong> {error.message}{' '}
            <button type="button" className="btn btn-ghost" onClick={reload}>
              Try Again
            </button>
          </div>
        </div>
      )}

      <div className="tablewrap" aria-busy={loading}>
        {loading && !data ? (
          <Skeleton />
        ) : data && data.items.length === 0 ? (
          <Empty title={filtered ? 'No tickets match these filters' : 'The board is empty'}>
            {filtered ? 'Loosen a filter or clear them all.' : 'Run a sync to pull tickets from the FieldServe API.'}
          </Empty>
        ) : (
          <table className="board">
            <caption className="sr-only">
              Tickets, {formatNumber(total)} shown, page {state.page} of {pages}
            </caption>
            <thead>
              <tr>
                {th('id', 'Ticket')}
                <th scope="col">Subject</th>
                {th('stage', 'Stage')}
                {th('owner', 'Waiting On')}
                {th('status', 'Status')}
                <th scope="col">Flags</th>
              </tr>
            </thead>
            <tbody>
              {data?.items.map(t => (
                <tr key={t.id} aria-selected={state.ticket === t.id} onClick={() => onOpen(t.id)}>
                  <td data-label="Ticket">
                    <a className="idlink" href={`?ticket=${t.id}`} onClick={e => { e.preventDefault(); e.stopPropagation(); onOpen(t.id) }} translate="no">
                      #{t.id}
                    </a>
                  </td>
                  <td className="cell-subject" data-label="Subject">
                    <div className="truncate" title={t.subject}>{t.subject}</div>
                    <div className="sub truncate">
                      {[t.storeCode && <span key="c" className="mono" translate="no">{t.storeCode}</span>, t.store, t.jobType].filter(Boolean).reduce((acc, x, i) => (i ? [...acc, ' · ', x] : [x]), [])}
                    </div>
                  </td>
                  <td data-label="Stage">
                    <div className="stagecell">
                      <span>{t.stage}</span>
                      <Progress stage={t.stage} />
                    </div>
                  </td>
                  <td data-label="Waiting on">{t.actionOwner ? <span className="owner">{t.actionOwner}</span> : <span className="muted">{'—'}</span>}</td>
                  <td data-label="Status">
                    <StatusChip status={t.status} />
                  </td>
                  <td data-label="Flags">
                    {t.integrity.length > 0 ? (
                      <span className="flag" title={t.integrity.join('\n')}>
                        <Warning size={14} />
                        <span className="num">{t.integrity.length}</span>
                        <span className="sr-only">integrity issues: {t.integrity.join(', ')}</span>
                      </span>
                    ) : (
                      <span className="muted">{'—'}</span>
                    )}
                    {t.unsynced?.length > 0 && <span className="sr-only">Edited, waiting for sync</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {total > PAGE_SIZE && (
        <nav className="pager" aria-label="Pagination">
          <span className="num">
            {formatNumber((state.page - 1) * PAGE_SIZE + 1)}–{formatNumber(Math.min(state.page * PAGE_SIZE, total))} of {formatNumber(total)}
          </span>
          <span className="group">
            <button type="button" className="btn" disabled={state.page <= 1} onClick={() => update({ page: state.page - 1 }, { push: true })}>
              <Prev size={14} /> Previous
            </button>
            <button type="button" className="btn" disabled={state.page >= pages} onClick={() => update({ page: state.page + 1 }, { push: true })}>
              Next <Next size={14} />
            </button>
          </span>
        </nav>
      )}
      <p className="sub" style={{ marginTop: '0.75rem' }}>
        Edits made here are written to the sheet and pushed to FieldServe on the next sync.
      </p>
    </>
  )
}
