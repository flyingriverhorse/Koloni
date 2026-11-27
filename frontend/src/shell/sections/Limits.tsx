import { useState } from 'react'
import type { Budget, Project } from '../../api/types'
import { UNENFORCED, unenforced } from '../../usage/budgetText'
import { GUIDE } from '../guide'
import { type From, fromOf, Legend, limitOf, More, part, Row, Said, sent, type Setter, typed, within } from './part'
import { moneySaid } from './said'
import { USUAL } from './usual'

/** What so many levels allow: "Orchestrator → sub-agent → its own sub-agent" for 2. */
function levelsChain(levels: number): string {
  if (levels === 1) return 'Orchestrator → sub-agent (it opens no more)'
  return ['Orchestrator', 'sub-agent', ...Array<string>(levels - 1).fill('its own sub-agent')].join(' → ')
}

/** A number as typed, and what of it can be sent: undefined for anything that cannot. `shown`: what the section's
 *  sentence says - what is typed, or what is saved while what is typed cannot be sent. */
interface Field<T> {
  text: string
  set: Setter<string>
  value: T
  shown: T
  from: From
}

/** A number field, `start` as saved: its cell says one that cannot be sent is changed and not saved, as one that
 *  differs; `usual` is a new project's. */
function useField<T>(start: string, read: (text: string) => T, usual: unknown): Field<T> {
  const [text, set] = useState(start)
  const value = read(text)
  const kept = read(start)
  return {
    text,
    set,
    value,
    shown: value === undefined ? kept : value,
    from: value === undefined ? 'dirty' : fromOf(value, kept, usual),
  }
}

/**
 * This project › Limits and money: what a month may cost and a job's budget up front; under More limits (closed unless
 * asked open, each time with a new count: the app's link to Continue's steps) how many agents, Continue's steps and a
 * discussion's tokens.
 */
export function useLimits(project: Project, spend: Budget | null, toApp?: () => void, moreAsked?: number) {
  // Empty: no limit. Anything else has to be a whole number from 1 to 1000 - nothing else is sent.
  const most = useField(
    typed(project.max_agents || null),
    text =>
      text.trim() === '' ? null : /^[1-9]\d{0,3}$/.test(text.trim()) && Number(text) <= 1000 ? Number(text) : undefined,
    USUAL.max_agents,
  )
  const parallel = useField(
    String(project.spawn_max_parallel ?? 2),
    text => within(text, 1, 32),
    USUAL.spawn_max_parallel,
  )
  const depth = useField(String(project.spawn_max_depth ?? 2), text => within(text, 1, 4), USUAL.spawn_max_depth)
  const per = useField(String(project.spawn_max_agents ?? 6), text => within(text, 1, 20), USUAL.spawn_max_agents)
  // K-devam-butce: a whole number from 1 to 200. (A server older than the page has no such field yet.)
  const more = useField(
    String(project.continue_steps ?? 25),
    text => (/^[1-9]\d{0,2}$/.test(text.trim()) && Number(text) <= 200 ? Number(text) : undefined),
    USUAL.continue_steps,
  )
  // Empty: no limit. Anything else has to be a whole number above zero.
  const turn = useField(
    typed(project.turn_token_limit || null),
    text => (text.trim() === '' ? null : /^[1-9]\d*$/.test(text.trim()) ? Number(text) : undefined),
    USUAL.turn_token_limit,
  )
  // Empty: no limit. (The user, 6 Nov: a discussion's tokens have none by default.)
  const talk = useField(
    typed(project.discussion_budget),
    text => limitOf(text, Number.MAX_SAFE_INTEGER),
    USUAL.discussion_budget,
  )
  // Empty: no budget. Anything else has to be an amount above zero; "12,5" is 12.5.
  const budget = useField(
    typed(project.monthly_budget),
    text => {
      const amount = text.trim().replace(',', '.')
      return amount === '' ? null : /^\d*\.?\d+$/.test(amount) && Number(amount) > 0 ? Number(amount) : undefined
    },
    USUAL.monthly_budget,
  )
  const fields = [most, parallel, depth, per, more, turn, talk, budget]
  const patch = {
    ...sent('max_agents', most.value, project.max_agents),
    ...sent('spawn_max_parallel', parallel.value, project.spawn_max_parallel ?? 2),
    ...sent('spawn_max_depth', depth.value, project.spawn_max_depth ?? 2),
    ...sent('spawn_max_agents', per.value, project.spawn_max_agents ?? 6),
    ...sent('continue_steps', more.value, project.continue_steps),
    ...sent('turn_token_limit', turn.value, project.turn_token_limit),
    ...sent('discussion_budget', talk.value, project.discussion_budget ?? null),
    ...sent('monthly_budget', budget.value, project.monthly_budget),
  }
  // (Anything under More limits not at its default: said on it while it is closed.)
  const usual: [Field<unknown>, number | null][] = [
    [most, null],
    [parallel, 2],
    [depth, 2],
    [per, 6],
    [more, 25],
    [talk, null],
  ]
  const set = usual.filter(([field, value]) => field.value !== value).length
  const now = { monthly_budget: budget.shown, turn_token_limit: turn.shown }
  return part(
    patch,
    fields.every(field => field.value !== undefined),
    <>
      <Said title="Limits and money">{moneySaid(now, spend)}</Said>
      <MoneyLimits budget={budget} turn={turn} spend={spend} />
      <More
        label="More limits"
        count={usual.length}
        set={set}
        bad={usual.some(([field]) => field.value === undefined)}
        asked={moreAsked}
      >
        <AgentLimits most={most} parallel={parallel} depth={depth} per={per} more={more} toApp={toApp} />
        <TalkRow talk={talk} />
      </More>
      <Legend />
    </>,
  )
}

