import { ChatsCircle, FileText, Lightbulb, ListChecks, Robot, TerminalWindow, User, UsersThree, Wrench, X } from '@phosphor-icons/react'
import { poSaid, poTokens } from '../canvas/deriveGraph'
import { discussionLine, nameIn } from '../discussion/discussionText'
import { type ReactNode, useEffect, useRef } from 'react'
import { flushSync } from 'react-dom'
import { AttachmentPreview, Minis } from '../chat/Attach'
import { linksIn } from '../chat/attachments'
import { Markdown } from '../chat/Markdown'
import { plannedBy } from '../chat/planText'
import { AgentCard } from '../agents/AgentCard'
import { agentState, agentWhere, when } from '../agents/AgentWindow'
import { OwnSubAgentWork } from '../agents/OwnSubAgent'
import { homeOf, isOwnSubAgent, ownSubAgentBrief, ownSubAgentTask, subAgentIds } from '../agents/ownWork'
import type { Agent, Command, FileChange, Merge, PendingRole, Provider, Question, Run } from '../api/types'
import { commandSeconds, commandStatus, placeLabel, TONE_COLOR } from '../commands/commandStatus'
import { CHANGE_LABEL } from '../changes/changeLabel'
import { CommandRow } from '../commands/CommandRow'
import { TOOL_STATUS, ToolRow } from '../chat/ToolRow'
import { toolSummary } from '../chat/toolSummary'
import { memberTag, nameIn as nameInRoom, roomLine, spentLines } from '../room/roomText'
import { StatusLabel } from '../shell/StatusLabel'
import type { ConvState } from '../state/applyEvent'
import { useApp } from '../state/store'

interface Props {
  /** Open a discussion's shared place. */
  onOpenDiscussion?: (discussionId: string) => void
  /** Open a room's window. */
  onOpenRoom?: (roomId: string) => void
  /** Open an agent's own window: what it said and did, as it happens. */
  onOpenAgent?: (agentId: string) => void
  state: ConvState | null
  /** The providers as they stand now: what a failed agent's plan key says to do. */
  providers?: Provider[]
  selectedId: string | null
  onClose: () => void
  /** Rendered for a selected file change (diff and decision buttons). */
  renderChange?: (change: FileChange) => ReactNode
  onOpenChange?: (changeId: string) => void
  /** Rendered for a command that waits for a decision. */
  renderCommandApproval?: (command: Command) => ReactNode
  /** Asked to select another node (a sub-agent from its parent's list). */
  onSelect?: (nodeId: string) => void
  /** Rendered for a sub-agent that waits to be opened. */
  renderSpawnApproval?: (agent: Agent) => ReactNode
  /** Rendered for what the selected agent changed in its working copy, while you are asked about it. */
  renderMerge?: (merge: Merge, agent: Agent) => ReactNode
  /** Rendered for a role the selected agent asked to create. */
  renderRoleApproval?: (role: PendingRole) => ReactNode
  /** Rendered for a question the selected agent is waiting on. */
  renderQuestion?: (question: Question) => ReactNode
}

function Header({
  icon,
  title,
  sub,
  onClose,
  action,
}: {
  icon: ReactNode
  title: string
  sub: ReactNode
  onClose: () => void
  action?: ReactNode
}) {
  return (
    <div className="insp-head">
      <span className="insp-icon">{icon}</span>
      <div className="insp-titles">
        <div className="insp-title">{title}</div>
        <div className="mono muted insp-sub">{sub}</div>
      </div>
      {action}
      <button type="button" className="icon-btn" aria-label="Close inspector" onClick={onClose}>
        <X size={15} />
      </button>
    </div>
  )
}

/** The Assistant PO's node (`po:<turn>`): what came of its request, and why each one dropped was dropped - never its answer. */
function poPanel(state: ConvState | null, kind: string | undefined, refId: string | undefined, onClose: () => void): ReactNode {
  const po = kind === 'po' ? state?.runs.find(r => r.id === refId)?.po : null
  if (!po) return null
  return (
    <>
      <Header icon={<Lightbulb size={16} />} title="Assistant PO" sub={[po.provider_name, po.model_id ?? 'model not known', poTokens(po)].filter(Boolean).join(' · ')} onClose={onClose} />
      <div className="insp-body">
        <p>{[poSaid(po), po.note].filter(Boolean).join(': ')}</p>
        <div className="kicker">Dropped, and why</div>
        {po.dropped.length === 0 && <p className="muted">None.</p>}
        {po.dropped.map((one, i) => (
          <p key={i}>
            <span className="mono">{one.title || '(no title)'}:</span> {one.why}
          </p>
        ))}
        {po.dropped_more > 0 && <p className="muted">and {po.dropped_more} more, not listed</p>}
      </div>
    </>
  )
}

