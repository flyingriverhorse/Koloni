import { Play, Stop } from '@phosphor-icons/react'
import { useEffect, useState } from 'react'
import { api, errorText } from '../api/client'
import type { Hold } from '../api/types'
import { usePanel } from './usePanel'

const many = (n: number, one: string) => `${n} ${one}${n === 1 ? '' : 's'}`
const OWN = 'Your own messages still run: only what starts by itself is held.'
/** The answer as the server gives it, or null: anything else is taken for not held, and nothing is shown. */
const shaped = (found: unknown) => (found && typeof found === 'object' && ['stopped', 'backlogs', 'nights'].every(key => Array.isArray((found as Record<string, unknown>)[key])) ? (found as Hold) : null)
const MISSED = 'After Resume a trigger waits for its next time: times missed while held are skipped, also for triggers that catch up, and files changed meanwhile start nothing.'

/** What Stop everything would hold: the triggers that are on, the backlogs that work themselves, the nights. */
function heldNow(hold: Hold): string {
  const counts: [number, string][] = [
    [hold.triggers, many(hold.triggers, 'trigger')],
    [hold.backlogs.length, many(hold.backlogs.length, 'backlog')],
    [hold.nights.length, `${many(hold.nights.length, 'project')} working while you’re away`],
  ]
  const parts = counts.filter(([n]) => n > 0).map(([, said]) => said)
  if (parts.length === 0) return 'Triggers and backlogs are held until you resume.'
  const named = parts.length > 1 ? `${parts.slice(0, -1).join(', ')} and ${parts.at(-1)}` : parts[0]
  return `${named} ${counts.reduce((sum, [n]) => sum + n, 0) === 1 ? 'is' : 'are'} held until you resume.`
}

/**
 * In the top bar, on every page: one Stop for every turn of every chat. It asks first, saying what runs and what will
 * be held; then lists what it stopped and what it holds, with Resume. While held, the bar says so.
 */
