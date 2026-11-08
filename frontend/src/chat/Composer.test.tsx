import { act, fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import type { OwnCommand, Provider, Role } from '../api/types'
import { ModelPicker } from '../models/ModelPicker'
import { WorkTogether } from '../room/WorkTogether'
import { resetStoreForTests, useApp } from '../state/store'
import { useContext } from 'react'
import { CloseMore } from '../shell/usePanel'
import { Composer } from './Composer'

// The drafts are kept in the store (slice 36): one test's is not the next one's.
afterEach(() => resetStoreForTests())

const props = {
  running: false,
  permissionMode: 'ask' as const,
  onSend: vi.fn().mockResolvedValue(undefined),
  onStop: vi.fn(),
  onPermissionMode: vi.fn(),
}

test('Enter sends and clears; Shift+Enter adds a line', async () => {
  const onSend = vi.fn().mockResolvedValue(undefined)
  render(<Composer {...props} onSend={onSend} />)
  const box = screen.getByLabelText('Message')
  await userEvent.type(box, 'fix it{Shift>}{Enter}{/Shift}now{Enter}')
  expect(onSend).toHaveBeenCalledWith('fix it\nnow', false)
  expect(box).toHaveValue('')
})

test('an empty or blank draft cannot be sent', async () => {
  const onSend = vi.fn().mockResolvedValue(undefined)
  render(<Composer {...props} onSend={onSend} />)
  expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled()
  await userEvent.type(screen.getByLabelText('Message'), '   {Enter}')
  expect(onSend).not.toHaveBeenCalled()
})

test('while running, Stop appears and a new message can still be queued', async () => {
  const onStop = vi.fn()
  const onSend = vi.fn().mockResolvedValue(undefined)
  render(<Composer {...props} running onStop={onStop} onSend={onSend} />)
  await userEvent.click(screen.getByRole('button', { name: 'Stop' }))
  expect(onStop).toHaveBeenCalled()
  await userEvent.type(screen.getByLabelText('Message'), 'also do this')
  await userEvent.click(screen.getByRole('button', { name: 'Queue' }))
  expect(onSend).toHaveBeenCalledWith('also do this', false)
})

test('while running, Stop is a square with no words just before Queue, in Send’s place; More and Plan first keep their names (one line: the user’s report)', () => {
  render(<Composer {...props} running onPlanFirst={vi.fn()} />)
  const stop = screen.getByRole('button', { name: 'Stop' })
  const queue = screen.getByRole('button', { name: 'Queue' })
  expect(stop).toHaveTextContent(/^$/)
  expect(stop).toHaveAttribute('title')
  expect(stop.nextElementSibling).toBe(queue)
  expect(queue).toHaveAttribute('title', 'Queue')
  // Where their words are not shown, the names stay (and a tooltip says them).
  expect(screen.getByRole('button', { name: 'More' })).toHaveAttribute('title', 'More')
  expect(screen.getByRole('switch', { name: 'Plan first' }).closest('label')).toHaveAttribute('title', expect.stringMatching(/^Plan first/))
})

test('a failed send keeps the draft and shows the reason', async () => {
  const onSend = vi.fn().mockRejectedValue({ detail: 'message is empty' })
  render(<Composer {...props} onSend={onSend} />)
  await userEvent.type(screen.getByLabelText('Message'), 'hello{Enter}')
  expect(await screen.findByRole('alert')).toHaveTextContent('message is empty')
  expect(screen.getByLabelText('Message')).toHaveValue('hello')
})

test('⚙ Chat on the model’s line opens this chat’s sheet over the row; Esc closes it, the focus back on ⚙; with no chat there is none', async () => {
  const { rerender } = render(<Composer {...props} />)
  expect(screen.queryByRole('button', { name: 'This chat’s settings' })).toBeNull()
  rerender(<Composer {...props} sheet={<p>its rows</p>} />)
  const gear = screen.getByRole('button', { name: 'This chat’s settings' })
  // (on the model's line; the level and Plan first stay where they are, on the line below)
  expect(gear.closest('.composer-line')).not.toBeNull()
  expect(screen.getByLabelText('Permission level').closest('.composer-line')).toBeNull()
  await userEvent.click(gear)
  expect(within(screen.getByRole('dialog', { name: 'This chat' })).getByText('its rows')).toBeInTheDocument()
  await userEvent.keyboard('{Escape}')
  expect(screen.queryByRole('dialog', { name: 'This chat' })).toBeNull()
  expect(gear).toHaveFocus()
})

test('under More (a narrow row), what in ⚙ Chat goes elsewhere folds More too', async () => {
  const closeMore = vi.fn()
  function Elsewhere() {
    const close = useContext(CloseMore)
    return (
      <button type="button" onClick={close}>
        All settings
      </button>
    )
  }
  render(
    <CloseMore.Provider value={closeMore}>
      <Composer {...props} sheet={<Elsewhere />} />
    </CloseMore.Provider>,
  )
  await userEvent.click(screen.getByRole('button', { name: 'This chat’s settings' }))
  await userEvent.click(screen.getByRole('button', { name: 'All settings' }))
  expect(screen.queryByRole('dialog', { name: 'This chat' })).toBeNull()
  expect(closeMore).toHaveBeenCalledTimes(1)
})

test('the permission level selector reports the new level', async () => {
  const onPermissionMode = vi.fn()
  render(<Composer {...props} onPermissionMode={onPermissionMode} />)
  await userEvent.selectOptions(screen.getByLabelText('Permission level'), 'full_auto')
  expect(onPermissionMode).toHaveBeenCalledWith('full_auto')
})

test('full auto on this machine carries a standing warning; in Docker it does not', () => {
  const { rerender } = render(<Composer {...props} permissionMode="full_auto" location="host" />)
  expect(screen.getByRole('note')).toHaveTextContent('Commands run on this machine without asking.')
  rerender(<Composer {...props} permissionMode="full_auto" location="docker" />)
  expect(screen.queryByRole('note')).not.toBeInTheDocument()
  rerender(<Composer {...props} permissionMode="auto_edit" location="host" />)
  expect(screen.queryByRole('note')).not.toBeInTheDocument()
})

// The user's pick (7 Nov, sample C): line one is what it runs on, line two how far it may go and Send. The model's button
// may be cut with "…" (B-400: it broke letter by letter): model first, so the cut takes the least; its whole name in its
// tooltip, its name and its window.
test('two lines, two jobs: the model and New topic, then 📎, the level and Send; the model’s whole name in its tooltip and window', async () => {
  const copilot = { id: 'p1', name: 'Copilot', kind: 'copilot_cli', default_model: 'gpt-6-luna', models: [] } as unknown as Provider
  const model = <ModelPicker providers={[copilot]} providerId={null} modelId={null} leadAuto onSave={vi.fn()} />
  render(<Composer {...props} model={model} topic={{ title: 'Fix the greeting' }} />)
  const whole = 'Orchestrator: automatic · Copilot · gpt-6-luna'
  const button = screen.getByRole('button', { name: `Model: ${whole}` })
  expect(button).toHaveAttribute('title', expect.stringMatching(new RegExp(`^${whole}: `)))
  // shown model first; the provider and the lead are the parts that give way
  const label = button.querySelector('.model-picker-label')!
  expect(label).toHaveTextContent('gpt-6-luna · Copilot · Orchestrator: automatic')
  expect(label.querySelector('.model-picker-provider')).toHaveTextContent('· Copilot')
  expect(label.querySelector('.model-picker-lead')).toHaveTextContent('· Orchestrator: automatic')
  const [line, controls] = ['.composer-line', '.composer-controls'].map(at => document.querySelector<HTMLElement>(at)!)
  expect(within(line).getByRole('button', { name: 'New topic' })).toBeInTheDocument()
  expect(within(controls).getByRole('button', { name: 'Attach' })).toBe(controls.firstElementChild!.firstElementChild)
  expect(within(controls).getByLabelText('Permission level')).toBeInTheDocument()
  await userEvent.click(button)
  expect(screen.getByRole('form', { name: 'Model for this conversation' })).toHaveTextContent(`Now: ${whole}`)
})

test('the level shows its short names; the chosen one’s full name is its tooltip and its description', () => {
  const { rerender } = render(<Composer {...props} />)
  const level = screen.getByRole('combobox', { name: 'Permission level' })
  expect(Array.from(level.querySelectorAll('option'), option => option.textContent)).toEqual(['Ask', 'Auto-edit', 'Full auto'])
  expect(level).toHaveAttribute('title', 'Ask before changes')
  expect(level).toHaveAccessibleDescription('Ask before changes')
  rerender(<Composer {...props} permissionMode="auto_edit" />)
  expect(level).toHaveAttribute('title', 'Auto-edit files')
  expect(level).toHaveAccessibleDescription('Auto-edit files')
})

// --- topics (slice 18b) ------------------------------------------------------------------------

// (No line above the box: "New topic" stands beside the model, and says in its tooltip where the message goes.)
const toggle = () => screen.getByRole('button', { name: 'New topic' })
const goesOnWith = (title: string) => expect(toggle()).toHaveAttribute('title', expect.stringContaining(`goes on with ${title}`))
const startsNew = () => expect(toggle()).toHaveAttribute('aria-pressed', 'true')

test('no "Continuing" line above the box; beside the model, "New topic" says in its tooltip which topic the message goes on with', () => {
  const { rerender } = render(<Composer {...props} />)
  expect(screen.queryByRole('button', { name: 'New topic' })).not.toBeInTheDocument()
  rerender(<Composer {...props} topic={{ title: 'Fix the greeting' }} />)
  expect(screen.queryByText(/Continuing/)).not.toBeInTheDocument()
  expect(toggle()).toHaveAttribute('aria-pressed', 'false')
  goesOnWith('Fix the greeting')
  expect(toggle().closest('.composer-line')).not.toBeNull()
  // a trigger's topic is said to be one
  rerender(<Composer {...props} topic={{ title: 'Nightly look', scheduled: true }} />)
  goesOnWith('Nightly look, a trigger’s topic')
})

test('"New topic" is chosen for the next message only: it is sent as one, and the choice is over', async () => {
  const onSend = vi.fn().mockResolvedValue(undefined)
  render(<Composer {...props} onSend={onSend} topic={{ title: 'Fix the greeting' }} />)
  await userEvent.click(toggle())
  startsNew()
  await userEvent.type(screen.getByLabelText('Message'), 'write the docs{Enter}')
  expect(onSend).toHaveBeenCalledWith('write the docs', true)
  goesOnWith('Fix the greeting')
  await userEvent.type(screen.getByLabelText('Message'), 'and the tests{Enter}')
  expect(onSend).toHaveBeenLastCalledWith('and the tests', false)
})

test('pressed again, "New topic" goes back to the topic it names', async () => {
  const onSend = vi.fn().mockResolvedValue(undefined)
  const { rerender } = render(<Composer {...props} onSend={onSend} topic={{ title: 'Fix the greeting' }} />)
  await userEvent.click(toggle())
  // the user looks at a turn of another topic meanwhile: the choice stands, and the tooltip names that one
  rerender(<Composer {...props} onSend={onSend} topic={{ title: 'Write the docs' }} />)
  startsNew()
  expect(toggle()).toHaveAttribute('title', expect.stringContaining('go on with Write the docs'))
  await userEvent.click(toggle())
  goesOnWith('Write the docs')
  await userEvent.type(screen.getByLabelText('Message'), 'go on{Enter}')
  expect(onSend).toHaveBeenCalledWith('go on', false)
})

test('a send that failed keeps the choice of a new topic; another conversation does not inherit it', async () => {
  const onSend = vi.fn().mockRejectedValue({ detail: 'no' })
  const { rerender } = render(<Composer {...props} onSend={onSend} topic={{ title: 'Fix the greeting' }} scope="c1" />)
  await userEvent.click(toggle())
  await userEvent.type(screen.getByLabelText('Message'), 'docs{Enter}')
  await screen.findByRole('alert')
  startsNew()
  rerender(<Composer {...props} onSend={onSend} topic={{ title: 'Something else' }} scope="c2" />)
  goesOnWith('Something else')
})

test('with turns but no topic of the user’s to go on with, there is nothing to choose: the message starts one', async () => {
  const onSend = vi.fn().mockResolvedValue(undefined)
  render(<Composer {...props} onSend={onSend} topic="new" />)
  expect(screen.queryByRole('button', { name: 'New topic' })).not.toBeInTheDocument()
  await userEvent.type(screen.getByLabelText('Message'), 'hello{Enter}')
  expect(onSend).toHaveBeenCalledWith('hello', true)
})

test('another topic the message could go to instead is offered beside it, and not while a new topic is chosen', async () => {
  const onPick = vi.fn()
  const other = { label: 'Write into Nightly look instead', onPick }
  const { rerender } = render(<Composer {...props} topic={{ title: 'Fix the greeting' }} other={other} />)
  await userEvent.click(screen.getByRole('button', { name: 'Write into Nightly look instead' }))
  expect(onPick).toHaveBeenCalledTimes(1)
  // "New topic" chosen: pressing it again is the only way back
  await userEvent.click(toggle())
  expect(screen.queryByRole('button', { name: 'Write into Nightly look instead' })).not.toBeInTheDocument()
  // with no topic of the user's the other is still offered
  rerender(<Composer {...props} topic="new" other={other} scope="c2" />)
  expect(screen.getByRole('button', { name: 'Write into Nightly look instead' })).toBeInTheDocument()
})

// --- the draft is the conversation's, and outlives the box (slice 36) -----------------------

test('a draft is kept for its conversation: another conversation has its own, and a new box finds it again', async () => {
  const { rerender, unmount } = render(<Composer {...props} scope="c1" />)
  await userEvent.type(screen.getByLabelText('Message'), 'half a thought')
  rerender(<Composer {...props} scope="c2" />)
  expect(screen.getByLabelText('Message')).toHaveValue('')
  await userEvent.type(screen.getByLabelText('Message'), 'another')
  rerender(<Composer {...props} scope="c1" />)
  expect(screen.getByLabelText('Message')).toHaveValue('half a thought')
  // the box goes - another page, a hidden chat - and a new one has it
  unmount()
  render(<Composer {...props} scope="c1" />)
  expect(screen.getByLabelText('Message')).toHaveValue('half a thought')
  expect(useApp.getState().drafts).toEqual({ c1: 'half a thought', c2: 'another' })
})

test('a send clears only its own conversation’s draft, and only once it has gone', async () => {
  let done = () => {}
  const onSend = vi.fn(() => new Promise<void>(resolve => (done = resolve)))
  useApp.getState().setDraft('c2', 'keep me')
  const { rerender } = render(<Composer {...props} onSend={onSend} scope="c1" />)
  await userEvent.type(screen.getByLabelText('Message'), 'go{Enter}')
  expect(onSend).toHaveBeenCalledWith('go', false)
  expect(useApp.getState().drafts.c1).toBe('go') // not gone yet: still there
  rerender(<Composer {...props} onSend={onSend} scope="c2" />) // the user moves on meanwhile
  await act(async () => done())
  expect(useApp.getState().drafts).toEqual({ c1: '', c2: 'keep me' })
  expect(screen.getByLabelText('Message')).toHaveValue('keep me')
})

test('what was written while a message was going is not cleared when it has gone', async () => {
  let done = () => {}
  const onSend = vi.fn(() => new Promise<void>(resolve => (done = resolve)))
  render(<Composer {...props} onSend={onSend} scope="c1" />)
  await userEvent.type(screen.getByLabelText('Message'), 'first{Enter}')
  await userEvent.type(screen.getByLabelText('Message'), ' and more')
  await act(async () => done())
  expect(onSend).toHaveBeenCalledWith('first', false)
  expect(screen.getByLabelText('Message')).toHaveValue('first and more')
})

test('before there is a conversation, a draft is the project’s: another project has its own', async () => {
  useApp.setState({ projectId: 'p1' })
  const { rerender } = render(<Composer {...props} />)
  await userEvent.type(screen.getByLabelText('Message'), 'for p1')
  act(() => useApp.setState({ projectId: 'p2' }))
  rerender(<Composer {...props} />)
  expect(screen.getByLabelText('Message')).toHaveValue('')
  act(() => useApp.setState({ projectId: 'p1' }))
  rerender(<Composer {...props} />)
  expect(screen.getByLabelText('Message')).toHaveValue('for p1')
})

// --- slash commands (slice 46) -----------------------------------------------------------------

const roles = (...names: string[]) => names.map(name => ({ id: name, name, description: `${name}'s work.` }) as Role)
const menu = () => screen.queryByRole('listbox', { name: 'Commands' })
const option = (name: RegExp) => within(menu()!).getByRole('option', { name })
const names = () => within(menu()!).getAllByRole('option').map(o => o.querySelector('.palette-name')?.textContent)

test('/ at the start opens the commands above the box; in the middle it is plain text', async () => {
  render(<Composer {...props} />)
  const box = screen.getByRole('textbox', { name: 'Message' })
  await userEvent.type(box, 'a/b')
  expect(menu()).not.toBeInTheDocument()
  await userEvent.clear(box)
  await userEvent.type(box, '/')
  expect(box).toHaveAttribute('aria-haspopup', 'listbox')
  expect(box).toHaveAttribute('aria-controls', menu()!.id)
  expect(names()).toEqual(['/new', '/room', '/stop', '/model', '/mode', '/plan', '/compare'])
  // each says what it does; the first is the one Enter takes
  expect(option(/^\/stop/)).toHaveTextContent('Stop the work in progress')
  expect(box).toHaveAttribute('aria-activedescendant', within(menu()!).getAllByRole('option')[0].id)
  // a click on it, or on its scrollbar, leaves the focus in the box
  expect(fireEvent.mouseDown(menu()!)).toBe(false)
  expect(menu()).not.toHaveAttribute('tabindex', '0')
})

test('typing filters, the arrows move, Esc closes and leaves the text - and only the menu', async () => {
  const onChat = vi.fn()
  const onSend = vi.fn().mockResolvedValue(undefined)
  render(
    <div onKeyDown={e => e.key === 'Escape' && onChat()}>
      <Composer {...props} onSend={onSend} />
    </div>,
  )
  const box = screen.getByRole('textbox', { name: 'Message' })
  await userEvent.type(box, '/mo')
  expect(names()).toEqual(['/model', '/mode'])
  await userEvent.keyboard('{ArrowDown}')
  expect(option(/^\/mode\b/)).toHaveAttribute('aria-selected', 'true')
  expect(box).toHaveAttribute('aria-activedescendant', option(/^\/mode\b/).id)
  await userEvent.keyboard('{ArrowDown}')
  expect(option(/^\/model/)).toHaveAttribute('aria-selected', 'true')
  await userEvent.keyboard('{Escape}')
  expect(menu()).not.toBeInTheDocument()
  expect(box).toHaveValue('/mo')
  expect(onChat).not.toHaveBeenCalled()
  // written again from the start, it is back
  await userEvent.clear(box)
  await userEvent.type(box, '/mo')
  expect(menu()).toBeInTheDocument()
  await userEvent.keyboard('{Escape}')
  // nothing matches: no menu, and Enter sends what was written
  await userEvent.type(box, 'xyz{Enter}')
  expect(onSend).toHaveBeenCalledWith('/moxyz', false)
})

test('/stop stops the turn at work; with none it is off, says why, and Enter does nothing', async () => {
  const onStop = vi.fn()
  const onSend = vi.fn().mockResolvedValue(undefined)
  const { rerender } = render(<Composer {...props} onStop={onStop} onSend={onSend} />)
  const box = screen.getByRole('textbox', { name: 'Message' })
  await userEvent.type(box, '/st')
  expect(option(/^\/stop/)).toHaveAttribute('aria-disabled', 'true')
  expect(option(/^\/stop/)).toHaveTextContent('nothing is at work')
  await userEvent.keyboard('{Enter}')
  expect(onStop).not.toHaveBeenCalled()
  expect(onSend).not.toHaveBeenCalled()
  rerender(<Composer {...props} running onStop={onStop} onSend={onSend} />)
  expect(option(/^\/stop/)).not.toHaveAttribute('aria-disabled')
  await userEvent.keyboard('{Enter}')
  expect(onStop).toHaveBeenCalledOnce()
  expect(box).toHaveValue('')
  expect(menu()).not.toBeInTheDocument()
})

test('/new: the next message goes to a new topic', async () => {
  const onSend = vi.fn().mockResolvedValue(undefined)
  render(<Composer {...props} onSend={onSend} topic={{ title: 'Fix the greeting' }} scope="c1" />)
  const box = screen.getByRole('textbox', { name: 'Message' })
  await userEvent.type(box, '/new{Enter}')
  expect(box).toHaveValue('')
  startsNew()
  await userEvent.type(box, 'hello{Enter}')
  expect(onSend).toHaveBeenCalledWith('hello', true)
})

test('/<role> task: a chip with its sign; the message asks the Lead to hand the task to that role', async () => {
  useApp.setState({ roles: roles('Lead', 'Coder', 'Security reviewer') })
  const onSend = vi.fn().mockResolvedValue(undefined)
  render(<Composer {...props} onSend={onSend} />)
  const box = screen.getByRole('textbox', { name: 'Message' })
  await userEvent.type(box, '/')
  // every role but the Lead's, which the message goes to anyway
  expect(names()).toEqual(['/new', '/room', '/stop', '/model', '/mode', '/plan', '/compare', '/Coder', '/Security reviewer'])
  await userEvent.type(box, 'cod{Tab}')
  const chip = screen.getByText('/Coder')
  expect(chip).toHaveClass('tag', 'tag-accent')
  expect(box).toHaveValue('')
  expect(box).toHaveFocus()
  expect(box).toHaveAccessibleDescription(/Coder role/)
  await userEvent.type(box, 'fix the tests{Enter}')
  expect(onSend).toHaveBeenCalledWith('Ask a sub-agent in the Coder role to do this: fix the tests', false)
  // the chip goes with the message
  expect(screen.queryByText('/Coder')).not.toBeInTheDocument()
})

test('a role written out in full, any case and Turkish letters folded, is a chip too; Backspace at its edge removes it', async () => {
  useApp.setState({ roles: roles('Coder', 'Test Uzmanı') })
  const onSend = vi.fn().mockResolvedValue(undefined)
  render(<Composer {...props} onSend={onSend} />)
  const box = screen.getByRole('textbox', { name: 'Message' })
  await userEvent.type(box, '/test uzmani check it')
  expect(screen.getByText('/Test Uzmanı')).toBeInTheDocument()
  expect(box).toHaveValue('check it')
  await userEvent.type(box, '{Home}{Backspace}')
  expect(screen.queryByText('/Test Uzmanı')).not.toBeInTheDocument()
  expect(box).toHaveValue('check it')
  await userEvent.clear(box)
  await userEvent.type(box, '/CODER {Enter}')
  expect(screen.getByText('/Coder')).toBeInTheDocument()
  // a chip and no task is nothing to send
  expect(onSend).not.toHaveBeenCalled()
})

test('/model, /room and /mode open what their buttons open; closed, the chat says to open it first', async () => {
  const pick = vi.fn()
  const model = (
    <button type="button" className="model-picker-button" onClick={pick}>
      Model
    </button>
  )
  const room = <WorkTogether roles={roles('Coder', 'Reviewer')} providers={[]} limits={{ posts: null, tokens: null, minutes: null }} busy={false} onOpen={vi.fn()} />
  const { rerender } = render(<Composer {...props} model={model} beside={room} />)
  const box = screen.getByRole('textbox', { name: 'Message' })
  await userEvent.type(box, '/model{Enter}')
  expect(pick).toHaveBeenCalledOnce()
  expect(box).toHaveValue('')
  await userEvent.type(box, '/room{Enter}')
  expect(screen.getByRole('form', { name: 'Work together' })).toBeVisible()
  await userEvent.keyboard('{Escape}')
  await userEvent.type(box, '/mode{Enter}')
  expect(screen.getByLabelText('Permission level')).toHaveFocus()

  rerender(<Composer {...props} compact model={model} beside={room} />)
  await userEvent.type(box, '/mo')
  expect(option(/^\/model/)).toHaveAttribute('aria-disabled', 'true')
  expect(option(/^\/model/)).toHaveTextContent('open the chat for this')
  expect(option(/^\/mode\b/)).toHaveAttribute('aria-disabled', 'true')
})

test('without a model or a room to open, /model and /room are off', async () => {
  render(<Composer {...props} />)
  await userEvent.type(screen.getByRole('textbox', { name: 'Message' }), '/')
  expect(option(/^\/model/)).toHaveAttribute('aria-disabled', 'true')
  expect(option(/^\/room/)).toHaveAttribute('aria-disabled', 'true')
})

test('the best match first: named in full, then starting so, then holding it', async () => {
  useApp.setState({ roles: roles('Debugger', 'Coder') })
  render(<Composer {...props} />)
  await userEvent.type(screen.getByRole('textbox', { name: 'Message' }), '/de')
  expect(names()).toEqual(['/Debugger', '/model', '/mode', '/Coder'])
})

test('what Esc left as it was written stays text: a space after it makes no chip', async () => {
  useApp.setState({ roles: roles('Tester') })
  const onSend = vi.fn().mockResolvedValue(undefined)
  render(<Composer {...props} onSend={onSend} />)
  const box = screen.getByRole('textbox', { name: 'Message' })
  await userEvent.type(box, '/tester{Escape} is a word{Enter}')
  expect(screen.queryByText('/Tester')).not.toBeInTheDocument()
  expect(onSend).toHaveBeenCalledWith('/tester is a word', false)
})

test('Tab on a command that is off is not taken: the focus moves on', async () => {
  render(<Composer {...props} />)
  const box = screen.getByRole('textbox', { name: 'Message' })
  await userEvent.type(box, '/stop')
  expect(option(/^\/stop/)).toHaveAttribute('aria-disabled', 'true')
  await userEvent.tab()
  expect(box).not.toHaveFocus()
  expect(box).toHaveValue('/stop')
})

test('a role of the user named as a command is not a second command of that name', async () => {
  useApp.setState({ roles: roles('Stop', 'New', 'Coder') })
  render(<Composer {...props} running />)
  await userEvent.type(screen.getByRole('textbox', { name: 'Message' }), '/')
  expect(names()).toEqual(['/new', '/room', '/stop', '/model', '/mode', '/plan', '/compare', '/Coder'])
})

// --- plan first (slice 49) ---------------------------------------------------------------------

test('Plan first stands beside the permission level and says when it is turned on or off', async () => {
  const onPlanFirst = vi.fn()
  const { rerender } = render(<Composer {...props} planFirst={false} onPlanFirst={onPlanFirst} />)
  const box = screen.getByRole('switch', { name: 'Plan first' })
  expect(box).not.toBeChecked()
  await userEvent.click(box)
  expect(onPlanFirst).toHaveBeenLastCalledWith(true)
  rerender(<Composer {...props} planFirst onPlanFirst={onPlanFirst} />)
  expect(screen.getByRole('switch', { name: 'Plan first' })).toBeChecked()
})

test('/plan turns Plan first over, before a Planner role of the same start; without a conversation it is off', async () => {
  useApp.setState({ roles: roles('Planner') })
  const onPlanFirst = vi.fn()
  const { rerender } = render(<Composer {...props} planFirst onPlanFirst={onPlanFirst} />)
  const box = screen.getByRole('textbox', { name: 'Message' })
  await userEvent.type(box, '/plan')
  expect(names()).toEqual(['/plan', '/Planner'])
  expect(option(/^\/plan\b/)).toHaveTextContent('Switch Plan first off')
  await userEvent.keyboard('{Enter}')
  expect(onPlanFirst).toHaveBeenLastCalledWith(false)
  expect(box).toHaveValue('')
  rerender(<Composer {...props} />)
  await userEvent.type(box, '/plan')
  expect(option(/^\/plan\b/)).toHaveAttribute('aria-disabled', 'true')
})

// --- the user's own commands (slice 53) --------------------------------------------------------

const own = (name: string, template: string, extra: Partial<OwnCommand> = {}) =>
  ({ id: name, name, description: `${name}'s line`, template, role: null, project_id: null, ...extra }) as OwnCommand

test('own commands are listed under the built-ins, with their line', async () => {
  useApp.setState({ roles: roles('Coder'), ownCommands: [own('test-yaz', 'Write tests for {args}')] })
  render(<Composer {...props} />)
  await userEvent.type(screen.getByRole('textbox', { name: 'Message' }), '/')
  expect(names()).toEqual(['/new', '/room', '/stop', '/model', '/mode', '/plan', '/compare', '/Coder', '/test-yaz'])
  expect(option(/^\/test-yaz/)).toHaveTextContent("test-yaz's line")
})

test('one chosen puts its text in the box, {args} what was typed after its name; it is sent only as edited', async () => {
  useApp.setState({ ownCommands: [own('test-yaz', 'Write tests for {args}. $& {args}')] })
  const onSend = vi.fn().mockResolvedValue(undefined)
  render(<Composer {...props} onSend={onSend} />)
  const box = screen.getByRole('textbox', { name: 'Message' })
  await userEvent.type(box, '/TEST-yaz login form')
  expect(names()).toEqual(['/test-yaz'])
  await userEvent.keyboard('{Enter}')
  expect(onSend).not.toHaveBeenCalled()
  expect(box).toHaveValue('Write tests for login form. $& login form')
  expect(menu()).not.toBeInTheDocument()
  await userEvent.type(box, '!{Enter}')
  expect(onSend).toHaveBeenCalledWith('Write tests for login form. $& login form!', false)
})

test('a text with no {args} has what was typed added after it', async () => {
  useApp.setState({ ownCommands: [own('tidy', 'Tidy the imports')] })
  render(<Composer {...props} />)
  const box = screen.getByRole('textbox', { name: 'Message' })
  await userEvent.type(box, '/tidy in app{Enter}')
  expect(box).toHaveValue('Tidy the imports in app')
})

test('with a role, it becomes that role’s chip with the text; a role that is gone leaves the text alone', async () => {
  useApp.setState({
    roles: roles('Translator'),
    ownCommands: [own('cevir', 'Translate to Turkish: {args}', { role: 'Translator' }), own('gone', 'Do {args}', { role: 'Ghost' })],
  })
  const onSend = vi.fn().mockResolvedValue(undefined)
  render(<Composer {...props} onSend={onSend} />)
  const box = screen.getByRole('textbox', { name: 'Message' })
  await userEvent.type(box, '/cevir hello{Enter}')
  expect(screen.getByText('/Translator')).toBeInTheDocument()
  expect(box).toHaveValue('Translate to Turkish: hello')
  await userEvent.keyboard('{Enter}')
  expect(onSend).toHaveBeenCalledWith('Ask a sub-agent in the Translator role to do this: Translate to Turkish: hello', false)
  await userEvent.type(box, '/gone it{Enter}')
  expect(box).toHaveValue('Do it')
})

test('an own command named like a role is not offered: the role’s chip is meant', async () => {
  useApp.setState({ roles: roles('Coder'), ownCommands: [own('coder', 'x'), own('tidy', 'y')] })
  render(<Composer {...props} />)
  await userEvent.type(screen.getByRole('textbox', { name: 'Message' }), '/')
  expect(names()).toEqual(['/new', '/room', '/stop', '/model', '/mode', '/plan', '/compare', '/Coder', '/tidy'])
})

test('with no line of its own, the menu shows the text’s first line, cut at 80', async () => {
  useApp.setState({ ownCommands: [own('long', `${'a'.repeat(100)}\nsecond line`, { description: '' })] })
  render(<Composer {...props} />)
  await userEvent.type(screen.getByRole('textbox', { name: 'Message' }), '/lo')
  expect(option(/^\/long/)).toHaveTextContent(`/long ${'a'.repeat(79)}…`)
  expect(option(/^\/long/)).not.toHaveTextContent('second line')
})

test('what is typed after a command may take more lines: the menu stays on it', async () => {
  useApp.setState({ ownCommands: [own('review', 'Review this: {args}')] })
  render(<Composer {...props} />)
  const box = screen.getByRole('textbox', { name: 'Message' })
  await userEvent.type(box, '/review first{Shift>}{Enter}{/Shift}second')
  expect(names()).toEqual(['/review'])
  await userEvent.keyboard('{Enter}')
  expect(box).toHaveValue('Review this: first\nsecond')
})

const CODE = 'import os\n\ndef greet(name):\n    return name\n'
const paste = (box: HTMLElement, text: string) => fireEvent.paste(box, { clipboardData: { getData: () => text } })

test('pasted code is put in the box fenced, said under it, and one press puts it back as pasted', async () => {
  const onSend = vi.fn().mockResolvedValue(undefined)
  render(<Composer {...props} onSend={onSend} />)
  const box = screen.getByRole('textbox', { name: 'Message' })
  await userEvent.type(box, 'look:')
  paste(box, CODE)
  expect(box).toHaveValue('look:\n```python\nimport os\n\ndef greet(name):\n    return name\n```')
  expect(screen.getByRole('status')).toHaveTextContent('Pasted as code (python) · Paste as plain text')
  await userEvent.click(screen.getByRole('button', { name: 'Paste as plain text' }))
  expect(box).toHaveValue(`look:${CODE}`)
  expect(box).toHaveFocus()
  expect(screen.getByRole('status')).toBeEmptyDOMElement()
  // Again, and sent as it stands: the fence goes with it.
  await userEvent.clear(box)
  paste(box, CODE)
  await userEvent.click(screen.getByRole('button', { name: 'Send' }))
  expect(onSend).toHaveBeenCalledWith('```python\nimport os\n\ndef greet(name):\n    return name\n```', false)
})

test('the note goes with the next edit, or a few seconds on; prose is pasted as it is', async () => {
  vi.useFakeTimers()
  try {
    render(<Composer {...props} />)
    const box = screen.getByRole('textbox', { name: 'Message' })
    paste(box, CODE)
    expect(screen.getByRole('status')).toHaveTextContent('Pasted as code (python)')
    act(() => void vi.advanceTimersByTime(8000))
    expect(screen.getByRole('status')).toBeEmptyDOMElement()
    paste(box, CODE)
    expect(screen.getByRole('status')).not.toBeEmptyDOMElement()
    fireEvent.change(box, { target: { value: 'x' } })
    expect(screen.getByRole('status')).toBeEmptyDOMElement()
  } finally {
    vi.useRealTimers()
  }
  const box = screen.getByRole('textbox', { name: 'Message' })
  // (not taken: the browser pastes it itself)
  expect(paste(box, 'Hi,\nthe report reads fine.\nThanks')).toBe(true)
  expect(screen.getByRole('status')).toBeEmptyDOMElement()
})

const FENCED = '```python\nimport os\n\ndef greet(name):\n    return name\n```'
const caretOf = (box: HTMLElement) => [(box as HTMLTextAreaElement).selectionStart, (box as HTMLTextAreaElement).selectionEnd]

test('pasted mid-line, before more words: the fence takes lines of its own, the cursor after it; back as pasted, after the paste', async () => {
  render(<Composer {...props} />)
  const box = screen.getByRole('textbox', { name: 'Message' }) as HTMLTextAreaElement
  fireEvent.change(box, { target: { value: 'see this and fix it' } })
  box.setSelectionRange(9, 9)
  paste(box, CODE)
  expect(box).toHaveValue(`see this \n${FENCED}\nand fix it`)
  expect(caretOf(box)).toEqual([10 + FENCED.length + 1, 10 + FENCED.length + 1])
  await userEvent.click(screen.getByRole('button', { name: 'Paste as plain text' }))
  expect(box).toHaveValue(`see this ${CODE}and fix it`)
  expect(caretOf(box)).toEqual([9 + CODE.length, 9 + CODE.length])
})

test('pasted over a selection: the selection is what it takes the place of', () => {
  render(<Composer {...props} />)
  const box = screen.getByRole('textbox', { name: 'Message' }) as HTMLTextAreaElement
  fireEvent.change(box, { target: { value: 'fix OLD\nnow' } })
  box.setSelectionRange(4, 7)
  paste(box, CODE)
  expect(box).toHaveValue(`fix \n${FENCED}\nnow`)
})

test('after a role’s chip: the chip stays, the offsets are the text’s, and the task sent starts the fence on a line of its own', async () => {
  useApp.setState({ roles: roles('Coder') })
  const onSend = vi.fn().mockResolvedValue(undefined)
  render(<Composer {...props} onSend={onSend} />)
  const box = screen.getByRole('textbox', { name: 'Message' }) as HTMLTextAreaElement
  await userEvent.type(box, '/Coder ')
  expect(box).toHaveValue('')
  paste(box, CODE)
  expect(box).toHaveValue(FENCED)
  expect(caretOf(box)).toEqual([FENCED.length, FENCED.length])
  await userEvent.click(screen.getByRole('button', { name: 'Paste as plain text' }))
  expect(box).toHaveValue(CODE)
  expect(caretOf(box)).toEqual([CODE.length, CODE.length])
  expect(useApp.getState().drafts['new in ']).toBe(`/Coder ${CODE}`)
  await userEvent.clear(box)
  paste(box, CODE)
  await userEvent.click(screen.getByRole('button', { name: 'Send' }))
  expect(onSend).toHaveBeenCalledWith(`Ask a sub-agent in the Coder role to do this:\n${FENCED}`, false)
})

test('pasted into a fence the user opened, it goes as it is', () => {
  render(<Composer {...props} />)
  const box = screen.getByRole('textbox', { name: 'Message' })
  fireEvent.change(box, { target: { value: '```\n' } })
  // (not taken: the browser pastes it itself)
  expect(paste(box, CODE)).toBe(true)
  expect(screen.getByRole('status')).toBeEmptyDOMElement()
})

test('the note stays past its seconds while its link has the focus, and goes when the focus leaves it', () => {
  vi.useFakeTimers()
  try {
    render(<Composer {...props} />)
    paste(screen.getByRole('textbox', { name: 'Message' }), CODE)
    const link = screen.getByRole('button', { name: 'Paste as plain text' })
    act(() => link.focus())
    act(() => void vi.advanceTimersByTime(10_000))
    expect(screen.getByRole('status')).toHaveTextContent('Pasted as code (python)')
    act(() => link.blur())
    expect(screen.getByRole('status')).toBeEmptyDOMElement()
  } finally {
    vi.useRealTimers()
  }
})
