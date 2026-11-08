import { X } from '@phosphor-icons/react'
import { type CSSProperties, type PointerEvent, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { WAITS } from '../agents/agentStatus'
import type { Usage } from '../api/types'
import { waitingId } from '../chat/waiting'
import { StatusLabel } from '../shell/StatusLabel'
import type { ConvState } from '../state/applyEvent'
import { useApp } from '../state/store'
import { totalCost } from '../usage/cost'
import { type Mark, type Wait, place, timeline, took } from './timeline'

interface Props {
  state: ConvState
  runId: string
  /** Open an agent's window. */
  onOpen: (agentId: string) => void
  onClose: () => void
}

const HEIGHT_KEY = 'koloni-timeline-height'
const HEIGHT = 220
/** The least it is (its header and two lanes), and how much a key moves its edge. */
const LEAST = 120
const STEP = 24
/** At most this share of the canvas, and never so tall that less than ROOM is left above it: the chat's and the view window's least, with their headers on the stage. */
const MOST = 0.6
const ROOM = 330

function storedHeight(): number {
  try {
    const kept = Number(localStorage.getItem(HEIGHT_KEY))
    return kept >= LEAST ? kept : HEIGHT
  } catch {
    return HEIGHT
  }
}

const n = (value: number | null) => (value === null ? '–' : value.toLocaleString('en-US'))
const lengthOf = (wait: Wait) => took(wait.from !== null && wait.to !== null ? wait.to - wait.from : null)
const waitLabel = (wait: Wait) => (wait.who === 'you' ? WAITS : wait.who ? `waits for ${wait.who}` : 'waits')
/** The sign of a mark, beside its colour: an end (failed, stopped, a limit), or something opened or ended on the way. */
const SIGN: Record<string, [sign: string, kind: string]> = { failed: ['✕', 'bad'], 'limit reached': ['!', 'bad'], stopped: ['■', 'stop'] }

/**
 * A turn's timeline, as a strip under the canvas (slice 44): each agent a row - start, length,
 * what it waited for, how it stands - and beside it the same in time, a bar with its calls,
 * waits and marks. The rows are a table, read out as one; the drawing is not read out.
 */
export function TimelineStrip({ state, runId, onOpen, onClose }: Props) {
  const [now, setNow] = useState(Date.now)
  const line = useMemo(() => timeline(state, runId, now), [state, runId, now])
  const atWork = line?.atWork ?? false
  useEffect(() => {
    if (!atWork) return
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [atWork])

  // The known cost, as the chat's turn summary reads it: once the turn is over (while it works it would be out of date at once).
  const [usage, prices] = [useApp(s => s.usage), useApp(s => s.prices)]
  const [spent, setSpent] = useState<Usage['by_model'] | null>(null)
  useEffect(() => {
    if (atWork) return
    let mine = true
    // A reading that fails leaves the cost a dash.
    usage(null, null, runId).then(
      usage => mine && setSpent(usage.by_model),
      () => {},
    )
    return () => {
      mine = false
    }
  }, [usage, runId, atWork])

  const strip = useRef<HTMLElement>(null)
  const [height, setHeight] = useState(storedHeight)
  // The windows over the stage (the chat, its buttons, the view window) stand on the strip, not over it (base.css).
  useLayoutEffect(() => {
    const stage = strip.current?.closest<HTMLElement>('.stage')
    // (Never more than the strip can be - canvas.css - on a window made shorter since.)
    stage?.style.setProperty('--timeline-h', `min(${height}px, ${MOST * 100}%)`)
    return () => void stage?.style.removeProperty('--timeline-h')
  }, [height])
  const tallest = () => {
    const canvas = strip.current?.parentElement?.clientHeight
    return canvas ? Math.max(LEAST, Math.floor(Math.min(canvas * MOST, canvas - ROOM))) : null
  }
  // As its separator tells it; a height kept from a taller window is cut to this one's as it opens.
  // shortcut: measured as it opens and as it is resized, not as the window changes size (as the chat's edge).
  const [most, setMost] = useState<number | null>(null)
  useLayoutEffect(() => {
    const top = tallest()
    if (top === null) return
    // (Measured from the page, which is what an effect is for.)
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setMost(top)
    setHeight(was => Math.min(was, top))
  }, [])
  const resize = (to: number) => {
    const top = tallest()
    if (top !== null) setMost(top)
    const next = Math.round(Math.min(top ?? Infinity, Math.max(LEAST, to)))
    setHeight(next)
    try {
      localStorage.setItem(HEIGHT_KEY, String(next))
    } catch {
      // the height just does not persist
    }
  }
  const drag = (event: PointerEvent<HTMLDivElement>) => {
    const bottom = strip.current?.getBoundingClientRect().bottom
    if (event.currentTarget.hasPointerCapture?.(event.pointerId) && bottom) resize(bottom - event.clientY)
  }

  if (!line) return null
  const at = (t: number) => `${place(t, line)}%`
  const span = (from: number, to: number): CSSProperties => ({ left: at(from), width: `${Math.max(0, place(to, line) - place(from, line))}%` })
  const since = (t: number | null) => (t === null ? '–' : `+${took(t - line.from)}`)
  const marked = (marks: Mark[]) => marks.map(m => `${m.what} ${since(m.at)}`).join(', ')
  const totals: [string, string][] = [
    ['Length', took(line.length)],
    ['Agents', String(line.agents)],
    ['Tokens', line.tokens.input_tokens === null && line.tokens.output_tokens === null ? '–' : `in ${n(line.tokens.input_tokens)} · out ${n(line.tokens.output_tokens)}`],
    ['Known cost', spent && !atWork ? totalCost(spent, prices) : '–'],
    ...(line.marks.length > 0 ? [['Its work', marked(line.marks)] as [string, string]] : []),
  ]
  const index = new Map(line.lanes.map((l, i) => [l.id, i]))
  // (What still waits for you leads to its card on Ready for you, where it is answered.)
  const answer = (key: string) => useApp.getState().showReady(true, waitingId(key))

  return (
    <section ref={strip} id="timeline" className="timeline" aria-label="Timeline" style={{ height }}>
      <div
        className="timeline-edge"
        role="separator"
        aria-orientation="horizontal"
        aria-label="Timeline height"
        aria-valuemin={LEAST}
        aria-valuemax={most ?? undefined}
        aria-valuenow={height}
        tabIndex={0}
        onPointerDown={event => {
          // (No text is selected as it is dragged.)
          event.preventDefault()
          event.currentTarget.setPointerCapture?.(event.pointerId)
        }}
        onPointerMove={drag}
        onKeyDown={event => {
          const to = { ArrowUp: height + STEP, ArrowDown: height - STEP, Home: LEAST, End: Infinity }[event.key]
          if (to === undefined) return
          event.preventDefault()
          resize(to)
        }}
      />
      <div className="tl-head">
        <span className="kicker">Timeline</span>
        <dl className="tl-totals">
          {totals.map(([term, value]) => (
            <div key={term}>
              <dt>{term}</dt> <dd className="mono">{value}</dd>
            </div>
          ))}
        </dl>
        <button type="button" className="icon-btn" aria-label="Close timeline" title="Close timeline" onClick={onClose}>
          <X size={14} />
        </button>
      </div>
      <div className="tl-scroll">
        <table className="tl-table" aria-label="Its agents in time">
          <thead>
            <tr>
              <th>Agent</th>
              <th>Start</th>
              <th>Length</th>
              <th>Waiting</th>
              <th>Status</th>
              {/* Where the line ends, drawn at its right by canvas.css. The drawing is not read out: nor is its column. */}
              <th className="tl-axis" aria-hidden data-to={`+${took(line.to - line.from)}`}>
                Time
              </th>
            </tr>
          </thead>
          <tbody>
            {line.lanes.map(lane => {
              const open = () => onOpen(lane.agentId)
              const up = lane.parent === null ? 0 : index.get(lane.id)! - index.get(lane.parent)!
              return (
                <tr key={lane.id} className={`tl-row tl-depth-${Math.min(lane.depth, 4)}${lane.cli ? ' tl-cli' : ''}`}>
                  <td>
                    <button type="button" className="tl-name" style={{ paddingInlineStart: `${lane.depth * 14 + 4}px` }} title={lane.cli ? `${lane.name} (its CLI’s own sub-agent)` : lane.name} onClick={open}>
                      {lane.name}
                    </button>
                  </td>
                  <td className="mono">{since(lane.from)}</td>
                  <td className="mono">{took(lane.from !== null && lane.to !== null ? lane.to - lane.from : null)}</td>
                  <td>
                    {lane.waits.length === 0 ? (
                      'none'
                    ) : (
                      <div className="tl-waits" title={lane.waits.map(w => `${waitLabel(w)} ${lengthOf(w)} · ${w.what}`).join('; ')}>
                        {lane.waits.map((wait, i) => (
                          <span key={i} className="tl-waited">
                            {wait.key ? (
                              <button type="button" className="tag tag-warn" title="Answer it under Ready for you" onClick={() => answer(wait.key!)}>
                                {waitLabel(wait)}
                              </button>
                            ) : (
                              <span className={wait.who === 'you' ? 'tag tag-warn' : 'tag'}>{waitLabel(wait)}</span>
                            )}{' '}
                            <span className="mono">{lengthOf(wait)}</span> · {wait.what}
                          </span>
                        ))}
                      </div>
                    )}
                  </td>
                  <td>
                    <StatusLabel color={lane.status[1]}>{lane.status[0]}</StatusLabel>
                    {/* What a bar's marks say, but the state already said. */}
                    {lane.marks.some(m => m.what !== lane.status[0]) && (
                      <div className="muted tl-marked">{marked(lane.marks.filter(m => m.what !== lane.status[0]))}</div>
                    )}
                  </td>
                  <td className="tl-track" aria-hidden onClick={open}>
                    <div className="tl-lane">
                      {up > 0 && lane.opened !== null && <span className="tl-spawn" style={{ left: at(lane.opened), ['--up' as string]: up }} />}
                      {lane.from !== null && lane.to !== null && (
                        <span className={`tl-bar${lane.atWork ? ' tl-bar-work' : ''}`} style={{ ...span(lane.from, lane.to), ['--c' as string]: lane.status[1] }} title={`${lane.name} · ${lane.status[0]}`} />
                      )}
                      {lane.calls.map((call, i) => (
                        <span key={i} className={`tl-call${call.status === 'failed' ? ' tl-call-failed' : ''}`} style={span(call.from, call.to)} title={`${call.name} · ${took(call.to - call.from)}`} />
                      ))}
                      {lane.waits.map(
                        (wait, i) =>
                          wait.from !== null &&
                          wait.to !== null && (
                            <span key={i} className={`tl-wait${wait.who === 'you' ? ' tl-wait-you' : ''}`} style={span(wait.from, wait.to)} title={`${waitLabel(wait)} · ${took(wait.to - wait.from)} · ${wait.what}`}>
                              <span className={wait.who === 'you' ? 'tag tag-warn' : 'tag'}>
                                {waitLabel(wait)} {took(wait.to - wait.from)}
                              </span>
                            </span>
                          ),
                      )}
                      {lane.marks.map((m, i) => (
                        <span key={i} className={`tl-mark tl-mark-${SIGN[m.what]?.[1] ?? 'way'}`} style={{ left: at(m.at) }} title={`${m.what} ${since(m.at)}`}>
                          {SIGN[m.what]?.[0] ?? '◆'}
                        </span>
                      ))}
                    </div>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </section>
  )
}
