import { expect, test } from 'vitest'
import { trigger, triggerRun } from './fixtures'
import {
  PRESET,
  allowIn,
  commandLines,
  blank,
  budgetOf,
  fieldOf,
  fromTrigger,
  leaveOf,
  offLine,
  outcomeOf,
  toBody,
  toPatch,
  validate,
  whenOf,
  withConversation,
} from './triggerText'

test('a trigger says when it starts a turn, in words', () => {
  expect(whenOf(trigger({ config: { every_minutes: 60 } }))).toBe('every 60 minutes')
  expect(whenOf(trigger({ config: { every_minutes: 1 } }))).toBe('every 1 minute')
  expect(whenOf(trigger({ config: { at: '09:00', days: 'weekdays' } }))).toBe('weekdays at 09:00')
  expect(whenOf(trigger({ config: { at: '21:30', days: 'daily' } }))).toBe('every day at 21:30')
  expect(whenOf(trigger({ kind: 'files', config: { glob: 'src/**/*.py' } }))).toBe('when src/**/*.py changes')
  expect(whenOf(trigger({ kind: 'webhook', config: {} }))).toBe('on a request from outside')
})

test('what its turns may do without asking is summed up, and nothing allowed is "reads only"', () => {
  const leave = (permissions: object, lines?: string[]) => leaveOf(trigger({ permissions, ...(lines && { command_lines: lines }) } as never))
  expect(leave({ write: false, commands: [], agents: 0 })).toBe('reads only')
  expect(leave({ write: true, commands: [], agents: 0 })).toBe('may change files')
  // the commands are named by their lines, which the server reads off the conversation's list: never by a rule's id
  expect(leave({ write: false, commands: ['r1'], agents: 0 }, ['python -m pytest -q'])).toBe('may run: python -m pytest -q')
  expect(leave({ write: false, commands: [], agents: 1 })).toBe('may open 1 agent')
  expect(leave({ write: true, commands: ['r1', 'r2'], agents: 3 }, ['make test', 'make lint'])).toBe('may change files · may run: make test; make lint · may open 3 agents')
  // a ticked rule that was since taken off the conversation's list is in neither: nothing is claimed for it
  expect(leave({ write: false, commands: [], agents: 0 }, [])).toBe('reads only')
  expect(commandLines(trigger({ permissions: { write: false, commands: ['r1'], agents: 0 }, command_lines: ['make test'] } as never))).toEqual(['make test'])
  // what a trigger keeps are rules' ids: where no lines are said, an id is never shown as a command it may run
  expect(commandLines(trigger({ permissions: { write: false, commands: ['r1'], agents: 0 }, command_lines: undefined } as never))).toEqual([])
  expect(leave({ write: false, commands: ['r1'], agents: 0 })).toBe('reads only')
})

test('its budget is said as it is', () => {
  expect(budgetOf({ steps: 15, minutes: 10, per_day: 24 })).toBe('15 model steps and 10 minutes a run · 24 runs a day')
  expect(budgetOf({ steps: 1, minutes: 1, per_day: 1 })).toBe('1 model step and 1 minute a run · 1 run a day')
})

test('how a time it came due ended: an outcome nobody has put down yet is "running"', () => {
  const said = (outcome: Parameters<typeof triggerRun>[1], late = false) => outcomeOf(triggerRun('1', outcome, { late }))
  expect(said(null)).toBe('running')
  expect(said('completed')).toBe('completed')
  expect(said('failed')).toBe('failed')
  expect(said('budget')).toBe('stopped: over its budget')
  expect(said('stopped')).toBe('stopped')
  expect(said('skipped_busy')).toBe('skipped: conversation was busy')
  expect(said('skipped_budget')).toBe("skipped: day's budget used")
  expect(said('completed', true)).toBe('completed · late')
})

test('why KOLONİ switched a trigger off is said; one the user switched off, or one that is on, says nothing', () => {
  expect(offLine(trigger({ enabled: false, failures: 3, off_because: 'budget: 15 model steps used' }))).toBe(
    'switched off after 3 failures: budget: 15 model steps used',
  )
  expect(offLine(trigger({ enabled: false, failures: 0, off_because: 'its conversation is gone' }))).toBe('switched off: its conversation is gone')
  expect(offLine(trigger({ enabled: false, off_because: null }))).toBeNull()
  expect(offLine(trigger({ enabled: true, off_because: null }))).toBeNull()
})

