import { useCallback, useEffect, useState } from 'react'
import { api } from './api.js'
import { Header } from './components/Header.jsx'
import { History } from './components/History.jsx'
import { Home } from './components/Home.jsx'
import { InfoIcon } from './components/icons.jsx'
import { JobPanel } from './components/JobPanel.jsx'
import { Jobs } from './components/Jobs.jsx'
import { People } from './components/People.jsx'
import { Welcome } from './components/Welcome.jsx'
import { Notice } from './components/ui.jsx'
import { useResource, useServerEvents, useUrlState } from './hooks.js'
import { buildQuery } from './lib.js'

const TITLES = {
  home: 'Home',
  jobs: 'All Jobs',
  problems: 'Jobs That Need a Look',
  people: 'People',
  history: 'History'
}
const SEEN_KEY = 'fieldserve-board-welcome-seen'

function seenBefore() {
  try {
    return window.localStorage.getItem(SEEN_KEY) === '1'
  } catch {
    return false // storage can be blocked; showing the guide again is harmless
  }
}
function rememberSeen() {
  try {
    window.localStorage.setItem(SEEN_KEY, '1')
  } catch {
    /* ignore */
  }
}

export default function App() {
  const [state, update] = useUrlState()
  const [refreshKey, setRefreshKey] = useState(0)
  const [syncing, setSyncing] = useState(false)
  const [toasts, setToasts] = useState([])
  const [welcome, setWelcome] = useState(() => !seenBefore())

  const refresh = useCallback(() => setRefreshKey(k => k + 1), [])
  const notify = useCallback((message, tone) => {
    const id = Math.random().toString(36).slice(2)
    setToasts(t => [...t, { id, message, tone }])
    setTimeout(() => setToasts(t => t.filter(x => x.id !== id)), 6000)
  }, [])

  const health = useResource(signal => api.health(signal), [refreshKey])
  const facets = useResource(signal => api.facets(signal), [refreshKey])
  const summary = useResource(signal => api.summary(signal), [refreshKey])

  useEffect(() => {
    if (health.data) setSyncing(health.data.syncing)
  }, [health.data])

  // If the live connection is blocked, still notice when a running update finishes.
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
        /* keep trying */
      }
    }, 2500)
    return () => clearInterval(timer)
  }, [syncing, refresh])

  useServerEvents(event => {
    if (event.type === 'sync.started') setSyncing(true)
    if (event.type === 'sync.finished') {
      setSyncing(false)
      notify('Up to date. Your jobs are now the same as FieldServe’s.')
      refresh()
    }
    if (event.type === 'sync.failed') {
      setSyncing(false)
      notify(`The update didn’t work: ${event.error}`, 'bad')
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

  const closeWelcome = () => {
    rememberSeen()
    setWelcome(false)
  }

  const hrefFor = v => buildQuery({ ...state, view: v, stage: '', owner: '', q: '', status: '', flagged: false, page: 1, ticket: null })
  const navigate = (e, v) => {
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.button === 1) return
    e.preventDefault()
    update({ view: v, stage: '', owner: '', q: '', status: '', flagged: false, page: 1, ticket: null }, { push: true })
  }

  const view = TITLES[state.view] ? state.view : 'home'
  useEffect(() => {
    document.title = `${TITLES[view]} · FieldServe Job Board`
  }, [view])

  const go = patch => update({ stage: '', owner: '', q: '', status: '', flagged: false, page: 1, ticket: null, ...patch }, { push: true })
  const openJob = id => update({ ticket: id }, { push: true })

  return (
    <>
      <a className="skip" href="#main">
        Skip to the content
      </a>
      <Header view={view} href={hrefFor} onNavigate={navigate} health={health.data} syncing={syncing} onSync={startSync} onHelp={() => setWelcome(true)} summary={summary.data} />

      {health.data && !health.data.loginRequired && (
        <div className="testbar" role="note">
          <InfoIcon size={16} />
          <span>
            <b>Test mode.</b> There is no login, so anyone with this link can see and change these jobs.
          </span>
        </div>
      )}

      <main id="main" className="page" tabIndex={-1}>
        {health.error && (
          <Notice tone="red" title="This page can’t reach the server right now">
            Check your internet connection, then reload the page.
          </Notice>
        )}
        {view === 'home' && <Home summary={summary.data} onGo={go} />}
        {(view === 'jobs' || view === 'problems') && (
          <>
            <h1>{view === 'problems' ? 'Jobs that need a look' : 'All jobs'}</h1>
            <p className="lead">
              {view === 'problems'
                ? 'These jobs have something that doesn’t add up. Open one to see what, and how to fix it.'
                : 'Every job, with its next step and the person who needs to act. Press a job to open it.'}
            </p>
            <Jobs state={state} update={update} facets={facets.data} refreshKey={refreshKey} onOpen={openJob} problemsOnly={view === 'problems'} />
          </>
        )}
        {view === 'people' && <People summary={summary.data} onPick={owner => go({ view: 'jobs', owner })} />}
        {view === 'history' && <History tab={state.tab} onTab={tab => update({ tab })} refreshKey={refreshKey} onOpen={openJob} />}
      </main>

      {state.ticket && (
        <JobPanel key={state.ticket} id={state.ticket} refreshKey={refreshKey} onClose={() => update({ ticket: null }, { push: true })} onSaved={refresh} notify={notify} canSync={Boolean(health.data?.canSync)} />
      )}

      <Welcome
        open={welcome}
        onClose={closeWelcome}
        onTour={() => {
          closeWelcome()
          go({ view: 'home' })
        }}
      />

      <div className="toasts" aria-live="polite">
        {toasts.map(t => (
          <div key={t.id} className="toast" data-tone={t.tone}>
            {t.message}
          </div>
        ))}
      </div>
    </>
  )
}
