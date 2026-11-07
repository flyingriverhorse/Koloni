import { useState } from 'react'
import type { Project } from '../../api/types'
import { GUIDE } from '../guide'
import { part, Row } from './part'

/** This project › Notifications: where an agent's notifications go, in what form, and the day's summary. */
export function useNotifications(project: Project, desktopAvailable: boolean) {
  // The notification address is a secret: the one that is set is never read back, only replaced or removed.
  const [notifyUrl, setNotifyUrl] = useState('')
  const [removeNotify, setRemoveNotify] = useState(false)
  const [notifyFormat, setNotifyFormat] = useState(project.notify_format)
  const [notifyDesktop, setNotifyDesktop] = useState(project.notify_desktop)
  const [dayNote, setDayNote] = useState(project.day_note_at ?? '')
  const patch = {
    ...(notifyUrl.trim() ? { notify_url: notifyUrl.trim() } : removeNotify && { notify_url: '' }),
    ...(notifyFormat !== project.notify_format && { notify_format: notifyFormat }),
    ...(notifyDesktop !== project.notify_desktop && { notify_desktop: notifyDesktop }),
    ...((dayNote || null) !== project.day_note_at && { day_note_at: dayNote || null }),
  }
  // The address is now the one that is set, which is never shown again.
  const saved = () => {
    setNotifyUrl('')
    setRemoveNotify(false)
  }
  return part(
    patch,
    true,
    <>
      <h2>Notifications</h2>
      <Row
        label="Notification address"
        htmlFor="notify-url"
        doc={GUIDE.settingsNotifications} why="Your webhook (Slack, Discord, ntfy or your own service). Agents’ notifications are posted there in the format below; an agent never picks the address."
        warn={
          <span id="notify-url-note" className="choice-note">
            {project.has_notify_url ? 'A notification address is set. It is not shown again; type a new one to replace it.' : 'No notification address is set.'}
          </span>
        }
      >
        <input id="notify-url" className="input mono" value={notifyUrl} maxLength={500} autoComplete="off" placeholder="https://hooks.example.com/…" aria-describedby="notify-url-note" onChange={e => setNotifyUrl(e.target.value)} />
      </Row>
      <Row label="Post it as" htmlFor="notify-format">
        <select id="notify-format" className="input" value={notifyFormat} onChange={e => setNotifyFormat(e.target.value as Project['notify_format'])}>
          <option value="slack">{'JSON {"text": …} - Slack, Mattermost'}</option>
          <option value="discord">{'JSON {"content": …} - Discord'}</option>
          <option value="text">Plain text - ntfy</option>
        </select>
      </Row>
      <Desktop project={project} available={desktopAvailable} on={notifyDesktop} set={setNotifyDesktop} />
      {project.has_notify_url && !notifyUrl.trim() && (
        <label className="choice">
          <input type="checkbox" checked={removeNotify} onChange={e => setRemoveNotify(e.target.checked)} />
          <span>Remove the notification address</span>
        </label>
      )}
      <Row
        label="Send the day’s summary at"
        htmlFor="day-note-at"
        doc={GUIDE.settingsNotifications} why="Once a day, by this computer’s clock: the Board’s Today numbers as text, sent to the address and the desktop above. Counted from the record; no model is asked. Empty: not sent."
      >
        <input id="day-note-at" type="time" className="input mono" value={dayNote} onChange={e => setDayNote(e.target.value)} />
      </Row>
    </>,
    { saved },
  )
}

/** A desktop notification, where this system shows one. */
function Desktop({ project, available, on, set }: { project: Project; available: boolean; on: boolean; set: (on: boolean) => void }) {
  return (
    <>
      {/* One that is already on can still be taken off. */}
      <label className={`choice${available || on ? '' : ' choice-disabled'}`}>
        <input type="checkbox" checked={on} disabled={!available && !on} onChange={e => set(e.target.checked)} />
        <span>
          Show a desktop notification
          <span className="choice-note">
            {available
              ? `On this Windows machine, as “KOLONİ - ${project.name}”: when an agent notifies you, and when something waits for you. With an address too, an agent’s notifications go to both. With neither, agents have no notify tool.`
              : 'A desktop notification is not available on this system.'}
          </span>
        </span>
      </label>
    </>
  )
}