// --- the form ----------------------------------------------------------------------------------

test('a new trigger allows nothing, has the usual budget and makes up for a missed run', () => {
  const values = blank('c1')
  expect(values).toMatchObject({ kind: 'schedule', every: '60', write: false, commands: [], agents: '0', steps: '15', minutes: '10', perDay: '24', catchUp: true })
  expect(toBody({ ...values, name: ' Nightly ', message: ' Look. ' })).toEqual({
    name: 'Nightly',
    kind: 'schedule',
    conversation_id: 'c1',
    message: 'Look.',
    config: { every_minutes: 60 },
    permissions: { write: false, commands: [], agents: 0 },
    budget: { steps: 15, minutes: 10, per_day: 24 },
    catch_up: true,
    // No end, and skipped when nothing changed (K-tetik-bitis, K-tetik-degismedi); made by you, from no agent's card.
    ends: null,
    run_unchanged: false,
    enabled: true,
    proposal_id: null,
  })
})

test('each kind sends its own settings and nothing else', () => {
  const base = { ...blank('c1'), name: 'T', message: 'm' }
  expect(toBody({ ...base, schedule: 'at', at: '09:00', days: 'weekdays' }).config).toEqual({ at: '09:00', days: 'weekdays' })
  expect(toBody({ ...base, kind: 'files', glob: ' src/**/*.py ' }).config).toEqual({ glob: 'src/**/*.py' })
  expect(toBody({ ...base, kind: 'webhook' }).config).toEqual({})
  // the commands it may run are the ticked rules of the conversation's list, by their ids
  expect(toBody({ ...base, commands: ['r2', 'r1'] }).permissions.commands).toEqual(['r2', 'r1'])
})

test('rules belong to one conversation: another conversation chosen, the ticks are cleared', () => {
  const values = { ...blank('c1'), commands: ['r1', 'r2'], write: true }
  expect(withConversation(values, 'c2')).toMatchObject({ conversationId: 'c2', commands: [], write: true })
  // the same one chosen again changes nothing
  expect(withConversation(values, 'c1')).toBe(values)
})

test('a trigger is edited from what it has; its kind is not sent again', () => {
  const kept = trigger({
    name: 'Tests', kind: 'schedule', config: { at: '07:15', days: 'daily' }, conversation_id: 'c2', message: 'Run them.',
    permissions: { write: true, commands: ['r7'], agents: 2 }, budget: { steps: 30, minutes: 20, per_day: 4 }, catch_up: false,
  })
  const values = fromTrigger(kept)
  expect(values).toMatchObject({ schedule: 'at', at: '07:15', days: 'daily', write: true, commands: ['r7'], agents: '2', steps: '30', minutes: '20', perDay: '4', catchUp: false })
  const patch = toPatch(values)
  expect(patch).not.toHaveProperty('kind')
  expect(patch).not.toHaveProperty('enabled')
  expect(patch).toMatchObject({ name: 'Tests', conversation_id: 'c2', config: { at: '07:15', days: 'daily' }, permissions: { write: true, commands: ['r7'], agents: 2 }, catch_up: false })
})

