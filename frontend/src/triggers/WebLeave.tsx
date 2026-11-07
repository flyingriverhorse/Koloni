import { useEffect, useState } from 'react'
import { errorText } from '../api/client'

interface Props {
  /** The conversation the trigger's turns go into: the hosts are that conversation's. */
  conversationId: string
  web: boolean
  /** The ticked hosts. */
  hosts: string[]
  notify: boolean
  onChange: (change: { web?: boolean; hosts?: string[]; notify?: boolean }) => void
  /** Read the hosts a conversation makes GET requests to without asking. */
  onHosts: (conversationId: string) => Promise<string[]>
}

/**
 * What a trigger's turns may send out of this machine with nobody watching: a web search, a
 * request to a host, a notification. A host is ticked from the list of its conversation -
 * the ones "Always allow GET to …" put there - and never typed. One the trigger already has
 * is listed too, so that it can be seen and unticked.
 */
export function WebLeave({ conversationId, web, hosts, notify, onChange, onHosts }: Props) {
  const [read, setRead] = useState<{ of: string; hosts: string[] } | null>(null)
  const [failed, setFailed] = useState<string | null>(null)

  useEffect(() => {
    if (!conversationId) return
    let current = true
    onHosts(conversationId).then(
      found => {
        if (!current) return
        setRead({ of: conversationId, hosts: found })
        setFailed(null)
      },
      err => {
        if (current) setFailed(errorText(err))
      },
    )
    return () => {
      current = false
    }
  }, [conversationId, onHosts])

  const listed = read?.of === conversationId ? read.hosts : null
  const shown = listed && [...new Set([...listed, ...hosts])]

  return (
    <>
      <label className="choice" htmlFor="trigger-web">
        <input id="trigger-web" type="checkbox" aria-label="May search the web" checked={web} aria-describedby="trigger-web-note" onChange={e => onChange({ web: e.target.checked })} />
        <span>
          May search the web
          <span id="trigger-web-note" className="choice-note">
            Its work searches the web without asking you. The query leaves this machine.
          </span>
        </span>
      </label>
      {conversationId && (
        <fieldset className="trigger-leave" aria-label="May make requests to these hosts">
          <legend>May make requests to these hosts</legend>
          <p className="choice-note">With nobody watching, a ticked host is asked with GET and HEAD only - over https on its usual port, unless it is written here with another scheme and port - and a redirect to anywhere else is not followed. Nothing on this machine or its network is ever reached.</p>
          {failed && (
            <div role="alert" className="alert">
              {failed}
            </div>
          )}
          {shown === null && !failed && <p className="muted trigger-note">Reading this conversation’s list…</p>}
          {shown?.length === 0 && (
            <p className="muted trigger-note">This conversation has no allowed hosts yet. A host gets on its list when you answer a request in the chat with “Always allow GET to …”.</p>
          )}
          {shown?.map(host => (
            <label key={host} className="choice">
              <input type="checkbox" checked={hosts.includes(host)} onChange={event => onChange({ hosts: event.target.checked ? [...hosts, host] : hosts.filter(other => other !== host) })} />
              <span className="mono">{host}</span>
            </label>
          ))}
        </fieldset>
      )}
      <label className="choice" htmlFor="trigger-notify">
        <input id="trigger-notify" type="checkbox" aria-label="May send you notifications" checked={notify} aria-describedby="trigger-notify-note" onChange={e => onChange({ notify: e.target.checked })} />
        <span>
          May send you notifications
          <span id="trigger-notify-note" className="choice-note">
            Where the project’s settings say - your desktop, your notification address - and nowhere else. With neither set there is no such tool.
          </span>
        </span>
      </label>
    </>
  )
}
