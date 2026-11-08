import { ArrowCounterClockwise, ArrowDown, CaretRight, ChatsCircle, Clock, Copy, DotsThree, FolderOpen, GitBranch, Graph, Moon } from '@phosphor-icons/react'
import { SUMMARISING, titleOf as agentTitle } from '../agents/agentStatus'
import { Fragment, type ReactNode, useEffect, useId, useMemo, useRef, useState } from 'react'
import { Markdown, UserText } from './Markdown'
import { AgentSaid, isFrame } from './AgentSaid'
import { QuestionCard, QuestionRow } from '../agents/QuestionCard'
import { RoleApproval } from '../agents/RoleApproval'
import { SkillApproval } from '../agents/SkillApproval'
import { SpawnApproval, type SpawnDecision } from '../agents/SpawnApproval'
import { failureText, nextStep, planConsole } from '../agents/failure'
import { SpawnRow } from '../agents/SpawnRow'
import { isReadyCard, keptNote, readyLine, turnTeams } from '../agents/teamRun'
import { staysOn } from '../agents/staysOn'
import type { Agent, Attachment, Compare, FileChange, Merge, Message, Price, Provider, NotesOffer, Question, Role, Run, ToolCall, TriggerProposal, Usage } from '../api/types'
import { Minis } from './Attach'
import { linksIn } from './attachments'
import { ChangeActions, type ChangeAction } from '../changes/ChangeActions'
import { WAITS_FOR_A_PLACE } from '../changes/changeLabel'
import { canContinue, hasCard, pendingMerge } from '../changes/copies'
import { type Choices, MergeCard, type Shown } from '../changes/MergeCard'
import { NotApplied } from '../changes/NotApplied'
import { UndoCard } from '../changes/UndoCard'
import { callWaits } from '../claims/claims'
import { CommandApproval, type CommandDecision } from '../commands/CommandApproval'
import { OutsideApproval, type OutsideDecision } from '../commands/OutsideApproval'
import { WebApproval } from '../commands/WebApproval'
import { CommandRow } from '../commands/CommandRow'
import { TERMINAL, type ConvState } from '../state/applyEvent'
import { discussionLine } from '../discussion/discussionText'
import { MemoryTold } from '../memory/MemoryTold'
import { NotesOfferCard } from '../knowledge/NotesOfferCard'
import { RoomRow } from '../room/RoomRow'
import { continuesFrom, titleOf } from '../topics/topics'
import { refusedIn } from '../triggers/refused'
import type { Allow } from '../triggers/triggerText'
import { WouldHaveAsked } from '../triggers/WouldHaveAsked'
import { TriggerProposalCard } from '../triggers/TriggerProposalCard'
import { ReadAloud, SaidAloud } from '../voice/VoiceControls'
import { AwayCard, AwayFrom } from '../backlog/Away'
import { NightRow } from '../ready/NightRow'
import { type BranchSaid, useApp } from '../state/store'
import { InjectionWarning } from './InjectionWarning'
import { PlanCard } from './PlanCard'
import { RequestRow } from './RequestRow'
import { TalkRow, talkOf } from './TalkRow'
import { requestsOf } from '../agents/teamRequests'
import { ToolRow } from './ToolRow'
import { ToolRun } from './ToolRun'
import { TurnSummary } from './TurnSummary'
import { callsByMessage, toolRuns } from './toolRuns'
import { answerLast } from './chatLine'
import { asksOutside } from './toolSummary'
import { PARTS, type Waiting, decidedOf, waitingId, waitingOf } from './waiting'
import { DecidedForYou } from './DecidedForYou'
import { CompareView } from './CompareView'
import { modelName } from '../shell/modelName'
import { foldRepeats } from '../shell/repeats'
import { usePanel } from '../shell/usePanel'
import { when, workOf } from '../canvas/turns'

interface Props {
  state: ConvState
  onRemoveQueued: (runId: string) => void
  onOpenChange: (changeId: string) => void
  onDecide: (changeId: string, action: ChangeAction) => Promise<void>
  onDecideCommand: (commandId: string, decision: CommandDecision) => Promise<void>
  /** Let a web search or an HTTP request go out once, always, or not at all. */
  onDecideWeb?: (requestId: string, decision: CommandDecision) => Promise<void>
  onSelectAgent?: (agentId: string) => void
  onDecideSpawn?: (agentId: string, decision: SpawnDecision) => Promise<void>
  /** A role an agent asked to create, or a path outside the project: once, or its whole folder. */
  onDecideRole?: (toolCallId: string, decision: SpawnDecision, scope?: 'once' | 'folder' | 'ask_scripts') => Promise<void>
  /** Approve a plan turn's plan (as edited) or turn it down (with why). */
  onDecidePlan?: (runId: string, decision: SpawnDecision, text?: string, overBudget?: boolean) => Promise<void>
  /** Take an agent's changes into the project - with whose side is taken of each file that clashes - or discard them. */
  onDecideMerge?: (mergeId: string, decision: SpawnDecision, choices?: Choices, shown?: Shown, said?: BranchSaid) => Promise<void>
  /** Run the project's check command on what an agent's card would take. */
  onCheckMerge?: (mergeId: string, choices: Choices) => Promise<void>
  /** Commit the files that were taken from an agent, with this message. */
  onCommitMerge?: (mergeId: string, message: string, hooks?: 'with' | 'without') => Promise<void>
  onAnswer?: (questionId: string, answer: string) => Promise<void>
  onOpenDiscussion?: (discussionId: string) => void
  /** Show a turn's room: its window. */
  onOpenRoom?: (roomId: string) => void
  /** Open a trigger's form with something its turn was refused allowed in it - not saved. */
  onAllowInTrigger?: (triggerId: string, allow: Allow) => void
  /**
   * The roles and providers as they stand now: a card that asks before an agent goes on
   * from an earlier turn says where its role would run today. Not known, it does not.
   */
  roles?: Role[]
  providers?: Provider[]
  /** What a turn's agents spent and its known cost, read when an answer's details are opened; without it the cost is a dash. */
  onUsage?: (runId: string) => Promise<Usage>
  prices?: Price[]
  /** A comparison of two models (slice 54): read, and decided - one side's work taken (its turn), or both thrown away (null). */
  onLoadCompare?: (compareId: string) => Promise<Compare>
  onDecideCompare?: (compareId: string, runId: string | null) => Promise<Compare>
  /** Show a message's work on the canvas: its turn. */
  onShowTurn?: (runId: string) => void
  /** Open the project's git map (slice 70): from KOLONİ's line on what a turn did to git. */
  onShowGit?: () => void
}

/** A side of a comparison as its section names it: "provider · model", from its lead's record. */
function sideName(state: ConvState, runId: string): string {
  const lead = state.agents.find(a => a.run_id === runId && a.depth === 0)
  return [lead?.provider_name ?? 'A side', lead?.model_id && modelName(lead.model_id)].filter(Boolean).join(' · ')
}

