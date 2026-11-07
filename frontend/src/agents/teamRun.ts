import type { Agent, ChatTeam, ChatTeamState, FileChange, Question } from '../api/types'
import { inScratch } from '../changes/copies'
import type { ConvState } from '../state/applyEvent'

/** The text KOLONİ's card starts with where a chat's recipes meet (app/agent.py READY_FOR_YOU). */
export const READY_FOR_YOU = 'Ready for you'
/** That card's title as shown (sample A): "Ready for you" is left to the panel; the card is still known by its prefix. */
export const TEAMS_READY = "Teams' work is ready"
/** KOLONİ's own Ready for you card: KOLONİ's (`leave`), and by its prefix - an agent's question that starts so is the agent's. */
export const isReadyCard = (q: Pick<Question, 'question' | 'leave'>) => q.leave && q.question.startsWith(READY_FOR_YOU)
/** A question's text as shown: KOLONİ's Ready for you card under its own title, its prefix left out. */
export const shownQuestion = (q: Pick<Question, 'question' | 'leave'>) => (isReadyCard(q) ? `${TEAMS_READY}${q.question.slice(READY_FOR_YOU.length)}` : q.question)
/** KOLONİ's options shown in the one word for no (a leave for a tool says "Deny"); sent as they are. An agent's stand as it wrote them. */
export const shownOption = (option: string, leave: boolean) => (leave && option === 'Deny' ? 'Reject' : option)

// B-103: hues far enough apart to be told apart at a glance, as many as a chat has teams (MAX_CHAT_TEAMS).
const HUES = [30, 215, 335, 175, 90, 265]

/**
 * The colours of teams shown together: each its own, from its id, where that is free, else the next free one - two
 * never alike (B-103). In both themes a mid tone, for a strip and a border, never for text.
 * `after`: others shown with them (an agent kept beside a recipe) take what is left, never a team's colour.
 * shortcut: past six teams colours repeat, and a team takes another colour where its own is taken - so on the Teams
 * board, among every team, it may not be its colour in a chat (`chatColours`); give teams a colour of their own on the
 * Teams tab if users want to pick it.
 */
export function teamColours(teamIds: string[], after: string[] = []): Map<string, string> {
  return spread([...[...teamIds].sort(), ...after], HUES, '45% 50%')
}

// Who talked with whom on a canvas: more saturated than the teams' (their frames are a strip, a talk line dotted), no
// red or amber (findings and the accent), each next one far from those before it.
const TALK_HUES = [205, 135, 295, 170, 330, 250]

/**
 * A colour for each pair of agents that talked on one canvas (`pairs`: sorted ids joined), in turn from TALK_HUES: two
 * pairs are far apart. shortcut: past six pairs colours repeat (who is on the 💬's hover).
 */
export const talkColours = (pairs: string[]): Map<string, string> =>
  new Map([...pairs].sort().map((pair, at) => [pair, `hsl(${TALK_HUES[at % TALK_HUES.length]} 65% 48%)`]))

// Each id its own hue, from its id, where that is free, else the next free one. (In one order whatever order they are
// shown in: the same ids, the same colours on every screen.)
function spread(ids: string[], hues: number[], tone: string): Map<string, string> {
  const [colours, used] = [new Map<string, string>(), new Set<number>()]
  for (const id of ids) {
    let hash = 0
    for (const char of id) hash = (hash * 31 + char.charCodeAt(0)) % 9973
    let at = hash % hues.length
    for (let tries = 0; used.has(at) && tries < hues.length; tries++) at = (at + 1) % hues.length
    used.add(at)
    colours.set(id, `hsl(${hues[at]} ${tone})`)
  }
  return colours
}

/** One team's colour on its own (`teamColours`). */
export const teamColour = (teamId: string): string => teamColours([teamId]).get(teamId)!

/**
 * B-103: the colours of a chat's teams - its rows now and every turn's - from one set, so a team has one colour on all
 * of the chat's screens, the canvas of any of its turns and its teams' window alike.
 */
export const chatColours = (state: Pick<ConvState, 'conversation' | 'runs'>, after: string[] = []): Map<string, string> =>
  teamColours([...new Set([...state.conversation.teams, ...state.runs.flatMap(run => run.teams ?? [])].map(row => row.team_id))], after)

/**
 * B-107: a turn's chat teams as it left them - its own record (`Run.teams`), with the chat's rows still of that turn
 * over it - not as the chat's teams are now.
 */
export function turnTeams(state: Pick<ConvState, 'conversation' | 'runs'>, runId: string): (ChatTeam & { state: ChatTeamState })[] {
  const live = state.conversation.teams.filter(row => row.state?.run_id === runId)
  const kept = state.runs.find(run => run.id === runId)?.teams ?? []
  return [...kept.map(row => live.find(one => one.team_id === row.team_id) ?? row), ...live.filter(one => !kept.some(row => row.team_id === one.team_id))].filter(
    (row): row is ChatTeam & { state: ChatTeamState } => row.state?.run_id === runId,
  )
}

/** The files a row's agents changed, by path once each. */
export const filesOf = (state: Pick<ConvState, 'fileChanges'>, row: { state: ChatTeamState }) =>
  new Set(state.fileChanges.filter(f => row.state.agents.includes(f.agent_id ?? '') && !inScratch(f.path)).map(f => f.path)).size

