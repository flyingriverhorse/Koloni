import { useState } from 'react'
import type { Project } from '../../api/types'
import { GUIDE } from '../guide'
import { part, Row } from './part'

/** This project › Notifications: whether an agent's notifications show on the desktop, and the day's summary. */
export function useNotifications(project: Project, desktopAvailable: boolean) {
  const [notifyDesktop, setNotifyDesktop] = useState(project.notify_desktop)
  const [dayNote, setDayNote] = useState(project.day_note_at ?? '')
  const patch = {
    ...(notifyDesktop !== project.notify_desktop && { notify_desktop: notifyDesktop }),
    ...((dayNote || null) !== project.day_note_at && { day_note_at: dayNote || null }),
  }
  return part(
    patch,
    true,
    <>
      <h2>Notifications</h2>
      <Desktop project={project} available={desktopAvailable} on={notifyDesktop} set={setNotifyDesktop} />
      <Row
        label="Send the day’s summary at"
        htmlFor="day-note-at"
        doc={GUIDE.settingsNotifications}
        why="Once a day, by this computer’s clock: Usage’s Today numbers for this project as text, shown as a desktop notification. Counted from the record; no model is asked. Empty: not sent."
      >
        <input
          id="day-note-at"
          type="time"
          className="input mono"
          value={dayNote}
          onChange={e => setDayNote(e.target.value)}
        />
      </Row>
    </>,
  )
}

/** A desktop notification, where this system shows one. */
function Desktop({
  project,
  available,
  on,
  set,
}: {
  project: Project
  available: boolean
  on: boolean
  set: (on: boolean) => void
}) {
  return (
    <>
      {/* One that is already on can still be taken off. */}
      <label className={`choice${available || on ? '' : ' choice-disabled'}`}>
        <input type="checkbox" checked={on} disabled={!available && !on} onChange={e => set(e.target.checked)} />
        <span>
          Show a desktop notification
          <span className="choice-note">
            {available
              ? `On this Windows machine, as “KOLONİ - ${project.name}”: when an agent notifies you, and when something waits for you. Off, agents have no notify tool.`
              : 'A desktop notification is not available on this system.'}
          </span>
        </span>
      </label>
    </>
  )
}
