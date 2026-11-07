import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import { ApiError } from '../api/client'
import type { AllowedCommand, Conversation, Trigger, TriggerLogEntry } from '../api/types'
import { conversation } from '../test-fixtures'
import { moreOf, newTrigger, trigger, triggerRun } from './fixtures'
import { TriggersPage } from './TriggersPage'
import { TriggersStatus } from './TriggersStatus'

const second: Conversation = { ...conversation, id: 'c2', title: 'Nightly work' }
const rule = (id: string, prefix: string, conversationId = 'c'): AllowedCommand => ({ id, prefix, conversation_id: conversationId, danger: '', created_at: 't' })

function handlers(rules: Record<string, AllowedCommand[]> = {}) {
  return {
    onCreate: vi.fn(async (values: object) => ({ ...trigger(values as Partial<Trigger>), id: 'new', key: null as string | null })),
    onSave: vi.fn().mockResolvedValue(undefined),
    onDelete: vi.fn().mockResolvedValue(undefined),
    onRun: vi.fn().mockResolvedValue('run-9'),
    onShowTurn: vi.fn(),
    onDraftTaken: vi.fn(),
    onRules: vi.fn(async (conversationId: string) => rules[conversationId] ?? []),
    onAddRule: vi.fn(async (conversationId: string, prefix: string) => rule(`new-${prefix}`, prefix, conversationId)),
  }
}

function page(triggers: Trigger[] | null, h = handlers(), over: object = {}) {
  render(<TriggersPage triggers={triggers} conversations={[conversation, second]} draft={null} origin="http://127.0.0.1:8790" {...h} {...over} />)
  return h
}
const form = () => screen.getByRole('form', { name: /trigger/i })
const card = (name: string) => screen.getByRole('article', { name })

test('each trigger is a card: when it starts, where, what it may do, its budget, and its last run', () => {
  page([
    trigger({ runs: [triggerRun('1', 'completed')] }),
    trigger({
      id: 't2', name: 'On push', kind: 'webhook', config: {}, conversation_id: 'c2',
      permissions: { write: true, commands: ['r1'], agents: 1 }, command_lines: ['python -m pytest -q'],
    } as Partial<Trigger>),
  ])
  const first = card('Nightly look')
  expect(first).toHaveTextContent('every 60 minutes')
  expect(first).toHaveTextContent('in Fix greeting')
  expect(first).toHaveTextContent('reads only')
  expect(first).toHaveTextContent('15 model steps and 10 minutes a run · 24 runs a day')
  expect(first).toHaveTextContent(/last run .+ · completed/)
  const other = card('On push')
  expect(other).toHaveTextContent('on a request from outside')
  expect(other).toHaveTextContent('in Nightly work')
  expect(other).toHaveTextContent('may change files · may run: python -m pytest -q · may open 1 agent')
  // it never came due: nothing is said to have run
  expect(other).toHaveTextContent('has not run yet')
  expect(within(other).getByRole('switch', { name: 'On push is on' })).toBeChecked()
})

test('a trigger KOLONİ switched off says why, where it cannot be missed; one you switched off says only that it is off', () => {
  page([
    trigger({ enabled: false, failures: 3, off_because: 'budget: 15 model steps used' }),
    trigger({ id: 't2', name: 'Paused by me', enabled: false }),
  ])
  expect(within(card('Nightly look')).getByRole('alert')).toHaveTextContent('switched off after 3 failures: budget: 15 model steps used')
  expect(within(card('Nightly look')).getByRole('switch')).not.toBeChecked()
  expect(within(card('Paused by me')).queryByRole('alert')).not.toBeInTheDocument()
  expect(card('Paused by me')).toHaveTextContent('off')
})

test('93-B2: a schedule slowed down for finding nothing says so and when it runs next; "Back to every 60 minutes" sends only the touch', async () => {
  const h = page([trigger({ slowed: 4, next_at: '2026-10-05T13:00:00Z' }), trigger({ id: 't2', name: 'Asleep', slowed: 3, enabled: false })])
  const slowed = within(card('Nightly look')).getByRole('status')
  expect(slowed).toHaveTextContent(/^Slowed down: the last 4 runs found nothing — next at .*\d\d:\d\d/)
  await userEvent.click(within(slowed).getByRole('button', { name: 'Back to every 60 minutes' }))
  expect(h.onSave).toHaveBeenCalledWith('t1', {})
  // (switched off it waits for nothing: switched on, it is on its own times anyway)
  expect(card('Asleep')).not.toHaveTextContent('Slowed down')
})

test('the switch turns a trigger on and off; "Run now" starts its turn and says a refusal beside it', async () => {
  const h = page([trigger()])
  await userEvent.click(screen.getByRole('switch', { name: 'Nightly look is on' }))
  expect(h.onSave).toHaveBeenCalledWith('t1', { enabled: false })
  await userEvent.click(screen.getByRole('button', { name: 'Run now' }))
  expect(h.onRun).toHaveBeenCalledWith('t1')
  // the turn it started is the one to look at
  await waitFor(() => expect(h.onShowTurn).toHaveBeenCalledWith('c', 'run-9'))
  h.onRun.mockRejectedValueOnce(new ApiError(409, 'the conversation is at work: nothing was started'))
  await userEvent.click(screen.getByRole('button', { name: 'Run now' }))
  expect(await within(card('Nightly look')).findByRole('alert')).toHaveTextContent('the conversation is at work: nothing was started')
})

