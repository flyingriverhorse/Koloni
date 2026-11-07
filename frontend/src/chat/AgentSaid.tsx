import { CaretDown, CaretRight } from '@phosphor-icons/react'
import { useState } from 'react'
import { AGENT_STATUS } from '../agents/agentStatus'
import type { Agent, Message } from '../api/types'
import { Markdown } from './Markdown'

/** KOLONİ's word to a CLI Lead that a sub-agent's report follows (app/agent.py SPAWN_ENDED_SEE): its model's, not the user's (K-r152). */
export const isFrame = (m: Pick<Message, 'role' | 'from_agent_id' | 'content'>) =>
  m.role === 'agent' && m.from_agent_id === null && /^KOLONİ, of your spawn_agent for .+: what came of it follows, as a message from /.test(m.content)

// K-kanit's line under a report (app/ledger.py DID): in sight while the report is folded.
const DID = /^What it did.*?, from KOLONİ's record: .*$/m
// A part KOLONİ hands a model JSON-quoted, as data (app/team.py `quoted`: team_requests LATE, TO_LEAD - KOLONİ's words,
// though sent in the asker's name).
// shortcut: by those texts' wording; mark such a message on the server if their wording is seen to drift from this.
const AS_DATA = /^(KOLONİ: [\s\S]*?)\s*([^.:\n]+), as data: ("(?:[^"\\]|\\.)*")([\s\S]*)$/
// A message longer than this, or one with KOLONİ's record under it, is a report: folded.
// shortcut: a count by eye; fold by the message's kind if the server marks reports one day.
const FOLD_LINES = 3
const SAID_CHARS = 140

/** What a report says first: its first line that is no heading or fence, to its first full stop. */
function firstSaid(text: string): string {
  for (const raw of text.split('\n')) {
    const line = raw.replace(/[*_`]/g, '').replace(/^[\s>*-]+/, '').trim()
    if (!line || /^\s*(#|```)/.test(raw) || line === 'What it said last:' || DID.test(line)) continue
    const said = line.split(/(?<=[.!?])\s/)[0]
    return said.length > SAID_CHARS ? `${said.slice(0, SAID_CHARS - 1)}…` : said
  }
  return ''
}

/** The quoted part of `content` and the words around it; null where it has none, or it does not read as JSON. */
function asData(content: string): { said: string; label: string; quoted: string } | null {
  const found = AS_DATA.exec(content)
  if (!found) return null
  try {
    const quoted: unknown = JSON.parse(found[3])
    // (TO_LEAD's words go on after the quote, ". Decide what…": its full stop is the one before the label.)
    return typeof quoted === 'string' ? { said: `${found[1]} ${found[4].replace(/^[.\s]+/, '')}`.trim(), label: found[2].trim(), quoted } : null
  } catch {
    return null
  }
}

/**
 * Another agent's message to the Lead, or KOLONİ's, in the chat (K-r152): in markdown, as the Lead's own (B-362); a
 * report folded to one line - who, how it stands, what it says first - with KOLONİ's record of what it did under it;
 * a part handed on as data folded, with its real line breaks.
 */
export function AgentSaid({ message, from, agent }: { message: Message; from: string; agent?: Agent }) {
  const [open, setOpen] = useState(false)
  const data = asData(message.content)
  // A spawn's result opens with KOLONİ's "<its name> finished." / "failed: " / "stopped after …": the line says it.
  const own =
    agent && message.content.startsWith(`${agent.name} `)
      ? message.content.slice(agent.name.length + 1).replace(/^(?:finished\.|failed: |stopped after [^\n]*)/, '')
      : message.content
  const did = message.content.match(DID)?.[0]
  const head = (said: string, label?: string) => (
    <button type="button" className="tool-run-head" aria-expanded={open} onClick={() => setOpen(!open)}>
      <span className="muted" style={{ display: 'grid' }}>
        {open ? <CaretDown size={12} /> : <CaretRight size={12} />}
      </span>
      <span className="tool-run-what">
        <strong>{label ?? from}</strong>
        {said && ` · ${said}`}
      </span>
    </button>
  )
  if (data) {
    return (
      <div className="msg msg-from">
        <div className="asked-by mono">from KOLONİ</div>
        <div className="markdown">
          <Markdown written>{data.said}</Markdown>
        </div>
        <div className="tool-run">
          {head('', data.label)}
          {open && <div className="tool-run-body msg-quote">{data.quoted}</div>}
        </div>
      </div>
    )
  }
  if (!message.from_agent_id || (!did && message.content.trim().split('\n').length <= FOLD_LINES)) {
    return (
      <div className="msg msg-from">
        <div className="asked-by mono">from {from}</div>
        <div className="markdown">
          <Markdown written>{message.content}</Markdown>
        </div>
      </div>
    )
  }
  const status = agent ? AGENT_STATUS[agent.status][0] : ''
  return (
    <div className="msg msg-from">
      <div className="tool-run">
        {head([status, firstSaid(own)].filter(Boolean).join(' · '))}
        {open && (
          <div className="tool-run-body markdown">
            <Markdown written>{message.content.replace(DID, '').trim()}</Markdown>
          </div>
        )}
      </div>
      {did && <div className="muted">{did}</div>}
    </div>
  )
}
