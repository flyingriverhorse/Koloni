// Records of a topic with several turns, shared by the canvas's tests.
import { agent, convState, fileChange, run, topic, userMessage } from '../test-fixtures'
import type { ConvState } from '../state/applyEvent'
import { when } from './turns'

/** The time the message of turn n (from 1) was sent, as the screen says it: 10:01, 10:02, … */
export const sentAt = (n: number) => when(`2026-10-05T10:0${n}:00Z`)

/**
 * A topic of so many turns (t1, t2, …), each with a lead and a Coder that goes on from the
 * Coder of the turn before; and one turn of another topic (other).
 */
export function topicOf(turns: number): ConvState {
  const ids = Array.from({ length: turns }, (_, n) => `t${n + 1}`)
  return convState({
    topics: [topic('ta', 'Fix the greeting'), topic('tb', 'Write the docs')],
    runs: [...ids.map(id => run(id, 'completed', { topic_id: 'ta' })), run('other', 'completed', { topic_id: 'tb' })],
    messages: [...ids.map((id, n) => ({ ...userMessage(id, `message ${n + 1}\nmore of it`), created_at: `2026-10-05T10:0${n + 1}:00Z` })), userMessage('other', 'Write the docs')],
    agents: [
      ...ids.flatMap((id, n) => [
        agent(id, 'completed', { continues_id: n ? ids[n - 1] : null }),
        agent(id, 'completed', {
          id: `coder-${id}`,
          parent_agent_id: id,
          role_name: 'Coder',
          depth: 1,
          task: `task ${n + 1}`,
          report: `report ${n + 1}`,
          continues_id: n ? `coder-${ids[n - 1]}` : null,
        }),
      ]),
      agent('other', 'completed'),
    ],
    fileChanges: [fileChange('f1', 't1', { agent_id: 'coder-t1' })],
  })
}
