import { useCallback, useEffect, useRef, useState } from 'react'
import { socketUrl } from './api.js'
import { buildQuery, parseQuery } from './lib.js'

/** Filters, view and open ticket live in the URL so every state is linkable. */
export function useUrlState() {
  const [state, setState] = useState(() => parseQuery(window.location.search))

  useEffect(() => {
    const onPop = () => setState(parseQuery(window.location.search))
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])

  const update = useCallback((patch, { push = false } = {}) => {
    setState(prev => {
      const next = { ...prev, ...patch }
      const url = `${window.location.pathname}${buildQuery(next)}`
      if (url !== `${window.location.pathname}${window.location.search}`) {
        window.history[push ? 'pushState' : 'replaceState'](null, '', url)
      }
      return next
    })
  }, [])

  return [state, update]
}

/** Runs ``load`` with an AbortSignal; ignores stale or aborted responses. */
export function useResource(load, deps) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)
  const [tick, setTick] = useState(0)

  useEffect(() => {
    const ctrl = new AbortController()
    setLoading(true)
    load(ctrl.signal)
      .then(value => {
        setData(value)
        setError(null)
      })
      .catch(err => {
        if (err.name !== 'AbortError') setError(err)
      })
      .finally(() => {
        if (!ctrl.signal.aborted) setLoading(false)
      })
    return () => ctrl.abort()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick])

  const reload = useCallback(() => setTick(t => t + 1), [])
  return { data, error, loading, reload }
}

/** One socket for the page's lifetime; the handler is read through a ref. */
export function useServerEvents(onEvent) {
  const handler = useRef(onEvent)
  handler.current = onEvent

  useEffect(() => {
    let socket
    let timer
    let closed = false
    let attempt = 0

    const connect = () => {
      socket = new WebSocket(socketUrl())
      socket.onopen = () => {
        attempt = 0
      }
      socket.onmessage = event => {
        try {
          handler.current(JSON.parse(event.data))
        } catch {
          /* ignore malformed frames */
        }
      }
      socket.onclose = () => {
        if (closed) return
        attempt += 1
        timer = setTimeout(connect, Math.min(1000 * 2 ** attempt, 15000))
      }
    }
    connect()
    return () => {
      closed = true
      clearTimeout(timer)
      socket?.close()
    }
  }, [])
}

export function useDebounced(value, ms = 250) {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return debounced
}
