import type { NewTrigger, Trigger, TriggerBudget, TriggerChange, TriggerProposal, TriggerRun } from '../api/types'
import { when } from '../canvas/turns'

/** The server's bounds (app/triggers.py, app/schemas.py): said beside the fields, and checked before anything is sent. */
export const LIMITS = {
  name: 80,
  message: 4000,
  every: [5, 7 * 24 * 60],
  glob: 200,
  commands: 20,
  agents: [0, 4],
  steps: [1, 200],
  minutes: [1, 240],
  perDay: [1, 500],
  runs: [1, 1000],
} as const

const some = (count: number, one: string) => `${count} ${one}${count === 1 ? '' : 's'}`

/** The days a schedule can name, in week order, as the server takes them (app/triggers.py `WEEK`). */
export const WEEK = [
  ['mon', 'Monday'],
  ['tue', 'Tuesday'],
  ['wed', 'Wednesday'],
  ['thu', 'Thursday'],
  ['fri', 'Friday'],
  ['sat', 'Saturday'],
  ['sun', 'Sunday'],
] as const
export type Day = (typeof WEEK)[number][0]

type Config = { every_minutes?: number; at?: string; days?: string | Day[]; glob?: string }

/** Chosen days in words, as the server says them: "Fridays", "Mondays and Thursdays". */
function daysInWords(days: Day[]): string {
  const names = WEEK.filter(([day]) => days.includes(day)).map(([, name]) => `${name}s`)
  return names.length > 1 ? `${names.slice(0, -1).join(', ')} and ${names.at(-1)}` : (names[0] ?? '')
}

/** When a trigger starts a turn, in words. */
export function whenOf(trigger: Pick<Trigger, 'kind' | 'config'>): string {
  const config = trigger.config as Config
  if (trigger.kind === 'files') return `when ${config.glob ?? 'its files'} changes`
  if (trigger.kind === 'webhook') return 'on a request from outside'
  if (typeof config.every_minutes === 'number') return `every ${some(config.every_minutes, 'minute')}`
  if (config.at) return `${Array.isArray(config.days) ? daysInWords(config.days) : config.days === 'weekdays' ? 'weekdays' : 'every day'} at ${config.at}`
  return 'by the clock'
}

/**
 * The command lines a trigger's turns may run, as the server reads them off its
 * conversation's allow list (`command_lines`). A ticked rule that was since taken off that
 * list is not among them. What the trigger itself keeps (`permissions.commands`) are the
 * rules' ids, and never shown as commands.
 */
export function commandLines(trigger: Trigger): string[] {
  const told: unknown = trigger.command_lines
  return Array.isArray(told) ? told.filter((line): line is string => typeof line === 'string') : []
}

/** What a trigger's turns may do without asking; with nothing allowed they only read. */
export function leaveOf(trigger: Trigger): string {
  const { write, agents, web, hosts, notify } = trigger.permissions
  const lines = commandLines(trigger)
  const parts = [
    write && 'may change files',
    lines.length > 0 && `may run: ${lines.join('; ')}`,
    agents > 0 && `may open ${some(agents, 'agent')}`,
    web && 'may search the web',
    hosts && hosts.length > 0 && `may make GET and HEAD requests to: ${hosts.join(', ')}`,
    notify && 'may notify',
  ].filter(Boolean)
  return parts.length > 0 ? parts.join(' · ') : 'reads only'
}

export function budgetOf(budget: TriggerBudget): string {
  return `${some(budget.steps, 'model step')} and ${some(budget.minutes, 'minute')} a run · ${some(budget.per_day, 'run')} a day`
}

const OUTCOME: Record<NonNullable<TriggerRun['outcome']>, string> = {
  completed: 'completed',
  failed: 'failed',
  budget: 'stopped: over its budget',
  stopped: 'stopped',
  skipped_busy: 'skipped: conversation was busy',
  skipped_budget: "skipped: day's budget used",
  skipped_month: "skipped: over the project's monthly budget",
  skipped_limit: "skipped: its provider was over its limit",
  skipped_same: 'skipped: nothing changed since the last run',
}

