import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api.js'
import { useResource } from '../hooks.js'
import { changedFields, draftFrom, formatTime } from '../lib.js'
import { CheckIcon, Close, External, InfoIcon } from './icons.jsx'
import { Chip, DocChip, Progress, Skeleton, StatusChip } from './ui.jsx'

const DOCS = [
  { key: 'purchase_order', label: 'Purchase Order', hint: 'A link. NA is not accepted.' },
  { key: 'delivery_note', label: 'Delivery Note', hint: 'A link, or NA if nothing was delivered.' },
  { key: 'work_report', label: 'Work Report', hint: 'A link. NA is never accepted.' },
  { key: 'invoice', label: 'Invoice', hint: 'A link, or NA (for example under warranty).' }
]

export function Drawer({ id, refreshKey, onClose, onSaved, notify }) {
  const ref = useRef(null)
  const { data, error, loading, reload } = useResource(signal => api.ticket(id, signal), [id, refreshKey])
  const [draft, setDraft] = useState(null)
  const [saving, setSaving] = useState(false)
  const [problem, setProblem] = useState('')

  // Native <dialog> gives us the focus trap, Escape and inert background.
  useEffect(() => {
    const dialog = ref.current
    if (dialog && !dialog.open) {
      dialog.showModal()
      dialog.focus({ preventScroll: true }) // land on the panel, not on the close button
    }
    return () => dialog?.open && dialog.close()
  }, [])

  useEffect(() => {
    if (data) {
      setDraft(draftFrom(data))
      setProblem('')
    }
  }, [data])

  const changes = useMemo(() => (data && draft ? changedFields(draftFrom(data), draft) : {}), [data, draft])
  const dirty = Object.keys(changes).length > 0

  // Warn before a reload or tab close throws away typing.
  useEffect(() => {
    if (!dirty) return undefined
    const warn = e => {
      e.preventDefault()
      e.returnValue = ''
    }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [dirty])

  const requestClose = () => {
    if (dirty && !window.confirm('Discard your unsaved changes?')) return
    onClose()
  }

  const save = async syncNow => {
    setSaving(true)
    setProblem('')
    try {
      await api.edit(id, changes, syncNow)
      notify(syncNow ? 'Saved and synced.' : 'Saved to the sheet. It will be pushed on the next sync.')
      onSaved()
      reload()
    } catch (err) {
      setProblem(err.message)
    } finally {
      setSaving(false)
    }
  }

  const set = (key, value) => setDraft(d => ({ ...d, [key]: value }))
  const pending = data?.steps.find(s => s.status === 'pending')

  return (
    <dialog
      ref={ref}
      className="drawer"
      tabIndex={-1}
      aria-labelledby="drawer-title"
      onCancel={e => {
        if (dirty && !window.confirm('Discard your unsaved changes?')) e.preventDefault()
        else onClose()
      }}
      onClick={e => e.target === ref.current && requestClose()}
    >
      <div className="drawer-body">
        <header className="drawer-head">
          <div style={{ minWidth: 0 }}>
            <span className="mono muted" translate="no">
              Ticket #{id}
            </span>
            <h2 id="drawer-title">{data?.subject ?? 'Loading…'}</h2>
            {data && (
              <div className="meta">
                <StatusChip status={data.status} />
                {data.storeCode && <Chip><span className="mono" translate="no">{data.storeCode}</span></Chip>}
                {data.store && <span>{data.store}</span>}
                {data.jobType && <Chip>{data.jobType}</Chip>}
                <span className="muted">Updated {formatTime(data.updatedAt)}</span>
              </div>
            )}
          </div>
          <button type="button" className="btn btn-icon btn-ghost" aria-label="Close ticket" onClick={requestClose}>
            <Close size={18} />
          </button>
        </header>

        <div className="drawer-scroll">
          {error && <p className="error" role="alert">{error.message}</p>}
          {loading && !data && <Skeleton rows={5} />}
          {data && draft && (
            <>
              <div className="callout" data-done={data.stage === 'Done'}>
                {data.stage === 'Done' ? (
                  <>
                    <strong>All six steps are complete</strong>
                    <small>Nobody needs to act on this ticket.</small>
                  </>
                ) : (
                  <>
                    <small>Waiting on</small>
                    <strong>{data.actionOwner || 'Nobody on the roster'}</strong>
                    <small>for {data.stage}</small>
                  </>
                )}
              </div>

              {data.integrity.length > 0 && (
                <div className="banner" role="alert" style={{ margin: 0 }}>
                  <InfoIcon size={18} />
                  <ul style={{ margin: 0, paddingLeft: '1.1rem' }}>
                    {data.integrity.map(i => (
                      <li key={i}>{i}</li>
                    ))}
                  </ul>
                </div>
              )}

              {data.unsynced?.length > 0 && (
                <div className="unsynced" role="status">
                  <InfoIcon size={16} />
                  <span>
                    Edited in the sheet, not yet pushed: <b>{data.unsynced.join(', ')}</b>.
                  </span>
                </div>
              )}

              <section aria-labelledby="steps-h">
                <h3 id="steps-h" style={{ marginBottom: '0.9rem', fontSize: '0.9rem' }}>
                  Workflow <span style={{ marginLeft: '0.5rem', verticalAlign: 'middle' }}><Progress stage={data.stage} /></span>
                </h3>
                <ol className="steps">
                  {data.steps.map((s, i) => (
                    <li key={s.key} data-s={s.status}>
                      <span className="step-ico" aria-hidden="true">
                        {s.status === 'complete' ? <CheckIcon size={13} /> : i + 1}
                      </span>
                      <div>
                        <div className="step-title">
                          <strong>{s.label}</strong>
                          <span className="sub">
                            {s.status === 'complete' ? (s.detail === 'waived' ? 'Waived' : 'Complete') : s.status === 'pending' ? 'Pending' : 'Not reached'}
                            {s.detail && s.detail !== 'waived' ? ` · ${s.detail}` : ''}
                          </span>
                        </div>
                        <div className="sub">{s.owner ? `Owner: ${s.owner}` : 'Owner: nobody on the roster'}</div>
                      </div>
                    </li>
                  ))}
                </ol>
              </section>

              <form
                id="ticket-form"
                onSubmit={e => {
                  e.preventDefault()
                  if (dirty && !saving) save(false)
                }}
                className="formgrid"
                aria-label="Edit ticket"
              >
                <div className="field">
                  <label htmlFor="f-status">Status</label>
                  <select id="f-status" name="status" className="select" value={draft.status} onChange={e => set('status', e.target.value)}>
                    {data.options.status.map(s => (
                      <option key={s}>{s}</option>
                    ))}
                  </select>
                </div>
                <div className="field">
                  <label htmlFor="f-manager">Manager</label>
                  <select id="f-manager" name="manager" className="select" value={draft.manager} onChange={e => set('manager', e.target.value)}>
                    <option value="">Unassigned</option>
                    {draft.manager && !data.options.managers.includes(draft.manager) && <option>{draft.manager}</option>}
                    {data.options.managers.map(m => (
                      <option key={m}>{m}</option>
                    ))}
                  </select>
                </div>
                <div className="field wide">
                  <label htmlFor="f-engineer">Engineer</label>
                  <select id="f-engineer" name="engineer" className="select" value={draft.engineer} onChange={e => set('engineer', e.target.value)}>
                    <option value="">Unassigned</option>
                    {draft.engineer && !data.options.engineers.includes(draft.engineer) && <option>{draft.engineer}</option>}
                    {data.options.engineers.map(m => (
                      <option key={m}>{m}</option>
                    ))}
                  </select>
                </div>
                {DOCS.map(({ key, label, hint }) => {
                  const saved = data.documents[key]
                  return (
                    <div key={key} className="docrow wide">
                      <div className="head">
                        <label htmlFor={`f-${key}`} style={{ fontSize: '0.8125rem', fontWeight: 500, color: 'var(--ink-2)' }}>
                          {label}
                        </label>
                        <span style={{ display: 'inline-flex', gap: '0.4rem', alignItems: 'center' }}>
                          {saved.state === 'url' && (
                            <a href={saved.value} target="_blank" rel="noreferrer noopener" className="sub" aria-label={`Open ${label} in a new tab`}>
                              <External size={13} />
                            </a>
                          )}
                          <DocChip state={saved.state} />
                        </span>
                      </div>
                      <input
                        id={`f-${key}`}
                        name={key}
                        className="input"
                        type="text"
                        inputMode="url"
                        autoComplete="off"
                        spellCheck={false}
                        placeholder="https://files.example/…  or NA"
                        value={draft[key]}
                        onChange={e => set(key, e.target.value)}
                      />
                      <p className="hint">{hint}</p>
                    </div>
                  )
                })}
              </form>
              <div aria-live="polite">{problem && <p className="error">{problem}</p>}</div>
            </>
          )}
        </div>

        <footer className="drawer-foot">
          <span className="sub" style={{ marginRight: 'auto', alignSelf: 'center' }}>
            {dirty ? `${Object.keys(changes).length} unsaved change${Object.keys(changes).length === 1 ? '' : 's'}` : pending ? `Next: ${pending.label}` : ''}
          </span>
          <button type="button" className="btn" onClick={() => draft && data && setDraft(draftFrom(data))} disabled={!dirty || saving}>
            Revert
          </button>
          <button type="submit" form="ticket-form" className="btn" disabled={!dirty || saving}>
            {saving ? 'Saving…' : 'Save to Sheet'}
          </button>
          <button type="button" className="btn btn-primary" disabled={!dirty || saving} onClick={() => save(true)}>
            Save &amp; Sync
          </button>
        </footer>
      </div>
    </dialog>
  )
}