test('the last times it came due open under the card: when, how each ended, late or not; one that started a turn leads to it', async () => {
  const h = page([
    trigger({
      runs: [
        triggerRun('4', null),
        triggerRun('3', 'skipped_busy'),
        triggerRun('2', 'budget', { late: true }),
        triggerRun('1', 'completed'),
      ],
    }),
  ])
  expect(screen.queryByRole('list', { name: 'Recent runs of Nightly look' })).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Recent runs (4)' }))
  const runs = within(screen.getByRole('list', { name: 'Recent runs of Nightly look' })).getAllByRole('listitem')
  expect(runs.map(r => r.textContent!.replace(/^.*?· /, ''))).toEqual(['running', 'skipped: conversation was busy', 'stopped: over its budget · late', 'completed'])
  // a time that started no turn has nothing to lead to
  expect(within(runs[1]).queryByRole('button')).not.toBeInTheDocument()
  await userEvent.click(within(runs[3]).getByRole('button'))
  expect(h.onShowTurn).toHaveBeenCalledWith('c', 'run-1')
})

test('a new trigger starts with nothing allowed, each permission said in a sentence, the usual budget with its bounds, and catch-up ticked', async () => {
  const h = page([])
  expect(screen.getByText(/No trigger yet/)).toBeInTheDocument()
  await newTrigger()
  const f = within(form())
  expect(f.getByLabelText('May change files')).not.toBeChecked()
  expect(f.getByText('Its work writes and edits files in the project without asking you.')).toBeInTheDocument()
  // what a sub-agent's allowed command does without it is said too
  expect(f.getByText('Without it, nothing a sub-agent or its commands write in its own working copy reaches the project.')).toBeInTheDocument()
  expect(f.getByText('With nobody watching, a ticked command runs exactly as written - no extra arguments.')).toBeInTheDocument()
  expect(f.getByLabelText('May open sub-agents')).toHaveValue(0)
  // the rest of its note behind ⓘ, and the field described by both
  expect(f.getByLabelText('May open sub-agents')).toHaveAccessibleDescription('How many sub-agents a run may open in all: 0 to 4. Each may do only what this trigger allows.')
  expect(f.getByLabelText('Model steps a run')).toHaveValue(15)
  expect(f.getByLabelText('Minutes a run')).toHaveValue(10)
  expect(f.getByLabelText('Runs a day')).toHaveValue(24)
  expect(f.getByText('1 to 200, all its agents together.')).toBeInTheDocument()
  expect(f.getByText('1 to 240.')).toBeInTheDocument()
  expect(f.getByText('1 to 500.')).toBeInTheDocument()
  expect(f.getByLabelText('Run once when KOLONİ starts if a run was missed')).toBeChecked()

  // nothing is sent until it can be saved: what is missing is said beside its field
  await userEvent.click(f.getByRole('button', { name: 'Add trigger' }))
  expect(h.onCreate).not.toHaveBeenCalled()
  expect(f.getByLabelText('Name')).toHaveAccessibleDescription('Give it a name.')
  expect(f.getByLabelText('Message')).toHaveAccessibleDescription('Write the message it sends.')
  await userEvent.clear(f.getByLabelText('Every so many minutes'))
  await userEvent.type(f.getByLabelText('Every so many minutes'), '3')
  await userEvent.click(f.getByRole('button', { name: 'Add trigger' }))
  expect(f.getByLabelText('Every so many minutes')).toHaveAccessibleDescription('At least 5 minutes, at most 10080 (a week).')

  await userEvent.type(f.getByLabelText('Name'), 'Hourly look')
  await userEvent.type(f.getByLabelText('Message'), 'Look the project over.')
  await userEvent.clear(f.getByLabelText('Every so many minutes'))
  await userEvent.type(f.getByLabelText('Every so many minutes'), '30')
  await userEvent.click(f.getByRole('button', { name: 'Add trigger' }))
  expect(h.onCreate).toHaveBeenCalledWith({
    name: 'Hourly look', kind: 'schedule', conversation_id: 'c', message: 'Look the project over.', config: { every_minutes: 30 },
    permissions: { write: false, commands: [], agents: 0 }, budget: { steps: 15, minutes: 10, per_day: 24 }, catch_up: true, enabled: true,
    ends: null, run_unchanged: false, proposal_id: null,
  })
  await waitFor(() => expect(screen.queryByRole('form')).not.toBeInTheDocument())
})