/** How one time a trigger came due ended. With no outcome on record its turn is still running. */
export function outcomeOf(run: TriggerRun): string {
  return `${run.outcome === null ? 'running' : OUTCOME[run.outcome]}${run.late ? ' · late' : ''}`
}

/** What a trigger does, as its row says it: its message's first sentence. */
export function whatOf(message: string): string {
  return message.trim().split(/(?<=[.!?])\s/)[0]
}

/** An outcome's tag: done, failed, still running, or neither. */
export function outcomeTone(run: TriggerRun): string {
  if (run.outcome === 'completed') return 'tag tag-ok'
  if (run.outcome === 'failed' || run.outcome === 'budget') return 'tag tag-del'
  return run.outcome === null ? 'tag tag-accent' : 'tag'
}

/** 93-B2: a schedule whose last runs found nothing, spaced out; null while it keeps its own times. */
export function slowedLine(trigger: Trigger): string | null {
  if (!trigger.slowed || !trigger.enabled) return null
  return `Slowed down: the last ${trigger.slowed} runs found nothing${trigger.next_at ? ` — next at ${when(trigger.next_at)}` : ''}`
}

/** Why KOLONİ switched a trigger off; null while it is on, or when the user switched it off. */
export function offLine(trigger: Trigger): string | null {
  if (trigger.enabled || !trigger.off_because) return null
  // (Its end came - "ended: 10 runs done" - whatever failed before it.)
  if (trigger.off_because.startsWith('ended:')) return trigger.off_because
  return trigger.failures > 0 ? `switched off after ${some(trigger.failures, 'failure')}: ${trigger.off_because}` : `switched off: ${trigger.off_because}`
}

/** When a trigger ends by itself (K-tetik-bitis): "after 10 runs", "after 2026-11-01"; null for no end. */
export function endOf(ends: Trigger['ends']): string | null {
  if (ends?.runs != null) return `after ${some(ends.runs, 'run')}`
  if (ends?.until) return `after ${ends.until}`
  return null
}

/** A trigger's end on its card, with the runs counted toward it. */
export function endLine(trigger: Trigger): string {
  const end = endOf(trigger.ends)
  if (!end) return 'no end: it runs until you switch it off'
  return trigger.ends?.runs != null ? `${end} · ${trigger.ran} done` : end
}

/** What no end may cost, from the budget as typed: said under "No end" in the form. */
export function costNote(values: Pick<FormValues, 'steps' | 'minutes' | 'perDay'>): string {
  return `Up to ${values.perDay} runs a day, each up to ${values.steps} model steps and ${values.minutes} minutes, for as long as it is on.`
}

// --- the form ------------------------------------------------------------------------------

/** The form as it is typed: numbers are text until they are checked. */
export interface FormValues {
  name: string
  kind: Trigger['kind']
  /** By the clock: every so many minutes, or at a time of day. */
  schedule: 'every' | 'at'
  every: string
  at: string
  /** Every day, Monday to Friday, or the days ticked in `week`. */
  days: 'daily' | 'weekdays' | 'chosen'
  week: Day[]
  glob: string
  conversationId: string
  message: string
  write: boolean
  /** The ticked rules of the conversation's allow list, by their ids. */
  commands: string[]
  agents: string
  /** May search the web. */
  web: boolean
  /** The hosts it may make requests to, picked from the conversation's allowed hosts. */
  hosts: string[]
  /** May send the user a notification. */
  notify: boolean
  steps: string
  minutes: string
  perDay: string
  catchUp: boolean
  /** When it ends by itself: never, after so many runs, or after a day (the last it runs on). */
  ends: 'none' | 'runs' | 'until'
  endRuns: string
  endUntil: string
  /** By the clock: runs even when nothing changed since its last run. */
  runUnchanged: boolean
}

export type Field = 'name' | 'when' | 'days' | 'glob' | 'conversation' | 'message' | 'commands' | 'agents' | 'steps' | 'minutes' | 'perDay' | 'ends'

