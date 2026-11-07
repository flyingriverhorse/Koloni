import { DotsSixVertical, X } from '@phosphor-icons/react'
import { Panel, type PanelPosition } from '@xyflow/react'
import { type CSSProperties, useEffect, useRef, useState } from 'react'
import type { ChannelMessage } from '../api/types'
import { useMove } from '../shell/move'

/** What the box of who said what shows (K-canvas-dili): talk and findings, the last so many, each cut this short till "more". */
export const SAID: ReadonlySet<string> = new Set(['message', 'reply', 'findings'])
export const SAID_LINES = 30
const SAID_CHARS = 200

/** Findings, as what each is ("- what | kind: … | role: …" on record). */
const findingsOf = (content: string) => content.split('\n').filter(line => line.startsWith('- ')).map(line => line.slice(2).split(' | ')[0])
const clock = (iso: string) => new Date(iso).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })

interface Props {
  /** Where on the canvas it opens (saidSide.ts), till the user moves it. */
  position: PanelPosition
  style?: CSSProperties
  /** Who to whom: "Web app coordinator ↔ Data coordinator", or whose talk it is. */
  title: string
  said: ChannelMessage[]
  /** Who said it, by their agent's id. */
  nameOf: (agentId: string) => string
  /** Its pair's colour (the line's), for a message. */
  colourOf: (message: ChannelMessage) => string
  /** Said on the right - the other side of the talk. */
  right: (message: ChannelMessage) => boolean
  onClose: () => void
}

/**
 * Who said what (the user's, 5 Nov: "plain text, no colour, no separation"), as a short conversation: a bubble a message,
 * its sender on top in its pair's colour and when, the two sides left and right; a reply or findings tagged so, findings a
 * list; the newest at the foot, in view.
 */
export function SaidBox({ position, style, title, said, nameOf, colourOf, right, onClose }: Props) {
  const list = useRef<HTMLOListElement>(null)
  const box = useRef<HTMLDivElement>(null)
  // Dragged by its head, or the arrow keys on its grip, inside the canvas; kept in this browser (shell/move.ts).
  const move = useMove('koloni-said-spot', box)
  const last = said[said.length - 1]?.id
  useEffect(() => {
    if (list.current) list.current.scrollTop = list.current.scrollHeight
  }, [last])
  return (
    <Panel
      ref={box}
      position={position}
      style={move.moved ? move.style : style}
      className={`canvas-said nodrag nopan nowheel${move.moved ? ' moved' : ''}`}
      role="region"
      aria-label="What was said"
      aria-live="polite"
    >
      <div className="canvas-said-head" {...move.header}>
        <span className="move-grip" aria-label="Move this box" title="Move this box: drag, or the arrow keys; a double click or Enter puts it back" {...move.handle}>
          <DotsSixVertical size={12} />
        </span>
        <b className="canvas-said-title">{title}</b>
        <button type="button" className="icon-btn" aria-label="Close what was said" onClick={onClose}>
          <X size={12} />
        </button>
      </div>
      <ol ref={list} className="canvas-said-list">
        {said.map(message => (
          <Bubble key={message.id} message={message} who={nameOf(message.from_agent_id)} colour={colourOf(message)} right={right(message)} />
        ))}
      </ol>
    </Panel>
  )
}

function Bubble({ message, who, colour, right }: { message: ChannelMessage; who: string; colour: string; right: boolean }) {
  const [more, setMore] = useState(false)
  const long = message.kind !== 'findings' && message.content.length > SAID_CHARS
  return (
    <li className={`said-bubble${right ? ' said-right' : ''}`} style={{ '--pair': colour } as CSSProperties}>
      <div className="said-who">
        <b>{who}</b>
        <time className="muted">{clock(message.created_at)}</time>
        {message.kind !== 'message' && <span className="tag">{message.kind}</span>}
      </div>
      {message.kind === 'findings' ? (
        <ul className="said-findings">
          {findingsOf(message.content).map((finding, i) => (
            <li key={i}>{finding}</li>
          ))}
        </ul>
      ) : (
        <p>{long && !more ? `${message.content.slice(0, SAID_CHARS)}…` : message.content}</p>
      )}
      {long && (
        <button type="button" className="link-btn" aria-expanded={more} onClick={() => setMore(!more)}>
          {more ? 'less' : 'more'}
        </button>
      )}
    </li>
  )
}
