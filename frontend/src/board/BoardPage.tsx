import { useEffect, useState } from 'react'
import { AGENT_STATUS, titleOf } from '../agents/agentStatus'
import { Quiet, SignChip } from '../agents/signs'
import { errorText } from '../api/client'
import type { Board } from '../api/types'
import { ENDED, ENDED_COLOR, when } from '../canvas/turns'
import { Hint } from '../shell/Hint'
import { StatusLabel } from '../shell/StatusLabel'
import { BROKE, type Column, columnOf, count, GOING, lastAt, since } from './columns'
import { conflictLine } from './conflicts'

type BoardConversation = Board['conversations'][number]
type BoardAgent = BoardConversation['agents'][number]
type BoardOutcome = NonNullable<NonNullable<BoardConversation['turn']>['outcomes']>[number]

/** K-board-sonuc: how a sub-agent of the last turn came out, as a tag. (Which of them "Re-run the ones that failed" opens again the server says: `rerun`.) */
const OUTCOME: Record<BoardOutcome['outcome'], [words: string, tag: string]> = {
  nothing: ['did nothing', 'tag'],
  timed_out: ['timed out', 'tag tag-warn'],
  silent: ['went silent', 'tag tag-warn'],
  error: ['error', 'tag tag-del'],
}

// The events of the project's other conversations do not come to this page: it reads again.
const READ_AGAIN_MS = 5000

const SECTIONS: [column: Column, name: string, color: string, empty: string][] = [
  ['work', 'At work', 'var(--accent)', 'No agent is at work in this project.'],
  ['today', 'Ended today', 'var(--ok)', 'Nothing ended today.'],
]

interface Props {
  board: Board | null
  error: string | null
  /** The conversation that is open, if one is: its row is marked. */
  currentId: string | null
  onLoad: () => Promise<void>
  /** Opens a conversation; rejects when it cannot be opened (it was deleted meanwhile). */
  onOpen: (conversationId: string) => Promise<void>
  /** What waits for your word anywhere: Ready for you's total (tek-ev §2: one line here, the list there). */
  waiting?: number
  onReady?: () => void
  /** K-board-sonuc: a row's "Re-run the ones that failed". Rejects with why it could not. */
  onRerun?: (conversationId: string) => Promise<void>
}

/** An agent at work: its state, and the file it holds or waits for. (Its model and working copy are in its chat.) */
function AgentRow({ agent }: { agent: BoardAgent }) {
  // (In the words its own conversation uses.)
  const [label, color] = AGENT_STATUS[agent.status]
  const wait = agent.waiting_for
  return (
    // (Focusable from code only: where focus goes when its sign is answered.)
    <li className="board-agent" tabIndex={-1}>
      <span className="board-agent-name">{titleOf(agent.name)}</span>
      {agent.role !== agent.name && <span className="muted">{agent.role}</span>}
      <StatusLabel color={color}>{label}</StatusLabel>
      {agent.sign && <SignChip agentId={agent.id} sign={agent.sign} />}
      {agent.status === 'running' && <Quiet lastEventAt={agent.last_event_at} inTool={agent.in_tool} />}
      {wait && (
        <span className="muted">
          <span className="mono">{wait.path}</span>, held by {titleOf(wait.agent_name)}
        </span>
      )}
      {agent.holds.length > 0 && (
        <span className="muted">
          holds <span className="mono">{agent.holds.join(', ')}</span>
        </span>
      )}
    </li>
  )
}

/** A sub-agent of the last turn that ended, with how it came out: its state, and the class as a tag. */
function OutcomeRow({ agent }: { agent: BoardOutcome }) {
  const [label, color] = AGENT_STATUS[agent.status]
  const [words, tag] = OUTCOME[agent.outcome]
  return (
    <li className="board-agent">
      <span className="board-agent-name">{titleOf(agent.name)}</span>
      {agent.role !== agent.name && <span className="muted">{agent.role}</span>}
      <StatusLabel color={color}>{label}</StatusLabel>
      <span className={tag}>{words}</span>
    </li>
  )
}