/** A new trigger: by the clock every hour, allowed nothing, with the usual budget. */
export function blank(conversationId: string): FormValues {
  return {
    name: '',
    kind: 'schedule',
    schedule: 'every',
    every: '60',
    at: '09:00',
    days: 'daily',
    week: [],
    glob: '',
    conversationId,
    message: '',
    write: false,
    commands: [],
    agents: '0',
    web: false,
    hosts: [],
    notify: false,
    steps: '15',
    minutes: '10',
    perDay: '24',
    catchUp: true,
    ends: 'none',
    endRuns: '10',
    endUntil: '',
    runUnchanged: false,
  }
}

/**
 * What a trigger's turns know of the rest of the conversation: said where its conversation
 * is chosen, and of the ready-made trigger - an agent kept on a project is not told what
 * the user says elsewhere.
 */
export const OWN_TOPIC =
  'A trigger’s messages have a topic of their own and do not see what you say in your topics. To tell it something, change its message, or write in its topic from one of its messages.'

/** "Keep an agent on this project": every hour, reading only, with a message to make your own. */
export function PRESET(conversationId: string): FormValues {
  return {
    ...blank(conversationId),
    name: 'Keep an agent on this project',
    message:
      'Look the project over: do the tests still pass, is there anything new that looks wrong? Write what you find on the notebook and remember what is worth keeping. Change nothing.',
  }
}

/**
 * Ready-made triggers: each only fills the form, on top of a blank one - so it is allowed
 * nothing but reading, with the usual budget, until the user changes that and saves.
 */
// A file change can come often: the tests card starts fewer turns a day than a new trigger.
const FILES_PER_DAY = 6

export const READY: { name: string; says: string; values: Partial<FormValues> }[] = [
  {
    name: 'Every morning: summarise the work since the last working day',
    says: 'Weekdays at 09:00, the first on the next one. Reads only.',
    values: {
      schedule: 'at',
      at: '09:00',
      days: 'weekdays',
      message: 'Summarise the work in this project since the last working day: what was asked, what changed, what failed and what is still open. Write it on the notebook. Change nothing.',
    },
  },
  {
    name: 'When source files change: run the tests',
    says: `Each change under src/ runs it (at most ${FILES_PER_DAY} a day); with no src/ folder it never starts - change the pattern to your own. To let it run the tests, tick your test command in the form.`,
    values: { kind: 'files', glob: 'src/**/*', perDay: String(FILES_PER_DAY), message: 'Files under src/ changed. Run the project’s tests and say which fail and why. Change nothing.' },
  },
  {
    name: 'Every Friday at 17:00: check the dependencies',
    says: 'Fridays at 17:00, the first on the next Friday. Reads only.',
    values: {
      schedule: 'at',
      at: '17:00',
      days: 'chosen',
      week: ['fri'],
      message: 'Look over the project’s dependencies: which are not pinned, which are no longer used, which appear twice? Write what you find on the notebook. Change nothing.',
    },
  },
]

/** Its kind, when it starts and its message, as the form takes them: a trigger's, or an agent's proposed one's. */
function startsIn(made: Pick<Trigger, 'name' | 'kind' | 'config' | 'message' | 'conversation_id'>): FormValues {
  const config = made.config as Config
  const fresh = blank(made.conversation_id)
  return {
    ...fresh,
    name: made.name,
    kind: made.kind,
    schedule: config.at ? 'at' : 'every',
    every: typeof config.every_minutes === 'number' ? String(config.every_minutes) : fresh.every,
    at: config.at ?? fresh.at,
    days: Array.isArray(config.days) ? 'chosen' : config.days === 'weekdays' ? 'weekdays' : 'daily',
    week: Array.isArray(config.days) ? [...config.days] : [],
    glob: config.glob ?? '',
    message: made.message,
  }
}

function endsIn(ends: Trigger['ends']): Pick<FormValues, 'ends' | 'endRuns' | 'endUntil'> {
  if (ends?.runs != null) return { ends: 'runs', endRuns: String(ends.runs), endUntil: '' }
  if (ends?.until) return { ends: 'until', endRuns: '10', endUntil: ends.until }
  return { ends: 'none', endRuns: '10', endUntil: '' }
}