/** How long a row's why is in the chat's one line; the card in full says all of it. */
const WHY_CHARS = 60

/**
 * K-hazir-satir: KOLONİ's Ready for you card as the chat says it, in one line - "Teams' work is ready · Web app 3 files ·
 * Docs 1 file, kept apart". What the card says that changes what Take in does is said here too: a team with no recipe
 * kept apart (this Take in does not take it), a row that is not at its end and why, and what a team that ended early
 * left that Take in takes in with the rest (M1). Counted as the card was `asked` (N5); a row's state only while it
 * is still asked - once answered, the answer says what came of it. The card in full is on the Ready for you list.
 * K-r152: with a team that ended badly the line is no "Teams' work is ready" - each team says its own state, "Docs is
 * ready (1 file) · Web app failed (0 files)".
 */
export function readyLine(state: Pick<ConvState, 'conversation' | 'runs' | 'fileChanges' | 'agents'>, runId: string, asked?: { at: string; open: boolean }): string {
  const changes = asked ? state.fileChanges.filter(f => f.created_at <= asked.at) : state.fileChanges
  const rows = turnTeams(state, runId).filter(row => row.state.status !== 'waiting')
  // Ended badly: so on its row, or every agent of it ended and one failed, none finished (a lead that failed at once).
  const ended = (row: (typeof rows)[number]) => {
    const mine = state.agents.filter(a => row.state.agents.includes(a.id))
    if (['failed', 'stopped', 'interrupted'].includes(row.state.status)) return row.state.status
    return mine.length > 0 && mine.some(a => a.status === 'failed') && mine.every(a => a.status === 'failed' || a.status === 'cancelled') ? 'failed' : null
  }
  const anyEnded = rows.some(row => ended(row))
  const said = rows.map(row => {
    const { team, status, why, recipe } = row.state
    const count = filesOf({ fileChanges: changes }, row)
    const files = `${count} file${count === 1 ? '' : 's'}`
    const what = recipe ? files : count ? `${files}, kept apart` : 'nothing to take in'
    const short = why && why.length > WHY_CHARS ? `${why.slice(0, WHY_CHARS - 1)}…` : why
    if (anyEnded) {
      const word = ended(row) ?? (['ready', 'done', 'in'].includes(status) ? 'is ready' : status)
      return `${team} ${word}${asked?.open !== false && short ? `: ${short}` : ''} (${what})`
    }
    const stands = asked?.open !== false && (!['ready', 'done', 'in'].includes(status) || why) ? `${status}${short ? `: ${short}` : ''} · ` : ''
    return `${team} ${stands}${what}`
  })
  const { left } = endedEarly(rows, changes, runId)
  return [...(anyEnded ? [] : ["Teams' work is ready"]), ...said, ...(left && asked?.open !== false ? [left] : [])].join(' · ')
}

/**
 * What a team's agents reported they used, added up; `unreported`: one of them said nothing (counted as nothing,
 * shown as "–", never guessed). Null tokens: none of them said.
 */
export function rowTokens(agents: Agent[], ids: string[]): { tokens: number | null; unreported: boolean } {
  const mine = agents.filter(a => ids.includes(a.id))
  const told = mine.filter(a => a.input_tokens !== null || a.output_tokens !== null)
  return {
    tokens: told.length ? told.reduce((sum, a) => sum + (a.input_tokens ?? 0) + (a.output_tokens ?? 0), 0) : null,
    unreported: told.length < mine.length,
  }
}

/** Tokens as the canvas says them: "41k tokens", with "+ –" where an agent did not say. */
export function tokensLine({ tokens, unreported }: { tokens: number | null; unreported: boolean }): string {
  const said = tokens === null ? '–' : tokens >= 1000 ? `${Math.round(tokens / 1000)}k` : String(tokens)
  return `${said} tokens${unreported && tokens !== null ? ' + –' : ''}`
}

/**
 * The teams of a turn's recipes that ended before their end (B-84, G1.3): why each ended ("Web app: rule broken: Test
 * it was not done."), and the note that Take in takes the one copy in whole - what such a team left in it too. Not a
 * team with no recipe (its copy is its own), nor one stopped as its turn ended at Ready for you, nor one whose end is
 * not known (`ended_ready` null: a row of before batch-16).
 */
export function endedEarly(teams: ChatTeam[], changes: FileChange[], runId: string): { why: string[]; left: string } {
  const early = teams.flatMap(({ state }) =>
    state?.run_id === runId && state.recipe && (state.status === 'failed' || state.status === 'stopped') && state.ended_ready === false ? [state] : [],
  )
  return {
    why: early.filter(state => state.why).map(state => `${state.team}: ${state.why}.`),
    left: early
      .filter(state => changes.some(f => f.status === 'in_copy' && state.agents.includes(f.agent_id ?? '')))
      .map(state => `Take in also takes in what ${state.team} left before it stopped.`)
      .join(' '),
  }
}

/** On the Lead's kept copy of a turn's recipes (`endedEarly`), in one line; "" for none. */
export function keptNote(teams: ChatTeam[], changes: FileChange[], runId: string): string {
  const { why, left } = endedEarly(teams, changes, runId)
  return [...why, left].filter(Boolean).join(' ')
}