interface RowProps {
  conversation: BoardConversation
  column: Column
  current: boolean
  onOpen: (conversationId: string) => void
  /** Opens again the last turn's sub-agents that failed, in a new turn; rejects with why it could not. */
  onRerun?: (conversationId: string) => Promise<void>
}

/**
 * A chat's row: its title opens it; under it when it last did something, or for one that ended how and when, with
 * how many agents; its agents at work, or how those of its last turn came out.
 */
function ChatRow({ conversation, column, current, onOpen, onRerun }: RowProps) {
  const turn = conversation.turn
  // (`?? []`: a server older than the page sends none.)
  const outcomes = turn?.outcomes ?? []
  const failed = turn && !GOING.has(turn.status) ? outcomes.filter(agent => agent.rerun).length : 0
  const [rerunning, setRerunning] = useState(false)
  const [notRerun, setNotRerun] = useState<string | null>(null)
  async function rerun() {
    setRerunning(true)
    setNotRerun(null)
    try {
      await onRerun?.(conversation.conversation_id)
    } catch (err) {
      setNotRerun(errorText(err))
    } finally {
      setRerunning(false)
    }
  }
  const end = turn?.ended_at ?? turn?.started_at
  const broke = turn && column !== 'work' && BROKE.has(turn.status) ? ENDED[turn.status] : null
  const facts = (() => {
    if (column === 'work') {
      const at = lastAt(conversation)
      return [at ? `${since(at)} ago` : turn && ENDED[turn.status]]
    }
    if (!turn) return ['never ran']
    // (`!= null`: a server older than the page sends no count.)
    return [turn.agents != null && count(turn.agents, 'agent'), end && when(end)]
  })()
  const title = `board-title-${conversation.conversation_id}`
  return (
    <li className="board-card" aria-labelledby={title}>
      <button id={title} type="button" className="usage-open board-title" aria-current={current ? 'true' : undefined} onClick={() => onOpen(conversation.conversation_id)}>
        {conversation.title}
      </button>
      <p className="board-facts muted">
        {broke && <StatusLabel color={ENDED_COLOR[broke]}>{broke}</StatusLabel>}
        {/* (Beside its tag, apart by the gap: a "·" would start the line when it wraps.) */}
        <span>{facts.filter(Boolean).join(' · ')}</span>
      </p>
      {conversation.agents.length + outcomes.length > 0 && (
        <ul className="board-agents">
          {conversation.agents.map((agent, index) => (
            <AgentRow key={`${agent.name} ${index}`} agent={agent} />
          ))}
          {outcomes.map(agent => (
            <OutcomeRow key={agent.id} agent={agent} />
          ))}
        </ul>
      )}
      {failed > 0 && onRerun && (
        <div>
          <button type="button" className="btn btn-small" disabled={rerunning} onClick={() => void rerun()}>
            Re-run the ones that failed
          </button>
          {notRerun && (
            <p role="alert" className="alert">
              They could not be re-run: {notRerun}
            </p>
          )}
        </div>
      )}
    </li>
  )
}

/**
 * The project now (tek-ev §2): how many agents are at work against its limit, one line to what waits for you (Ready
 * for you), where two chats want one file, the chats at work and those that ended today; the older ones folded.
 */