type Notice = { title: string; text?: string; alert: boolean; step?: string | null; console?: string | null }

const KOLONI_LINES = new Set<Message['role']>(['git', 'landed', 'koloni'])

/** A line of KOLONİ's own in the chat, which no agent wrote: on git, on where a turn's work is, or another. */
function KoloniLine({ message, onShowGit }: { message: Message; onShowGit?: () => void }) {
  if (message.role === 'git') {
    // What a turn did to the project's git (slice 70): a branch switched, a worktree opened.
    return (
      <div className="msg msg-from git-said" role="note">
        <GitBranch size={13} aria-hidden />
        <span className="git-said-text">{message.content}</span>
        {onShowGit && (
          <button type="button" className="btn btn-small" onClick={onShowGit}>
            Show git
          </button>
        )}
      </div>
    )
  }
  if (message.role === 'landed') {
    // B-205: under the answer, where the turn's work is - from KOLONİ's records, not the model's words.
    return (
      <p className="msg msg-from landed-said" role="note" title="From KOLONİ's records, not the model's words">
        <FolderOpen size={13} aria-hidden />
        <span>
          <span className="landed-by">KOLONİ:</span> {message.content}
        </span>
      </p>
    )
  }
  // A role a Lead's answer named but never opened this turn (K-lead-andigi-rol); at Take in, what stays in a copy (B-383).
  // Above the answer it follows (`answerLast`).
  return (
    <p className="msg msg-from muted" role="note">
      {message.content}
    </p>
  )
}

/** A turn's end as a card that only tells: a failure is said at once - an alert - with the one thing to do about it. */
function RunNotice({ notice }: { notice: Notice }) {
  return (
    <div role={notice.alert ? 'alert' : undefined} className="cmd-approval card-tell">
      <div className="kicker cmd-approval-kicker">{notice.title}</div>
      {notice.text && <p className="card-said">{notice.text}</p>}
      {notice.step && <p className="card-said">{notice.step}</p>}
      {notice.console && (
        <a href={notice.console} target="_blank" rel="noreferrer">
          See what is left in Alibaba's console
        </a>
      )}
    </div>
  )
}

/** What to say under a turn once its run has ended without completing: its title and why. */
function runNotice(run: Run, lead?: Agent, providers: Provider[] = []): Notice | null {
  switch (run.status) {
    case 'failed': {
      // Why the lead's model failed, in plain words, before the provider's own.
      const why = lead && failureText(lead)
      const failed = { failure: null, failure_resets_at: null, ...lead, error: run.error }
      // shortcut: matched by the provider's name, as a card's spend is; a renamed provider's agents are not found.
      const provider = providers.find(p => p.name === lead?.provider_name)
      return run.error === 'step_limit'
        ? { title: 'Stopped at its step limit', alert: true }
        : {
            title: 'Run failed',
            text: `${why ? `${why}. ` : ''}${run.error}`,
            alert: true,
            // The one thing to do about it, as the inspector says it (slice 38f).
            step: nextStep(failed, provider),
            console: planConsole(failed, provider),
          }
    }
    case 'cancelled':
      return run.started_at ? { title: 'Stopped', alert: false } : null
    case 'interrupted':
      return { title: 'Interrupted by a server restart', text: 'Send a message to continue.', alert: false }
    default:
      return null
  }
}

interface ChangeLineProps {
  change: FileChange
  onOpen: () => void
  onDecide: (action: ChangeAction) => Promise<void>
}

/** The decision on a path outside the project, as the tool-call route takes it. */
function outsideWord(decide: Handlers['onDecideRole'], callId: string) {
  return (decision: OutsideDecision) => (decision === 'reject' ? decide(callId, 'reject') : decide(callId, 'approve', decision))
}

function ChangeLine({ change, onOpen, onDecide }: ChangeLineProps) {
  return (
    <div className={`chat-change${change.status === 'proposed' ? ' chat-change-waiting' : ''}`}>
      <span className="mono chat-change-path">{change.path}</span>
      <span className="mono" style={{ color: 'var(--ok)' }}>+{change.additions}</span>
      <span className="mono" style={{ color: 'var(--del)' }}>−{change.deletions}</span>
      <button type="button" className="btn btn-small" onClick={onOpen}>
        View diff
      </button>
      <ChangeActions change={change} onDecide={onDecide} />
    </div>
  )
}

type Handlers = Required<
  Omit<Props, 'state' | 'onRemoveQueued' | 'onOpenDiscussion' | 'onOpenRoom' | 'onAllowInTrigger' | 'onDecidePlan' | 'roles' | 'providers' | 'onUsage' | 'prices' | 'onLoadCompare' | 'onDecideCompare' | 'onShowTurn' | 'onShowGit'>
>
type Known = Required<Pick<Props, 'roles' | 'providers'>>
/** What `SubtreeRequests` needs to put a card before you and take your word on it. */
export type RequestHandlers = Handlers
const NONE: never[] = []
// Calls that once stood alone (a card, a row that waited): what you decided stays in sight, not folded into a line, until a reload.
const stood = new Set<string>()

/**
 * Everything the agents under one sub-agent are waiting on you for. Their own
 * conversation is not in the chat, so their questions are brought here, each one
 * saying who asks. (A room's members were opened by no call of the lead's: theirs are
 * brought to the room's window the same way.)
 */