export function HoldStatus({ every, onOpen, onHeld }: { every: number; onOpen: (conversationId: string) => void; onHeld?: (held: boolean) => void }) {
  const [hold, setHold] = useState<Hold | null>(null)
  const held = Boolean(hold?.held)
  useEffect(() => onHeld?.(held), [held, onHeld])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const { open, setOpen, close, button, panel } = usePanel()
  // Read as often as the Board, and again as the panel opens: what it asks about is how things stand now.
  useEffect(() => {
    let live = true
    const read = () => void api.get<Hold>('/hold').then(found => live && setHold(shaped(found)), () => {})
    read()
    const timer = setInterval(() => document.hidden || read(), every)
    return () => {
      live = false
      clearInterval(timer)
    }
  }, [every, open])

  async function ask(path: string) {
    setBusy(true)
    setError(null)
    try {
      const found = await api.post<Hold>(path)
      setHold(shaped(found))
      if (!shaped(found)?.held) close()
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  if (!hold) return null
  // One line for each chat, however many of its turns stopped.
  const chats = new Map<string, { title: string; turns: number; project: string | null; at: string }>()
  for (const { conversation_id, title, project, created_at } of hold.stopped) {
    const was = chats.get(conversation_id)
    // (Listed by when they ended, last first: a chat's line keeps the time of its turn that ended last.)
    chats.set(conversation_id, { title, project, at: was?.at ?? created_at, turns: (was?.turns ?? 0) + 1 })
  }
  const time = (at: string, second = false) => new Date(at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', ...(second && { second: '2-digit' }) })
  // B-175: chats of one title are told apart by their projects where those differ, else by when the turn was sent -
  // to the second where two were sent in one minute (B-180).
  // shortcut: two sent in one second still read alike; number them if that is seen.
  const apart = (chat: { title: string; project: string | null; at: string }) => {
    const same = [...chats.values()].filter(other => other.title === chat.title)
    if (same.length < 2) return null
    const minute = same.filter(other => time(other.at) === time(chat.at)).length > 1
    return (new Set(same.map(other => other.project)).size === same.length && chat.project) || time(chat.at, minute)
  }
  const told = new Map([...chats].map(([cid, chat]) => [cid, apart(chat)]))
  const since = hold.since && time(hold.since)
  return (
    <>
      <button
        ref={button}
        type="button"
        className={`btn${hold.held ? ' hold-held' : ''}`}
        // (Named here: in a narrow window its words are not shown, theme/triggers.css.)
        aria-label={hold.held ? 'Held · Resume' : 'Stop everything'}
        aria-expanded={open}
        title={hold.held ? 'Held: what was stopped and what is held, and Resume' : 'Stop every turn in every chat, and hold triggers and backlogs'}
        onClick={() => (open ? close() : setOpen(true))}
      >
        {hold.held ? <Play size={13} /> : <Stop size={13} weight="fill" />}
        <span className="hold-words">
          {hold.held ? (
            <>
              Held<span className="hold-resume"> · Resume</span>
            </>
          ) : (
            'Stop everything'
          )}
        </span>
      </button>
      {open && (
        <div ref={panel} tabIndex={-1} className="allow-list-panel hold-panel" role="dialog" aria-label={hold.held ? 'Everything is held' : 'Stop everything'}>
          {hold.held ? (
            <>
              <div className="kicker">Everything is held{since && ` since ${since}`}</div>
              <section aria-label="Stopped">
                <div className="kicker">Stopped</div>
                {hold.stopping > 0 && <p className="muted">{many(hold.stopping, 'turn')} still stopping…</p>}
                {chats.size === 0 ? (
                  hold.stopping === 0 && <p className="muted">Nothing was running.</p>
                ) : (
                  <ul className="hold-list">
                    {[...chats].map(([cid, chat]) => (
                      <li key={cid}>
                        <button
                          type="button"
                          className="link-btn"
                          onClick={() => {
                            onOpen(cid)
                            close()
                          }}
                        >
                          {chat.title}
                        </button>
                        {told.get(cid) && <span className="muted"> · {told.get(cid)}</span>}
                        {chat.turns > 1 && <span className="muted"> · {chat.turns} turns</span>}
                      </li>
                    ))}
                  </ul>
                )}
              </section>
              <section aria-label="Held">
                <div className="kicker">Held</div>
                <ul className="hold-list">
                  <li>{hold.triggers > 0 ? `${many(hold.triggers, 'trigger')} on` : 'Triggers'}</li>
                  {hold.backlogs.map(name => (
                    <li key={name}>Backlog of {name}: its next task waits</li>
                  ))}
                  {hold.nights.map(name => (
                    <li key={`night ${name}`}>While you’re away · {name}: its next job waits</li>
                  ))}
                  <li>New work while you’re away</li>
                </ul>
              </section>
              <p className="muted">{MISSED}</p>
              <p className="muted">{OWN}</p>
              {/* R147: Resume lets go of what starts by itself only - in the server's words. */}
              {hold.stays_stopped && <p>Resume: {hold.stays_stopped}</p>}
              <div className="change-actions">
                <button type="button" className="btn btn-small btn-primary" disabled={busy} onClick={() => void ask('/hold/resume')}>
                  <Play size={13} />
                  Resume
                </button>
              </div>
            </>
          ) : (
            <>
              <div className="kicker">Stop everything?</div>
              <p>
                {hold.running === 0 ? 'No turn is running now.' : `${many(hold.running, 'turn')} running in your chats will stop.`} {heldNow(hold)}
              </p>
              <p className="muted">{MISSED}</p>
              <p className="muted">{OWN} Previews left serving keep running.</p>
              <div className="change-actions">
                <button type="button" className="btn btn-small btn-danger" disabled={busy} onClick={() => void ask('/hold')}>
                  <Stop size={13} weight="fill" />
                  {busy ? 'Stopping…' : 'Stop everything'}
                </button>
                <button type="button" className="btn btn-small" onClick={close}>
                  Cancel
                </button>
              </div>
            </>
          )}
          {error && (
            <div role="alert" className="alert">
              {error}
            </div>
          )}
        </div>
      )}
    </>
  )
}