test('what cannot be saved is said beside its field before anything is sent', () => {
  const good = { ...blank('c1'), name: 'T', message: 'm' }
  expect(validate(good)).toEqual({})
  expect(validate({ ...good, name: ' ' })).toEqual({ name: 'Give it a name.' })
  expect(validate({ ...good, name: 'x'.repeat(81) }).name).toMatch(/at most 80/)
  expect(validate({ ...good, message: '' })).toEqual({ message: 'Write the message it sends.' })
  expect(validate({ ...good, conversationId: '' })).toEqual({ conversation: 'Choose the conversation its messages go into.' })
  expect(validate({ ...good, every: '4' })).toEqual({ when: 'At least 5 minutes, at most 10080 (a week).' })
  expect(validate({ ...good, every: '5' })).toEqual({})
  expect(validate({ ...good, every: '2.5' }).when).toBeDefined()
  expect(validate({ ...good, schedule: 'at', at: '' })).toEqual({ when: 'Give the time of day as HH:MM.' })
  expect(validate({ ...good, kind: 'files', glob: '' }).glob).toBeDefined()
  expect(validate({ ...good, kind: 'files', glob: '../x' }).glob).toMatch(/inside the project/)
  expect(validate({ ...good, kind: 'files', glob: '/abs/*.py' }).glob).toBeDefined()
  expect(validate({ ...good, kind: 'files', glob: 'src/**/*.py' })).toEqual({})
  expect(validate({ ...good, commands: Array.from({ length: 21 }, (_, n) => `r${n}`) }).commands).toMatch(/at most 20/)
  expect(validate({ ...good, agents: '5' })).toEqual({ agents: 'From 0 to 4.' })
  expect(validate({ ...good, steps: '0' })).toEqual({ steps: 'From 1 to 200.' })
  expect(validate({ ...good, steps: '201' })).toEqual({ steps: 'From 1 to 200.' })
  expect(validate({ ...good, minutes: '241' })).toEqual({ minutes: 'From 1 to 240.' })
  expect(validate({ ...good, perDay: '' })).toEqual({ perDay: 'From 1 to 500.' })
})

test('what the server refuses is put beside the field it is about', () => {
  expect(fieldOf('a trigger needs a name of at most 80 characters')).toBe('name')
  expect(fieldOf("My command CLI works with its own tools, so a trigger can't start this conversation's Orchestrator on it: with nobody watching, only an agent that works with KOLONİ's tools runs - choose another provider.")).toBe('conversation')
  expect(fieldOf('a trigger needs a message of at most 4000 characters')).toBe('message')
  expect(fieldOf('every_minutes must be a whole number from 5 to 10080')).toBe('when')
  expect(fieldOf('at must be a time of day written "HH:MM"')).toBe('when')
  expect(fieldOf('the pattern must name paths inside the project folder: no drive')).toBe('glob')
  expect(fieldOf('more than 5000 files match this pattern; name fewer')).toBe('glob')
  expect(fieldOf('a command a trigger may run is ticked on its conversation\'s allow list, by the id of a rule there: "python hello.py" is not the id of a rule on that list')).toBe('commands')
  expect(fieldOf('a trigger belongs to a conversation of its own project')).toBe('conversation')
  expect(fieldOf('origin not allowed')).toBeNull()
})

test('“Keep an agent on this project” fills the form: by the clock every hour, reading only, with a message to edit', () => {
  const values = PRESET('c1')
  expect(values).toMatchObject({ name: 'Keep an agent on this project', kind: 'schedule', schedule: 'every', every: '60', write: false, commands: [], agents: '0', conversationId: 'c1' })
  expect(values.message).toBe(
    'Look the project over: do the tests still pass, is there anything new that looks wrong? Write what you find on the notebook and remember what is worth keeping. Change nothing.',
  )
  expect(validate(values)).toEqual({})
})

test('a request it would have asked is filled into the form, and nothing it already allows is taken away', () => {
  const rules = [{ id: 'r1', prefix: 'make test' }, { id: 'r2', prefix: 'python check.py' }]
  const values = fromTrigger(trigger({ permissions: { write: false, commands: ['r1'], agents: 1 } }))
  expect(allowIn(values, { write: true }, rules)).toMatchObject({ write: true, commands: ['r1'], agents: '1' })
  // a command is allowed by ticking the rule of the conversation's list that is exactly that line
  expect(allowIn(values, { command: 'python check.py' }, rules)).toMatchObject({ commands: ['r1', 'r2'], write: false })
  // a rule that is ticked already is not ticked twice
  expect(allowIn(values, { command: 'make test' }, rules).commands).toEqual(['r1'])
  // a line that is on no rule ticks nothing: it has to be added to the conversation's list first, by the user
  expect(allowIn(values, { command: 'python check.py --fast' }, rules).commands).toEqual(['r1'])
  expect(allowIn(values, { agents: 1 }, rules).agents).toBe('2')
  expect(allowIn({ ...values, agents: '4' }, { agents: 1 }, rules).agents).toBe('4')
})
