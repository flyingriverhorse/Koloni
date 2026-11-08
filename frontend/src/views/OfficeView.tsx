/**
 * A Word document, a workbook or a slide deck in the Workspace (K-belge-ciktilari): drawn by /office/viewer.html, in a
 * sandboxed frame of no origin whose page loads nothing but its own files and reaches nothing (`app.views.VIEWER_HEADERS`),
 * as the draw.io viewer is. The app reads the file - 5 MB at most, as the server serves it - and posts its bytes in.
 */
import { useEffect, useRef, useState } from 'react'
import { keyHeader } from '../api/client'
import type { OfficeKind, Said } from './office/viewer'

export function OfficeView({ src, path, kind }: { src: string; path: string; kind: OfficeKind }) {
  const frame = useRef<HTMLIFrameElement>(null)
  const loads = useRef(0)
  const [loaded, setLoaded] = useState(false)
  const [stopped, setStopped] = useState(false)
  const [data, setData] = useState<ArrayBuffer | null>(null)
  const [line, setLine] = useState<string | null>(null)

  useEffect(() => {
    let gone = false
    // (With the page's key: a document is served on its keyless door only with it - `api.deps.keyed_if_read_by_the_app`.)
    fetch(src, { headers: keyHeader() })
      .then(answer => (answer.ok ? answer.arrayBuffer() : Promise.reject(answer.status)))
      .then(
        read => !gone && setData(read),
        status => !gone && setLine(status === 413 ? 'Too large to show: over 5 MB.' : 'It could not be read.'),
      )
    return () => {
      gone = true
    }
  }, [src])

  // (To '*': a frame of no origin cannot be named as postMessage's target; a frame gone elsewhere is taken off at its second load.)
  useEffect(() => {
    if (loaded && data) frame.current?.contentWindow?.postMessage({ kind, data }, '*')
  }, [loaded, data, kind])

  useEffect(() => {
    // Only its own frame is heard: no other page, no other frame. (Sandboxed, it is of no origin: 'null' - one of an origin is not it.)
    function heard(event: MessageEvent) {
      if (event.source !== frame.current?.contentWindow || event.origin !== 'null' || !event.data || typeof event.data !== 'object') return
      const said = event.data as Said
      if ('failed' in said) setLine(`It could not be drawn: ${String(said.failed)}`)
    }
    window.addEventListener('message', heard)
    return () => window.removeEventListener('message', heard)
  }, [])

  // (A frame that loads a second time went elsewhere by itself - a link in the document: taken off, as a page's is.)
  if (stopped) return <p className="view-empty muted">The document tried to go elsewhere; it was stopped.</p>
  return (
    <div className="view-diagram">
      {line && (
        <p className="view-empty muted" role="status">
          {line}
        </p>
      )}
      <iframe
        ref={frame}
        className="view-frame"
        title={`Document ${path}`}
        sandbox="allow-scripts"
        src="/office/viewer.html"
        onLoad={() => {
          loads.current += 1
          if (loads.current > 1) setStopped(true)
          else setLoaded(true)
        }}
      />
    </div>
  )
}
