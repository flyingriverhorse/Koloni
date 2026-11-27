import { expect, test } from 'vitest'
import type { Budget, JudgeOut } from '../../api/types'
import {
  agentsSaid,
  appSaid,
  askedSaid,
  dataSaid,
  doneSaid,
  folderSaid,
  memorySaid,
  moneySaid,
  notifySaid,
  voiceSaid,
} from './said'

// Each section's sentence is made from the values as they stand: another value, another sentence - never a fixed claim.

test('How agents work: who changes the files, the Scout, and what a new chat starts with', () => {
  const now = {
    lead_work: 'delegates',
    suggest_tasks: true,
    suggest_tier: 'fast',
    teams_mode: 'none',
  } as const
  expect(agentsSaid(now, 0)).toBe(
    'The Orchestrator plans, asks and checks; sub-agents change the files. After each turn the Scout suggests follow-up tasks, from the fast tier. New chats start with no teams.',
  )
  expect(agentsSaid({ ...now, lead_work: 'itself', suggest_tasks: false, teams_mode: 'lead' }, 2)).toBe(
    'The Orchestrator changes the files itself. No follow-up tasks are suggested. New chats start with the Orchestrator choosing their teams and 2 other folders.',
  )
})

test('When you’re asked: the judge as it is set, who answers a card that waits, and when a sub-agent asks', () => {
  const now = {
    full_auto_judge: true,
    judge_risky: 'refuse',
    judge_words: false,
    when_away: 'lead',
    away_minutes: 5,
    spawn_approval: 'auto',
  } as const
  expect(askedSaid(now)).toBe(
    'At Full auto a small model looks at each command the list does not stop; one it finds risky is refused and its agent goes another way - after 3 refusals in a row it asks you. When a card has waited 5 minutes - at once while you’re away - the Orchestrator answers what it safely can. Opening a sub-agent asks you when it matters.',
  )
  expect(askedSaid({ ...now, judge_risky: 'ask', judge_words: true })).toMatch(
    /^At Full auto a small model .*; one it finds risky waits for you on a card\. It also lets a delete or a push run when a line you saved names it\./,
  )
  // Off: no judge - and its box for your words says nothing then, whatever it holds.
  expect(
    askedSaid({ ...now, full_auto_judge: false, judge_words: true, when_away: 'waits', spawn_approval: 'never' }),
  ).toBe(
    'At Full auto no judge looks at commands: what the list does not stop runs. Every card waits for you, while you’re away too. Sub-agents open without asking.',
  )
  expect(askedSaid({ ...now, away_minutes: 1 })).toContain('When a card has waited 1 minute -')
  expect(askedSaid({ ...now, away_minutes: 0 })).toContain(
    'The Orchestrator answers what it safely can of a card at once.',
  )
})

test('When the work is done: what runs after a change, how far failing work goes back, and how it reaches git', () => {
  const now = {
    after_change: 'check',
    fix_rounds: null,
    stronger_model: true,
    git_commit: false,
    finish_way: null,
  } as const
  expect(doneSaid(now)).toBe(
    'After a change tests run, and a Reviewer reads a big or security-touching one; failing work goes back until it passes, then to a stronger model.',
  )
  expect(
    doneSaid({
      ...now,
      after_change: 'tests',
      fix_rounds: 1,
      stronger_model: false,
      git_commit: true,
      finish_way: 'pull_request',
    }),
  ).toBe(
    'After a change tests run; failing work goes back up to 1 time. Each sub-agent’s work is offered as a git commit. A team’s finished branch becomes a pull request.',
  )
  expect(doneSaid({ ...now, after_change: 'nothing', finish_way: 'merge' })).toBe(
    'Nothing is tested or reviewed after a change. A team’s finished branch is merged here.',
  )
})

const spend = (over: Partial<Budget> = {}): Budget => ({
  budget: 50,
  currency: 'USD',
  spent: 23.4,
  at_least: false,
  share: 0.468,
  warn: false,
  over: false,
  ...over,
})

