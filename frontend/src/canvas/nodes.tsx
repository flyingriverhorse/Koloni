import { CaretDown, CaretRight, ChatsCircle, Clock, FileText, Lightbulb, ListChecks, Moon, Robot, User, UsersThree } from '@phosphor-icons/react'
import { Handle, type Node, type NodeProps, Position } from '@xyflow/react'
import { type CSSProperties, type ReactNode, useContext, useEffect, useState } from 'react'
import { api, errorText } from '../api/client'
import { AGENT_STATUS, WAITS } from '../agents/agentStatus'
import { SignChip, Since } from '../agents/signs'
import { ranOn } from '../shell/modelName'
import { StatusLabel } from '../shell/StatusLabel'
import { AwayReport } from '../backlog/Away'
import { doneSaid } from '../backlog/awayText'
import { useApp } from '../state/store'
import { type AgentData, type AttachmentData, type AwayData, type AwayJobData, type DiscussionData, type GroupData, type PlanData, type PoData, poSaid, poTokens, type ReadyData, type RequestData, type RoomData, type RoundData, type TeamData, statusWords } from './deriveGraph'
import { NodeActions, ToggleGroup } from './toggleGroup'

type Tone = 'idle' | 'running' | 'approval'

/**
 * Where lines leave and come in at a node's top and foot: in a team's frame between two of a column, a findings arc, and
 * a line across to another frame (K-canvas-dili), an approved plan down to its Lead. Only the line shows.
 */
const Ends = () => (
  <>
    <Handle type="source" id="found-out" position={Position.Bottom} isConnectable={false} className="found-handle" />
    <Handle type="target" id="found-in" position={Position.Top} isConnectable={false} className="found-handle" />
    <Handle type="source" id="up-out" position={Position.Top} isConnectable={false} className="found-handle" />
    <Handle type="target" id="up-in" position={Position.Bottom} isConnectable={false} className="found-handle" />
    <Handle type="source" id="plan-out" position={Position.Bottom} isConnectable={false} className="found-handle" />
    <Handle type="target" id="plan-in" position={Position.Top} isConnectable={false} className="found-handle" />
  </>
)

interface CardProps {
  icon: ReactNode
  title: string
  label?: string
  tone?: Tone
  selected?: boolean
  children: ReactNode
}

function Card({ icon, title, label, tone = 'idle', selected, children }: CardProps) {
  return (
    <div className={`node node-${tone}${selected ? ' node-selected' : ''}`}>
      <Handle type="target" position={Position.Left} isConnectable={false} />
      <div className="node-head">
        <span className="node-icon">{icon}</span>
        <span className="node-title">{title}</span>
        {label && <span className="node-label mono">{label}</span>}
      </div>
      <div className="node-body">{children}</div>
      <Handle type="source" position={Position.Right} isConnectable={false} />
      <Ends />
    </div>
  )
}

function clock(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
}

export function RequestNode({ data, selected }: NodeProps<Node<RequestData & Record<string, unknown>>>) {
  return (
    <Card
      icon={data.trigger === null ? <User size={13} /> : <Clock size={13} />}
      // Nobody wrote this just now: a trigger started the turn.
      title={data.trigger === null ? 'You' : 'Trigger'}
      label={clock(data.time)}
      selected={selected}
    >
      {/* (Three lines at most - the user's, 5 Nov: what was written, whole, is in the side panel.) */}
      {data.trigger !== null && data.trigger !== '' && <div className="node-meta mono">{data.trigger} · nobody watching</div>}
      <div className={`node-text${data.trigger ? ' node-text-one' : ''}`}>
        {data.queued && <span className="tag tag-accent">Queued</span>} {data.text}
      </div>
    </Card>
  )
}

/** A file the user attached (slice 85b): small, in its kind's colour; a click opens it in the inspector. */
export function AttachmentNode({ data, selected }: NodeProps<Node<AttachmentData & Record<string, unknown>>>) {
  return (
    <div className={`node node-attachment${selected ? ' node-selected' : ''}`} style={{ '--c': `var(${data.colour})` } as CSSProperties}>
      <Handle type="target" position={Position.Left} isConnectable={false} />
      <span className="file-ic mono" aria-hidden="true">
        {data.label}
      </span>
      <span className="att-text">
        <b className="node-title" title={data.name}>
          {data.name}
        </b>
        <span className="att-meta">{data.meta}</span>
      </span>
      <Handle type="source" position={Position.Right} isConnectable={false} />
    </div>
  )
}

