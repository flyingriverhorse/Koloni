import type { Budget, JudgeOut, Project, Storage } from '../../api/types'
import type { VoiceSettings } from '../../voice/voice'
import { UNENFORCED, unenforced } from '../../usage/budgetText'

/**
 * Each section of Settings first reads itself in a sentence or two (0.1.10): what happens now, made from the values as
 * they stand on the page - `{...project, ...what its Save would send}` - so it changes as they are changed. A clause
 * whose value is not known is left out, never guessed.
 */
type Now<K extends keyof Project> = Pick<Project, K>

const times = (n: number, one: string) => `${n} ${one}${n === 1 ? '' : 's'}`

const LEAD: Record<Project['lead_work'], string> = {
  delegates: 'The Orchestrator plans, asks and checks; sub-agents change the files.',
  decides: 'The Orchestrator makes a small change itself; bigger work goes to a sub-agent.',
  itself: 'The Orchestrator changes the files itself.',
}
const TEAMS: Record<Project['teams_mode'], string> = {
  lead: 'the Orchestrator choosing their teams',
  manual: 'the teams a chat kept for them',
  none: 'no teams',
}

/** This project › How agents work. */
export function agentsSaid(now: Now<'lead_work' | 'suggest_tasks' | 'suggest_tier' | 'teams_mode'>, folders: number) {
  const scout = now.suggest_tasks
    ? `After each turn the Scout suggests follow-up tasks, from the ${now.suggest_tier} tier.`
    : 'No follow-up tasks are suggested.'
  const others = folders ? ` and ${times(folders, 'other folder')}` : ''
  return `${LEAD[now.lead_work] ?? ''} ${scout} New chats start with ${TEAMS[now.teams_mode] ?? 'no teams'}${others}.`
}

const SPAWN: Record<Project['spawn_approval'], string> = {
  auto: 'Opening a sub-agent asks you when it matters.',
  always: 'Every sub-agent asks you before it opens.',
  never: 'Sub-agents open without asking.',
}

/** This project › When you’re asked. */
export function askedSaid(
  now: Now<'full_auto_judge' | 'judge_risky' | 'judge_words' | 'when_away' | 'away_minutes' | 'spawn_approval'>,
) {
  const judge = !now.full_auto_judge
    ? 'At Full auto no judge looks at commands: what the list does not stop runs.'
    : now.judge_risky === 'ask'
      ? 'At Full auto a small model looks at each command the list does not stop; one it finds risky waits for you on a card.'
      : 'At Full auto a small model looks at each command the list does not stop; one it finds risky is refused and its agent goes another way - after 3 refusals in a row it asks you.'
  const words =
    now.full_auto_judge && now.judge_words ? ' It also lets a delete or a push run when a line you saved names it.' : ''
  const away =
    now.when_away !== 'lead'
      ? 'Every card waits for you, while you’re away too.'
      : now.away_minutes === 0
        ? 'The Orchestrator answers what it safely can of a card at once.'
        : `When a card has waited ${times(now.away_minutes, 'minute')} - at once while you’re away - the Orchestrator answers what it safely can.`
  return `${judge}${words} ${away} ${SPAWN[now.spawn_approval] ?? ''}`.trim()
}

const AFTER: Record<Project['after_change'], string> = {
  check: 'After a change tests run, and a Reviewer reads a big or security-touching one',
  tests: 'After a change tests run',
  nothing: 'Nothing is tested or reviewed after a change.',
}

/** This project › When the work is done. */
export function doneSaid(
  now: Now<'after_change' | 'stronger_model' | 'git_commit' | 'finish_way'> & { fix_rounds: number | null },
) {
  const back =
    now.after_change === 'nothing'
      ? ''
      : `; failing work goes back ${now.fix_rounds === null ? 'until it passes' : `up to ${times(now.fix_rounds, 'time')}`}${now.stronger_model ? ', then to a stronger model' : ''}.`
  const commit = now.git_commit ? ' Each sub-agent’s work is offered as a git commit.' : ''
  const branch =
    now.finish_way === 'merge'
      ? ' A team’s finished branch is merged here.'
      : now.finish_way === 'pull_request'
        ? ' A team’s finished branch becomes a pull request.'
        : ''
  return `${AFTER[now.after_change] ?? ''}${back}${commit}${branch}`
}

const amount = (value: number) => value.toLocaleString('en', { maximumFractionDigits: 2 })

