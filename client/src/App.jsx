import { useCallback, useEffect, useState } from 'react'
import { api } from './api.js'
import { useResource, useServerEvents, useUrlState } from './hooks.js'
import { buildQuery } from './lib.js'
import { ActivityView } from './components/Activity.jsx'
import { Board } from './components/Board.jsx'
import { Drawer } from './components/Drawer.jsx'
import { Rail } from './components/Rail.jsx'
import { Workload } from './components/Workload.jsx'

const TITLES = {
  board: ['Ticket Board', 'Every ticket, the step it is stuck on, and whose move it is.'],
  workload: ['Workload', 'How many tickets are waiting on each person right now.'],
  integrity: ['Integrity', 'Tickets marked Closed or Resolved whose paperwork says otherwise, and documents that are not links.'],
  activity: ['Activity', 'What the sync pushed, what it refused, and every time both sides disagreed.']
}

export default function App() {
  const [state, update] = useUrlState()
  const [refreshKey, setRefreshKey] = useState(0)
  const [syncing, setSyncing] = useState(false)
  const [toasts, setToasts] = useState([])

  const refresh = useCallback(() => setRefreshKey(k => k + 1), [])
  const notify = useCallback((message, tone) => {
    const id = Math.random().toString(36).slice(2)
    setToasts(t => [...t, { id, message, tone }])
    setTimeout(() => setToasts(t => t.filter(x => x.id !== id)), 5000)
  }, [])

  const health = useResource(signal => api.health(signal), [refreshKey])
  const facets = useResource(signal => api.facets(signal), [refreshKey])
  const summary = useResource(signal => api.summary(signal), [refreshKey])

  useEffect(() => {
    if (health.data) setSyncing(health.data.syncing)
  }, [health.data])

  // Belt and braces: if the socket is unavailable (a proxy, a login prompt), poll
  // until the running sync is over so the UI can never stay stuck on "Syncing".
  useEffect(() => {
    if (!syncing) return undefined
    const timer = setInterval(async () => {
      try {
        const status = await api.syncStatus()
        if (!status.syncing) {
          setSyncing(false)
          refresh()
        }
      } catch {
        /* keep polling */
      }
    }, 2500)
    return () => clearInterval(timer)
  }, [syncing, refresh])

  useServerEvents(event => {
    if (event.type === 'sync.started') setSyncing(true)
    if (event.type === 'sync.finished') {
      setSyncing(false)
      const r = event.result
      notify(`Sync finished: ${r.pushed} pushed, ${r.conflicts} conflict${r.conflicts === 1 ? '' : 's'}, ${r.rejected} rejected.`)
      refresh()
    }
    if (event.type === 'sync.failed') {
      setSyncing(false)
      notify(`Sync failed: ${event.error}`, 'bad')
      refresh()
    }
    if (event.type === 'board.changed') refresh()
  })

  const startSync = async () => {
    setSyncing(true)
    try {
      await api.startSync()
    } catch (err) {
      setSyncing(false)
      notify(err.message, 'bad')
    }
  }

  // "Integrity" is the board with the integrity filter on; it keeps its own nav entry.
  const view = state.view === 'board' && state.flagged && !state.stage && !state.owner && !state.q ? 'integrity' : state.view
  const hrefFor = v => {
    if (v === 'integrity') return buildQuery({ ...state, view: 'board', flagged: true, stage: '', owner: '', q: '', status: '', page: 1, ticket: null })
    if (v === 'board') return buildQuery({ ...state, view: 'board', flagged: false, stage: '', owner: '', q: '', status: '', page: 1, ticket: null })
    return buildQuery({ ...state, view: v, ticket: null })
  }
  const navigate = (e, v) => {
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.button === 1) return
    e.preventDefault()
    if (v === 'integrity') update({ view: 'board', flagged: true, stage: '', owner: '', q: '', status: '', page: 1, ticket: null }, { push: true })
    else if (v === 'board') update({ view: 'board', flagged: false, stage: '', owner: '', q: '', status: '', page: 1, ticket: null }, { push: true })
    else update({ view: v, ticket: null }, { push: true })
  }

  const [title, blurb] = TITLES[view] ?? TITLES.board
  const open = id => update({ ticket: id }, { push: true })

  useEffect(() => {
    document.title = `${title} · FieldServe`
  }, [title])

  return (
    <>
      <a className="skip" href="#main">
        Skip to content
      </a>
      <div className="shell">
        <Rail view={view} href={hrefFor} onNavigate={navigate} health={health.data} syncing={syncing} onSync={startSync} summary={summary.data} />
        <main id="main" className="main" tabIndex={-1}>
          <header className="page-head">
            <div>
              <h1>{title}</h1>
              <p>{blurb}</p>
            </div>
          </header>

          {(state.view === 'board') && (
            <Board state={state} update={update} facets={facets.data} summary={summary.data} refreshKey={refreshKey} onOpen={open} />
          )}
          {state.view === 'workload' && (
            <Workload
              summary={summary.data}
              onPickOwner={owner => update({ view: 'board', owner, flagged: false, stage: '', q: '', page: 1 }, { push: true })}
              onPickStage={stage => update({ view: 'board', stage, owner: '', flagged: false, q: '', page: 1 }, { push: true })}
            />
          )}
          {state.view === 'activity' && <ActivityView tab={state.tab} onTab={tab => update({ tab })} refreshKey={refreshKey} onOpen={open} />}
        </main>
      </div>

      {state.ticket && (
        <Drawer key={state.ticket} id={state.ticket} refreshKey={refreshKey} onClose={() => update({ ticket: null }, { push: true })} onSaved={refresh} notify={notify} />
      )}

      <div className="toasts" aria-live="polite" aria-atomic="false">
        {toasts.map(t => (
          <div key={t.id} className="toast" data-tone={t.tone}>
            {t.message}
          </div>
        ))}
      </div>
    </>
  )
}