/** More files than FOLD_FILES on a message: one box, "N files", folded until it is opened. */
export function FilesNode({ id, data, selected }: NodeProps<Node<GroupData & Record<string, unknown>>>) {
  const toggle = useContext(ToggleGroup)
  return (
    <div className={`node group files-group${data.open ? ' group-open' : ''}${selected ? ' node-selected' : ''}`}>
      <div className="group-head files-head node-head">
        <span className="node-icon">
          <FileText size={13} />
        </span>
        <span className="node-title">{data.summary}</span>
        <button
          type="button"
          className="group-fold nodrag"
          aria-expanded={data.open}
          aria-label={`${data.open ? 'Collapse' : 'Expand'} ${data.summary}`}
          onClick={event => {
            event.stopPropagation()
            toggle(id)
          }}
          onDoubleClick={event => event.stopPropagation()}
        >
          {data.open ? <CaretDown size={12} /> : <CaretRight size={12} />}
        </button>
      </div>
    </div>
  )
}

export function DiscussionNode({ data, selected }: NodeProps<Node<DiscussionData & Record<string, unknown>>>) {
  return (
    <Card
      icon={<ChatsCircle size={13} />}
      title="Discussion"
      label={data.line}
      tone={data.running ? 'running' : 'idle'}
      selected={selected}
    >
      <div className="node-line">{data.topic}</div>
      {/* Whose turn it is, or who takes part: the last things said are in the side panel (the user's, 5 Nov). */}
      {data.speaking ? (
        <div className="node-meta mono" style={{ color: 'var(--accent)' }}>
          {data.speaking} is speaking…
        </div>
      ) : (
        <div className="node-meta mono" title={data.members.join(' · ')}>
          {data.members.join(' · ')}
        </div>
      )}
    </Card>
  )
}

/** A room: its goal, and whether it waits for you - else how far its list is, or who is in it. */
export function RoomNode({ data, selected }: NodeProps<Node<RoomData & Record<string, unknown>>>) {
  return (
    <Card
      icon={<UsersThree size={13} />}
      title="Room"
      label={data.line}
      tone={data.attention ? 'approval' : data.running ? 'running' : 'idle'}
      selected={selected}
    >
      <div className="node-line">{data.goal}</div>
      {data.attention ? (
        <div className="node-meta mono" style={{ color: 'var(--warn)' }}>
          Waits for you
        </div>
      ) : (
        <div className="node-meta mono">{data.items || data.members.join(' · ')}</div>
      )}
    </Card>
  )
}

/** A plan turn's plan (slice 49), at the turn's start: what became of it, and who wrote it. */
export function PlanNode({ data, selected }: NodeProps<Node<PlanData & Record<string, unknown>>>) {
  return (
    <Card
      icon={<ListChecks size={13} />}
      title="Plan"
      label={data.status === 'writing' ? 'being written' : data.status}
      tone={data.status === 'proposed' ? 'approval' : data.status === 'writing' ? 'running' : 'idle'}
      selected={selected}
    >
      <div className="node-said">{data.by ?? 'Only reads; nothing changes before you approve.'}</div>
    </Card>
  )
}

/** The Assistant PO asked once the turn ended (the user's, 7 Nov): what came of it, what it spent, the way to the To-do list. A click opens why each one dropped was dropped. */
export function PoNode({ data, selected }: NodeProps<Node<PoData & Record<string, unknown>>>) {
  const { openTodo } = useContext(NodeActions)
  return (
    <Card icon={<Lightbulb size={13} />} title="Assistant PO" label={data.model_id ?? 'model not known'} selected={selected}>
      <div className="node-line" style={data.heard ? undefined : { color: 'var(--warn)' }}>
        {poSaid(data)}
      </div>
      <div className="node-meta mono">
        {poTokens(data)}{' '}
        <button
          type="button"
          className="link-btn nodrag"
          onClick={event => {
            event.stopPropagation() // (the To-do page, not the panel)
            openTodo?.()
          }}
        >
          To-do →
        </button>
      </div>
    </Card>
  )
}