/** This project › Money and limits. */
export function moneySaid(
  now: { monthly_budget?: number | null; turn_token_limit?: number | null },
  spend: Budget | null,
) {
  const currency = spend?.currency ? ` ${spend.currency}` : ''
  const month =
    now.monthly_budget == null
      ? 'No monthly budget.'
      : spend && unenforced(spend)
        ? `${UNENFORCED}.`
        : `This month may cost at most ${amount(now.monthly_budget)}${currency}: at 80% you are told, at 100% a new message asks before its work starts.`
  const spent =
    spend?.spent != null ? ` ${spend.at_least ? 'At least ' : ''}${amount(spend.spent)}${currency} so far.` : ''
  const job =
    now.turn_token_limit == null
      ? 'A message’s work has no token limit.'
      : `A message’s work stops past ${amount(now.turn_token_limit)} tokens.`
  return `${month}${spent} ${job}`
}

/** This project › Memory and web. */
export function memorySaid(now: Now<'auto_notes' | 'search_url' | 'search_order' | 'memory_links'>) {
  const notes = now.auto_notes
    ? 'After each message’s work a fast model notes what it found.'
    : 'Nothing is noted by itself.'
  const then = now.search_order === 'cli' ? 'a CLI, then the built-in search' : 'the built-in search, then a CLI'
  const search = now.search_url?.trim() ? `your SearXNG first, then ${then}` : then
  const links = now.memory_links.length
    ? ` Recall also looks in ${times(now.memory_links.length, 'other project')}.`
    : ''
  return `${notes} A web search asks ${search}.${links}`
}

/** This project › Notifications. */
export function notifySaid(now: Now<'notify_desktop' | 'day_note_at'>, available: boolean) {
  const desktop = now.notify_desktop
    ? 'A desktop notification shows when an agent notifies you or something waits for you.'
    : available
      ? 'No desktop notification is shown.'
      : 'A desktop notification is not available on this system.'
  const day = now.day_note_at ? ` The day’s summary comes at ${now.day_note_at}.` : ' No day’s summary is sent.'
  return desktop + day
}

/** This project › This folder: what of the project the folder’s .koloni/ keeps. */
export function folderSaid(koloni: Project['koloni'] | undefined) {
  if (!koloni) return 'This folder’s .koloni/ is not read by this server.'
  const settings = koloni.settings_kept
    ? 'Some of this project’s settings are kept in .koloni/settings.json in this folder, in git.'
    : 'No setting of this project is kept in this folder.'
  const rules = koloni.rules_kept ? ' Every agent here is given the rules in .koloni/rules.md.' : ''
  return settings + rules
}

/** The app › Agents: each clause once its value is read. */
export function appSaid({
  language,
  compactAt,
  judge,
  experimental,
}: {
  language: string | undefined
  compactAt: number | null | undefined
  judge: JudgeOut | undefined
  experimental: boolean | undefined
}) {
  const own = judge?.now && judge.provider_id === judge.now.provider_id && judge.model_id === judge.now.model_id
  return [
    language !== undefined &&
      `Agents answer in ${language ? language : 'the language you write in'}, in every project.`,
    compactAt != null && `An agent’s context is summarised past ${compactAt}% of its model’s window.`,
    judge &&
      (judge.now
        ? `KOLONİ’s judges ask ${judge.now.model_id}${own ? '' : ', the Fast tier’s first'}.`
        : 'No model can be asked for KOLONİ’s judges now: each command they would look at waits for you.'),
    experimental !== undefined &&
      `Experimental features are ${experimental ? 'offered' : 'not offered'} on the Models page.`,
  ]
    .filter(Boolean)
    .join(' ')
}

/** The app › Voice: this browser’s. */
export function voiceSaid(now: Pick<VoiceSettings, 'autoRead' | 'mode' | 'language' | 'voice'>, gemini: boolean) {
  const reads = now.mode === 'summary' ? 'a short summary when the work ends' : 'the whole answer as it is written'
  const voice = gemini ? 'Gemini’s voice' : now.voice ? 'the voice you chose' : 'the browser’s own voice'
  return `Auto-read is ${now.autoRead ? 'on' : 'off'}; it reads ${reads}. Dictation listens for ${now.language}; reading aloud is ${voice}. Kept in this browser.`
}

/** The app › Your data: what KOLONİ's data takes on this machine, once counted, and the places no agent opens. */
export function dataSaid(storage: Storage | null, never: number | null) {
  const sizes = storage ? [storage.db_mb, storage.backups_mb, storage.copies_mb, storage.logs_mb] : []
  const counted = sizes.every(size => size !== null)
  const total = sizes.reduce<number>((sum, size) => sum + (size ?? 0), 0)
  return [
    storage && counted && `KOLONİ’s data takes ${amount(total)} MB on this machine.`,
    never !== null && `${times(never, 'place')} no agent opens, in any project.`,
  ]
    .filter(Boolean)
    .join(' ')
}