export function SubtreeRequests({ root, state, on, known }: { root: Agent; state: ConvState; on: Handlers; known: Known }) {
  const continueSteps = useApp(s => s.projects.find(p => p.id === state.conversation.project_id)?.continue_steps)
  const inside = new Map<string, Agent>([[root.id, root]])
  // Agents are stored parents first, so one pass collects the whole sub-tree.
  for (const agent of state.agents) {
    if (agent.parent_agent_id && inside.has(agent.parent_agent_id)) inside.set(agent.id, agent)
  }
  const lead = state.agents.find(a => a.run_id === root.run_id && a.depth === 0)?.name ?? ''
  const toLead = (call: ToolCall) => talkOf(call).to.trim().toLowerCase() === lead.toLowerCase()
  const asks = (agentId: string) => (
    <div className="asked-by mono">{inside.get(agentId)?.name || 'Agent'} asks</div>
  )
  return (
    <>
      {state.toolCalls
        // What they wrote to the lead is already in the chat, as a message from them.
        .filter(t => t.name === 'message_agent' && inside.has(t.agent_id) && !toLead(t))
        .sort((a, b) => a.seq - b.seq)
        .map(t => (
          <TalkRow key={t.id} call={t} from={inside.get(t.agent_id)?.name || 'Agent'} />
        ))}
      {state.questions
        .filter(q => q.status === 'pending' && inside.has(q.agent_id))
        .map(q => (
          <Fragment key={q.id}>
            {/* Leave for a tool is KOLONİ's question, about that agent's call: the agent asks nothing. */}
            {q.leave ? <div className="asked-by mono">for {inside.get(q.agent_id)?.name || 'Agent'}</div> : asks(q.agent_id)}
            <ChatQuestion state={state} question={q} onAnswer={answer => on.onAnswer(q.id, answer)} />
          </Fragment>
        ))}
      {state.pendingRoles
        .filter(role => inside.has(role.agent_id))
        .map(role => (
          <Fragment key={role.tool_call_id}>
            {asks(role.agent_id)}
            <RoleApproval role={role} onDecide={decision => on.onDecideRole(role.tool_call_id, decision)} />
          </Fragment>
        ))}
      {state.pendingSkills
        .filter(skill => inside.has(skill.agent_id))
        .map(skill => (
          <Fragment key={skill.tool_call_id}>
            {asks(skill.agent_id)}
            <SkillApproval skill={skill} onDecide={(decision, scope) => on.onDecideRole(skill.tool_call_id, decision, scope)} />
          </Fragment>
        ))}
      {state.agents
        .filter(a => a.status === 'proposed' && a.id !== root.id && a.parent_agent_id && inside.has(a.parent_agent_id))
        .map(a => (
          <Fragment key={a.id}>
            {asks(a.parent_agent_id ?? '')}
            <SpawnApproval
              agent={a}
              openedBy={state.agents.find(parent => parent.id === a.parent_agent_id)?.name}
              continuesTurn={continuesFrom(state, a.id)}
              stays={staysOn(state, a, known.roles, known.providers)}
              onDecide={decision => on.onDecideSpawn(a.id, decision)}
            />
          </Fragment>
        ))}
      {state.commands
        .filter(c => c.status === 'proposed' && inside.has(c.agent_id))
        .map(c => (
          <Fragment key={c.id}>
            {asks(c.agent_id)}
            <CommandApproval command={c} why={state.toolCalls.find(t => t.id === c.tool_call_id)?.why_asked} onDecide={decision => on.onDecideCommand(c.id, decision)} />
          </Fragment>
        ))}
      {state.webRequests
        .filter(w => w.status === 'proposed' && inside.has(w.agent_id))
        .map(w => (
          <Fragment key={w.id}>
            {asks(w.agent_id)}
            <WebApproval
              request={w}
              call={state.toolCalls.find(call => call.id === w.tool_call_id)}
              // B-134: an expert's search is asked every time - no rule of the conversation covers it.
              // (As the server tells one: its role, found by name in any case, has knowledge.)
              expert={known.roles.some(role => role.name.toLowerCase() === inside.get(w.agent_id)?.role_name.toLowerCase() && (role.knows ?? []).some(one => one.mode === 'full' && (one.project_id === null || one.project_id === state.conversation.project_id)))}
              onDecide={decision => on.onDecideWeb(w.id, decision)}
            />
          </Fragment>
        ))}
      {state.toolCalls
        .filter(t => asksOutside(t) && inside.has(t.agent_id))
        .map(t => (
          <Fragment key={t.id}>
            {asks(t.agent_id)}
            <OutsideApproval
              call={t}
              who={inside.get(t.agent_id)?.name || 'Agent'}
              onDecide={outsideWord(on.onDecideRole, t.id)}
              plain={state.conversation.project_id === null}
            />
          </Fragment>
        ))}
      {state.fileChanges
        .filter(f => f.status === 'proposed' && inside.has(f.agent_id))
        .map(f => (
          <Fragment key={f.id}>
            {asks(f.agent_id)}
            <ChangeLine change={f} onOpen={() => on.onOpenChange(f.id)} onDecide={action => on.onDecide(f.id, action)} />
          </Fragment>
        ))}
      {/* What a sub-agent changed in its working copy: asked about once, for all of it. */}
      {state.merges
        .filter(m => hasCard(m) && inside.has(m.agent_id))
        .map(m => (
          <MergeCard
            key={m.id}
            merge={m}
            name={inside.get(m.agent_id)?.name || 'Agent'}
            unfinished={inside.get(m.agent_id)?.status === 'failed'}
            onDecide={(...said) => on.onDecideMerge(m.id, ...said)}
            onCheck={choices => on.onCheckMerge(m.id, choices)}
            onCommit={(message, hooks) => on.onCommitMerge(m.id, message, hooks)}
            onContinue={continueSteps != null && canContinue(state, m) ? { steps: continueSteps, run: () => useApp.getState().continueMerge(m.id) } : undefined}
          />
        ))}
      {/* Settled, and not all of it reached the project: said here, in a turn nobody watched too. */}
      {state.merges
        .filter(m => inside.has(m.agent_id))
        .map(m => (
          <NotApplied key={m.id} merge={m} name={inside.get(m.agent_id)?.name || 'Agent'} />
        ))}
    </>
  )
}

/**
 * A question in the chat, as its card - or, answered, what was asked and said. KOLONİ's Ready for you card is one line
 * here, with its choices and a way to the card in full on the Ready for you list (K-hazir-satir).
 */
function ChatQuestion({ state, question, onAnswer }: { state: ConvState; question: Question; onAnswer: (answer: string) => Promise<void> }) {
  const line = isReadyCard(question) ? readyLine(state, question.run_id, { at: question.created_at, open: question.status === 'pending' }) : undefined
  if (question.status !== 'pending') return <QuestionRow question={question} text={line} />
  const details = () => useApp.getState().showReady(true, waitingId(question.id))
  return (
    <>
      <QuestionCard question={question} onAnswer={onAnswer} line={line === undefined ? undefined : { text: line, onDetails: details }} />
      {/* K-lead-bekliyor (R116): a message sent meanwhile is queued below, with nothing by the question saying why it waits. */}
      {state.runs.some(r => r.status === 'queued') && (
        <div role="note" className="muted cmd-approval-note">
          Your message waits until this question is answered
        </div>
      )}
    </>
  )
}


/** A merge's card's words on its agent, as the inspector gives them: its name, whether it finished, and - a Lead's, a recipe's copy - what Take in takes in with it. */
function mergeSaid(state: ConvState, merge: Merge): { name: string; unfinished: boolean; also: string } {
  const agent = state.agents.find(a => a.id === merge.agent_id)
  return {
    name: agent?.name || agent?.role_name || 'Agent',
    unfinished: agent?.status === 'failed',
    also: agent?.depth === 0 ? keptNote(turnTeams(state, merge.run_id), state.fileChanges, merge.run_id) : '',
  }
}

/** A proposed trigger's card, with what Approve, Edit and Reject do (slice 69). */
/** K-bilgi 6: a Project notes offer's card, answered through the store - whenever you like. */
function NotesCard({ offer }: { offer: NotesOffer }) {
  return <NotesOfferCard offer={offer} onAnswer={(lines, add) => useApp.getState().answerNotesOffer(offer.id, lines, add)} />
}

function ProposalCard({ proposal }: { proposal: TriggerProposal }) {
  return <TriggerProposalCard proposal={proposal} onDecide={decision => useApp.getState().decideProposal(proposal.id, decision)} onEdit={() => useApp.getState().editProposal(proposal)} />
}