type AgentProps = NodeProps<Node<AgentData & Record<string, unknown>>>

/** A finished agent of a step's newest round, the step having had rounds before (the user's, 4 Nov): one line. */
export function AgentNode(props: AgentProps) {
  return props.data.chip ? <AgentChip {...props} /> : <AgentCard {...props} />
}

/** Its name and how it ended; a click picks it, two open its window - as on its card (the node's own clicks). */
function AgentChip({ data, selected }: AgentProps) {
  const name = data.name || data.role
  const chip = data.chip!
  return (
    <div className={`node node-chip${selected ? ' node-selected' : ''}${data.colour ? ' group-team' : ''}`} style={data.colour ? ({ '--team': data.colour } as CSSProperties) : undefined}>
      <Handle type="target" position={Position.Left} isConnectable={false} />
      <button type="button" className="node-chip-button" aria-label={`${name}: ${chip.said}`} title={data.findings?.detail ?? data.activity}>
        <span className="node-chip-name">{name}</span>
        <span style={{ color: chip.colour }}>{chip.said}</span>
      </button>
      <Handle type="source" position={Position.Right} isConnectable={false} />
      <Ends />
    </div>
  )
}

/**
 * A step's earlier round (the user's, 4 Nov): one line - "▸ Round 2 · 4 reviewed · 2 blocking" - that opens its agents'
 * cards under it, in place, and folds them again.
 */
export function RoundNode({ id, data }: NodeProps<Node<RoundData & Record<string, unknown>>>) {
  const toggle = useContext(ToggleGroup)
  return (
    <div className="node-round">
      <Handle type="target" position={Position.Left} isConnectable={false} />
      <button
        type="button"
        className="node-round-button nodrag"
        aria-expanded={data.open}
        aria-label={[data.said, data.attention && WAITS, data.result].filter(Boolean).join(' · ')}
        onClick={event => {
          event.stopPropagation() // opening a round is not picking anything
          toggle(id)
        }}
        onDoubleClick={event => event.stopPropagation()}
      >
        <span className="node-chip-name">
          <span aria-hidden="true">{data.open ? '▾' : '▸'}</span> {data.said}
        </span>
        {/* (Something in it waits for the user: it stays open, and says so - as a closed box does.) */}
        {(data.result || data.attention) && (
          <span style={{ color: data.attention ? 'var(--warn)' : data.colour }}>{[data.attention && WAITS, data.result].filter(Boolean).join(' · ')}</span>
        )}
      </button>
      <Handle type="source" position={Position.Right} isConnectable={false} />
      <Ends />
    </div>
  )
}

/**
 * An agent (the user's, 5 Nov): three lines at most - its name and model, its state in plain words, and what it did,
 * counted. The rest - its tools, commands and files, tokens, tier, why it was chosen, its raw stream - is in the side
 * panel and its window, a click away. Waiting for you, it is lit as such.
 */
/** As an agent's state is drawn: at work, waiting for you, or neither. */
const toneOf = (status: AgentData['status']): Tone =>
  status === 'running' || status === 'waiting' ? 'running' : status === 'waiting_approval' || status === 'proposed' ? 'approval' : 'idle'