export function BoardPage({ board, error, currentId, onLoad, onOpen, waiting = 0, onReady, onRerun }: Props) {
  const [notOpened, setNotOpened] = useState<string | null>(null)

  useEffect(() => {
    // One read at a time: a slow answer is waited for, not asked for again on top of itself.
    let reading = false
    const read = async () => {
      if (reading) return
      reading = true
      try {
        await onLoad()
      } finally {
        reading = false
      }
    }
    void read()
    const timer = setInterval(() => void read(), READ_AGAIN_MS)
    return () => clearInterval(timer)
  }, [onLoad])

  async function open(conversationId: string) {
    setNotOpened(null)
    try {
      await onOpen(conversationId)
    } catch (err) {
      // It is said here, on the page the user is on - and the board, which still listed
      // it, is read again.
      setNotOpened(errorText(err))
      void onLoad()
    }
  }

  // Each section keeps the order the board is read in: the last changed first.
  const placed: Record<Column, BoardConversation[]> = { work: [], today: [], older: [] }
  for (const conversation of board?.conversations ?? []) placed[columnOf(conversation)].push(conversation)
  const row = (conversation: BoardConversation, column: Column) => (
    <ChatRow
      key={conversation.conversation_id}
      conversation={conversation}
      column={column}
      current={conversation.conversation_id === currentId}
      onOpen={id => void open(id)}
      onRerun={onRerun}
    />
  )
  const chatTitle = (id: string) => board?.conversations.find(c => c.conversation_id === id)?.title ?? 'another conversation'
  return (
    <div className="memory-page">
      <div className="conv-head board-head">
        <h2>Board</h2>
        {board && (
          <span className="muted" role="status">
            {board.limit === null ? `${count(board.running, 'agent')} at work · no limit` : `${board.running} of ${board.limit} agents at work`}
          </span>
        )}
      </div>
      <p className="muted memory-hint">
        “Re-run the ones that failed” sends a new message asking its Orchestrator to open just those again, each with its role and task.{' '}
        <Hint>
          For when several conversations work in one project at the same time. A sub-agent of a conversation’s last message that did nothing,
          timed out, went silent or failed is tagged so. What waits for your word is on Ready for you; what a chat changed, in its Workspace;
          the day’s numbers, on Usage.
        </Hint>
      </p>
      {error && (
        <div role="alert" className="alert">
          The board could not be read: {error}
        </div>
      )}
      {notOpened && (
        <div role="alert" className="alert">
          That conversation could not be opened: {notOpened}
        </div>
      )}
      {waiting > 0 && (
        <p className="ready-line">
          <span className="dot" aria-hidden="true" />
          <span>{waiting === 1 ? '1 thing waits for you' : `${waiting} things wait for you`}</span>
          {onReady && (
            <button type="button" className="usage-open" onClick={onReady}>
              Open Ready for you →
            </button>
          )}
        </p>
      )}
      {board && board.conflicts.length > 0 && (
        <ul className="board-conflicts" aria-label="Two conversations want one file">
          {board.conflicts.map(conflict => (
            <li key={`${conflict.path} ${conflict.holder.conversation_id}`} className="board-conflict">
              <span>{conflictLine(board, conflict)}</span>
              <button type="button" className="btn btn-small" aria-label={`Open «${chatTitle(conflict.holder.conversation_id)}»`} onClick={() => void open(conflict.holder.conversation_id)}>
                Open
              </button>
            </li>
          ))}
        </ul>
      )}
      {!board ? (
        !error && <p className="muted">Reading the board…</p>
      ) : (
        <div className="board-columns">
          {SECTIONS.map(([column, name, color, empty]) => (
            <section key={column} className="board-column" aria-label={name}>
              <h3 className="kicker">
                <StatusLabel color={color}>{`${name} · ${placed[column].length}`}</StatusLabel>
              </h3>
              {placed[column].length > 0 ? <ul className="board-cards">{placed[column].map(c => row(c, column))}</ul> : <p className="muted">{empty}</p>}
              {column === 'today' && placed.older.length > 0 && (
                <details className="more board-older">
                  <summary>{placed.older.length} older</summary>
                  <ul className="board-cards" aria-label="Older">
                    {placed.older.map(c => row(c, 'older'))}
                  </ul>
                </details>
              )}
            </section>
          ))}
        </div>
      )}
    </div>
  )
}
