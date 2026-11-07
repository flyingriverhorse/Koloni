import { Copy } from '@phosphor-icons/react'
import { useState } from 'react'
import { errorText } from '../api/client'
import { useApp } from '../state/store'

/**
 * What the agent's CLI wrote itself, line by line - also what KOLONİ's record passes over - is not drawn: its
 * start-up blob and the whole files it read would fill the panel (K-inspector, R160); its steps say what it did.
 * "Copy raw" puts every line the backend still keeps on the clipboard, as the CLI wrote them.
 */
export function CopyRaw({ agentId }: { agentId: string }) {
  const [busy, setBusy] = useState(false)
  const [said, setSaid] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  async function copy() {
    setBusy(true)
    setSaid(null)
    setError(null)
    try {
      const lines: string[] = []
      let after = 0
      for (;;) {
        const told = await useApp.getState().rawStream(agentId, after)
        if (!told.available) return setSaid('Its model is not a CLI: there is no raw stream.')
        lines.push(...told.lines.map(line => line.text))
        // One answer carries only so many lines: the rest is asked for at once.
        if (!told.more || told.lines.length === 0) break
        after = told.lines[told.lines.length - 1].n
      }
      if (lines.length === 0) return setSaid('Nothing its CLI wrote is kept.')
      await navigator.clipboard.writeText(lines.join('\n'))
      setSaid(`Copied ${lines.length} ${lines.length === 1 ? 'line' : 'lines'}`)
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="raw-copy">
      <div>
        <button type="button" className="btn btn-small" disabled={busy} onClick={() => void copy()}>
          <Copy size={12} />
          Copy raw
        </button>{' '}
        {/* (On the page before it says anything: a live region that comes already filled is not read out.) */}
        <span role="status" className="muted">
          {said}
        </span>
      </div>
      {error && (
        <div role="alert" className="alert">
          The raw stream could not be read: {error}
        </div>
      )}
      <p className="muted">
        What its CLI wrote itself, line by line. Kept in memory only: it is gone when KOLONİ restarts. Secrets KOLONİ knows (of 8
        characters or more) are hidden, and whatever follows /api/hooks/ in a line; anything else the CLI printed is copied as it is.
      </p>
    </div>
  )
}