/** What has an Esc of its own, which the inspector's Esc leaves to it. */
const OWN_ESC = '.chat, .turns, .changes, [role="dialog"], input, textarea, select, [contenteditable="true"]'

export function Inspector({
  state,
  providers,
  selectedId,
  onClose: close,
  renderChange,
  onOpenChange,
  renderCommandApproval,
  onSelect,
  renderSpawnApproval,
  renderMerge,
  renderRoleApproval,
  renderQuestion,
  onOpenAgent,
  onOpenDiscussion,
  onOpenRoom,
}: Props) {
  // What had the focus when the inspector opened: it has it back when it is closed.
  const opener = useRef<Element | null>(null)
  const windowed = useApp(s => s.agentWindowId)
  const aside = useRef<HTMLElement>(null)
  const open = selectedId !== null
  useEffect(() => {
    opener.current = open ? document.activeElement : null
  }, [open])
  function onClose() {
    const back = opener.current
    // (Focus in it goes back to what opened it; focus elsewhere - on a node - stays where it is.)
    const lost = document.activeElement === document.body || aside.current?.contains(document.activeElement)
    close()
    if (lost && back instanceof HTMLElement && back.isConnected) back.focus()
  }
  // Its window takes the panel's room, and the focus: the button pressed goes with the panel (not back to the opener).
  function openWindow(agentId: string) {
    flushSync(() => {
      onOpenAgent?.(agentId)
      close()
    })
    document.querySelector<HTMLElement>('.agent-window')?.focus()
  }
  // Esc closes it wherever the focus is - on the node that opened it, say - but for a layer
  // with an Esc of its own: the chat, More, the turn list, a window, a panel, a field.
  const shut = useRef(onClose)
  useEffect(() => {
    shut.current = onClose
  })
  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape' || event.defaultPrevented) return
      const at = event.target instanceof Element ? event.target : null
      if (at && !aside.current?.contains(at) && at.closest(OWN_ESC)) return
      shut.current()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open])
  const roleOf = (agentId: string) => state?.agents.find(a => a.id === agentId)?.name || 'unknown'
  // The approved plan over a work turn's Lead (`planned:<plan's turn>`) opens as the plan turn's own node does.
  const [kind, refId] = selectedId ? selectedId.replace(/^planned:/, 'plan:').split(/:(.*)/s) : []
  // Agent and Tools nodes point at an agent; its turn is the run it belongs to.
  // A sub-agent of a CLI's own, and the node of its tools, point at the call it is.
  const subAgents = subAgentIds(state?.toolCalls ?? [])
  const subAgent = state?.toolCalls.find(t => t.id === refId && isOwnSubAgent(t))
  const agent = state?.agents.find(a => a.id === refId)
  const run = state?.runs.find(r => r.id === agent?.run_id)
  const change = state?.fileChanges.find(f => f.id === refId)
  const request = state?.messages.find(m => m.run_id === refId && m.role === 'user')
  const command = state?.commands.find(c => c.id === refId)
  // A file of the user's (slice 85b), or the box of a message's many files (its turn's: "files:<run>").
  const file = kind === 'attachment' ? state?.attachments.find(a => a.id === refId) : undefined
  const filesOf = (messageId: string | undefined) => state?.attachments.filter(a => messageId && a.message_id === messageId && !a.frame_of) ?? []

  // (onClose is only handed on, to the panel's close button: no ref is read while it draws.)
  // oxlint-disable-next-line react/refs
  let content: ReactNode = poPanel(state, kind, refId, onClose)
  if (state && kind === 'request' && request) {
    content = (
      <>
        <Header icon={<User size={16} />} title="You" sub={when(request.created_at)} onClose={onClose} />
        <div className="insp-body">
          <p className="insp-request">{request.content}</p>
          <Minis files={filesOf(request.id)} links={linksIn(request.content)} />
        </div>
      </>
    )
  } else if (state && file) {
    const to = file.given_to.map(roleOf)
    content = (
      <>
        <Header icon={<FileText size={16} />} title={file.name} sub={to.length ? `handed to ${to.join(', ')}` : 'attached by you'} onClose={onClose} />
        <div className="insp-body">
          <AttachmentPreview file={file} />
        </div>
      </>
    )
  } else if (state && kind === 'files' && request) {
    content = (
      <>
        <Header icon={<FileText size={16} />} title={`${filesOf(request.id).length} files`} sub="attached by you" onClose={onClose} />
        <div className="insp-body">
          <Minis files={filesOf(request.id)} links={[]} />
        </div>
      </>
    )
  } else if (state && kind === 'agent' && agent && run) {
    const [label, color] = agentState(state, agent)
    content = (
      <>
        <Header icon={<Robot size={16} />} title={agent.name || agent.role_name}
          sub={
            // (Under its name, which the panel's width leaves whole: its window has them on one line.)
            <>
              <StatusLabel color={color}>{label}</StatusLabel> {agentWhere(state, agent)}
            </>
          }
          onClose={onClose}
          action={
            onOpenAgent && (
              <button type="button" className="btn btn-small" onClick={() => openWindow(agent.id)}>
                Open window
              </button>
            )
          }
        />
        {/* Its report card; its whole story is in its window - while that is open, not beside it as well (R160). */}
        <div className="insp-body">
          {windowed === agent.id ? (
            <p className="muted">Shown in its window.</p>
          ) : (
            <AgentCard
              key={agent.id}
              agent={agent}
              state={state}
              providers={providers}
              onOpenChange={id => onOpenChange?.(id)}
              onSelectAgent={id => onSelect?.(`agent:${id}`)}
              renderSpawnApproval={renderSpawnApproval}
              renderMerge={renderMerge}
              renderRoleApproval={renderRoleApproval}
              renderQuestion={renderQuestion}
              renderCommandApproval={renderCommandApproval}
            />
          )}
        </div>
      </>
    )
  } else if (state && kind === 'discussion' && state.discussions.some(d => d.id === refId)) {
    const discussion = state.discussions.find(d => d.id === refId)!
    const said = state.discussionPosts.filter(p => p.discussion_id === discussion.id && p.kind === 'said' && !p.passed)
    content = (
      <>
        <Header
          icon={<ChatsCircle size={16} />}
          title="Discussion"
          sub={discussionLine(discussion)}
          onClose={onClose}
          action={
            onOpenDiscussion && (
              <button type="button" className="btn btn-small" onClick={() => onOpenDiscussion(discussion.id)}>
                Open discussion
              </button>
            )
          }
        />
        <div className="insp-body">
          <p className="insp-request">{discussion.topic}</p>
          <div className="kicker">In it</div>
          <p className="mono">{discussion.members.map(m => nameIn(state, m.agent_id)).join(' · ')}</p>
          <div className="kicker">Said last</div>
          {said.length === 0 && <p className="muted">Nothing yet.</p>}
          {said.slice(-3).map(p => (
            <p key={p.id}>
              <span className="mono">{nameIn(state, p.agent_id)}:</span> {p.content}
            </p>
          ))}
        </div>
      </>
    )
  } else if (state && kind === 'room' && state.rooms.some(r => r.id === refId)) {
    const room = state.rooms.find(r => r.id === refId)!
    const said = state.roomPosts.filter(p => p.room_id === room.id).sort((a, b) => a.number - b.number)
    content = (
      <>
        <Header
          icon={<UsersThree size={16} />}
          title="Room"
          sub={roomLine(room)}
          onClose={onClose}
          action={
            onOpenRoom && (
              <button type="button" className="btn btn-small" onClick={() => onOpenRoom(room.id)}>
                Open the room
              </button>
            )
          }
        />
        <div className="insp-body">
          <p className="insp-request">{room.goal}</p>
          <div className="kicker">In it</div>
          <p className="mono">{room.members.map(m => memberTag(state, room, m)).join(' · ')}</p>
          <div className="kicker">Spent of its budget</div>
          <p className="mono">{spentLines(room).join(' · ')}</p>
          <div className="kicker">Said last</div>
          {said.length === 0 && <p className="muted">Nothing yet.</p>}
          {said.slice(-3).map(p => (
            <p key={p.id}>
              <span className="mono">{nameInRoom(state, p.agent_id)}:</span> {p.text}
            </p>
          ))}
        </div>
      </>
    )
  } else if (state && kind === 'plan' && state.runs.some(r => r.id === refId && r.plan)) {
    // The plan node points at its turn; the plan as it stands, edited or not.
    const plan = state.runs.find(r => r.id === refId)?.plan as NonNullable<Run['plan']>
    content = (
      <>
        <Header icon={<ListChecks size={16} />} title={`Plan · ${plan.status}`} sub={plannedBy(plan)} onClose={onClose} />
        <div className="insp-body markdown">
          <Markdown>{plan.text}</Markdown>
        </div>
      </>
    )
  } else if (state && kind === 'subagent' && subAgent) {
    const [label, color] = TOOL_STATUS[subAgent.status]
    // What it waits on the user for in words: leave for itself, or for a tool of its.
    const asked = state.questions.filter(
      q =>
        q.status === 'pending' &&
        (q.tool_call_id === subAgent.id ||
          homeOf(state.toolCalls.find(t => t.id === q.tool_call_id), subAgents) === subAgent.id),
    )
    content = (
      <>
        <Header
          icon={<Robot size={16} />}
          title={ownSubAgentTask(subAgent) || 'Sub-agent'}
          sub={`own sub-agent of ${roleOf(subAgent.agent_id)}`}
          onClose={onClose}
          action={
            onOpenAgent && (
              <button type="button" className="btn btn-small" onClick={() => openWindow(subAgent.agent_id)}>
                Open window
              </button>
            )
          }
        />
        <div className="insp-body">
          {asked.map(q => renderQuestion?.(q))}
          <dl className="facts">
            <dt>Status</dt>
            <dd className="mono" style={{ color }}>
              {label}
            </dd>
            <dt>Kind</dt>
            <dd className="mono">{ownSubAgentBrief(subAgent).kind ?? 'unknown'}</dd>
            <dt>Opened by</dt>
            <dd className="mono">the CLI itself; it is not one of KOLONİ’s agents</dd>
            <dt>Started</dt>
            <dd className="mono">{when(subAgent.started_at)}</dd>
            <dt>Ended</dt>
            <dd className="mono">{when(subAgent.ended_at)}</dd>
          </dl>
          <OwnSubAgentWork state={state} call={subAgent} onOpenChange={onOpenChange} />
        </div>
      </>
    )
  } else if (state && (kind === 'tools' || kind === 'owntools') && (agent || subAgent)) {
    // The two tool nodes: what KOLONİ ran for the agent, and what the CLI used on its
    // own - by the agent itself, or inside one of its own sub-agents.
    const own = kind === 'owntools'
    const calls = state.toolCalls
      .filter(
        t =>
          t.agent_id === (agent?.id ?? subAgent?.agent_id) &&
          (t.origin === 'cli') === own &&
          homeOf(t, subAgents) === (subAgent?.id ?? null) &&
          t.name !== 'run_command' &&
          !subAgents.has(t.id) &&
          !state.agents.some(a => a.tool_call_id === t.id),
      )
      .sort((a, b) => a.seq - b.seq)
    content = (
      <>
        <Header
          icon={<Wrench size={16} />}
          title={own ? 'Own tools' : 'Tools'}
          sub={`${calls.length} calls`}
          onClose={onClose}
        />
        <div className="insp-body">
          {calls.map(call => (
            <ToolRow key={call.id} call={call} />
          ))}
        </div>
      </>
    )
  } else if (state && kind === 'commands' && (agent || subAgent)) {
    // A card of many commands: the agent's own, or those of one of its CLI's own sub-agents.
    const commands = state.commands.filter(
      c =>
        c.agent_id === (agent?.id ?? subAgent?.agent_id) &&
        homeOf(state.toolCalls.find(t => t.id === c.tool_call_id), subAgents) === (subAgent?.id ?? null),
    )
    content = (
      <>
        <Header icon={<TerminalWindow size={16} />} title="Commands" sub={`${commands.length} commands`} onClose={onClose} />
        <div className="insp-body">
          {commands.map(command => (
            <CommandRow key={command.id} command={command} failed={state.toolCalls.find(t => t.id === command.tool_call_id)?.status === 'failed'} />
          ))}
        </div>
      </>
    )
  } else if (state && kind === 'changes' && (agent || subAgent)) {
    // A card of many changed files, as the card holds them: one that waits for the user has a card of its own.
    const changes = state.fileChanges.filter(
      f =>
        f.status !== 'proposed' &&
        f.agent_id === (agent?.id ?? subAgent?.agent_id) &&
        homeOf(state.toolCalls.find(t => t.id === f.tool_call_id), subAgents) === (subAgent?.id ?? null),
    )
    content = (
      <>
        <Header icon={<FileText size={16} />} title="Files" sub={`${changes.length} files`} onClose={onClose} />
        <div className="insp-body">
          {changes.map(change => (
            <div key={change.id} className="chat-change">
              <span className="mono chat-change-path" title={change.path}>
                {change.path}
              </span>
              <span className="mono" style={{ color: 'var(--ok)' }}>+{change.additions}</span>
              <span className="mono" style={{ color: 'var(--del)' }}>−{change.deletions}</span>
              <span className={CHANGE_LABEL[change.status][1]}>{CHANGE_LABEL[change.status][0]}</span>
              <button type="button" className="btn btn-small" aria-label={`Open ${change.path}`} onClick={() => onSelect?.(`file:${change.id}`)}>
                Open
              </button>
            </div>
          ))}
        </div>
      </>
    )
  } else if (state && kind === 'call' && state.toolCalls.some(t => t.id === refId)) {
    // One call, picked from the list of an expanded tool node: open at once.
    const call = state.toolCalls.find(t => t.id === refId)!
    const [label, color] = TOOL_STATUS[call.status]
    content = (
      <>
        <Header icon={<Wrench size={16} />} title={toolSummary(call)} sub="one tool call" onClose={onClose} />
        <div className="insp-body">
          <dl className="facts">
            <dt>Status</dt>
            <dd className="mono" style={{ color }}>
              {label}
            </dd>
            <dt>Agent</dt>
            <dd className="mono">{roleOf(call.agent_id)}</dd>
            <dt>Run by</dt>
            <dd className="mono">{call.origin === 'cli' ? 'the CLI itself, with a tool of its own' : 'KOLONİ'}</dd>
            <dt>Started</dt>
            <dd className="mono">{when(call.started_at)}</dd>
            <dt>Ended</dt>
            <dd className="mono">{when(call.ended_at)}</dd>
          </dl>
          <div className="kicker">Arguments</div>
          <pre className="mono insp-output">{call.arguments || '{}'}</pre>
          <div className="kicker">Result</div>
          <pre className="mono insp-output">{call.result ?? '(no result yet)'}</pre>
        </div>
      </>
    )
  } else if (state && kind === 'command' && command) {
    const status = commandStatus(command)
    const seconds = commandSeconds(command)
    content = (
      <>
        <Header
          icon={<TerminalWindow size={16} />}
          title="Command"
          sub={placeLabel(command)}
          onClose={onClose}
        />
        <div className="insp-body">
          <pre className="mono cmd-approval-command">{command.command}</pre>
          <dl className="facts">
            <dt>Status</dt>
            <dd className="mono" style={{ color: TONE_COLOR[status.tone] }}>
              {status.label}
            </dd>
            <dt>Agent</dt>
            <dd className="mono">{roleOf(command.agent_id)}</dd>
            <dt>Run by</dt>
            <dd className="mono">{command.origin === 'cli' ? "the CLI itself, with a tool of its own" : 'KOLONİ'}</dd>
            <dt>Folder</dt>
            <dd className="mono">{command.cwd ?? 'not known'}</dd>
            <dt>Runs on</dt>
            <dd className="mono">{placeLabel(command)}</dd>
            <dt>Duration</dt>
            <dd className="mono">{seconds === null ? '—' : `${seconds}s`}</dd>
            <dt>Time limit</dt>
            <dd className="mono">{command.timeout_seconds}s</dd>
          </dl>
          {command.status === 'proposed' && renderCommandApproval?.(command)}
          {command.output !== '' && <pre className="mono insp-output">{command.output}</pre>}
          {command.output === '' && command.status !== 'proposed' && (
            <p className="muted">No output.</p>
          )}
        </div>
      </>
    )
  } else if (state && kind === 'file' && change) {
    content = (
      <>
        <Header
          icon={<FileText size={16} />}
          title={change.path.split('/').pop() ?? change.path}
          sub={change.path}
          onClose={onClose}
        />
        <div className="insp-body">
          <dl className="facts">
            <dt>Agent</dt>
            <dd className="mono">{roleOf(change.agent_id)}</dd>
            <dt>Made by</dt>
            <dd className="mono">{change.origin === 'cli' ? "the CLI itself, with a tool of its own" : 'KOLONİ'}</dd>
            <dt>Kind</dt>
            <dd className="mono">
              {change.kind === 'create' ? 'new file' : change.kind === 'delete' ? 'deleted file' : 'edit'}
            </dd>
            <dt>Status</dt>
            <dd>
              <span className={CHANGE_LABEL[change.status][1]}>{CHANGE_LABEL[change.status][0]}</span>
            </dd>
          </dl>
          {renderChange?.(change)}
        </div>
      </>
    )
  }

  // Hidden until something is selected, so the canvas keeps the room.
  if (!content) return null
  return (
    <aside ref={aside} className="inspector" aria-label="Inspector">
      {content}
    </aside>
  )
}