/**
 * Ready for you (K-bekleyenler): everything of the chat that waits for you, in one list and answered from it, with the
 * cards the chat draws - also what the chat could not draw where it stands (B-99, B-128). A question no longer asked is
 * shown grey, with nothing to answer.
 */
export function WaitingList({ state, on, onDecidePlan, known }: WaitingProps) {
  const id = useId()
  // (What can be answered now: a question no longer asked waits for nothing - the panel counts these.)
  const rows = waitingOf(state).filter(row => row.current)
  const teams = useApp(s => s.teams)
  const nameOf = (agentId: string | null) => agentTitle(state.agents.find(a => a.id === agentId)?.name || 'Agent', teams)
  // B-183: in the same place as below, so Decided for you stays mounted once its last one is changed - and
  // says whom that Change was sent to.
  if (rows.length === 0 && decidedOf(state).length === 0)
    return (
      <div className="msg-list msg-empty muted">
        Nothing waits for you.
        <DecidedForYou state={state} />
      </div>
    )
  return (
    <div className="msg-list waiting-list">
      {PARTS.map(([head, kinds], part) => {
        const mine = rows.filter(row => kinds.includes(row.kind))
        return (
          mine.length > 0 && (
            <section key={head} aria-labelledby={`${id}-${part}`}>
              <h3 id={`${id}-${part}`} className="kicker">
                {head}
              </h3>
              {mine.map(row => (
                <Fragment key={row.key}>
                  {/* (A merge's card names its agent; a ready copy is KOLONİ's to ask; the plan is the turn's.) */}
                  {row.agentId && row.kind !== 'ready' && row.what !== 'merge' && (
                    <div className="asked-by mono">
                      {row.what === 'question' && row.item.leave ? `for ${nameOf(row.agentId)}` : `${nameOf(row.agentId)} asks`}
                    </div>
                  )}
                  {/* (By its id the chat's ready line opens the list at it: K-hazir-satir.) */}
                  <div id={waitingId(row.key)} tabIndex={-1}>
                    <WaitingCard state={state} row={row} on={on} onDecidePlan={onDecidePlan} known={known} />
                  </div>
                </Fragment>
              ))}
            </section>
          )
        )
      })}
      {/* What only told you, last and not counted: Decided for you is its own card, under its own title. (Second child
          here as in the empty list: B-183.) */}
      <DecidedForYou state={state} />
    </div>
  )
}

type WaitingProps = { state: ConvState; on: Handlers; onDecidePlan: Required<Props>['onDecidePlan']; known: Known }

/** One thing that waits for you, as its own card: on the chat's Ready for you list and on Ready for you's rows (tek-ev §1). */
export function WaitingCard({ state, row, on, onDecidePlan, known }: WaitingProps & { row: Waiting }): ReactNode {
  const continueSteps = useApp(s => s.projects.find(p => p.id === state.conversation.project_id)?.continue_steps)
  const teams = useApp(s => s.teams)
  const nameOf = (agentId: string | null) => agentTitle(state.agents.find(a => a.id === agentId)?.name || 'Agent', teams)
  switch (row.what) {
    case 'question':
      return <QuestionCard question={row.item} onAnswer={answer => on.onAnswer(row.item.id, answer)} />
    case 'command':
      return <CommandApproval command={row.item} why={state.toolCalls.find(t => t.id === row.item.tool_call_id)?.why_asked} onDecide={decision => on.onDecideCommand(row.item.id, decision)} />
    case 'change':
      return <ChangeLine change={row.item} onOpen={() => on.onOpenChange(row.item.id)} onDecide={action => on.onDecide(row.item.id, action)} />
    case 'web':
      return <WebApproval request={row.item} call={state.toolCalls.find(call => call.id === row.item.tool_call_id)} onDecide={decision => on.onDecideWeb(row.item.id, decision)} />
    case 'spawn':
      return (
        <SpawnApproval
          agent={row.item}
          openedBy={nameOf(row.item.parent_agent_id)}
          continuesTurn={continuesFrom(state, row.item.id)}
          stays={staysOn(state, row.item, known.roles, known.providers)}
          onDecide={decision => on.onDecideSpawn(row.item.id, decision)}
        />
      )
    case 'role':
      return <RoleApproval role={row.item} onDecide={decision => on.onDecideRole(row.item.tool_call_id, decision)} />
    case 'skill':
      return <SkillApproval skill={row.item} onDecide={(decision, scope) => on.onDecideRole(row.item.tool_call_id, decision, scope)} />
    case 'outside':
      return <OutsideApproval call={row.item} who={nameOf(row.item.agent_id)} onDecide={outsideWord(on.onDecideRole, row.item.id)} plain={state.conversation.project_id === null} />
    case 'plan':
      return <PlanCard run={row.item} onDecide={(...decision) => onDecidePlan(row.item.id, ...decision)} />
    case 'merge':
      return (
        <MergeCard
          merge={row.item}
          {...mergeSaid(state, row.item)}
          onDecide={(...said) => on.onDecideMerge(row.item.id, ...said)}
          onCheck={choices => on.onCheckMerge(row.item.id, choices)}
          onCommit={(message, hooks) => on.onCommitMerge(row.item.id, message, hooks)}
          onContinue={continueSteps != null && canContinue(state, row.item) ? { steps: continueSteps, run: () => useApp.getState().continueMerge(row.item.id) } : undefined}
        />
      )
    case 'away':
      return <AwayCard card={row.item} />
    case 'trigger':
      return <ProposalCard proposal={row.item} />
    case 'notes':
      return <NotesCard offer={row.item} />
    case 'night':
      return <NightRow job={row.item.job} onOpen={cid => void useApp.getState().openConversation(cid)} />
  }
}

/**
 * A message's ⋯ (slice 107): Copy, Restore to before it, Show its work on the canvas. `at` - its
 * time - tells one message's buttons from another's to a screen reader.
 */
function MessageMenu({ at, copy, onRestore, onShow }: { at: string; copy: string; onRestore?: () => void; onShow?: () => void }) {
  const { open, setOpen, close, button, panel } = usePanel()
  const [copied, setCopied] = useState(false)
  if (!open && copied) setCopied(false)
  const pick = (what: () => void) => () => {
    close()
    what()
  }
  return (
    <>
      <button
        ref={button}
        type="button"
        className="icon-btn msg-tool"
        aria-label={`Copy, restore, show its work · ${at}`}
        title="Copy, restore, show its work"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => (open ? close() : setOpen(true))}
      >
        <DotsThree size={14} weight="bold" />
      </button>
      {open && (
        <div ref={panel} tabIndex={-1} className="allow-list-panel msg-menu" role="menu" aria-label="Copy, restore, show its work">
          {/* (It stays open to say so; no clipboard here, or the browser refused: it stays "Copy".) */}
          <button type="button" role="menuitem" aria-live="polite" onClick={() => void navigator.clipboard?.writeText(copy).then(() => setCopied(true), () => {})}>
            <Copy size={13} /> {copied ? 'Copied' : 'Copy'}
          </button>
          {onRestore && (
            <button type="button" role="menuitem" onClick={pick(onRestore)}>
              <ArrowCounterClockwise size={13} /> Restore to before this message
            </button>
          )}
          {onShow && (
            <button type="button" role="menuitem" onClick={pick(onShow)}>
              <Graph size={13} /> Show its work on the canvas
            </button>
          )}
        </div>
      )}
    </>
  )
}