/** How many agents, at once and in all, and the steps Continue gives. */
function AgentLimits({
  most,
  parallel,
  depth,
  per,
  more,
  toApp,
}: {
  most: Field<number | null | undefined>
  parallel: Field<number | undefined>
  depth: Field<number | undefined>
  per: Field<number | undefined>
  more: Field<number | undefined>
  toApp?: () => void
}) {
  const crowded = parallel.value !== undefined && parallel.value > 8
  return (
    <>
      <Row
        label="At most this many agents at work in this project"
        from={most.from}
        htmlFor="max-agents"
        whyId="max-agents-more"
        doc={GUIDE.settingsLimits}
        why="When that many are at work, a new agent (a conversation’s Orchestrator too) waits for a slot and starts in its turn when one is free. An agent that waits for you, for a file or for its sub-agents holds no slot. The Chats list shows which chats are at work."
        warn={
          <span id="max-agents-note" className="choice-note">
            {most.value === undefined ? 'A whole number from 1 to 1000, or empty for no limit. ' : ''}
            Counted over all of this project’s conversations together.
          </span>
        }
      >
        <input
          id="max-agents"
          className="input mono"
          inputMode="numeric"
          value={most.text}
          placeholder="No limit"
          aria-invalid={most.value === undefined || undefined}
          aria-describedby="max-agents-note max-agents-more"
          onChange={e => most.set(e.target.value)}
        />
      </Row>
      <Row
        label="Agents at the same time"
        from={parallel.from}
        htmlFor="spawn-parallel"
        doc={GUIDE.settingsLimits}
        why="Of one message’s work. Each provider has its own limit too, in its window; this is the most over all of them."
        warn={
          <span className={`choice-note${crowded ? ' spawn-limit-warn' : ''}`}>
            {parallel.value === undefined ? '1 to 32. ' : ''}
            {/* Above 8 it is said, not refused: the user may take the risk (25 Oct). */}
            {crowded ? 'This may strain this machine and your subscription. ' : ''}
            Agents on a CLI that work at the same time spend your subscription at the same time.
          </span>
        }
      >
        <input
          id="spawn-parallel"
          className="input mono set-short"
          inputMode="numeric"
          value={parallel.text}
          aria-invalid={parallel.value === undefined || undefined}
          onChange={e => parallel.set(e.target.value)}
        />
      </Row>
      <Row
        label="Sub-agent levels"
        from={depth.from}
        htmlFor="spawn-depth"
        doc={GUIDE.settingsLimits}
        why="How deep sub-agents may open their own, from 1 to 4."
        warn={<span className="choice-note">{depth.value === undefined ? '1 to 4.' : levelsChain(depth.value)}</span>}
      >
        <input
          id="spawn-depth"
          className="input mono set-short"
          inputMode="numeric"
          value={depth.text}
          aria-invalid={depth.value === undefined || undefined}
          onChange={e => depth.set(e.target.value)}
        />
      </Row>
      <Row
        label="Sub-agents per request"
        from={per.from}
        htmlFor="spawn-agents"
        doc={GUIDE.settingsLimits}
        why="For each message you send, the Orchestrator opens at most this many in all. A recipe opens as many sub-agents as its drawing has: this limit is for the ones opened outside a recipe."
        warn={per.value === undefined && <span className="choice-note">1 to 20.</span>}
      >
        <input
          id="spawn-agents"
          className="input mono set-short"
          inputMode="numeric"
          value={per.text}
          aria-invalid={per.value === undefined || undefined}
          onChange={e => per.set(e.target.value)}
        />
      </Row>
      <ContinueRow more={more} toApp={toApp} />
    </>
  )
}