test('each kind has its own fields: a time of day, a path pattern, or none', async () => {
  const h = page([])
  await newTrigger()
  const f = within(form())
  await userEvent.type(f.getByLabelText('Name'), 'T')
  await userEvent.type(f.getByLabelText('Message'), 'm')
  await userEvent.click(f.getByLabelText('At a time of day'))
  await userEvent.clear(f.getByLabelText('Time'))
  await userEvent.type(f.getByLabelText('Time'), '07:30')
  await userEvent.selectOptions(f.getByLabelText('Days'), 'weekdays')
  await userEvent.selectOptions(f.getByLabelText('Starts'), 'files')
  expect(f.queryByLabelText('Time')).not.toBeInTheDocument()
  await userEvent.click(f.getByRole('button', { name: 'Add trigger' }))
  expect(f.getByLabelText('Path pattern')).toHaveAccessibleDescription(/Give a pattern/)
  await userEvent.type(f.getByLabelText('Path pattern'), 'src/**/*.py')
  await userEvent.click(f.getByRole('button', { name: 'Add trigger' }))
  expect(h.onCreate.mock.calls[0][0]).toMatchObject({ kind: 'files', config: { glob: 'src/**/*.py' } })
})

test('what the server refuses is said beside the field it is about, and the form stays open', async () => {
  const h = handlers()
  h.onCreate.mockRejectedValueOnce(new ApiError(422, 'more than 5000 files match this pattern; name fewer'))
  page([], h)
  await newTrigger()
  const f = within(form())
  await userEvent.type(f.getByLabelText('Name'), 'T')
  await userEvent.type(f.getByLabelText('Message'), 'm')
  await userEvent.selectOptions(f.getByLabelText('Starts'), 'files')
  await userEvent.type(f.getByLabelText('Path pattern'), '**/*')
  await userEvent.click(f.getByRole('button', { name: 'Add trigger' }))
  await waitFor(() => expect(f.getByLabelText('Path pattern')).toHaveAccessibleDescription(/^more than 5000 files match this pattern; name fewer/))
  // a refusal that names no field is said at the foot of the form
  h.onCreate.mockRejectedValueOnce(new ApiError(403, 'origin not allowed'))
  await userEvent.click(f.getByRole('button', { name: 'Add trigger' }))
  expect(await f.findByRole('alert')).toHaveTextContent('origin not allowed')
})

test('a webhook’s key and address are shown once, with a way to copy them and what they open', async () => {
  const h = handlers()
  h.onCreate.mockImplementationOnce(async (values: object) => ({ ...trigger({ ...(values as Partial<Trigger>), id: 't9' }), key: 'k'.repeat(43) }))
  const copy = vi.fn().mockResolvedValue(undefined)
  vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText: copy } })
  page([], h)
  await newTrigger()
  const f = within(form())
  await userEvent.type(f.getByLabelText('Name'), 'On push')
  await userEvent.type(f.getByLabelText('Message'), 'Look at what came in.')
  await userEvent.selectOptions(f.getByLabelText('Starts'), 'webhook')
  await userEvent.click(f.getByRole('button', { name: 'Add trigger' }))

  const shown = await screen.findByRole('region', { name: 'The address of On push' })
  const address = `http://127.0.0.1:8790/api/hooks/${'k'.repeat(43)}`
  expect(within(shown).getByText(address)).toBeInTheDocument()
  expect(shown).toHaveTextContent('This is shown once: it cannot be read back later.')
  expect(shown).toHaveTextContent('Anyone on this machine who has this address can run the trigger.')
  await userEvent.click(within(shown).getByRole('button', { name: 'Copy the address' }))
  expect(copy).toHaveBeenCalledWith(address)
  // put away, it is gone for good: nothing on the page still holds it
  await userEvent.click(within(shown).getByRole('button', { name: 'I have copied it' }))
  expect(screen.queryByText(address)).not.toBeInTheDocument()
  expect(document.body.innerHTML).not.toContain('k'.repeat(43))
  vi.unstubAllGlobals()
})

test('a webhook’s key is made anew only after a second word, and the new address is shown once', async () => {
  const onNewKey = vi.fn(async () => ({ ...trigger({ id: 'w', name: 'On push', kind: 'webhook' }), key: 'n'.repeat(43) }))
  page([trigger({ id: 'w', name: 'On push', kind: 'webhook' }), trigger({ id: 's', name: 'Nightly' })], handlers(), { onNewKey })
  // its row says where its address begins, never the key
  expect(card('On push')).toHaveTextContent('/api/hooks/… · the key is shown once · New key in ⋯')
  await userEvent.click(screen.getByRole('button', { name: 'More for Nightly' }))
  expect(screen.queryByRole('menuitem', { name: 'New key' })).not.toBeInTheDocument()
  await userEvent.keyboard('{Escape}')
  await moreOf('On push', 'New key')
  expect(card('On push')).toHaveTextContent('The old address stops at once.')
  await userEvent.click(within(card('On push')).getByRole('button', { name: 'Cancel' }))
  expect(onNewKey).not.toHaveBeenCalled()
  await moreOf('On push', 'New key')
  await userEvent.click(within(card('On push')).getByRole('button', { name: 'Make a new key' }))
  expect(onNewKey).toHaveBeenCalledWith('w')
  const shown = await screen.findByRole('region', { name: 'The address of On push' })
  expect(within(shown).getByText(`http://127.0.0.1:8790/api/hooks/${'n'.repeat(43)}`)).toBeInTheDocument()
})

test('a trigger of another kind is made without a word about a key', async () => {
  page([])
  await newTrigger()
  const f = within(form())
  await userEvent.type(f.getByLabelText('Name'), 'T')
  await userEvent.type(f.getByLabelText('Message'), 'm')
  await userEvent.click(f.getByRole('button', { name: 'Add trigger' }))
  await waitFor(() => expect(screen.queryByRole('form')).not.toBeInTheDocument())
  expect(screen.queryByText(/shown once/)).not.toBeInTheDocument()
})