/** An agent's proposed trigger in the form (slice 69): as proposed, allowed nothing, with the usual budget - yours to change. */
export function fromProposal(proposal: TriggerProposal): FormValues {
  return { ...startsIn(proposal), ...endsIn(proposal.ends) }
}

export function fromTrigger(trigger: Trigger): FormValues {
  return {
    ...startsIn(trigger),
    ...endsIn(trigger.ends),
    runUnchanged: trigger.run_unchanged,
    write: trigger.permissions.write,
    commands: [...(trigger.permissions.commands ?? [])],
    agents: String(trigger.permissions.agents),
    // (A trigger from before the web tools says nothing of them: off, and no host.)
    web: trigger.permissions.web ?? false,
    hosts: [...(trigger.permissions.hosts ?? [])],
    notify: trigger.permissions.notify ?? false,
    steps: String(trigger.budget.steps),
    minutes: String(trigger.budget.minutes),
    perDay: String(trigger.budget.per_day),
    catchUp: trigger.catch_up,
  }
}

/** Another conversation chosen: its allow list is another list, so no rule and no host stays ticked. */
export function withConversation(values: FormValues, conversationId: string): FormValues {
  return conversationId === values.conversationId ? values : { ...values, conversationId, commands: [], hosts: [] }
}

const whole = (text: string) => (/^\d+$/.test(text.trim()) ? Number(text) : Number.NaN)
const within = (text: string, [low, high]: readonly [number, number]) => {
  const value = whole(text)
  return value >= low && value <= high
}
const range = ([low, high]: readonly [number, number]) => `From ${low} to ${high}.`

/** What cannot be saved, by field; empty when everything can. */
export function validate(values: FormValues): Partial<Record<Field, string>> {
  const errors: Partial<Record<Field, string>> = {}
  if (!values.name.trim()) errors.name = 'Give it a name.'
  else if (values.name.trim().length > LIMITS.name) errors.name = `A name of at most ${LIMITS.name} characters.`
  if (!values.message.trim()) errors.message = 'Write the message it sends.'
  else if (values.message.trim().length > LIMITS.message) errors.message = `A message of at most ${LIMITS.message} characters.`
  if (!values.conversationId) errors.conversation = 'Choose the conversation its messages go into.'
  if (values.kind === 'schedule') {
    if (values.schedule === 'every' && !within(values.every, LIMITS.every)) {
      errors.when = `At least ${LIMITS.every[0]} minutes, at most ${LIMITS.every[1]} (a week).`
    }
    if (values.schedule === 'at' && !/^([01]\d|2[0-3]):[0-5]\d$/.test(values.at)) errors.when = 'Give the time of day as HH:MM.'
    else if (values.schedule === 'at' && values.days === 'chosen' && values.week.length === 0) errors.days = 'Tick at least one day.'
  }
  if (values.kind === 'files') {
    const pattern = values.glob.trim().replace(/\\/g, '/')
    if (!pattern) errors.glob = 'Give a pattern, such as src/**/*.py.'
    else if (pattern.length > LIMITS.glob || pattern.startsWith('/') || pattern.includes(':') || pattern.split('/').some(part => part === '' || part === '.' || part === '..')) {
      errors.glob = `The pattern names paths inside the project folder: no drive, no leading slash, no "..", at most ${LIMITS.glob} characters.`
    }
  }
  if (values.commands.length > LIMITS.commands) errors.commands = `A trigger may run at most ${LIMITS.commands} commands.`
  if (!within(values.agents, LIMITS.agents)) errors.agents = range(LIMITS.agents)
  if (!within(values.steps, LIMITS.steps)) errors.steps = range(LIMITS.steps)
  if (!within(values.minutes, LIMITS.minutes)) errors.minutes = range(LIMITS.minutes)
  if (!within(values.perDay, LIMITS.perDay)) errors.perDay = range(LIMITS.perDay)
  if (values.ends === 'runs' && !within(values.endRuns, LIMITS.runs)) errors.ends = range(LIMITS.runs)
  if (values.ends === 'until' && !/^\d{4}-\d{2}-\d{2}$/.test(values.endUntil)) errors.ends = 'Choose its last day.'
  return errors
}

