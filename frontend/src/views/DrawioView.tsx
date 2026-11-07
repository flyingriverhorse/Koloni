/**
 * A draw.io diagram in the Files window (K-drawio): drawn by the vendored viewer, /drawio/viewer.html, in a sandboxed
 * frame of an origin of its own whose page loads nothing but its own files (`app.views.VIEWER_HEADERS`). The app reads the
 * file and posts its text in; zoom, pages and layers are the viewer's. Save as PNG / SVG: the frame draws the picture and
 * the app writes it beside the diagram, by its name - the user's own write, no card.
 */
import { useEffect, useRef, useState } from 'react'
import { api, errorText } from '../api/client'

type Format = 'png' | 'svg'
/** What the frame says: drawn, or the picture asked for, or why not. */
type Said = { shown: true } | { failed: string } | { saved: Format; data: string }

/** A text's UTF-8 bytes as base64 (an SVG can hold any letter). */
function base64Of(text: string) {
  let bytes = ''
  for (const byte of new TextEncoder().encode(text)) bytes += String.fromCharCode(byte)
  return btoa(bytes)
}

/** Where its picture goes: beside it, by its name (as the server's `diagram.picture_of`). */
const pictureOf = (path: string, format: Format) => path.replace(/\.(drawio\.xml|drawio|dio)$/i, `.${format}`)

export function DrawioView({ src, path, projectId }: { src: string; path: string; projectId: string }) {
  const frame = useRef<HTMLIFrameElement>(null)
  const loads = useRef(0)
  const [loaded, setLoaded] = useState(false)
  const [stopped, setStopped] = useState(false)
  const [text, setText] = useState<string | null>(null)
  const [drawn, setDrawn] = useState(false)
  const [line, setLine] = useState<string | null>(null)
  // The picture the user asked for, till the frame answers: a picture it sends unasked is not written.
  const asked = useRef<Format | null>(null)

  useEffect(() => {
    let gone = false
    fetch(src)
      .then(answer => (answer.ok ? answer.text() : Promise.reject(answer.status)))
      .then(
        read => !gone && setText(read),
        () => !gone && setLine('It could not be read.'),
      )
    return () => {
      gone = true
    }
  }, [src])

  // (To '*': a frame of no origin cannot be named as postMessage's target; a frame gone elsewhere is taken off at its second load.)
  useEffect(() => {
    if (loaded && text !== null) frame.current?.contentWindow?.postMessage({ xml: text }, '*')
  }, [loaded, text])

  useEffect(() => {
    // Only its own frame is heard: no other page, no other frame. (Sandboxed, it is of no origin: 'null' - one of an origin is not it.)
    function heard(event: MessageEvent) {
      if (event.source !== frame.current?.contentWindow || event.origin !== 'null' || !event.data || typeof event.data !== 'object') return
      const said = event.data as Said
      if ('failed' in said) setLine(String(said.failed))
      else if ('shown' in said) setDrawn(true)
      else if ((said.saved === 'png' || said.saved === 'svg') && said.saved === asked.current) {
        asked.current = null
        const data = said.saved === 'png' ? String(said.data).split(',')[1] : base64Of(String(said.data))
        api.post<{ path: string }>(`/projects/${projectId}/diagram-picture`, { path, format: said.saved, data }).then(
          written => setLine(`Saved as ${written.path}.`),
          error => setLine(errorText(error)),
        )
      }
    }
    window.addEventListener('message', heard)
    return () => window.removeEventListener('message', heard)
  }, [path, projectId])

  const save = (format: Format) => {
    setLine(null)
    asked.current = format
    frame.current?.contentWindow?.postMessage({ save: format }, '*')
  }
  // (A frame that loads a second time went elsewhere by itself - a link in the diagram: taken off, as a page's is.)
  if (stopped) return <p className="view-empty muted">The diagram tried to go elsewhere; it was stopped.</p>
  return (
    <div className="view-diagram">
      <div className="view-where" role="group" aria-label="Save the diagram as a picture">
        <p className="muted" role="status">
          {line ?? `Save a picture of it beside it: ${pictureOf(path, 'png').split('/').at(-1)} or .svg`}
        </p>
        <button type="button" className="view-run" disabled={!drawn} onClick={() => save('png')}>
          Save as PNG
        </button>
        <button type="button" className="view-run" disabled={!drawn} onClick={() => save('svg')}>
          Save as SVG
        </button>
      </div>
      <iframe
        ref={frame}
        className="view-frame"
        title={`Diagram ${path}`}
        sandbox="allow-scripts"
        src="/drawio/viewer.html"
        onLoad={() => {
          loads.current += 1
          if (loads.current > 1) setStopped(true)
          else setLoaded(true)
        }}
      />
    </div>
  )
}