const OWN_TOPIC =
  'A trigger’s messages have a topic of their own and do not see what you say in your topics. To tell it something, change its message, or write in its topic from one of its messages.'

test('the page says, of “Keep an agent on this project” and under the form’s conversation, that a trigger’s turns do not see the user’s own topics', async () => {
  page([])
  // what the ready-made trigger is, said behind the page's ⓘ - before the form is open
  const about = screen.getByRole('button', { name: 'About this' })
  expect(about).toHaveAccessibleDescription(/“Keep an agent on this project” fills in a trigger that looks the project over every hour/)
  expect(about).toHaveAccessibleDescription(new RegExp(OWN_TOPIC))
  await newTrigger()
  // in the form: with the conversation field, whatever else is said of it
  const field = within(form()).getByLabelText('Conversation').closest('.field') as HTMLElement
  expect(field).toHaveTextContent('Its messages are added to this conversation.')
  expect(within(field).getByText(OWN_TOPIC)).toBeInTheDocument()
})

test('“Keep an agent on this project” opens the form filled in, reading only, and saves nothing by itself', async () => {
  const h = page([])
  await newTrigger(/^Keep an agent on this project/)
  const f = within(form())
  expect(f.getByLabelText('Name')).toHaveValue('Keep an agent on this project')
  expect(f.getByLabelText('Every so many minutes')).toHaveValue(60)
  expect(f.getByLabelText('Message')).toHaveValue(
    'Look the project over: do the tests still pass, is there anything new that looks wrong? Write what you find on the notebook and remember what is worth keeping. Change nothing.',
  )
  expect(f.getByLabelText('May change files')).not.toBeChecked()
  expect(h.onCreate).not.toHaveBeenCalled()
})

test('"New trigger" lists the ready-made triggers and a blank one; one fills the form, reading only, and is made only when it is added', async () => {
  const h = page([])
  await userEvent.click(screen.getByRole('button', { name: 'New trigger' }))
  const menu = screen.getByRole('menu', { name: 'New trigger' })
  expect(within(menu).getAllByRole('menuitem').map(item => item.querySelector('strong')!.textContent)).toEqual([
    'Keep an agent on this project',
    'Every morning: summarise the work since the last working day',
    'When source files change: run the tests',
    'Every Friday at 17:00: check the dependencies',
    'Start from blank',
  ])
  // what starts it, how often at most, and when it never does
  expect(within(menu).getByRole('menuitem', { name: /^When source files change/ })).toHaveTextContent('Each change under src/ runs it (at most 6 a day); with no src/ folder it never starts')
  // from the keyboard: the arrows go down the list, Enter picks
  await userEvent.keyboard('{ArrowDown}{ArrowDown}{ArrowDown}')
  expect(within(menu).getByRole('menuitem', { name: /^When source files change/ })).toHaveFocus()
  await userEvent.keyboard('{Enter}')
  expect(screen.queryByRole('menu')).toBeNull()
  const f = within(form())
  expect(f.getByLabelText('Name')).toHaveValue('When source files change: run the tests')
  expect(f.getByLabelText('Starts')).toHaveValue('files')
  expect(f.getByLabelText('Path pattern')).toHaveValue('src/**/*')
  expect(f.getByLabelText('May change files')).not.toBeChecked()
  expect(f.getByLabelText('May open sub-agents')).toHaveValue(0)
  expect(f.getByLabelText('Model steps a run')).toHaveValue(15)
  expect(f.getByLabelText('Runs a day')).toHaveValue(6)
  expect(h.onCreate).not.toHaveBeenCalled()
  await userEvent.click(f.getByRole('button', { name: 'Add trigger' }))
  expect(h.onCreate).toHaveBeenCalledWith(expect.objectContaining({ kind: 'files', config: { glob: 'src/**/*' }, permissions: expect.objectContaining({ write: false, agents: 0 }) }))
})

test('the Friday card is Fridays at 17:00, the first on the next Friday; the days are chosen in seven boxes (the server puts them in week order)', async () => {
  const h = page([])
  await userEvent.click(screen.getByRole('button', { name: 'New trigger' }))
  const friday = screen.getByRole('menuitem', { name: /^Every Friday at 17:00: check the dependencies/ })
  expect(friday).toHaveTextContent('Fridays at 17:00, the first on the next Friday.')
  await userEvent.click(friday)
  const f = within(form())
  expect(f.getByLabelText('Time')).toHaveValue('17:00')
  expect(f.getByLabelText('Days')).toHaveValue('chosen')
  const week = f.getByRole('group', { name: 'On these days' })
  expect(within(week).getAllByRole('checkbox')).toHaveLength(7)
  expect(within(week).getByRole('checkbox', { name: 'Friday' })).toBeChecked()
  await userEvent.click(within(week).getByRole('checkbox', { name: 'Friday' }))
  await userEvent.click(f.getByRole('button', { name: 'Add trigger' }))
  // none ticked: said beside the days, and nothing made
  expect(f.getByLabelText('Days')).toHaveAccessibleDescription('Tick at least one day.')
  expect(h.onCreate).not.toHaveBeenCalled()
  await userEvent.click(within(week).getByRole('checkbox', { name: 'Thursday' }))
  await userEvent.click(within(week).getByRole('checkbox', { name: 'Monday' }))
  await userEvent.click(f.getByRole('button', { name: 'Add trigger' }))
  expect(h.onCreate.mock.calls[0][0]).toMatchObject({ kind: 'schedule', config: { at: '17:00', days: ['thu', 'mon'] } })
})

