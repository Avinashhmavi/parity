const BASE = import.meta.env.VITE_API_URL || '/api'

export class ApiError extends Error {
  constructor(message, status) {
    super(message)
    this.status = status
  }
}

async function request(path, { method = 'GET', body, signal } = {}) {
  const res = await fetch(`${BASE}${path}`, {
    method,
    signal,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined
  })
  if (!res.ok) {
    let detail = res.statusText
    try {
      const data = await res.json()
      detail = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail)
    } catch {
      /* body was not JSON */
    }
    throw new ApiError(detail, res.status)
  }
  return res.status === 204 ? null : res.json()
}

const qs = params => {
  const p = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v !== '' && v !== false && v != null) p.set(k, String(v))
  }
  const s = p.toString()
  return s ? `?${s}` : ''
}

export const api = {
  health: signal => request('/health', { signal }),
  facets: signal => request('/facets', { signal }),
  summary: signal => request('/summary', { signal }),
  board: (params, signal) => request(`/board${qs(params)}`, { signal }),
  ticket: (id, signal) => request(`/tickets/${id}`, { signal }),
  edit: (id, changes, sync = false) => request(`/tickets/${id}${qs({ sync })}`, { method: 'PATCH', body: changes }),
  syncStatus: () => request('/sync'),
  startSync: () => request('/sync', { method: 'POST' }),
  conflicts: signal => request('/conflicts', { signal }),
  activity: signal => request('/activity', { signal }),
  noise: signal => request('/noise', { signal })
}

export function socketUrl() {
  const scheme = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${scheme}//${window.location.host}/ws`
}
