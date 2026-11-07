/**
 * Topics: going on with the same piece of work. A topic is the turns of a conversation
 * that go on with one thing; inside it an agent of an earlier turn can be gone on with.
 *
 * The rules here are the server's (`app/topics.py`), read off the same records: which
 * topic a message goes on with, which turn of its topic a turn is, and which agents an
 * agent goes on from. Everything is a pure function of the conversation's state.
 */
import type { Agent, Run, Topic } from '../api/types'
import { when } from '../canvas/turns'
import type { ConvState } from '../state/applyEvent'

const known = (state: ConvState, topicId: string | null): Topic | null =>
  (topicId && state.topics.find(topic => topic.id === topicId)) || null

/**
 * The topic the user was last in: that of the newest turn they started themselves in a
 * topic of their own. A trigger's turn never changes it, and neither does a message the
 * user sent into a trigger's topic - nor one they took back before its turn started:
 * nobody ever worked there. (A message still in the queue counts, as the server has it.)
 */
export function latestOfUser(state: ConvState): Topic | null {
  for (let index = state.runs.length - 1; index >= 0; index--) {
    const run = state.runs[index]
    const takenBack = run.status === 'cancelled' && !run.started_at
    const topic = run.unattended || takenBack ? null : known(state, run.topic_id)
    if (topic && topic.trigger_id === null) return topic
  }
  return null
}

/**
 * Where the next message goes: on with a topic, or into a new one. `instead` is the one
 * other place the line offers: a trigger's topic that is on screen, to write into - or,
 * once that was chosen, the user's own topic to go back to (null: back to a new topic).
 */
export type Next = { kind: 'topic'; topic: Topic; instead: Topic | null } | { kind: 'new'; instead: Topic | null }

/**
 * The topic the next message of the user's goes on with. `shown` is the turn on screen,
 * `into` a trigger's topic the user chose to write into.
 *
 * A turn of a topic of the user's own on screen: the message goes on with that topic. A
 * turn of a trigger's topic on screen does not take the message: looking is not choosing.
 * It goes on with the topic the user was last in - or starts their first - and the
 * trigger's topic is offered instead; only chosen (`into`) is it where the message goes.
 * In a conversation with no turn at all there is nothing to say (null).
 */
export function nextTopic(state: ConvState, shown: string | null, into: string | null = null): Next | null {
  const last = latestOfUser(state)
  const onScreen = known(state, state.runs.find(run => run.id === shown)?.topic_id ?? null)
  if (onScreen && onScreen.trigger_id === null) return { kind: 'topic', topic: onScreen, instead: null }
  if (onScreen && onScreen.id === into) return { kind: 'topic', topic: onScreen, instead: last }
  if (last) return { kind: 'topic', topic: last, instead: onScreen }
  return state.runs.length > 0 ? { kind: 'new', instead: onScreen } : null
}

/**
 * Which turn of its topic each turn is, from 1: only the turns that were started are
 * counted, so a message still in the queue has no number, and neither has a turn in no topic.
 */
export function turnNumbers(state: ConvState): Map<string, number> {
  const numbers = new Map<string, number>()
  const started = new Map<string, number>()
  for (const run of state.runs) {
    if (!run.topic_id || !run.started_at) continue
    const number = (started.get(run.topic_id) ?? 0) + 1
    started.set(run.topic_id, number)
    numbers.set(run.id, number)
  }
  return numbers
}

/** The name a trigger's turns go by: the trigger's own, as the newest turn it started has it. */
function triggerName(runs: Run[]): string {
  return runs.findLast(run => run.trigger_name)?.trigger_name || 'A trigger'
}

/** What a topic is called: its title, and for a trigger's topic the trigger's name. */
export function titleOf(state: ConvState, topic: Topic): string {
  if (topic.trigger_id === null) return topic.title
  return triggerName(state.runs.filter(run => run.topic_id === topic.id && run.trigger_id === topic.trigger_id))
}

/** One link of a chain: an agent, and which turn of the topic it worked in. */
export interface Link {
  agent: Agent
  turn: number
}

/**
 * An agent and the agents it goes on from, oldest first. The walk stays inside the
 * agent's own topic: a link that points anywhere else ends it there, and so does one
 * that points back into the chain, or forward in the topic.
 */
export function chainOf(state: ConvState, agentId: string, numbers = turnNumbers(state)): Link[] {
  const agent = state.agents.find(a => a.id === agentId)
  if (!agent) return []
  const topicId = state.runs.find(run => run.id === agent.run_id)?.topic_id ?? null
  const links: Link[] = [{ agent, turn: numbers.get(agent.run_id) ?? 1 }]
  if (!topicId) return links
  const seen = new Set([agent.id])
  let walk = agent
  while (walk.continues_id && !seen.has(walk.continues_id)) {
    const before = state.agents.find(a => a.id === walk.continues_id)
    const run = before && state.runs.find(r => r.id === before.run_id)
    const turn = before && numbers.get(before.run_id)
    if (!before || run?.topic_id !== topicId || turn === undefined || before.depth !== agent.depth) break
    // Further back in the topic each time: a chain never turns round.
    if (turn >= links[0].turn) break
    links.unshift({ agent: before, turn })
    seen.add(before.id)
    walk = before
  }
  return links
}

/** A message's time, as the chat says it ("10:42"): what a turn is called on screen (slice 107). */
export function messageTime(state: Pick<ConvState, 'messages' | 'runs'>, runId: string): string {
  const asked = state.messages.find(m => m.run_id === runId && (m.role === 'user' || m.role === 'trigger'))
  return when(asked?.created_at ?? state.runs.find(run => run.id === runId)?.created_at ?? '')
}

/**
 * The message a sub-agent goes on from, by its time: that of the link before it in its chain;
 * null for an agent that started clean. A lead is not said to continue: every turn of a topic
 * goes on from the one before, and the topic itself says that.
 */
export function continuesFrom(state: ConvState, agentId: string, numbers = turnNumbers(state)): string | null {
  const chain = chainOf(state, agentId, numbers)
  if (chain.length < 2 || chain[chain.length - 1].agent.depth === 0) return null
  return messageTime(state, chain[chain.length - 2].agent.run_id)
}

/**
 * The links of a sub-agent's chain before it: the agents of earlier turns of the topic it
 * goes on from, oldest first. None for an agent that started clean, and none for a lead -
 * what a topic's leads said is the chat.
 */
export function earlierLinks(state: ConvState, agentId: string): Link[] {
  const chain = chainOf(state, agentId)
  return chain.length > 1 && chain[chain.length - 1].agent.depth > 0 ? chain.slice(0, -1) : []
}

/**
 * The agent that went on from this one in a later turn, if one did: opened on its work
 * and not declined. One that still waits to be opened has not gone on yet.
 */
export function wentOnIn(state: ConvState, agentId: string): Link | null {
  const later = state.agents.findLast(a => a.continues_id === agentId && a.depth > 0 && a.status !== 'rejected' && a.status !== 'proposed')
  if (!later) return null
  const chain = chainOf(state, later.id)
  // Only as a link of that agent's chain: the same walk, from the other end.
  return chain.length >= 2 && chain[chain.length - 2].agent.id === agentId ? chain[chain.length - 1] : null
}