test('a trigger on chosen days says them in words and opens to edit with them ticked', async () => {
  page([trigger({ config: { at: '09:00', days: ['mon', 'thu'] } })])
  expect(card('Nightly look')).toHaveTextContent('Mondays and Thursdays at 09:00')
  await moreOf('Nightly look', 'Edit')
  const week = within(form()).getByRole('group', { name: 'On these days' })
  expect(within(week).getAllByRole('checkbox', { checked: true }).map(box => box.getAttribute('aria-label'))).toEqual(['Monday', 'Thursday'])
})

test('the morning one is weekdays at 09:00; with triggers there, "New trigger" is at the top of the page', async () => {
  page([trigger({})])
  expect(screen.queryByText(/No trigger yet/)).toBeNull()
  await newTrigger(/^Every morning/)
  const f = within(form())
  expect(f.getByLabelText('Time')).toHaveValue('09:00')
  expect(f.getByLabelText('Days')).toHaveValue('weekdays')
})

test('editing a trigger starts from what it has; its kind cannot be changed', async () => {
  const h = page([trigger({ permissions: { write: true, commands: [], agents: 2 } })])
  await moreOf('Nightly look', 'Edit')
  const f = within(form())
  expect(f.getByLabelText('Starts')).toBeDisabled()
  expect(f.getByLabelText('May change files')).toBeChecked()
  expect(f.getByLabelText('May open sub-agents')).toHaveValue(2)
  await userEvent.click(f.getByLabelText('May change files'))
  await userEvent.click(f.getByRole('button', { name: 'Save' }))
  expect(h.onSave).toHaveBeenCalledWith('t1', expect.objectContaining({ permissions: { write: false, commands: [], agents: 2 } }))
  expect(h.onSave.mock.calls[0][1]).not.toHaveProperty('kind')
})

// --- the commands a trigger may run: the ticked rules of its conversation's allow list ---------

const rules = { c: [rule('r1', 'python -m pytest -q'), rule('r2', 'make lint')], c2: [rule('r9', 'npm test', 'c2')] }

test('the commands a trigger may run are ticked from its conversation’s allow list, and sent by their ids', async () => {
  const h = page([], handlers(rules))
  await newTrigger()
  const f = within(form())
  const list = await f.findByRole('group', { name: 'May run these commands' })
  expect(h.onRules).toHaveBeenCalledWith('c')
  const boxes = within(list).getAllByRole('checkbox')
  expect(boxes.map(b => b.getAttribute('aria-label') ?? b.closest('label')?.textContent)).toEqual(['python -m pytest -q', 'make lint'])
  expect(boxes.every(b => !(b as HTMLInputElement).checked)).toBe(true)
  await userEvent.click(within(list).getByLabelText('make lint'))
  await userEvent.type(f.getByLabelText('Name'), 'T')
  await userEvent.type(f.getByLabelText('Message'), 'm')
  await userEvent.click(f.getByRole('button', { name: 'Add trigger' }))
  expect(h.onCreate.mock.calls[0][0]).toMatchObject({ permissions: { write: false, commands: ['r2'], agents: 0 } })
})

test('another conversation chosen: its own list is shown and the ticks are cleared', async () => {
  const h = page([], handlers(rules))
  await newTrigger()
  const f = within(form())
  await userEvent.click(await f.findByLabelText('make lint'))
  await userEvent.selectOptions(f.getByLabelText('Conversation'), 'c2')
  expect(await f.findByLabelText('npm test')).not.toBeChecked()
  expect(f.queryByLabelText('make lint')).not.toBeInTheDocument()
  await userEvent.type(f.getByLabelText('Name'), 'T')
  await userEvent.type(f.getByLabelText('Message'), 'm')
  await userEvent.click(f.getByRole('button', { name: 'Add trigger' }))
  expect(h.onCreate.mock.calls[0][0]).toMatchObject({ conversation_id: 'c2', permissions: { commands: [] } })
})

test('a conversation with no allowed commands says so and offers only to add one; added, it is on the list, not ticked for you', async () => {
  const h = page([], handlers({}))
  await newTrigger()
  const f = within(form())
  expect(await f.findByText('This conversation has no allowed commands yet.')).toBeInTheDocument()
  expect(f.queryByRole('checkbox', { name: /pytest/ })).not.toBeInTheDocument()
  expect(f.getByText("This also lets this conversation's own messages run it without asking.")).toBeInTheDocument()
  await userEvent.type(f.getByLabelText("Add a command to this conversation's list"), '  python check.py ')
  await userEvent.click(f.getByRole('button', { name: 'Add to the list' }))
  expect(h.onAddRule).toHaveBeenCalledWith('c', 'python check.py')
  const added = await f.findByLabelText('python check.py')
  expect(added).not.toBeChecked()
  expect(f.getByLabelText("Add a command to this conversation's list")).toHaveValue('')
  // the trigger itself is not made, or changed, by it
  expect(h.onCreate).not.toHaveBeenCalled()
  // a refusal is said beside the field
  h.onAddRule.mockRejectedValueOnce(new ApiError(422, 'a command is one line'))
  await userEvent.type(f.getByLabelText("Add a command to this conversation's list"), 'x')
  await userEvent.click(f.getByRole('button', { name: 'Add to the list' }))
  expect(await f.findByText('a command is one line')).toBeInTheDocument()
})

