import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import { ApiError } from '../api/client'
import type { Limits, Provider } from '../api/types'
import { readingOf } from './cards'
import { ModelsPage } from './ModelsPage'

// Slice 87: Claude Code's reading says where it came from, its card reads it now in one short turn, and its
// window says how to keep it fresh from the user's own Claude Code sessions.

const claude: Provider = {
  id: 'cc',
  name: 'Claude Code',
  kind: 'claude_cli',
  base_url: null,
  default_model: null,
  executable: null,
  mode: null,
  options: null,
  for_agents: false,
  note: null,
  models: [],
  only_listed: false,
  max_running: null,
  plan: false,
  step_down_at: null,
  day_limit: null,
  month_limit: null,
  has_key: false,
  position: 0,
  created_at: 't',
  updated_at: 't',
}
const handlers = () => ({
  onCreate: vi.fn().mockResolvedValue(undefined),
  onSave: vi.fn().mockResolvedValue(undefined),
  onDelete: vi.fn().mockResolvedValue(undefined),
  onTest: vi.fn().mockResolvedValue({ ok: true, model_id: 'x', tools_supported: true, error: null }),
})
const week = (used: number, source: string | null): Limits => ({
  unknown: null,
  read_at: new Date(Date.now() - 2 * 3600_000).toISOString(),
  failed: null,
  source,
  plan: null,
  windows: [{ name: 'seven_day', minutes: 10080, used_percent: used, resets_at: null, stale: false }],
  credits: null,
})
const SETUP = { command: '"C:/KOLONİ/.venv/Scripts/python.exe" "C:/KOLONİ/scripts/koloni_statusline.py" --koloni http://127.0.0.1:8790 --key k3y', script: 'C:\\KOLONİ\\scripts\\koloni_statusline.py' }

afterEach(() => vi.unstubAllGlobals())

test('a reading says where Claude Code said it after how long ago it was read', () => {
  expect(readingOf(claude, { limits: week(93, 'your Claude Code session') })).toMatchObject({ value: '7%', more: 'read 2 h ago, from your Claude Code session' })
  expect(readingOf(claude, { limits: week(93, 'a short run to read it') })).toMatchObject({ more: 'read 2 h ago, in a short run to read it' })
  expect(readingOf(claude, { limits: week(93, 'its last run') })).toMatchObject({ more: 'read 2 h ago, in its last run here' })
})

test('Claude Code’s card reads its plan now in one short turn, says so while it reads, and a failure keeps the last reading', async () => {
  let answer: (told: Limits) => void = () => {}
  let fails = false
  const onLimits = vi.fn((_id: string, afresh: boolean) => {
    if (!afresh) return Promise.resolve(week(83, 'its last run'))
    if (fails) return Promise.reject(new ApiError(500, 'Claude Code ended without saying its limits'))
    return new Promise<Limits>(resolve => (answer = resolve))
  })
  render(<ModelsPage providers={[claude]} {...handlers()} onLimits={onLimits} />)
  const card = await screen.findByRole('button', { name: /^Claude Code.*17%/ })
  const read = screen.getByRole('button', { name: 'Read Claude Code’s plan now' })
  // What it costs is said beside it, in words.
  expect(read).toHaveAccessibleDescription('one short request')
  expect(screen.getByText('one short request')).toBeVisible()
  await userEvent.click(read)
  expect(read).toBeDisabled()
  expect(read).toHaveTextContent('Reading…')
  expect(onLimits).toHaveBeenLastCalledWith('cc', true)
  answer(week(93, 'a short run to read it'))
  // How old it is beside it: an old reading does not pass for now's.
  await waitFor(() => expect(card).toHaveTextContent('7% left this week · read 2 h ago'))
  // Where it was read is behind the card's ⓘ.
  expect(card.parentElement!.querySelector('.hint')).toHaveTextContent('read 2 h ago, in a short run to read it')
  expect(read).toHaveTextContent('Read now')
  fails = true
  await userEvent.click(read)
  await waitFor(() => expect(card).toHaveTextContent(/7%\s*left this week · read 2 h ago\s*not read now: Claude Code ended without saying its limits/))
})

test('the Claude Code window says how its own sessions keep the reading fresh: the setting to add, to copy; KOLONİ writes nothing', async () => {
  const onClaudeSetup = vi.fn().mockResolvedValue(SETUP)
  render(<ModelsPage providers={[claude]} picked="cc" {...handlers()} onClaudeSetup={onClaudeSetup} />)
  await userEvent.click(screen.getByRole('tab', { name: 'Limits' }))
  const part = screen.getByRole('region', { name: 'Keep it fresh from your Claude Code sessions' })
  const line = `"statusLine": ${JSON.stringify({ type: 'command', command: SETUP.command })}`
  await waitFor(() => expect(part).toHaveTextContent(line))
  expect(part).toHaveTextContent('Add this to your Claude Code settings yourself: open your Claude Code settings file, %USERPROFILE%\\.claude\\settings.json')
  expect(part).toHaveTextContent('Claude Code picks it up on its next refresh')
  expect(part).toHaveTextContent('Already have a status line? End the command with … --then \\"your command\\""}; on Windows it runs under cmd.')
  const copied = vi.fn().mockResolvedValue(undefined)
  vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText: copied } })
  await userEvent.click(within(part).getByRole('button', { name: 'Copy the status line setting' }))
  expect(copied).toHaveBeenCalledWith(line)
  expect(await within(part).findByRole('button', { name: 'Copy the status line setting' })).toHaveTextContent('Copied')
})

test('a Claude Code that is not installed has no Read now: nothing is there to run its turn (B-61)', async () => {
  const onAvailability = vi.fn().mockResolvedValue({ installed: false, signed_in: null, models: [] })
  render(<ModelsPage providers={[claude]} {...handlers()} onAvailability={onAvailability} onLimits={vi.fn().mockResolvedValue(week(83, null))} />)
  expect(await screen.findByRole('button', { name: /^Claude Code.*not installed/ })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Read Claude Code’s plan now' })).toBeNull()
  // Its one action is then a Check, which runs no model.
  await userEvent.click(screen.getByRole('button', { name: 'Check Claude Code' }))
  expect(onAvailability).toHaveBeenLastCalledWith('cc')
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
})

test('what a plan has left is said once: on its card, not again in its window’s head', async () => {
  render(<ModelsPage providers={[claude]} {...handlers()} onLimits={vi.fn().mockResolvedValue(week(83, null))} />)
  await userEvent.click(await screen.findByRole('button', { name: /^Claude Code.*17%/ }))
  expect(screen.getByRole('dialog', { name: 'Claude Code' })).toBeInTheDocument()
  expect(screen.getAllByText(/17%/)).toHaveLength(1)
})

test('a Claude Code of another command is not kept fresh by the user’s sessions: no such part', async () => {
  const onClaudeSetup = vi.fn().mockResolvedValue(SETUP)
  render(<ModelsPage providers={[{ ...claude, executable: 'C:/tools/claude-work.cmd' }]} picked="cc" {...handlers()} onClaudeSetup={onClaudeSetup} />)
  await userEvent.click(screen.getByRole('tab', { name: 'Limits' }))
  expect(screen.queryByRole('region', { name: 'Keep it fresh from your Claude Code sessions' })).toBeNull()
  expect(onClaudeSetup).not.toHaveBeenCalled()
})