function AgentCard({ id, data, selected }: AgentProps) {
  const tone = toneOf(data.status)
  const name = data.name || data.role
  // Provider and model; with neither on record it says so rather than nothing.
  const where = ranOn(data.provider, data.modelId, data.modelFrom) || 'model unknown'
  const said = statusWords(data)
  return (
    <div className={`node node-agent node-${tone}${selected ? ' node-selected' : ''}${data.colour ? ' group-team' : ''}`} style={data.colour ? ({ '--team': data.colour } as CSSProperties) : undefined}>
      <Handle type="target" position={Position.Left} isConnectable={false} />
      <div className="node-head">
        <span className="node-icon">
          <Robot size={13} />
        </span>
        {/* Its name read in full; where it runs gives way first. */}
        <span className="node-names" title={`${name} · ${where}`}>
          <span className="node-title">{name}</span>
          <span className="node-where"> · {where}</span>
        </span>
      </div>
      <div className="node-body">
        {/* Its state's colour, as everywhere; its dot blinks while it is at work. */}
        <div className={`node-line mono${data.status === 'running' ? ' node-now' : ''}`} title={said}>
          {/* What was counted of its calls first, so that its state is what gets cut off. */}
          {data.sign && <SignChip agentId={id.replace(/^agent:/, '')} sign={data.sign} stopped={data.signStopped} />}
          <StatusLabel color={AGENT_STATUS[data.status][1]}>
            {data.since && <Since at={data.since} />}
            {said}
          </StatusLabel>
        </div>
        {(data.summary || data.spent) && <div className="node-meta mono">{[data.summary, data.spent].filter(Boolean).join(' · ')}</div>}
      </div>
      <Handle type="source" position={Position.Right} isConnectable={false} />
      <Ends />
    </div>
  )
}

const BRANCH_MARK = { done: ' ✓', now: ' …', next: '', stopped: ' (stopped)' } as const

/**
 * A chat team's recipe in the turn (slice 84b-2): a frame in its colour, drawn behind its agents' boxes. Its header
 * says the team, the recipe and its steps (done ticked, the one now filled), what its agents reported they used, and
 * holds its Stop and fold; at its recipe's end, or folded, a line says what it did or where it stands.
 */
export function TeamNode({ id, data }: NodeProps<Node<TeamData & Record<string, unknown>>>) {
  const toggle = useContext(ToggleGroup)
  const { stopTeam, finishTeam } = useContext(NodeActions)
  const [error, setError] = useState<string | null>(null)
  const [sent, setSent] = useState(false)
  const atWork = data.stands === 'running'
  // One word at a time: Stop and Finish now wait for the server's answer.
  const send = (word?: (teamId: string) => Promise<void>) => {
    setSent(true)
    void Promise.resolve(word?.(data.teamId))
      .catch(err => setError(errorText(err)))
      .finally(() => setSent(false))
  }
  return (
    <div className={`team-frame team-${data.stands}${data.open ? '' : ' team-shut'}`} style={{ '--team': data.colour } as CSSProperties}>
      <div className="team-head">
        <div className="team-title">
          {data.finished && <span className="team-tick">✓</span>}
          <b className="team-name">{data.team}</b>
          <span className="team-recipe">{data.recipe}</span>
          <span className="team-tokens mono muted">{data.tokens}</span>
          {atWork && !data.byRoles && (
            <button type="button" className="btn btn-small team-stop nodrag" aria-label={`Stop ${data.team}`} disabled={sent} onClick={() => send(stopTeam)}>
              Stop
            </button>
          )}
          {/* (A recipe's team: its steps are drawn. Finish now takes its work to Ready for you as it stands.) */}
          {atWork && !data.byRoles && data.steps.length > 0 && (
            <button type="button" className="btn btn-small team-stop nodrag" aria-label={`Finish ${data.team} now`} disabled={sent} onClick={() => send(finishTeam)}>
              Finish now
            </button>
          )}
          <button type="button" className="link-btn team-fold nodrag" aria-expanded={data.open} aria-label={`${data.open ? 'Fold' : 'Open'} ${data.team}`} onClick={() => toggle(id)}>
            {data.open ? 'fold' : 'open'}
          </button>
        </div>
        <ol className="team-steps" aria-label={`${data.recipe}: its steps`}>
          {data.steps.map(step => (
            <li key={step.id} className={`team-step team-step-${step.unmet ? 'unmet' : step.state}`} title={step.unmet ? `${step.name} · skipped: ${step.unmet}` : step.name} aria-current={step.state === 'now' ? 'step' : undefined}>
              {step.name}
              {/* K-tarif-kol: a group's branches, each its steps in order - "Checks: Build it ✓ → Test it … · Docs ✓". */}
              {step.branches && `: ${step.branches.map(line => line.map(one => one.name + BRANCH_MARK[one.state]).join(' → ')).join(' · ')}`}
              {data.many?.[step.id]?.map(many => ` · ${many}`)}
              {/* K-evrim: a step of candidates, the best score its measure gave. */}
              {step.best != null && ` · best ${step.best}`}
              {/* K-evrim-model: this round's, each with its model - "Coder 2 (gpt-luna): 85 · Coder (sonnet): 61". */}
              {step.scores && ` · ${step.scores}`}
              {step.missed != null && ` · target ${step.missed} not reached`}
              {step.room && <span className="team-step-room">Room</span>}
              {step.state === 'done' && ' ✓'}
              {/* (Its condition not met - no problem was found before it - is no rule broken.) */}
              {step.state === 'skipped' && (step.unmet ? ` · skipped: ${step.unmet}` : ' · skipped')}
              {step.round > 0 && ` · round ${step.round + 1}`}
              {step.own_check && ' · checked by its own writer'}
              {/* B-173: not a silent ✓ - what the user's choice left out of it. */}
              {step.left_out.length > 0 && ` · left out by your choice: ${step.left_out.join(', ')}`}
            </li>
          ))}
        </ol>
      </div>
      {/* Its steps at once (a group of its recipe's), round their agents: a dashed box. */}
      {data.open &&
        data.boxes?.map(box => (
          <div key={`${box.left},${box.top}`} className="team-at-once" style={box}>
            all at once
          </div>
        ))}
      {(!data.open || data.finished || !atWork || data.why) && <div className="team-foot">{data.summary}</div>}
      {error && (
        <p role="alert" className="alert team-foot">
          {error}
        </p>
      )}
      {/* (Its line to Ready for you: low, under its card - canvas.css.) */}
      <Handle type="source" position={Position.Right} isConnectable={false} className="team-out" />
      {/* Its door, by its header: the Lead's line comes in there, and the work line inside starts there. */}
      <Handle type="target" id="door-in" position={Position.Left} isConnectable={false} className="team-door" />
      <Handle type="source" id="door-out" position={Position.Left} isConnectable={false} className="team-door" />
    </div>
  )
}