test('editing: the rules it has ticked are ticked; one since taken off the list is simply not there', async () => {
  const kept = trigger({ permissions: { write: false, commands: ['r2'], agents: 0 }, command_lines: ['make lint'] } as Partial<Trigger>)
  const h = page([kept], handlers(rules))
  await moreOf('Nightly look', 'Edit')
  const f = within(form())
  expect(await f.findByLabelText('make lint')).toBeChecked()
  expect(f.getByLabelText('python -m pytest -q')).not.toBeChecked()
  await userEvent.click(f.getByLabelText('python -m pytest -q'))
  await userEvent.click(f.getByRole('button', { name: 'Save' }))
  expect(h.onSave.mock.calls[0][1]).toMatchObject({ permissions: { commands: ['r2', 'r1'] } })
})

// --- "Allow this in the trigger", from the chat ----------------------------------------------

test('a request allowed from the chat opens that trigger’s form with it filled in, says it is not saved, and saves nothing', async () => {
  const h = handlers(rules)
  page([trigger()], h, { draft: { triggerId: 't1', allow: { write: true } } })
  const f = within(form())
  expect(f.getByLabelText('Name')).toHaveValue('Nightly look')
  expect(f.getByLabelText('May change files')).toBeChecked()
  expect(f.getByRole('status')).toHaveTextContent('Not saved yet: “May change files” was switched on from the chat. Look it over and save.')
  expect(h.onDraftTaken).toHaveBeenCalled()
  expect(h.onSave).not.toHaveBeenCalled()
  await userEvent.click(f.getByRole('button', { name: 'Save' }))
  expect(h.onSave).toHaveBeenCalledWith('t1', expect.objectContaining({ permissions: { write: true, commands: [], agents: 0 } }))
})

test('a command allowed from the chat ticks its rule when the conversation’s list has that very line; otherwise it is put in the add field for you to add', async () => {
  const first = handlers(rules)
  const { unmount } = render(
    <TriggersPage triggers={[trigger()]} conversations={[conversation]} draft={{ triggerId: 't1', allow: { command: 'make lint' } }} origin="" {...first} />,
  )
  expect(await within(form()).findByLabelText('make lint')).toBeChecked()
  expect(within(form()).getByRole('status')).toHaveTextContent('“make lint” was ticked from the chat')
  expect(first.onAddRule).not.toHaveBeenCalled()
  unmount()

  const other = handlers(rules)
  render(<TriggersPage triggers={[trigger()]} conversations={[conversation]} draft={{ triggerId: 't1', allow: { command: 'python check.py' } }} origin="" {...other} />)
  const f = within(form())
  await f.findByLabelText('make lint')
  expect(f.getByLabelText("Add a command to this conversation's list")).toHaveValue('python check.py')
  expect(f.getByRole('status')).toHaveTextContent('“python check.py” is not on this conversation’s list yet')
  expect(other.onAddRule).not.toHaveBeenCalled()
  expect(other.onSave).not.toHaveBeenCalled()
})

test('one more sub-agent allowed from the chat raises the number by one', () => {
  page([trigger({ permissions: { write: false, commands: [], agents: 1 } })], handlers(), { draft: { triggerId: 't1', allow: { agents: 1 } } })
  expect(within(form()).getByLabelText('May open sub-agents')).toHaveValue(2)
})

test('a request for a trigger that is gone says so, and opens nothing', () => {
  const h = page([trigger()], handlers(), { draft: { triggerId: 'gone', allow: { write: true } } })
  expect(screen.getByRole('alert')).toHaveTextContent('That trigger is no longer there.')
  expect(screen.queryByRole('form')).not.toBeInTheDocument()
  expect(h.onDraftTaken).toHaveBeenCalled()
})

// --- the top bar -----------------------------------------------------------------------------

test('the top bar says how many triggers are on, and pauses them all; paused, it says so and offers to go on', async () => {
  const [onPause, onOpen] = [vi.fn().mockResolvedValue(undefined), vi.fn()]
  const all = [trigger(), trigger({ id: 't2' }), trigger({ id: 't3', enabled: false })]
  const { rerender } = render(<TriggersStatus triggers={all} paused={false} onPause={onPause} onOpen={onOpen} />)
  await userEvent.click(screen.getByRole('button', { name: '2 triggers on' }))
  expect(onOpen).toHaveBeenCalled()
  await userEvent.click(screen.getByRole('button', { name: 'Pause all' }))
  expect(onPause).toHaveBeenCalledWith(true)

  rerender(<TriggersStatus triggers={all} paused onPause={onPause} onOpen={onOpen} />)
  expect(screen.getByRole('button', { name: 'Triggers paused' })).toBeInTheDocument()
  expect(screen.queryByText(/triggers on/)).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Resume' }))
  expect(onPause).toHaveBeenLastCalledWith(false)

  rerender(<TriggersStatus triggers={[trigger()]} paused={false} onPause={onPause} onOpen={onOpen} />)
  expect(screen.getByRole('button', { name: '1 trigger on' })).toBeInTheDocument()
  // B-175: while Stop everything holds, none of them starts: the bar says held, not on
  rerender(<TriggersStatus triggers={[trigger()]} paused={false} held onPause={onPause} onOpen={onOpen} />)
  expect(screen.getByRole('button', { name: '1 trigger · held' })).toBeInTheDocument()
})