/** Up front: what one month may cost, and a job's budget - what one turn of work may spend. */
function MoneyLimits({
  turn,
  budget,
  spend,
}: {
  turn: Field<number | null | undefined>
  budget: Field<number | null | undefined>
  spend: Budget | null
}) {
  return (
    <>
      <Row
        label="Monthly budget"
        from={budget.from}
        htmlFor="monthly-budget"
        warn={
          <span className="choice-note" id="monthly-budget-note">
            {budget.value === undefined ? 'An amount above zero, or empty for no budget. ' : ''}
            {spend && unenforced(spend) ? `${UNENFORCED}. ` : ''}
            For this calendar month’s messages. In the currency of your prices (Usage, under Prices), else USD, as
            models.dev’s prices are used where you set none{spend?.currency ? ` - now ${spend.currency}` : ''}. At 80%
            you are told. At 100% a new message asks before its work starts. Work on a model with no price is not
            counted: Usage says how many there were.
          </span>
        }
      >
        <input
          id="monthly-budget"
          className="input mono"
          inputMode="decimal"
          value={budget.text}
          placeholder="No budget"
          aria-invalid={budget.value === undefined || undefined}
          aria-describedby="monthly-budget-note"
          onChange={e => budget.set(e.target.value)}
        />
      </Row>
      <Row
        label="Stop the work on a message over this many tokens"
        from={turn.from}
        htmlFor="turn-token-limit"
        warn={
          <span className="choice-note">
            <span id="turn-token-limit-note">
              {turn.value === undefined ? 'A whole number above zero, or empty for no limit. ' : ''}A job’s budget:
              tokens sent and written by all the agents working on one message, together - yours, a To-do task’s, or a
              job’s while you’re away. A job tried again, or a message that goes on with it, starts from zero.
            </span>{' '}
            <span id="turn-token-limit-more">
              Checked before each model step, and for a CLI session as its messages arrive. Once over, whatever is still
              at work is stopped and the work ends as failed, saying so. Only what a model reports is counted: a CLI
              that reports no tokens is not limited by this, and one that reports only at its end can go past it. Agents
              at work at the same time can each take one more step before the limit is seen.
            </span>
          </span>
        }
      >
        <input
          id="turn-token-limit"
          className="input mono"
          inputMode="numeric"
          value={turn.text}
          placeholder="No limit"
          aria-invalid={turn.value === undefined || undefined}
          aria-describedby="turn-token-limit-note turn-token-limit-more"
          onChange={e => turn.set(e.target.value)}
        />
      </Row>
    </>
  )
}

/** Under More limits: what one discussion may spend - within the job's budget, which holds its speakers too. */
function TalkRow({ talk }: { talk: Field<number | null | undefined> }) {
  return (
    <Row
      label="A discussion’s tokens, at most"
      from={talk.from}
      htmlFor="discussion-budget"
      doc={GUIDE.discussionsEnd}
      why="Each step of a speech sends the speaker’s whole work so far again, so the count grows faster than the talk does."
      warn={
        <span className="choice-note">
          {talk.value === undefined ? 'A whole number above 0, or empty for no limit. ' : ''}
          Sent and written by its speakers, together; a model that reports no tokens is not limited. It holds for
          discussions opened after it is saved. Its speakers count toward the job’s budget too: above that, the job
          stops first.
        </span>
      }
    >
      <input
        id="discussion-budget"
        className="input mono"
        inputMode="numeric"
        placeholder="No limit"
        value={talk.text}
        aria-invalid={talk.value === undefined || undefined}
        onChange={e => talk.set(e.target.value)}
      />
    </Row>
  )
}

/** K-devam-butce: the steps Continue gives; the step limit itself is the app's. */
function ContinueRow({ more, toApp }: { more: Field<number | undefined>; toApp?: () => void }) {
  return (
    <Row
      label="Continue gives this many more steps"
      from={more.from}
      htmlFor="continue-steps"
      doc={GUIDE.settingsLimits}
      why="What Continue gives an agent stopped at a step limit: on its card, or the Orchestrator’s at Full auto. An agent told to go on by a message gets a fresh app step limit instead."
      warn={
        <span className="choice-note">
          {more.value === undefined ? 'A whole number from 1 to 200. ' : ''}
          The step limit itself is the app’s:{' '}
          <button type="button" className="link-btn" onClick={toApp} disabled={!toApp}>
            Steps an agent may take
          </button>
          .
        </span>
      }
    >
      <input
        id="continue-steps"
        className="input mono"
        inputMode="numeric"
        value={more.text}
        aria-invalid={more.value === undefined || undefined}
        onChange={e => more.set(e.target.value)}
      />
    </Row>
  )
}
