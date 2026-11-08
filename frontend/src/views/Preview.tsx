/**
 * A server an agent's command keeps running, live (slice 42b): its header - where it serves, who
 * started it, how it stands; Reload, Open in browser, Stop - and its page. On its own, for any
 * window that shows one (the view window today, the Workspace window of 42c).
 */
import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { Command, Frame } from '../api/types'
import { commandStatus } from '../commands/commandStatus'

export const OpenInBrowser = ({ url }: { url: string }) => (
  <a className="view-run" href={url} target="_blank" rel="noopener noreferrer">
    Open in browser
  </a>
)

export function Preview({ command, who }: { command: Command; who: string }) {
  const url = command.preview_url
  const live = command.status === 'running'
  // Reload: the page is loaded anew.
  const [reloads, setReloads] = useState(0)
  return (
    <>
      <div className="view-where">
        <p className="mono muted" title={command.command}>
          {/* (how it stands first: what is cut short in a narrow header is where and who) */}
          <span role="status">{commandStatus(command).label}</span> · {url ?? command.command} · {who}
        </p>
        {live && url && (
          <button type="button" className="view-run" onClick={() => setReloads(reloads + 1)}>
            Reload
          </button>
        )}
        {url && <OpenInBrowser url={url} />}
        {live && (
          <button
            type="button"
            className="view-run"
            title="Stops the command, with everything it started"
            // (one already over says so on its record, which the window shows: nothing to add)
            onClick={() => void api.post(`/commands/${command.id}/stop`).catch(() => {})}
          >
            Stop
          </button>
        )}
      </div>
      <div className="view-body">
        <Page key={reloads} command={command} />
      </div>
    </>
  )
}

/**
 * Its page: in a frame of its own origin (its port is never the app's), with its scripts and
 * forms, never moving the app or opening windows. Only from its own command's output.
 */
function Page({ command }: { command: Command }) {
  const url = command.preview_url
  const live = command.status === 'running'
  const [framed, setFramed] = useState<boolean | null>(null)
  // (a page that refuses a frame shows the browser's error in it: the server is asked instead)
  useEffect(() => {
    if (!url || !live) return
    let gone = false
    api.get<Frame>(`/commands/${command.id}/frame`).then(
      answer => !gone && setFramed(answer?.frameable ?? null),
      () => {},
    )
    return () => {
      gone = true
    }
  }, [command.id, url, live])
  if (!live) return <p className="view-empty muted">It is not running any more.</p>
  if (!url) return <p className="view-empty muted">Waiting for the address it serves on…</p>
  // On the app's own port (the app opened from Vite's dev server, say), its scripts with its own
  // origin would be the app's: never framed. (URL and location both give a scheme's own port as ''.)
  const own = new URL(url).port === location.port
  if (framed === false || own) {
    return (
      <div className="view-empty muted">
        <p>{own ? 'It serves on KOLONİ’s own port: it is not shown here.' : 'This server does not allow being shown here.'}</p>
        <OpenInBrowser url={url} />
      </div>
    )
  }
  return <iframe className="view-frame" title={`Preview of ${url}`} src={url} sandbox="allow-scripts allow-same-origin allow-forms" />
}