test('Limits and money: the month’s budget - not enforced where prices are in several currencies - and a job’s', () => {
  expect(moneySaid({ monthly_budget: null, turn_token_limit: null }, null)).toBe(
    'No monthly budget. A message’s work has no token limit.',
  )
  expect(moneySaid({ monthly_budget: 50, turn_token_limit: 2_000_000 }, spend())).toBe(
    'This month may cost at most 50 USD: at 80% you are told, at 100% a new message asks before its work starts. 23.4 USD so far. A message’s work stops past 2,000,000 tokens.',
  )
  expect(moneySaid({ monthly_budget: 50, turn_token_limit: null }, spend({ currency: null, spent: null }))).toBe(
    'This budget is not enforced: prices are in more than one currency. A message’s work has no token limit.',
  )
  expect(moneySaid({ monthly_budget: 12.5 }, spend({ at_least: true }))).toContain('at most 12.5 USD')
  expect(moneySaid({ monthly_budget: 12.5 }, spend({ at_least: true }))).toContain('At least 23.4 USD so far.')
})

test('Memory and web, Notifications and This folder', () => {
  const memory = { auto_notes: false, search_url: null, search_order: 'builtin', memory_links: [] } as const
  expect(memorySaid(memory)).toBe('Nothing is noted by itself. A web search asks the built-in search, then a CLI.')
  expect(
    memorySaid({ ...memory, auto_notes: true, search_url: 'http://x', search_order: 'cli', memory_links: ['o'] }),
  ).toBe(
    'After each message’s work a fast model notes what it found. A web search asks your SearXNG first, then a CLI, then the built-in search. Recall also looks in 1 other project.',
  )
  expect(notifySaid({ notify_desktop: false, day_note_at: null }, true)).toBe(
    'No desktop notification is shown. No day’s summary is sent.',
  )
  expect(notifySaid({ notify_desktop: false, day_note_at: '18:00' }, false)).toBe(
    'A desktop notification is not available on this system. The day’s summary comes at 18:00.',
  )
  expect(notifySaid({ notify_desktop: true, day_note_at: null }, true)).toMatch(/^A desktop notification shows when/)
  const koloni = { settings_kept: false, rules_kept: false, rules: null, broken: [], asks: {} }
  expect(folderSaid(koloni)).toBe('No setting of this project is kept in this folder.')
  expect(folderSaid({ ...koloni, settings_kept: true, rules_kept: true })).toBe(
    'Some of this project’s settings are kept in .koloni/settings.json in this folder, in git. Every agent here is given the rules in .koloni/rules.md.',
  )
})

test('The app: each clause once its value is read - none guessed while it is not', () => {
  expect(appSaid({ language: undefined, compactAt: undefined, judge: undefined, experimental: undefined })).toBe('')
  const judge: JudgeOut = {
    provider_id: null,
    model_id: null,
    now: { provider_id: 'p1', provider_name: 'Local', model_id: 'quick', cli: false, measured: false },
    choices: [],
  }
  expect(appSaid({ language: '', compactAt: 75, judge, experimental: false })).toBe(
    'Agents answer in the language you write in, in every project. An agent’s context is summarised past 75% of its model’s window. KOLONİ’s judges ask quick, the Fast tier’s first. Experimental features are not offered on the Models page.',
  )
  expect(
    appSaid({
      language: 'Türkçe',
      compactAt: null,
      judge: { ...judge, provider_id: 'p1', model_id: 'quick' },
      experimental: true,
    }),
  ).toBe(
    'Agents answer in Türkçe, in every project. KOLONİ’s judges ask quick. Experimental features are offered on the Models page.',
  )
  expect(
    appSaid({ language: undefined, compactAt: undefined, judge: { ...judge, now: null }, experimental: undefined }),
  ).toBe('No model can be asked for KOLONİ’s judges now: each command they would look at waits for you.')
  expect(voiceSaid({ autoRead: false, mode: 'whole', language: 'en-US', voice: null }, false)).toBe(
    'Auto-read is off; it reads the whole answer as it is written. Dictation listens for en-US; reading aloud is the browser’s own voice. Kept in this browser.',
  )
  expect(voiceSaid({ autoRead: true, mode: 'summary', language: 'tr-TR', voice: 'v' }, true)).toContain(
    'Auto-read is on; it reads a short summary when the work ends. Dictation listens for tr-TR; reading aloud is Gemini’s voice.',
  )
  expect(dataSaid(null, null)).toBe('')
  expect(dataSaid({ db_mb: 1, backups_mb: 2, copies_mb: 3, logs_mb: 4 }, 2)).toBe(
    'KOLONİ’s data takes 10 MB on this machine. 2 places no agent opens, in any project.',
  )
  // (a size not counted in time: no total)
  expect(dataSaid({ db_mb: 1, backups_mb: null, copies_mb: 3, logs_mb: 4 }, 0)).toBe(
    '0 places no agent opens, in any project.',
  )
})