/** The card that puts the conversation back to before a message: what it would take back first. */
const restoreCard = (run: Run, title: string, onClose: () => void) => (
  <UndoCard path={`/conversations/${run.conversation_id}/restore?before=${run.id}`} title={title} confirm="Restore" onClose={onClose} />
)

/** What is drawn of it by a click: not a click that selected its words, nor one on a link or a button in it. */
const picked = (event: MouseEvent) => window.getSelection()?.isCollapsed !== false && !(event.target as Element).closest('a, button')

interface UserMessageProps {
  message: Message
  run?: Run
  files?: Attachment[]
  /** Where "Save these to the project too" put its files (slice 23): the changes in the project. */
  saved?: FileChange[]
  /** Its work changed files in the project. */
  changed: boolean
  onRemove: () => void
  onShow?: (runId: string) => void
}

/** The user's message: with ↺ when its work changed files, and ⋯ - Copy, Restore to before it, Show its work (slice 107). */
function UserMessage({ message, run, files = [], saved = [], changed, onRemove, onShow }: UserMessageProps) {
  const removed = run?.status === 'cancelled' && !run.started_at
  const [undoing, setUndoing] = useState<'undo' | 'restore' | null>(null)
  // (A turn that runs is stopped first: undoing it would race what it writes.)
  // (Not a comparison's, which would undo one side: its pick is undone under the two, `CompareView`.)
  // Only a message whose work changed files has it (slice 107 §3); a kept copy is decided on its card, or by Restore.
  const over = run && run.started_at && TERMINAL.has(run.status)
  const undoable = over && !run.compare_id && changed
  const at = when(message.created_at)
  return (
    <div className={`msg msg-user${removed ? ' msg-removed' : ''}`}>
      <div className="msg-user-row">
        {undoable && !undoing && (
          <button type="button" className="icon-btn msg-tool" aria-label={`Undo these changes · ${at}`} title="Undo these changes" onClick={() => setUndoing('undo')}>
            <ArrowCounterClockwise size={13} />
          </button>
        )}
        {run && !removed && (
          <MessageMenu
            at={at}
            copy={message.content || files.map(file => file.name).join('\n')}
            // (Not while it is queued or at work: it would race what it writes.)
            onRestore={over ? () => setUndoing('restore') : undefined}
            onShow={onShow && (() => onShow(run.id))}
          />
        )}
        <div className="msg-bubble" onClick={event => run && onShow && !removed && picked(event.nativeEvent) && onShow(run.id)}>
          {message.content && <UserText>{message.content}</UserText>}
          {/* The files sent with it (slice 85b), and its links: these are chips in the chat too. */}
          <Minis files={files} links={linksIn(message.content)} />
        </div>
      </div>
      {saved.map(change => (
        <div key={change.id} className="msg-meta muted att-saved">
          saved to <span className="mono">{change.path}</span>
        </div>
      ))}
      {/* (Not by `undoable`: once undone nothing it changed stands, and the card still says what was done.) */}
      {run && undoing === 'undo' && <UndoCard path={`/runs/${run.id}/undo`} title="Undo these changes" confirm="Undo" onClose={() => setUndoing(null)} />}
      {run && undoing === 'restore' && restoreCard(run, `Restore to before your ${at} message`, () => setUndoing(null))}
      {run?.status === 'queued' && (
        <div className="msg-meta">
          <span className="tag tag-accent">Queued</span>
          <button type="button" className="btn btn-small" onClick={onRemove}>
            Remove
          </button>
        </div>
      )}
      {removed && (
        <div className="msg-meta">
          <span className="tag">Removed from queue</span>
        </div>
      )}
    </div>
  )
}

/** What started a turn nobody was watching: the trigger's message, not the user's - with the same ⋯ (slice 107). */
function TriggerMessage({ message, run, onShow }: { message: Message; run?: Run; onShow?: (runId: string) => void }) {
  const [restoring, setRestoring] = useState(false)
  const at = when(message.created_at)
  return (
    <div className="msg msg-from">
      <div className="msg-user-row msg-from-row">
        <div className="asked-by trigger-badge mono" role="note" aria-label={`Started by the trigger ${run?.trigger_name ?? ''}`.trim()}>
          <Clock size={12} />
          <span>started by the trigger {run?.trigger_name ?? ''}</span>
          <span className="tag tag-warn">nobody watching</span>
        </div>
        {run && (
          <MessageMenu
            at={at}
            copy={message.content}
            onRestore={run.started_at && TERMINAL.has(run.status) ? () => setRestoring(true) : undefined}
            onShow={onShow && (() => onShow(run.id))}
          />
        )}
      </div>
      <div className="msg-quote" onClick={event => run && onShow && picked(event.nativeEvent) && onShow(run.id)}>
        {message.content}
      </div>
      {run && restoring && restoreCard(run, `Restore to before the ${at} message`, () => setRestoring(false))}
    </div>
  )
}

