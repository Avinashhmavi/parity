import { useEffect, useRef } from 'react'
import { STAGES, STEP_TEXT } from '../lib.js'
import { CloseIcon } from './icons.jsx'

/** First-visit guide, and the Help page. A native <dialog> gives focus handling and Escape for free. */
export function Welcome({ open, onClose, onTour }) {
  const ref = useRef(null)

  useEffect(() => {
    const dialog = ref.current
    if (!dialog) return undefined
    if (open && !dialog.open) {
      dialog.showModal()
      dialog.focus({ preventScroll: true }) // start at the top of the guide, not on the close button
    }
    if (!open && dialog.open) dialog.close()
    return undefined
  }, [open])

  return (
    <dialog ref={ref} className="welcome" tabIndex={-1} aria-labelledby="welcome-title" onClose={onClose} onClick={e => e.target === ref.current && onClose()}>
      <div className="welcome-body">
        <button type="button" className="btn btn-quiet welcome-close" onClick={onClose} aria-label="Close help">
          <CloseIcon />
        </button>
        <h2 id="welcome-title">Welcome. Here is how this works.</h2>
        <p className="lead">
          FieldServe installs and looks after security equipment (cameras, alarms, door access) in OmniMart stores. Every piece of work is a <b>job</b>. This page shows what each job is waiting for, and whose turn it is.
        </p>

        <ol className="how">
          <li>
            <b>See what is stuck.</b> Every job shows its <em>next step</em> and the person who needs to do it.
          </li>
          <li>
            <b>Find your jobs.</b> Use <em>People</em> to see who has work waiting, or search by store, name or job number.
          </li>
          <li>
            <b>Fix it right here.</b> Open a job, change it, press <em>Save changes</em>. FieldServe is updated for you.
          </li>
        </ol>

        <h3>Every job goes through six steps, in this order</h3>
        <ol className="six">
          {STAGES.map(s => (
            <li key={s}>
              <b>{STEP_TEXT[s].name}.</b> {STEP_TEXT[s].about}
            </li>
          ))}
        </ol>

        <h3>What the words mean</h3>
        <dl className="glossary">
          <dt>Next step</dt>
          <dd>The first of the six steps that is not finished yet.</dd>
          <dt>Needs a look</dt>
          <dd>Something doesn’t add up, for example a job marked Closed that is still missing its Invoice.</dd>
          <dt>Update Now</dt>
          <dd>Fetches the newest jobs from FieldServe and sends them the changes you saved. It also happens by itself every couple of minutes.</dd>
        </dl>

        <div className="welcome-actions">
          <button type="button" className="btn btn-primary btn-lg" onClick={onTour}>
            Show me the overview
          </button>
          <button type="button" className="btn btn-lg" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </dialog>
  )
}