/**
 * Where the turn's teams meet (slice 84b-2): dashed while it waits, saying for whom; "NEEDS YOU" once every team is at
 * its end, with each team's line and the checks its agents reported (never one nobody reported); "In the project ✓"
 * after Take in. What waits for you is answered in one place, the chat's Ready for you (K-bekleyenler): here, its count,
 * what it holds in one line, and the way there.
 */
export function ReadyNode({ data, selected }: NodeProps<Node<ReadyData & Record<string, unknown>>>) {
  const { openList } = useContext(NodeActions)
  const asked = data.questionId
  // B-67: its turn ended before Take in - the recipe's copy is kept, Take in or Discard is still yours.
  const kept = asked === null ? data.kept : null
  // (B-142: a Take in's clash waits in the list too - not "Nothing waits to be taken in.")
  const needs = asked !== null || kept !== null || data.rows.some(row => row.kept) || data.waiting.mine > 0
  const label = needs ? 'NEEDS YOU' : data.taken ? 'IN' : data.waits ? 'WAITS' : 'DONE'
  // B-84: what is in the project is said team by team - one taken in before is not "nothing".
  const inSoFar = data.inProject.length ? `In the project: ${data.inProject.join(', ')}.` : 'Nothing is in the project yet.'
  const said = kept
    ? `The work ended before Take in${data.left ? ` (${data.left})` : ''}: the work is kept in the recipe’s copy, not in the project.`
    : data.waits
      ? `Waits for ${data.waits}.`
      : needs
        ? `${data.notStarted.length ? `${data.notStarted.join(', ')} did not start.` : 'Every team is at its end.'} ${inSoFar}`
        : data.taken
          ? 'In the project ✓'
          : data.left
            ? `Not all of it is in the project: ${data.left}`
            : data.notStarted.length
              ? `${data.notStarted.join(', ')} did not start.`
              : 'Nothing waits to be taken in.'
  return (
    <div className={`node ready-node ${needs ? 'ready-needs' : data.taken ? 'ready-in' : 'ready-waits'}${selected ? ' node-selected' : ''}`}>
      <Handle type="target" position={Position.Left} isConnectable={false} className="ready-door" />
      <div className="node-head">
        <span className="node-icon">
          <ListChecks size={13} />
        </span>
        <span className="node-title">Ready for you</span>
        {data.waiting.count > 0 && <span className="tag tag-warn">{data.waiting.count}</span>}
        {data.waiting.decided > 0 && <span className="mono muted">{data.waiting.decided} decided</span>}
        <span className="node-label mono">{label}</span>
      </div>
      <div className="node-body">
        <div className="node-said">{said}</div>
        {data.rows.map(row => (
          <div key={row.team} className="ready-row" style={{ '--team': row.colour } as CSSProperties}>
            <b>{row.team}</b> · {row.recipe} {row.done && <span className="ready-ok">✓</span>}
            <div className="muted">{row.line}</div>
          </div>
        ))}
        {(asked || kept) && data.alsoTakes && <div className="muted">{data.alsoTakes}</div>}
        {asked && (
          <div className="ready-checks">
            {data.checks.length > 0 ? (
              data.checks.map(check => (
                <span key={check.text} className={`ready-check${check.passed ? '' : ' ready-check-left'}`}>
                  {check.text}
                </span>
              ))
            ) : (
              <span className="ready-check ready-check-none">no check reported by its agents</span>
            )}
          </div>
        )}
        {data.waiting.count + data.waiting.decided > 0 && (
          <div className="ready-list">
            <div>{data.waiting.summary}</div>
            <button type="button" className="link-btn nodrag" onClick={() => openList?.()}>
              Open the list →
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

const JOB_WORD = { planned: '', next: 'NEXT', working: 'WORKING', waits: 'WAITS', done: 'DONE', failed: 'NOT DONE', stopped: 'STOPPED' } as const
const openChat = (cid: string) => void useApp.getState().openConversation(cid)

/** A job of a night while you were away (slice 106), closed: its chat holds its agents, opened from here. */
export function AwayJobNode({ data, selected }: NodeProps<Node<AwayJobData & Record<string, unknown>>>) {
  const { job } = data
  const tone = job.state === 'working' ? 'running' : job.state === 'waits' ? 'approval' : 'idle'
  const chat = job.conversation_id
  return (
    <Card icon={<Moon size={13} />} title={job.title} label={JOB_WORD[job.state]} tone={tone} selected={selected}>
      <div className="node-said">{[job.team, job.state === 'done' ? doneSaid(job) : job.why].filter(Boolean).join(' · ')}</div>
      {chat && (
        <button type="button" className="link-btn nodrag" onClick={() => openChat(chat)}>
          ▸ open its chat
        </button>
      )}
    </Card>
  )
}

/** The morning's report of a night while you were away (slice 106): its own node, never written into the chat. */
export function AwayNode({ data, selected }: NodeProps<Node<AwayData & Record<string, unknown>>>) {
  const { away } = data
  // On screen: KOLONİ opened from now on does not go to it again (the morning's jump, App).
  const unseen = away.status === 'ended' && !away.seen_at ? away.id : null
  useEffect(() => {
    if (unseen) void api.post('/away/' + unseen + '/seen').catch(() => {})
  }, [unseen])
  const needs = (away.counts.waits ?? 0) > 0 || away.jobs.some(job => job.state === 'done' && job.kept.length > 0)
  return (
    <div className={`node away-node${selected ? ' node-selected' : ''}`}>
      <Handle type="target" position={Position.Left} isConnectable={false} />
      <div className="node-head">
        <span className="node-icon">
          <Moon size={13} />
        </span>
        <span className="node-title">{away.status === 'running' ? "While you're away" : 'While you were away'}</span>
        <span className="node-label mono">{away.status === 'running' ? 'WORKING' : needs ? 'NEEDS YOU' : 'DONE'}</span>
      </div>
      <div className="node-body nodrag nowheel">
        <AwayReport away={away} onOpen={openChat} />
      </div>
    </div>
  )
}
