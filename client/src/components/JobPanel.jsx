import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api.js'
import { useResource } from '../hooks.js'
import { changedFields, draftFrom, explainProblem, formatDate, nextAction, STATUS_TEXT, STEP_TEXT } from '../lib.js'
import { CheckIcon, CloseIcon, ExternalIcon, ProblemIcon } from './icons.jsx'
import { DocChip, Notice, Skeleton, StatusChip, StepDots } from './ui.jsx'

const DOCS = [
  { key: 'purchase_order', label: 'Purchase Order', help: 'The customer’s written approval. Paste the link.' },
  { key: 'delivery_note', label: 'Delivery Note', help: 'Proof parts reached the store. Paste the link, or press “Not needed” if nothing was delivered.', canSkip: true },
  { key: 'work_report', label: 'Work Report', help: 'The engineer’s report that the work is done. Paste the link. This one can never be skipped.' },
  { key: 'invoice', label: 'Invoice', help: 'The bill for the customer. Paste the link, or press “Not needed” (for example work under warranty).', canSkip: true }
]

export function JobPanel({ id, refreshKey, onClose, onSaved, notify, canSync }) {
  const ref = useRef(null)
  const { data: job, error, loading, reload } = useResource(signal => api.ticket(id, signal), [id, refreshKey])
  const [draft, setDraft] = useState(null)
  const [saving, setSaving] = useState(false)
  const [problem, setProblem] = useState('')
  const [saved, setSaved] = useState('')

  useEffect(() => {
    const dialog = ref.current
    if (dialog && !dialog.open) {
      dialog.showModal()
      dialog.focus({ preventScroll: true })
    }
    return () => dialog?.open && dialog.close()
  }, [])

  useEffect(() => {
    if (job) setDraft(draftFrom(job))
  }, [job])

  const changes = useMemo(() => (job && draft ? changedFields(draftFrom(job), draft) : {}), [job, draft])
  const dirty = Object.keys(changes).length > 0

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
    if (dirty && !window.confirm('You have changes that are not saved. Leave without saving?')) return
    onClose()
  }

  const save = async () => {
    setSaving(true)
    setProblem('')
    setSaved('')
    try {
      await api.edit(id, changes, canSync)
      setSaved(canSync ? 'Saved. FieldServe now has your changes.' : 'Saved in the sheet. It will be sent to FieldServe on the next update.')
      notify(canSync ? 'Saved and sent to FieldServe.' : 'Saved. It will be sent on the next update.')
      onSaved()
      reload()
    } catch (err) {
      setProblem(err.message)
    } finally {
      setSaving(false)
    }
  }

  const set = (key, value) => {
    setSaved('')
    setDraft(d => ({ ...d, [key]: value }))
  }
  const problems = job ? job.integrity.map(explainProblem) : []

  return (
    <dialog
      ref={ref}
      className="panel"
      tabIndex={-1}
      aria-labelledby="panel-title"
      onCancel={e => {
        if (dirty && !window.confirm('You have changes that are not saved. Leave without saving?')) e.preventDefault()
        else onClose()
      }}
      onClick={e => e.target === ref.current && requestClose()}
    >
      <div className="panel-body">
        <header className="panel-head">
          <div className="grow">
            <span className="job-id" translate="no">
              Job #{id}
            </span>
            <h2 id="panel-title">{job?.subject ?? 'Loading…'}</h2>
            {job && (
              <p className="muted">
                {[job.store && `Store: ${job.store}`, job.storeCode && `Code ${job.storeCode}`, job.jobType && `${job.jobType} job`, `Changed ${formatDate(job.updatedAt)}`].filter(Boolean).join('  ·  ')}
              </p>
            )}
          </div>
          <button type="button" className="btn btn-quiet" onClick={requestClose} aria-label="Close this job">
            <CloseIcon />
            Close
          </button>
        </header>

        <div className="panel-scroll">
          {error && <p className="error" role="alert">{error.message}</p>}
          {loading && !job && <Skeleton rows={4} />}
          {job && draft && (
            <>
              <section className="next" data-done={job.stage === 'Done'} aria-labelledby="next-h">
                <h3 id="next-h">What happens next</h3>
                <p className="next-text">{nextAction(job)}</p>
                <StepDots stage={job.stage} />
              </section>

              {problems.length > 0 && (
                <section className="problems" aria-labelledby="prob-h">
                  <h3 id="prob-h">
                    <ProblemIcon /> This job needs a look
                  </h3>
                  <ul>
                    {problems.map(p => (
                      <li key={p.title}>
                        <b>{p.title}</b>
                        {p.help && <span>{p.help}</span>}
                      </li>
                    ))}
                  </ul>
                </section>
              )}

              {job.unsynced?.length > 0 && (
                <Notice tone="amber" title="A change here hasn’t reached FieldServe yet">
                  It will be sent on the next update ({job.unsynced.join(', ')}). Press <b>Update Now</b> at the top to send it right away.
                </Notice>
              )}

              <section aria-labelledby="prog-h">
                <h3 id="prog-h">Progress</h3>
                <ol className="checklist">
                  {job.steps.map((s, i) => {
                    const t = STEP_TEXT[s.label]
                    const waived = s.detail === 'waived'
                    return (
                      <li key={s.key} data-s={s.status}>
                        <span className="tick" aria-hidden="true">
                          {s.status === 'complete' ? <CheckIcon size={16} /> : i + 1}
                        </span>
                        <span>
                          <b>{s.status === 'complete' ? (waived ? `${t.name}: not needed` : t.done) : t.name}</b>
                          <small>
                            {s.status === 'complete' && (s.owner ? `Responsible: ${s.owner}` : 'Done')}
                            {s.status === 'pending' && `${s.owner || 'Someone on the team'} needs to ${t.todo}.`}
                            {s.status === 'upcoming' && 'Comes later, once the steps above are finished.'}
                            {s.detail && s.detail !== 'waived' ? ` (${s.detail})` : ''}
                          </small>
                        </span>
                      </li>
                    )
                  })}
                </ol>
              </section>

              <form
                id="job-form"
                className="form"
                aria-label="Update this job"
                onSubmit={e => {
                  e.preventDefault()
                  if (dirty && !saving) save()
                }}
              >
                <h3>Update this job</h3>
                <p className="muted">Change anything below, then press <b>Save changes</b>.</p>

                <div className="field">
                  <label htmlFor="f-status">Where is the job?</label>
                  <select id="f-status" className="select" value={draft.status} onChange={e => set('status', e.target.value)}>
                    {job.options.status.map(s => (
                      <option key={s} value={s}>
                        {STATUS_TEXT[s] ?? s}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="two">
                  <div className="field">
                    <label htmlFor="f-manager">Manager in charge</label>
                    <select id="f-manager" className="select" value={draft.manager} onChange={e => set('manager', e.target.value)}>
                      <option value="">Nobody yet</option>
                      {draft.manager && !job.options.managers.includes(draft.manager) && <option>{draft.manager}</option>}
                      {job.options.managers.map(m => (
                        <option key={m}>{m}</option>
                      ))}
                    </select>
                  </div>
                  <div className="field">
                    <label htmlFor="f-engineer">Engineer going to the store</label>
                    <select id="f-engineer" className="select" value={draft.engineer} onChange={e => set('engineer', e.target.value)}>
                      <option value="">Nobody yet</option>
                      {draft.engineer && !job.options.engineers.includes(draft.engineer) && <option>{draft.engineer}</option>}
                      {job.options.engineers.map(m => (
                        <option key={m}>{m}</option>
                      ))}
                    </select>
                  </div>
                </div>

                {DOCS.map(({ key, label, help, canSkip }) => {
                  const doc = job.documents[key]
                  return (
                    <div key={key} className="field">
                      <div className="label-row">
                        <label htmlFor={`f-${key}`}>{label}</label>
                        <span className="doc-state">
                          {doc.state === 'url' && (
                            <a href={doc.value} target="_blank" rel="noreferrer noopener" aria-label={`Open the ${label} in a new tab`}>
                              Open <ExternalIcon size={14} />
                            </a>
                          )}
                          <DocChip state={doc.state} />
                        </span>
                      </div>
                      <div className="doc-input">
                        <input
                          id={`f-${key}`}
                          className="input"
                          type="text"
                          inputMode="url"
                          autoComplete="off"
                          spellCheck={false}
                          placeholder="Paste the link here"
                          value={draft[key]}
                          onChange={e => set(key, e.target.value)}
                        />
                        {canSkip && (
                          <button type="button" className="btn" onClick={() => set(key, 'NA')} disabled={draft[key] === 'NA'}>
                            Not needed
                          </button>
                        )}
                      </div>
                      <p className="hint">
                        {help}
                        {doc.state === 'junk' && <> Right now it says “{doc.value}”, which is not a link.</>}
                      </p>
                    </div>
                  )
                })}
              </form>
              <div aria-live="polite">
                {problem && <Notice tone="red" title="That couldn’t be saved">{problem}</Notice>}
                {saved && !dirty && <Notice tone="green" title={saved} icon={<CheckIcon />} />}
              </div>
            </>
          )}
        </div>

        <footer className="panel-foot">
          <span className="muted grow">{dirty ? `You have ${Object.keys(changes).length} unsaved ${Object.keys(changes).length === 1 ? 'change' : 'changes'}.` : 'No changes yet.'}</span>
          <button type="button" className="btn btn-lg" onClick={() => job && setDraft(draftFrom(job))} disabled={!dirty || saving}>
            Undo changes
          </button>
          <button type="submit" form="job-form" className="btn btn-primary btn-lg" disabled={!dirty || saving}>
            {saving ? 'Saving…' : 'Save changes'}
          </button>
        </footer>
      </div>
    </dialog>
  )
}

export { StatusChip }