/** Each field by the server's words for it, the first that matches wins. */
const FIELD_WORDS: [RegExp, Field][] = [
  // (First: a provider's name could hold any word - `OWN_TOOLS` in app/triggers.py.)
  [/a trigger can't start this conversation's Orchestrator/, 'conversation'],
  // (Before "conversation": a command that is not on the conversation's list names both.)
  [/command/, 'commands'],
  [/conversation/, 'conversation'],
  [/\bname of\b/, 'name'],
  [/\bmessage of\b/, 'message'],
  [/\bdays must\b/, 'days'],
  [/every_minutes|\bat must\b|schedule is/, 'when'],
  [/pattern|glob/, 'glob'],
  [/permissions\.agents/, 'agents'],
  [/budget\.steps/, 'steps'],
  [/budget\.minutes/, 'minutes'],
  [/budget\.per_day/, 'perDay'],
  [/\bends is\b|end date/, 'ends'],
]

/** The field a refusal of the server's is about, by its words; null when it names none. */
export function fieldOf(detail: string): Field | null {
  return FIELD_WORDS.find(([words]) => words.test(detail))?.[1] ?? null
}

function configOf(values: FormValues): Record<string, unknown> {
  if (values.kind === 'files') return { glob: values.glob.trim() }
  if (values.kind === 'webhook') return {}
  if (values.schedule === 'every') return { every_minutes: whole(values.every) }
  return { at: values.at, days: values.days === 'chosen' ? values.week : values.days }
}

/** What is sent to change a trigger: all the form holds. Its kind does not change, and whether it is on is its switch's. */
export function toPatch(values: FormValues): Required<Omit<TriggerChange, 'enabled'>> {
  return {
    name: values.name.trim(),
    conversation_id: values.conversationId,
    message: values.message.trim(),
    config: configOf(values),
    permissions: {
      write: values.write,
      commands: [...values.commands],
      agents: whole(values.agents),
      // What is left out is off, and no host: said only where it is allowed.
      ...(values.web && { web: true }),
      ...(values.hosts.length > 0 && { hosts: [...values.hosts] }),
      ...(values.notify && { notify: true }),
    },
    budget: { steps: whole(values.steps), minutes: whole(values.minutes), per_day: whole(values.perDay) },
    catch_up: values.catchUp,
    ends: values.ends === 'runs' ? { runs: whole(values.endRuns) } : values.ends === 'until' ? { until: values.endUntil } : null,
    run_unchanged: values.runUnchanged,
  }
}

/** What is sent to make a trigger; it is made switched on. `proposalId`: made from an agent's card, which is then done with. */
export function toBody(values: FormValues, proposalId: string | null = null): NewTrigger {
  return { ...toPatch(values), kind: values.kind, enabled: true, proposal_id: proposalId } as NewTrigger
}

/** Something a turn was refused because its trigger does not allow it, as the form can allow it. */
export type Allow = { write: true } | { command: string } | { agents: 1 }

/**
 * The form with one more thing allowed. A command is allowed by ticking the rule of the
 * conversation's allow list that is exactly that line; a line on no rule ticks nothing.
 */
export function allowIn(values: FormValues, allow: Allow, rules: { id: string; prefix: string }[]): FormValues {
  if ('write' in allow) return { ...values, write: true }
  if ('agents' in allow) {
    const now = whole(values.agents)
    return { ...values, agents: String(Math.min(LIMITS.agents[1], (Number.isNaN(now) ? 0 : now) + 1)) }
  }
  const rule = rules.find(r => r.prefix === allow.command)
  return rule && !values.commands.includes(rule.id) ? { ...values, commands: [...values.commands, rule.id] } : values
}