test('with no trigger, or before they are read, the top bar says nothing about them', () => {
  const { container, rerender } = render(<TriggersStatus triggers={null} paused={false} onPause={vi.fn()} onOpen={vi.fn()} />)
  expect(container).toBeEmptyDOMElement()
  rerender(<TriggersStatus triggers={[]} paused={false} onPause={vi.fn()} onOpen={vi.fn()} />)
  expect(container).toBeEmptyDOMElement()
  // triggers that are all off: none is on, and there is nothing to pause
  rerender(<TriggersStatus triggers={[trigger({ enabled: false })]} paused={false} onPause={vi.fn()} onOpen={vi.fn()} />)
  expect(screen.getByRole('button', { name: '0 triggers on' })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Pause all' })).not.toBeInTheDocument()
})

// --- what was made and changed (the record) ----------------------------------------------------

const entry = (id: string, what: TriggerLogEntry['what'], detail: string | null, over: Partial<TriggerLogEntry> = {}): TriggerLogEntry => ({
  id, project_id: 'p', trigger_id: 't1', name: 'Nightly look', at: '2026-10-08T09:00:00Z', what, detail, ...over,
})

test('a card lists what was done to its trigger, newest first: when, what, and how it stood afterwards', async () => {
  page([
    trigger({
      changes: [
        entry('3', 'switched off', 'after 3 failures in a row: model server unreachable'),
        entry('2', 'permissions changed', 'may write files; may run: python check.py'),
        entry('1', 'created', 'every 60 minutes; reads only; 15 model steps and 10 minutes a turn, 24 turns a day'),
      ],
    }),
  ])
  expect(screen.queryByRole('list', { name: 'Changes to Nightly look' })).not.toBeInTheDocument()
  await moreOf('Nightly look', 'Changes (3)')
  const rows = within(screen.getByRole('list', { name: 'Changes to Nightly look' })).getAllByRole('listitem')
  expect(rows.map(r => r.textContent!.replace(/^.*?· /, ''))).toEqual([
    'switched off: after 3 failures in a row: model server unreachable',
    'permissions changed: may write files; may run: python check.py',
    'created: every 60 minutes; reads only; 15 model steps and 10 minutes a turn, 24 turns a day',
  ])
  // within a card every row is this trigger's: its name is not said again
  expect(rows[0]).not.toHaveTextContent('Nightly look')
})

test('a trigger with nothing on record offers no list of changes; its ⋯ holds Edit and Delete', async () => {
  const h = page([trigger()])
  await userEvent.click(screen.getByRole('button', { name: 'More for Nightly look' }))
  expect(screen.getAllByRole('menuitem').map(item => item.textContent)).toEqual(['Edit', 'Delete'])
  await userEvent.click(screen.getByRole('menuitem', { name: 'Delete' }))
  expect(screen.queryByRole('menu')).toBeNull()
  // it cannot be undone: asked first, and Keep it keeps it
  const asked = screen.getByRole('alertdialog', { name: /^Delete Nightly look\? It cannot be undone/ })
  await userEvent.click(within(asked).getByRole('button', { name: 'Keep it' }))
  expect(h.onDelete).not.toHaveBeenCalled()
  await moreOf('Nightly look', 'Delete')
  await userEvent.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Delete' }))
  expect(h.onDelete).toHaveBeenCalledWith('t1')
})

test('a deleted trigger’s changes stay, folded at the bottom; a trigger still there keeps its own behind its ⋯', () => {
  page([trigger()], handlers(), {
    changes: [
      entry('9', 'deleted', null, { trigger_id: 'gone', name: 'Old watch' }),
      entry('8', 'created', null, { trigger_id: 'gone', name: 'Old watch' }),
      entry('7', 'renamed', 'it was "Look"'),
    ],
  })
  const fold = screen.getByText('Changes of deleted triggers (2)').closest('details')!
  expect(fold).not.toHaveAttribute('open')
  const rows = within(fold).getAllByRole('listitem', { hidden: true })
  expect(rows.map(r => r.textContent!.replace(/^.*?· /, ''))).toEqual(['Old watch · deleted', 'Old watch · created'])
})

test('with no deleted trigger on the project’s record there is no fold', () => {
  page([trigger()], handlers(), { changes: [entry('7', 'switched on', null)] })
  expect(screen.queryByText(/Changes of deleted triggers/)).not.toBeInTheDocument()
  page([], handlers(), { changes: null })
  expect(screen.queryByText(/Changes of deleted triggers/)).not.toBeInTheDocument()
})

test('a trigger on files says what holds two of them from starting each other for ever, and that a change waits for a busy conversation', async () => {
  page([])
  await newTrigger()
  const f = within(form())
  expect(f.getByLabelText('Conversation')).toHaveAccessibleDescription(/a run that falls due is skipped\. A trigger’s messages have a topic of their own/)
  await userEvent.selectOptions(f.getByLabelText('Starts'), 'files')
  expect(f.getByLabelText('Path pattern')).toHaveAccessibleDescription(
    /Two triggers that change each other’s files can keep starting each other; only “Runs a day” stops that\./,
  )
  expect(f.getByLabelText('Conversation')).toHaveAccessibleDescription(/a change to its files waits until the conversation is free/)
})

test('a command from the chat that is on no rule is added to the conversation’s list and ticked only by you, each in the form; nothing is saved until Save', async () => {
  const h = handlers(rules)
  page([trigger()], h, { draft: { triggerId: 't1', allow: { command: 'python check.py' } } })
  const f = within(form())
  await f.findByLabelText('make lint')
  // put in the add field, and no more: not on the list, not ticked, not saved
  expect(f.getByLabelText("Add a command to this conversation's list")).toHaveValue('python check.py')
  expect(f.queryByLabelText('python check.py')).not.toBeInTheDocument()
  expect(h.onAddRule).not.toHaveBeenCalled()
  // you add it to the list ...
  await userEvent.click(f.getByRole('button', { name: 'Add to the list' }))
  expect(h.onAddRule).toHaveBeenCalledWith('c', 'python check.py')
  const added = await f.findByLabelText('python check.py')
  expect(added).not.toBeChecked()
  expect(h.onSave).not.toHaveBeenCalled()
  // ... and you tick it; the trigger is changed when you save
  await userEvent.click(added)
  expect(h.onSave).not.toHaveBeenCalled()
  await userEvent.click(f.getByRole('button', { name: 'Save' }))
  expect(h.onSave).toHaveBeenCalledWith('t1', expect.objectContaining({ permissions: { write: false, commands: ['new-python check.py'], agents: 0 } }))
})

test('the page says in one line what it is for and that no agent makes a trigger; how triggers work is behind its one ⓘ', () => {
  page([])
  const line = screen.getByText(/^Work that starts by itself/)
  expect(line).toHaveTextContent(/^Work that starts by itself\. Only you make or change a trigger; no agent can\./)
  expect(line.closest('.hint')).toBeNull()
  expect(screen.queryByText('How this works')).not.toBeInTheDocument()
  expect(screen.getAllByRole('button', { name: 'About this' })).toHaveLength(1)
  expect(screen.getByRole('button', { name: 'About this' })).toHaveAccessibleDescription(/A trigger sends its message by the clock, when files change, or on a request from outside\./)
})

test('each row reads as a sentence: when → its message’s first sentence, the whole message in its title', () => {
  page([
    trigger({ message: 'Run the tests and say which fail. Change nothing.', config: { at: '09:00', days: 'weekdays' } }),
    trigger({ id: 't2', name: 'Docs', kind: 'files', config: { glob: 'docs/**' }, message: 'Is it still right?\nSay so.' }),
  ])
  const sentence = card('Nightly look').querySelector('.trigger-sentence')!
  expect(sentence).toHaveTextContent('weekdays at 09:00 → Run the tests and say which fail.')
  expect(sentence).toHaveAttribute('title', 'Run the tests and say which fail. Change nothing.')
  expect(card('Docs').querySelector('.trigger-sentence')).toHaveTextContent('when docs/** changes → Is it still right?')
})

test('an empty page offers "New trigger" where it says there is none, and only there', async () => {
  page([])
  const empty = screen.getByText(/No trigger yet/).closest('.trigger-empty') as HTMLElement
  expect(within(empty).getByRole('button', { name: 'New trigger' })).toBeInTheDocument()
  expect(screen.getAllByRole('button', { name: 'New trigger' })).toHaveLength(1)
  await userEvent.click(within(empty).getByRole('button', { name: 'New trigger' }))
  await userEvent.click(screen.getByRole('menuitem', { name: 'Start from blank' }))
  expect(form()).toBeInTheDocument()
})

test("a trigger's name is on its row, whole in its title", () => {
  const name = 'Look the whole project over every hour and say what changed since the last look'
  page([trigger({ name })])
  expect(within(card(name)).getByText(name)).toHaveAttribute('title', name)
})

test('the form opened takes the focus on its first field; Cancel gives it back to "New trigger"', async () => {
  page([])
  await newTrigger()
  expect(within(form()).getByLabelText('Name')).toHaveFocus()
  await userEvent.click(within(form()).getByRole('button', { name: 'Cancel' }))
  expect(screen.getByRole('button', { name: 'New trigger' })).toHaveFocus()
  // opened from a card, it goes back the same way
  cleanup()
  page([trigger({})])
  await moreOf('Nightly look', 'Edit')
  expect(within(form()).getByLabelText('Name')).toHaveFocus()
  await userEvent.click(within(form()).getByRole('button', { name: 'Cancel' }))
  expect(screen.getByRole('button', { name: 'New trigger' })).toHaveFocus()
})
