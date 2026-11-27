import type { Project } from '../../api/types'
import type { ProjectSettingsValues } from '../ProjectSettings'

/**
 * Each setting of This project as a new project has it: app/db/models.py `Project`'s column defaults
 * (tests/test_settings_usual.py keeps them the same). A cell says "the default" where a value is this.
 */
export const USUAL = {
  lead_work: 'delegates',
  suggest_tasks: true,
  suggest_tier: 'fast',
  teams_mode: 'none',
  also_in: [],
  read_in: [],
  full_auto_judge: true,
  judge_risky: 'refuse',
  judge_words: false,
  when_away: 'lead',
  away_minutes: 5,
  spawn_approval: 'auto',
  disposable_deletes: false,
  exec_location: 'host',
  docker_image: null,
  docker_network: false,
  longest_command: 10,
  hide_secrets: true,
  pass_env: null,
  canary: true,
  after_change: 'check',
  fix_rounds: null,
  stronger_model: true,
  check_kinds: {},
  measure_command: null,
  git_commit: false,
  finish_way: null,
  monthly_budget: null,
  turn_token_limit: null,
  max_agents: null,
  spawn_max_parallel: 2,
  spawn_max_depth: 2,
  spawn_max_agents: 6,
  continue_steps: 25,
  discussion_budget: null,
  auto_notes: false,
  memory_links: [],
  search_url: null,
  search_order: 'builtin',
  search_agy: false,
  notify_desktop: false,
  day_note_at: null,
} as const satisfies Partial<Record<keyof Project, unknown>>

/** Each setting a section's Save sends, by the name it has on the page: the save bar says these. */
const NAMES: Record<keyof ProjectSettingsValues, string> = {
  lead_work: 'Who changes the files',
  suggest_tasks: 'Suggest follow-up tasks after each turn',
  suggest_tier: 'Follow-up tasks from',
  teams_mode: 'New chats’ teams',
  teams: 'New chats’ teams',
  also_in: 'Other folders',
  read_in: 'Other folders',
  full_auto_judge: 'Full auto’s judge',
  judge_risky: 'When the judge finds a command risky',
  judge_words: 'Lets a delete or a push run when a line you saved names it',
  when_away: 'When you’re away',
  away_minutes: 'When you’re away',
  spawn_approval: 'Opening a sub-agent',
  disposable_deletes: 'Agents may delete what is disposable without asking',
  exec_location: 'Run commands on',
  docker_image: 'Image',
  docker_network: 'Allow network access',
  longest_command: 'Longest command (minutes)',
  hide_secrets: 'Hide secret files from commands',
  pass_env: 'Secret variables commands may see',
  canary: 'Planted test key (canary)',
  after_change: 'After a change',
  fix_rounds: 'Fix rounds',
  stronger_model: 'Then a stronger model',
  check_kinds: 'Check by kind of work',
  forget_tests_found: 'Forget the test command found',
  measure_command: 'Measure command',
  git_commit: 'Each sub-agent’s work as a git commit',
  finish_way: 'How a team’s finished branch reaches yours',
  monthly_budget: 'Monthly budget',
  turn_token_limit: 'Tokens a message’s work may take',
  max_agents: 'Agents at work in this project',
  spawn_max_parallel: 'Agents at the same time',
  spawn_max_depth: 'Sub-agent levels',
  spawn_max_agents: 'Sub-agents per request',
  continue_steps: 'Continue gives this many more steps',
  discussion_budget: 'A discussion’s tokens, at most',
  auto_notes: 'Note what the work found, by itself',
  memory_links: 'Also look in the memory of',
  search_url: 'Search address (SearXNG)',
  search_order: 'Otherwise search with',
  search_agy: 'Let agy search too',
  notify_desktop: 'Show a desktop notification',
  day_note_at: 'Send the day’s summary at',
}

/**
 * What a section's Save would change, by name, each once: what its patch sends that is not what is saved. (Where
 * commands run is sent whole with the rest of its section: only a value that moved is a change.)
 */
export function changes(project: Project, patch: ProjectSettingsValues): string[] {
  const kept = project as unknown as Record<string, unknown>
  const moved = Object.entries(patch).filter(
    ([key, value]) => JSON.stringify(value ?? null) !== JSON.stringify(kept[key] ?? null),
  )
  return [...new Set(moved.map(([key]) => NAMES[key as keyof ProjectSettingsValues] ?? key))]
}
