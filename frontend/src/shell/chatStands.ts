import { AGENT_STATUS, titleOf } from '../agents/agentStatus'
import type { Board, ListedConversation } from '../api/types'
import { count } from '../board/columns'
import { standingOf } from '../board/waiting'
import type { Stands } from '../ready/cells'
import type { ReadyItem } from '../ready/ready'
import { kindWord } from '../ready/ReadyViews'
import { ranOn } from './modelName'

type BoardConversation = Board['conversations'][number]

/** The states a chat's cell takes on the Chats page (0.1.10): Ready's meanings - idle is the empty cell. */
export type ChatStands = Exclude<Stands, 'proposed'>

/** Each state in words: its cell's label and the legend's. */
export const CHAT_WORD: Record<ChatStands, string> = {
  done: 'done',
  running: 'at work',
  yours: 'waits for your word',
  stuck: 'stuck',
  queued: 'idle',
}

/** How a chat stands: its cell, its line's first words and the rest of the line. */
export type ChatSaid = [stands: ChatStands, lead: string, rest: string]

/** What its last turn ran with: its agents, its model, its tokens where they are known. */
const ranOf = (turn: BoardConversation['turn']) =>
  turn
    ? [
        count(turn.agents, 'agent'),
        ranOn(turn.provider_name, turn.model_id),
        turn.tokens != null && `${turn.tokens.toLocaleString('en-US')} tokens`,
      ]
    : []

const line = (...parts: (string | false | null | undefined)[]) => parts.filter(Boolean).join(' · ')

/** A turn that ended, by how: done, stuck, or stopped (an empty cell). */
const ENDED: Partial<Record<string, [ChatStands, string]>> = {
  completed: ['done', 'Done'],
  failed: ['stuck', 'Stuck: its last turn failed'],
  interrupted: ['stuck', 'Stuck: its last turn was interrupted'],
  cancelled: ['queued', 'Stopped'],
}

/** Its agents at work, each with how it stands ("Coder working, Reviewer waiting"), the branches they work on, and
 *  what its turn runs with. */
function atWork(on: BoardConversation): ChatSaid {
  const who = on.agents.map(agent => `${titleOf(agent.name || agent.role)} ${AGENT_STATUS[agent.status][0]}`)
  const branches = [...new Set(on.agents.flatMap(agent => (agent.copy?.branch ? [agent.copy.branch] : [])))]
  const where = branches.length > 0 && `branch ${branches.join(', ')}`
  return ['running', who.join(', ') || 'At work', line(where, ...ranOf(on.turn))]
}

/**
 * How a chat stands, as its cell and one line say it on the Chats page (0.1.10): what waits for your word in it - Ready
 * for you's own rows of it (`mine`), the top bar's pill counts each, else what the Board says waits there -, what is at
 * work, a last turn stuck (or its To-do task blocked), done, stopped, or no turn yet. Null: the Board has no row of it
 * yet - nothing is said.
 */
export function chatStands(
  on: BoardConversation | undefined,
  mine: ReadyItem[],
  task: ListedConversation['backlog_task'] = null,
): ChatSaid | null {
  const standing = standingOf(on)
  if (mine.length > 0) {
    const kinds = [...new Set(mine.map(kindWord))].join(', ')
    return ['yours', mine.length === 1 ? 'Waits for your word' : `${mine.length} wait for your word`, kinds]
  }
  if (standing === 'waits') return ['yours', 'Waits for your word', '']
  if (!on) return null
  if (standing === 'working') return atWork(on)
  const ended = standing ? ENDED[standing] : undefined
  const ran = line(...ranOf(on.turn))
  if (task?.status === 'blocked' && ended?.[0] !== 'stuck') return ['stuck', 'Stuck: its To-do task is blocked', ran]
  return ended ? [...ended, ran] : ['queued', 'No turn yet', '']
}

/** The sentence under the comb: what is at work, what waits for your word (the top bar's pill's number), and today's. */
export function nowSaid(working: number, waits: number, stuck: number, done: number, read: boolean): string {
  const waiting =
    waits === 0
      ? 'nothing waits for your word'
      : `${count(waits, 'thing')} ${waits === 1 ? 'waits' : 'wait'} for your word`
  if (!read) return `How the chats stand is not read yet; ${waiting}.`
  const today = [done > 0 && `${done} done`, stuck > 0 && `${stuck} stuck`].filter(Boolean).join(', ')
  return `${working > 0 ? `${count(working, 'chat')} at work` : 'Nothing at work'}; ${waiting}.${today && ` Today ${today}.`}`
}