export function MessageList({
  state,
  onRemoveQueued,
  onOpenChange,
  onDecide,
  onDecideCommand,
  onDecideWeb = async () => {},
  onSelectAgent = () => {},
  onDecideSpawn = async () => {},
  onDecideRole = async () => {},
  onDecidePlan = async () => {},
  onDecideMerge = async () => {},
  onCheckMerge = async () => {},
  onCommitMerge = async () => {},
  onAnswer = async () => {},
  onOpenDiscussion = () => {},
  onOpenRoom = () => {},
  onAllowInTrigger,
  roles = NONE,
  providers = NONE,
  onUsage,
  prices,
  onLoadCompare,
  onDecideCompare,
  onShowTurn,
  onShowGit,
}: Props) {
  const on: Handlers = {
    onOpenChange,
    onDecide,
    onDecideCommand,
    onDecideWeb,
    onSelectAgent,
    onDecideSpawn,
    onDecideRole,
    onDecideMerge,
    onCheckMerge,
    onCommitMerge,
    onAnswer,
  }
  const scroller = useRef<HTMLDivElement>(null)
  const pinned = useRef(true)
  // Scrolled up: a button back to the latest, as a terminal has.
  const [away, setAway] = useState(false)
  // Each comparison's pick as its view last read it: the side not used folds into one closed row (slice 54).
  const [picks, setPicks] = useState<Record<string, string | null>>({})
  const teams = useApp(s => s.teams)
  const [loadCompare, decideCompare] = useMemo(() => {
    const seen = (compare: Compare) => {
      setPicks(was => (was[compare.id] === compare.chosen_run_id ? was : { ...was, [compare.id]: compare.chosen_run_id }))
      return compare
    }
    return [
      onLoadCompare && ((id: string) => onLoadCompare(id).then(seen)),
      onDecideCompare && ((id: string, runId: string | null) => onDecideCompare(id, runId).then(seen)),
    ]
  }, [onLoadCompare, onDecideCompare])

  // Follow new content only while the reader is already at the bottom.
  useEffect(() => {
    const el = scroller.current
    if (el && pinned.current) el.scrollTop = el.scrollHeight
  })

  const runs = new Map(state.runs.map(r => [r.id, r]))
  // K-isimler: a team's lead by its team's title, as the canvas has it (K-r152).
  const nameOf = (agentId: string | null) => agentTitle(state.agents.find(a => a.id === agentId)?.name || 'Agent', teams)
  // The chat is the conversation with the lead agent; what sub-agents say among
  // themselves is on the canvas and in Talk.
  const subAgents = new Set(state.agents.filter(a => a.depth > 0).map(a => a.id))
  // What the lead said in a discussion is in the shared place, not in the chat; a note it
  // was handed from the notebook is in the Notes tab. KOLONİ's frame of a report is its model's (K-r152).
  const shown = state.messages.filter(
    m => !m.discussion_id && !m.board_post_id && (!m.agent_id || !subAgents.has(m.agent_id)) && !isFrame(m),
  )
  // Turn by turn: a message queued during an earlier turn arrived before that turn's
  // later replies, but belongs after them. The sort is stable within a turn.
  const turn = new Map(state.runs.map((r, index) => [r.id, index]))
  const ordered = answerLast(
    [...shown].sort((a, b) => (turn.get(a.run_id) ?? Infinity) - (turn.get(b.run_id) ?? Infinity)),
  )
  const lastOfRun = new Map(ordered.map(m => [m.run_id, m.id]))
  // What KOLONİ told the lead the same, several times in a row in one turn, is one line (×N): never the
  // user's or an agent's words, nor a turn's last message (what is said under it goes with it).
  const repeated = new Map(
    foldRepeats(ordered, m => (m.role === 'memory' && lastOfRun.get(m.run_id) !== m.id ? `${m.run_id} ${m.agent_id} ${m.content}` : null)).map(
      ([m, count]) => [m.id, count],
    ),
  )

  // Where the topic changes: a line before the first message of a turn whose topic is not
  // that of the turn before it. "New" only the first time the topic is seen.
  const dividers = new Map<string, string>()
  const met = new Set<string>()
  let [turnBefore, topicBefore]: [string | null, string | null | undefined] = [null, undefined]
  for (const message of ordered) {
    if (message.run_id === turnBefore) continue
    turnBefore = message.run_id
    const topic = state.topics.find(t => t.id === runs.get(message.run_id)?.topic_id)
    if (topic && topicBefore !== undefined && topic.id !== topicBefore) {
      dividers.set(message.id, `${met.has(topic.id) ? 'Continuing' : 'New topic'}: ${titleOf(state, topic)}`)
    }
    if (topic) met.add(topic.id)
    topicBefore = topic?.id ?? null
  }

  // A comparison (slice 54): its message once, under the first side's turn, with the two side by side;
  // each side's answer is there, and what it did - with whatever waits for you - under its model's name.
  const firstSide = new Map<string, string>()
  for (const run of state.runs) if (run.compare_id && !firstSide.has(run.compare_id)) firstSide.set(run.compare_id, run.id)
  const withCalls = new Set(state.toolCalls.map(call => call.message_id))
  const sideWork = new Map<string, string>()
  for (const message of ordered) {
    if (runs.get(message.run_id)?.compare_id && withCalls.has(message.id) && !sideWork.has(message.run_id)) sideWork.set(message.run_id, message.id)
  }
  // Once one side is picked, what the other did is one closed row (the user's word, 25 Oct). (Both thrown away: as they were.)
  const unused = new Set(state.runs.filter(r => r.compare_id && picks[r.compare_id] && picks[r.compare_id] !== r.id).map(r => r.id))

  /** A call as the chat shows it; `stands`: it is more than a row - a card, a row that waits for you, or one of its own kind - and is never inside a run. */
  const callView = (call: ToolCall): { node: ReactNode; stands: boolean } => {
    const change = state.fileChanges.find(f => f.tool_call_id === call.id)
    const command = state.commands.find(c => c.tool_call_id === call.id)
    const child = state.agents.find(a => a.tool_call_id === call.id)
    // (A recipe's own questions - "Go on?", then "Take the work in?" - are put in the call that opened the agent of its
    // step, one after another: B-99.)
    const asks = state.questions.filter(q => q.tool_call_id === call.id)
    const asked = asks[0]
    const pending = asks.some(q => q.status === 'pending')
    // B-128: a Take in that met a clash waits on the Lead's card - under the Ready for you its turn's last Take in answered,
    // not only in the inspector (an earlier Take in's card is over).
    const tookIn = state.questions
      .filter(q => q.run_id === call.run_id && (q.answer === 'Take in' || q.answer === 'Fix the findings') && isReadyCard(q))
      .reduce<Question | null>((last, q) => (last && last.created_at > q.created_at ? last : q), null)
    const clash = tookIn?.tool_call_id === call.id
      ? state.merges.find(m => m.run_id === call.run_id && m.status === 'pending' && state.agents.some(a => a.id === m.agent_id && a.depth === 0))
      : undefined
    const question = asked && (
      <Fragment key={call.id}>
        {asks.map(q => (
          <ChatQuestion key={q.id} state={state} question={q} onAnswer={answer => onAnswer(q.id, answer)} />
        ))}
        {clash && (
          <MergeCard
            merge={clash}
            {...mergeSaid(state, clash)}
            onDecide={(...said) => onDecideMerge(clash.id, ...said)}
            onCheck={choices => onCheckMerge(clash.id, choices)}
            onCommit={(message, hooks) => onCommitMerge(clash.id, message, hooks)}
          />
        )}
      </Fragment>
    )
    if (call.name === 'open_room') {
      // Its members are asked for together, under the call; once it is open, it is the room.
      // (One refused opened none: the turn's room is a later call's.)
      const room = call.status !== 'failed' && state.rooms.find(r => r.agent_id === call.agent_id && r.run_id === call.run_id)
      return { stands: true, node: (
        <Fragment key={call.id}>
          {room ? (
            <RoomRow state={state} room={room} onOpen={() => onOpenRoom(room.id)} />
          ) : (
            <ToolRow call={call} waits={callWaits(state, call)} />
          )}
          {state.agents
            .filter(a => a.tool_call_id === call.id && a.status === 'proposed')
            .map(a => (
              <SpawnApproval
                key={a.id}
                agent={a}
                openedBy={nameOf(call.agent_id)}
                stays={staysOn(state, a, roles, providers)}
                onDecide={decision => onDecideSpawn(a.id, decision)}
              />
            ))}
          {question}
        </Fragment>
      ) }
    }
    if (child) {
      // A team's lead KOLONİ opened for another team's request (K-takimlar-arasi): the request's card.
      const asked = call.parent_call_id ? requestsOf(state, call.run_id).find(r => r.call.id === call.parent_call_id) : undefined
      return { stands: true, node: (
        <Fragment key={call.id}>
          {asked ? (
            <RequestRow request={asked} lead={child} state={state} onSelect={onSelectAgent} />
          ) : (
            <SpawnRow agent={child} onSelect={onSelectAgent} asks={pendingMerge(state, child.id) !== null} />
          )}
          {question}
          {child.status === 'proposed' && (
            <SpawnApproval
              agent={child}
              openedBy={state.agents.find(a => a.id === child.parent_agent_id)?.name}
              continuesTurn={continuesFrom(state, child.id)}
              stays={staysOn(state, child, roles, providers)}
              onDecide={decision => onDecideSpawn(child.id, decision)}
            />
          )}
          <SubtreeRequests root={child} state={state} on={on} known={{ roles, providers }} />
        </Fragment>
      ) }
    }
    const discussion = state.discussions.find(d => d.tool_call_id === call.id)
    if (discussion) {
      return { stands: true, node: (
        <div key={call.id} className="tool-row">
          <button
            type="button"
            className="tool-row-head"
            title="Open the discussion"
            onClick={() => onOpenDiscussion(discussion.id)}
          >
            <span style={{ color: 'var(--accent)', display: 'grid' }}>
              <ChatsCircle size={13} className={discussion.status === 'running' ? 'pulse' : undefined} />
            </span>
            <span className="tool-row-summary">
              <strong>Discussion</strong> <span className="muted">{discussion.topic.split('\n')[0]}</span>
            </span>
            <span className="tool-row-status mono muted">
              {discussion.members.length} agents · {discussionLine(discussion).toLowerCase()}
            </span>
          </button>
        </div>
      ) }
    }
    if (call.name === 'message_agent') {
      return { stands: true, node: <TalkRow key={call.id} call={call} from={nameOf(call.agent_id)} /> }
    }
    // Leave asked for a tool of an MCP server: the call keeps its row, with what it
    // was given and what came back, and the question stands under it.
    const leave = call.origin !== 'cli' && call.name !== 'ask_user'
    if (question && !leave) return { stands: true, node: question }
    const role = state.pendingRoles.find(r => r.tool_call_id === call.id)
    const skill = state.pendingSkills.find(r => r.tool_call_id === call.id)
    if (command) {
      return { stands: command.status === 'proposed' || command.status === 'approved', node: (
        <Fragment key={call.id}>
          <CommandRow command={command} failed={call.status === 'failed'} />
          {command.status === 'proposed' && (
            <CommandApproval
              command={command}
              why={call.why_asked}
              onDecide={decision => onDecideCommand(command.id, decision)}
            />
          )}
          {command.status === 'approved' && (
            <div role="note" className="muted cmd-approval-note">
              Approved — {WAITS_FOR_A_PLACE}
            </div>
          )}
        </Fragment>
      ) }
    }
    const web = state.webRequests.find(w => w.tool_call_id === call.id && w.status === 'proposed')
    const waits = pending ? 'waits for your answer' : callWaits(state, call)
    const decides = change?.status === 'proposed' || change?.status === 'approved'
    // (The Lead's pick of the chat's teams, slice 84b, is the chat's one line of it: never folded into a run.)
    const picked = call.name === 'pick_teams' && call.status === 'succeeded'
    return { stands: Boolean(asked || web || role || skill || waits || decides || picked || asksOutside(call)), node: (
      <Fragment key={call.id}>
        {/* (Nothing of it runs before the user's yes: it waits, it does not run.) */}
        <ToolRow call={call} waits={waits} />
        {question}
        {web && <WebApproval request={web} call={call} onDecide={decision => onDecideWeb(web.id, decision)} />}
        {role && <RoleApproval role={role} onDecide={decision => onDecideRole(call.id, decision)} />}
        {skill && <SkillApproval skill={skill} onDecide={(decision, scope) => onDecideRole(call.id, decision, scope)} />}
        {asksOutside(call) && (
          <OutsideApproval
            call={call}
            who={nameOf(call.agent_id)}
            onDecide={outsideWord(onDecideRole, call.id)}
            plain={state.conversation.project_id === null}
          />
        )}
        {change && (
          <ChangeLine
            change={change}
            onOpen={() => onOpenChange(change.id)}
            onDecide={action => onDecide(change.id, action)}
          />
        )}
      </Fragment>
    ) }
  }
  // A Lead's calls in a row, no words between them: one line, at its first call (K-ozet-satiri).
  const callsOf = callsByMessage(state.toolCalls)
  const views = new Map(
    ordered.flatMap(message => callsOf.get(message.id) ?? []).map(call => {
      const view = callView(call)
      if (view.stands) stood.add(call.id)
      return [call.id, view]
    }),
  )
  const toolLines = toolRuns(ordered, callsOf, call => stood.has(call.id))
  const lineAt = new Map(toolLines.map(calls => [calls[0].id, calls]))
  const inLine = new Set(toolLines.flatMap(calls => calls.slice(1).map(call => call.id)))
  const rowsOf = (calls: ToolCall[]) =>
    calls.map(call => {
      const line = lineAt.get(call.id)
      if (line) {
        return (
          <ToolRun key={call.id} calls={line} state={state}>
            {line.map(inner => views.get(inner.id)?.node)}
          </ToolRun>
        )
      }
      return inLine.has(call.id) ? null : views.get(call.id)?.node
    })

  if (state.messages.length === 0) {
    return <div className="msg-list msg-empty muted">Send a message to start.</div>
  }

  return (
    <div
      className="msg-list"
      // (Selected words here can be asked about: slice 80.)
      data-ask=""
      ref={scroller}
      onScroll={e => {
        const el = e.currentTarget
        pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40
        setAway(!pinned.current)
      }}
    >
      <AwayFrom chat={state.conversation.id} />
      {ordered.map(message => {
        const count = repeated.get(message.id)
        if (count === undefined) return null
        const run = runs.get(message.run_id)
        const notice =
          run && lastOfRun.get(run.id) === message.id
            ? runNotice(
                run,
                state.agents.find(a => a.run_id === run.id && a.depth === 0),
                providers,
              )
            : null
        // Under the turn's last message: one line for each agent of the turn whose model is
        // thinking right now, as the canvas has it. The lead is not named - the chat is its
        // conversation. A turn that thinks with no agent named says so once.
        const last = lastOfRun.get(message.run_id) === message.id
        const thinkers = last
          ? state.agents.filter(a => a.run_id === message.run_id && state.thinkingAgents.includes(a.id))
          : []
        const summarisers = last ? state.agents.filter(a => a.run_id === message.run_id && state.summarisingAgents.includes(a.id)) : []
        const thinking =
          last && thinkers.length === 0 && run?.id === state.thinkingRunId && state.thinkingAgentId === null
        const compare = run?.compare_id ?? null
        if (compare && message.role === 'user' && firstSide.get(compare) !== run?.id) return null
        const mine = callsOf.get(message.id) ?? []
        // A step whose words are none and whose calls are all in a line above: nothing of it to show (not even the list's gap).
        if (!last && !message.content && mine.length > 0 && mine.every(call => inLine.has(call.id))) return null
        return (
          <div key={message.id} className="msg-group">
            {dividers.has(message.id) && (
              <div role="separator" className="topic-divider">
                <span>{dividers.get(message.id)}</span>
              </div>
            )}
            {message.role === 'user' ? (
              <>
                <UserMessage
                  message={message}
                  run={run}
                  files={state.attachments.filter(one => one.message_id === message.id && !one.frame_of)}
                  saved={state.fileChanges.filter(change => change.run_id === message.run_id && change.attachment_id && change.status === 'applied')}
                  changed={workOf(state, [message.run_id]).files > 0}
                  onRemove={() => onRemoveQueued(message.run_id)}
                  onShow={onShowTurn}
                />
                {compare && loadCompare && decideCompare && (
                  <CompareView
                    compareId={compare}
                    state={state}
                    providers={providers}
                    onLoad={loadCompare}
                    onDecide={decideCompare}
                    onDecideMerge={onDecideMerge}
                    onCheckMerge={onCheckMerge}
                    onCommitMerge={onCommitMerge}
                  />
                )}
                {/* The message was a room's goal: one line here; the room itself is in its own window, with what it asks of you. */}
                {state.rooms
                  .filter(room => room.run_id === message.run_id && room.agent_id === null)
                  .map(room => (
                    <RoomRow key={room.id} state={state} room={room} onOpen={() => onOpenRoom(room.id)} />
                  ))}
              </>
            ) : message.role === 'memory' ? (
              <MemoryTold content={message.content} className="msg msg-from" count={count} />
            ) : KOLONI_LINES.has(message.role) ? (
              <KoloniLine message={message} onShowGit={onShowGit} />
            ) : message.role === 'away' ? (
              // KOLONİ's one line at the end of a night while you were away (slice 106): the report is on the canvas.
              <p className="msg msg-from away-said" role="note">
                <Moon size={13} />
                {message.content}
              </p>
            ) : message.role === 'trigger' ? (
              <TriggerMessage message={message} run={run} onShow={onShowTurn} />
            ) : message.role === 'agent' ? (
              // Another agent wrote to the lead; the lead's answer follows as its own message.
              <AgentSaid
                message={message}
                from={message.from_agent_id ? nameOf(message.from_agent_id) : 'KOLONİ'}
                agent={state.agents.find(a => a.id === message.from_agent_id)}
              />
            ) : (
              message.content &&
              !compare && (
                <>
                  <div className="msg msg-assistant markdown">
                    <ReadAloud id={message.id} content={message.content} written={message.status === 'complete'} />
                    <Markdown written={message.status === 'complete'}>{message.content}</Markdown>
                  </div>
                  <SaidAloud message={message} />
                </>
              )
            )}
            {sideWork.get(message.run_id) === message.id && !unused.has(message.run_id) && (
              <div role="separator" className="topic-divider">
                <span>{sideName(state, message.run_id)}’s work</span>
              </div>
            )}
            {!unused.has(message.run_id)
              ? rowsOf(mine)
              : sideWork.get(message.run_id) === message.id && (
                  // Every call of the side, at its first: the turn's later messages show none of them.
                  <details className="tool-run">
                    <summary className="tool-run-head">
                      <CaretRight size={12} className="muted" aria-hidden />
                      <span className="tool-run-what">The other side (not used)</span>
                    </summary>
                    <div className="tool-run-body">{rowsOf(ordered.filter(m => m.run_id === message.run_id).flatMap(m => callsOf.get(m.id) ?? []))}</div>
                  </details>
                )}
            {thinkers.map(a => (
              <div key={a.id} className="msg-status mono">
                {a.depth > 0 && `${a.name || 'Agent'} · `}Thinking…
              </div>
            ))}
            {summarisers.map(a => (
              <div key={a.id} className="msg-status mono">
                {a.depth > 0 && `${a.name || 'Agent'} · `}
                {SUMMARISING}
              </div>
            ))}
            {thinking && <div className="msg-status mono">Thinking…</div>}
            {/* The Lead's "While you're away" card (slice 106), under the turn that put it. */}
            {last &&
              state.away
                .filter(card => card.run_id === message.run_id)
                .map(card => <AwayCard key={card.id} card={card} />)}
            {/* A trigger an agent proposed in the turn (slice 69), under it. */}
            {last &&
              state.triggerProposals
                .filter(proposal => proposal.run_id === message.run_id)
                .map(proposal => <ProposalCard key={proposal.id} proposal={proposal} />)}
            {/* K-bilgi 6: what the turn (and turns nobody watched) found for the Project notes, under it. */}
            {last &&
              state.notesOffers
                .filter(offer => offer.run_id === message.run_id)
                .map(offer => <NotesCard key={offer.id} offer={offer} />)}
            {/* Text from outside that read like orders to one of the turn's agents (93-A4): the Lead's is not named. */}
            {last &&
              state.warnings
                .filter(w => w.run_id === message.run_id)
                .map(w => (
                  <InjectionWarning key={w.id} warning={w} agent={subAgents.has(w.agent_id ?? '') ? nameOf(w.agent_id) : undefined} />
                ))}
            {last && run?.plan_turn && (
              // (A later turn has started: as the server holds, it can only be turned down.)
              <PlanCard run={run} stale={state.runs.at(-1)?.id !== run.id} onDecide={(...decision) => onDecidePlan(run.id, ...decision)} />
            )}
            {/* Under the last message of a turn nobody was watching: what it was refused for want of somebody to ask. */}
            {last && run?.unattended && (
              <WouldHaveAsked
                refused={refusedIn(state, run.id)}
                onAllow={run.trigger_id && onAllowInTrigger ? allow => onAllowInTrigger(run.trigger_id as string, allow) : undefined}
              />
            )}
            {notice && <RunNotice notice={notice} />}
            {last && run?.started_at && TERMINAL.has(run.status) && !compare && <TurnSummary state={state} run={run} onOpenChange={onOpenChange} onUsage={onUsage} prices={prices} />}
          </div>
        )
      })}
      {away && (
        <button
          type="button"
          className="jump-bottom"
          aria-label="Jump to the latest"
          title="Jump to the latest"
          onClick={() => {
            const el = scroller.current
            if (!el) return
            el.scrollTo?.({ top: el.scrollHeight, behavior: window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' })
            pinned.current = true
            setAway(false)
          }}
        >
          <ArrowDown size={15} />
        </button>
      )}
    </div>
  )
}
