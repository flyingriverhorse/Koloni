import { act, fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import { ApiError } from '../api/client'
import type { OwnCommand, Provider, Role } from '../api/types'
import { ModelPicker } from '../models/ModelPicker'
import { resetStoreForTests, useApp } from '../state/store'
import { useContext } from 'react'
import { CloseMore } from '../shell/usePanel'
import { agent, convState, question, run } from '../test-fixtures'
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

test('while running, Stop appears and a new message can still be queued, After this turn', async () => {
  const onStop = vi.fn()
  const onSend = vi.fn().mockResolvedValue(undefined)
  render(<Composer {...props} running onStop={onStop} onSend={onSend} />)
  await userEvent.click(screen.getByRole('button', { name: 'Stop' }))
  expect(onStop).toHaveBeenCalled()
  await userEvent.type(screen.getByLabelText('Message'), 'also do this')
  await userEvent.click(screen.getByRole('button', { name: 'After this turn' }))
  expect(onSend).toHaveBeenCalledWith('also do this', false)
})

test('while the Orchestrator asks, the message box says to answer above - open, not as the closed chat’s small box', () => {
  useApp.setState({
    conv: convState({
      runs: [run('r', 'waiting_approval')],
      agents: [agent('r', 'waiting')],
      questions: [question('q', 'r')],
    }),
  })
  const { rerender } = render(<Composer {...props} running scope="c" />)
  expect(screen.getByLabelText('Message')).toHaveAttribute(
    'placeholder',
    'Answer the question above, or queue a message…',
  )
  // (Closed, nothing above the box asks: its line says what the Orchestrator asks.)
  rerender(<Composer {...props} running scope="c" compact />)
  expect(screen.getByLabelText('Message')).not.toHaveAttribute(
    'placeholder',
    'Answer the question above, or queue a message…',
  )
  // Nor on the Talk or Notes tab, over which the same box stands: the question is on the Chat tab.
  act(() => useApp.getState().showChatTab('Notes'))
  rerender(<Composer {...props} running scope="c" />)
  expect(screen.getByLabelText('Message')).not.toHaveAttribute(
    'placeholder',
    'Answer the question above, or queue a message…',
  )
})

test('while running, Stop is a square with no words on the status line over the box, Send now in Send’s place; More keeps its name', () => {
  const { container } = render(<Composer {...props} running />)
  const stop = screen.getByRole('button', { name: 'Stop' })
  const queue = screen.getByRole('button', { name: 'Send now' })
  expect(stop).toHaveTextContent(/^$/)
  expect(stop).toHaveAttribute('title')
  expect(stop.closest('.composer-status')).toBe(container.querySelector('.composer-box')!.firstElementChild)
  expect(queue).toHaveAttribute('title', 'Send now: the Orchestrator reads it in this turn')
  // Where their words are not shown, the names stay (and a tooltip says them).
  expect(screen.getByRole('button', { name: 'More' })).toHaveAttribute('title', 'More')
})

test('a failed send keeps the draft and shows the reason', async () => {
  const onSend = vi.fn().mockRejectedValue({ detail: 'message is empty' })
  render(<Composer {...props} onSend={onSend} />)
  await userEvent.type(screen.getByLabelText('Message'), 'hello{Enter}')
  expect(await screen.findByRole('alert')).toHaveTextContent('message is empty')
  expect(screen.getByLabelText('Message')).toHaveValue('hello')
})

test('Chat settings under the box opens this chat’s sheet over the row; Esc closes it, the focus back on it; with no chat there is none', async () => {
  const { rerender } = render(<Composer {...props} />)
  expect(screen.queryByRole('button', { name: 'This chat’s settings' })).toBeNull()
  rerender(<Composer {...props} sheet={<p>its rows</p>} />)
  const gear = screen.getByRole('button', { name: 'This chat’s settings' })
  // (under the box, in the quiet row; the level stays in the box's own row)
  expect(gear.closest('.composer-below')).not.toBeNull()
  expect(screen.getByRole('button', { name: /^Permission level:/ }).closest('.composer-bar')).not.toBeNull()
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

test('the permission level’s menu reports the new level', async () => {
  const onPermissionMode = vi.fn()
  render(<Composer {...props} onPermissionMode={onPermissionMode} />)
  await userEvent.click(screen.getByRole('button', { name: 'Permission level: Ask before changes' }))
  await userEvent.click(
    within(screen.getByRole('dialog', { name: 'Permission level' })).getByRole('menuitemradio', { name: 'Full auto' }),
  )
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
test('the model on the status line over the box, New topic under it, 📎 first in its row; the model’s whole name in its tooltip and window', async () => {
  const copilot = {
    id: 'p1',
    name: 'Copilot',
    kind: 'copilot_cli',
    default_model: 'gpt-6-luna',
    models: [],
  } as unknown as Provider
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
  expect(button.closest('.composer-status')).not.toBeNull()
  const [below, bar] = ['.composer-below', '.composer-bar'].map(at => document.querySelector<HTMLElement>(at)!)
  expect(within(below).getByRole('button', { name: 'New topic' })).toBeInTheDocument()
  expect(within(bar).getByRole('button', { name: 'Attach' })).toBe(bar.firstElementChild!.firstElementChild)
  expect(within(bar).getByRole('button', { name: /^Permission level:/ })).toBeInTheDocument()
  await userEvent.click(button)
  expect(screen.getByRole('form', { name: 'Model for this conversation' })).toHaveTextContent(`Now: ${whole}`)
})

test('the level shows its short name; its button and tooltip say it in full, and what it does', () => {
  const { rerender } = render(<Composer {...props} />)
  const level = screen.getByRole('button', { name: 'Permission level: Ask before changes' })
  expect(level).toHaveTextContent(/^Ask$/)
  expect(level).toHaveAttribute('title', 'Ask before changes: Each file change and command waits for your card')
  rerender(<Composer {...props} permissionMode="full_auto" />)
  expect(screen.getByRole('button', { name: 'Permission level: Full auto' })).toHaveTextContent(/^Full auto$/)
})

// --- topics (slice 18b) ------------------------------------------------------------------------

// (No line above the box: "New topic" stands beside the model, and says in its tooltip where the message goes.)
const toggle = () => screen.getByRole('button', { name: 'New topic' })
const goesOnWith = (title: string) =>
  expect(toggle()).toHaveAttribute('title', expect.stringContaining(`goes on with ${title}`))
const startsNew = () => expect(toggle()).toHaveAttribute('aria-pressed', 'true')

test('no "Continuing" line above the box; beside the model, "New topic" says in its tooltip which topic the message goes on with', () => {
  const { rerender } = render(<Composer {...props} />)
  expect(screen.queryByRole('button', { name: 'New topic' })).not.toBeInTheDocument()
  rerender(<Composer {...props} topic={{ title: 'Fix the greeting' }} />)
  expect(screen.queryByText(/Continuing/)).not.toBeInTheDocument()
  expect(toggle()).toHaveAttribute('aria-pressed', 'false')
  goesOnWith('Fix the greeting')
  expect(toggle().closest('.composer-below')).not.toBeNull()
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
const names = () =>
  within(menu()!)
    .getAllByRole('option')
    .map(o => o.querySelector('.palette-name')?.textContent)

test('/ at the start opens the commands above the box; in the middle it is plain text', async () => {
  render(<Composer {...props} />)
  const box = screen.getByRole('textbox', { name: 'Message' })
  await userEvent.type(box, 'a/b')
  expect(menu()).not.toBeInTheDocument()
  await userEvent.clear(box)
  await userEvent.type(box, '/')
  expect(box).toHaveAttribute('aria-haspopup', 'listbox')
  expect(box).toHaveAttribute('aria-controls', menu()!.id)
  expect(names()).toEqual(['/new', '/stop', '/model', '/mode', '/plan', '/compare'])
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

test('the arrows go round the menu; Enter while a letter is composed, and Shift+Enter in the small box, send nothing', async () => {
  const onSend = vi.fn().mockResolvedValue(undefined)
  const { rerender } = render(<Composer {...props} onSend={onSend} />)
  const box = screen.getByRole('textbox', { name: 'Message' })
  await userEvent.type(box, '/mo')
  expect(option(/^\/model/)).toHaveAttribute('aria-selected', 'true')
  // while a letter is composed the keys are the composition's, not the menu's
  expect(fireEvent.keyDown(box, { key: 'ArrowDown', isComposing: true })).toBe(true)
  expect(option(/^\/model/)).toHaveAttribute('aria-selected', 'true')
  expect(fireEvent.keyDown(box, { key: 'Enter', isComposing: true })).toBe(true)
  expect(box).toHaveValue('/mo')
  expect(menu()).toBeInTheDocument()
  await userEvent.keyboard('{ArrowUp}')
  expect(option(/^\/mode\b/)).toHaveAttribute('aria-selected', 'true')
  await userEvent.keyboard('{ArrowUp}')
  expect(option(/^\/model/)).toHaveAttribute('aria-selected', 'true')
  await userEvent.keyboard('{Escape}')
  await userEvent.clear(box)
  await userEvent.type(box, 'hi')
  fireEvent.keyDown(box, { key: 'Enter', isComposing: true })
  expect(onSend).not.toHaveBeenCalled()
  rerender(<Composer {...props} onSend={onSend} compact />)
  const small = screen.getByRole('textbox', { name: 'Message' })
  await userEvent.type(small, '{Shift>}{Enter}{/Shift}')
  expect(small).toHaveValue('hi')
  expect(onSend).not.toHaveBeenCalled()
  await userEvent.keyboard('{Enter}')
  expect(onSend).toHaveBeenCalledWith('hi', false)
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
  expect(names()).toEqual(['/new', '/stop', '/model', '/mode', '/plan', '/compare', '/Coder', '/Security reviewer'])
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

test('/model and /mode open what their buttons open; closed, the chat says to open it first', async () => {
  const pick = vi.fn()
  const model = (
    <button type="button" className="model-picker-button" onClick={pick}>
      Model
    </button>
  )
  const { rerender } = render(<Composer {...props} model={model} />)
  const box = screen.getByRole('textbox', { name: 'Message' })
  await userEvent.type(box, '/model{Enter}')
  expect(pick).toHaveBeenCalledOnce()
  expect(box).toHaveValue('')
  await userEvent.type(box, '/mode{Enter}')
  expect(screen.getByRole('dialog', { name: 'Permission level' })).toHaveFocus()

  rerender(<Composer {...props} compact model={model} />)
  await userEvent.type(box, '/mo')
  expect(option(/^\/model/)).toHaveAttribute('aria-disabled', 'true')
  expect(option(/^\/model/)).toHaveTextContent('open the chat for this')
  expect(option(/^\/mode\b/)).toHaveAttribute('aria-disabled', 'true')
})

test('without a model to open, /model is off - and rooms are gone: there is no /room (0.1.10)', async () => {
  render(<Composer {...props} />)
  await userEvent.type(screen.getByRole('textbox', { name: 'Message' }), '/')
  expect(option(/^\/model/)).toHaveAttribute('aria-disabled', 'true')
  expect(names()).not.toContain('/room')
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
  expect(names()).toEqual(['/new', '/stop', '/model', '/mode', '/plan', '/compare', '/Coder'])
})

// --- plan first (slice 49) ---------------------------------------------------------------------

test('Plan first is set in the level’s menu only: the row has no button for it, the menu’s switch turns it on', async () => {
  const onPlanFirst = vi.fn()
  const { rerender } = render(<Composer {...props} planFirst={false} onPlanFirst={onPlanFirst} />)
  expect(screen.queryByRole('button', { name: /Plan first/ })).toBeNull()
  await userEvent.click(screen.getByRole('button', { name: /^Permission level:/ }))
  const menu = () => within(screen.getByRole('dialog', { name: 'Permission level' }))
  expect(menu().getByRole('switch', { name: 'Plan first' })).not.toBeChecked()
  await userEvent.click(menu().getByRole('switch', { name: 'Plan first' }))
  expect(onPlanFirst).toHaveBeenLastCalledWith(true)
  rerender(<Composer {...props} planFirst onPlanFirst={onPlanFirst} />)
  expect(menu().getByRole('switch', { name: 'Plan first' })).toBeChecked()
  // On, the level says so; it is the row's only button that does.
  const level = screen.getByRole('button', { name: 'Permission level: Ask before changes, Plan first on' })
  expect(level).toHaveTextContent(/^Ask · plan$/)
  expect(screen.getAllByRole('button', { name: /Plan first/ })).toEqual([level])
})

test('the level in the row says " · no checks" where this chat’s changes are not checked (S10)', async () => {
  const onChange = vi.fn()
  render(<Composer {...props} checks={{ command: 'pytest', rounds: 2, chat: 'off', project: 'check', onChange }} />)
  expect(screen.getByRole('button', { name: 'Permission level: Ask before changes, no checks' })).toHaveTextContent(
    /^Ask · no checks$/,
  )
  await userEvent.click(screen.getByRole('button', { name: /^Permission level:/ }))
  await userEvent.click(
    within(screen.getByRole('dialog', { name: 'Permission level' })).getByRole('switch', {
      name: 'Test and review changes',
    }),
  )
  expect(onChange).toHaveBeenLastCalledWith(null)
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
  expect(names()).toEqual(['/new', '/stop', '/model', '/mode', '/plan', '/compare', '/Coder', '/test-yaz'])
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
    ownCommands: [
      own('cevir', 'Translate to Turkish: {args}', { role: 'Translator' }),
      own('gone', 'Do {args}', { role: 'Ghost' }),
    ],
  })
  const onSend = vi.fn().mockResolvedValue(undefined)
  render(<Composer {...props} onSend={onSend} />)
  const box = screen.getByRole('textbox', { name: 'Message' })
  await userEvent.type(box, '/cevir hello{Enter}')
  expect(screen.getByText('/Translator')).toBeInTheDocument()
  expect(box).toHaveValue('Translate to Turkish: hello')
  await userEvent.keyboard('{Enter}')
  expect(onSend).toHaveBeenCalledWith(
    'Ask a sub-agent in the Translator role to do this: Translate to Turkish: hello',
    false,
  )
  await userEvent.type(box, '/gone it{Enter}')
  expect(box).toHaveValue('Do it')
})

test('an own command named like a role is not offered: the role’s chip is meant', async () => {
  useApp.setState({ roles: roles('Coder'), ownCommands: [own('coder', 'x'), own('tidy', 'y')] })
  render(<Composer {...props} />)
  await userEvent.type(screen.getByRole('textbox', { name: 'Message' }), '/')
  expect(names()).toEqual(['/new', '/stop', '/model', '/mode', '/plan', '/compare', '/Coder', '/tidy'])
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
const caretOf = (box: HTMLElement) => [
  (box as HTMLTextAreaElement).selectionStart,
  (box as HTMLTextAreaElement).selectionEnd,
]

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

// --- 0.1.5: the "Kovan konsolu" ---------------------------------------------------------------------------------------

test('one box: status line, message, one row - Attach, level, Auto-read, Dictate, Send; under it Workspace first, New topic, Chat settings, More, what waits elsewhere', () => {
  const { container } = render(
    <Composer
      {...props}
      onPlanFirst={vi.fn()}
      topic={{ title: 'Fix the greeting' }}
      sheet={<p>its rows</p>}
      workspace={<button type="button">Workspace 2 waiting</button>}
      waits={{ count: 2, onOpen: vi.fn() }}
    />,
  )
  const box = container.querySelector('.composer-row > .composer-box')!
  expect(Array.from(box.children, child => child.className.split(' ')[0])).toEqual([
    'composer-status',
    'composer-field',
    'composer-pasted',
    'composer-bar',
  ])
  const bar = box.querySelector<HTMLElement>('.composer-bar')!
  expect(
    within(bar)
      .getAllByRole('button')
      .map(b => b.getAttribute('aria-label') ?? b.textContent),
  ).toEqual([
    'Attach',
    'Permission level: Ask before changes',
    // (Auto-read and Dictate stand before Send where this browser can speak and listen: jsdom can neither.)
    'Send',
  ])
  expect(within(bar).getByRole('button', { name: 'Send' }).closest('.composer-actions')).not.toBeNull()
  const below = container.querySelector<HTMLElement>('.composer-row > .composer-below')!
  expect(
    within(below)
      .getAllByRole('button')
      .map(b => b.getAttribute('aria-label') ?? b.textContent),
  ).toEqual([
    'Workspace 2 waiting',
    'New topic',
    'This chat’s settings',
    'More',
    'Open Ready for you: 2 more wait elsewhere',
  ])
  expect(within(below).getByRole('button', { name: 'This chat’s settings' })).toHaveTextContent(/Chat settings/)
  // The tab order is the box's: the status line, the message, the row, then under it.
  expect(
    screen.getByLabelText('Message').compareDocumentPosition(within(bar).getByRole('button', { name: 'Send' })) &
      Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy()
})

test('the placeholder says what a message does now: ask, write into this turn, answer the question above', () => {
  useApp.setState({
    conv: convState({ runs: [run('r', 'completed')], agents: [agent('r', 'completed')] }),
    projectId: 'p',
  })
  const { rerender } = render(<Composer {...props} scope="c" />)
  expect(screen.getByLabelText('Message')).toHaveAttribute('placeholder', 'Ask about this project or request a change…')
  rerender(<Composer {...props} scope="c" running />)
  expect(screen.getByLabelText('Message')).toHaveAttribute(
    'placeholder',
    'Write to the Orchestrator - it reads it in this turn…',
  )
  useApp.setState({
    conv: convState({
      runs: [run('r', 'waiting_approval')],
      agents: [agent('r', 'waiting')],
      questions: [question('q', 'r')],
    }),
  })
  rerender(<Composer {...props} scope="c" running />)
  expect(screen.getByLabelText('Message')).toHaveAttribute(
    'placeholder',
    'Answer the question above, or queue a message…',
  )
})

test('/mode opens the level’s menu', async () => {
  render(<Composer {...props} onPlanFirst={vi.fn()} />)
  await userEvent.type(screen.getByLabelText('Message'), '/mode{Enter}')
  expect(screen.getByRole('dialog', { name: 'Permission level' })).toHaveFocus()
})

test('"N more wait elsewhere" is a quiet button under the box, only while something waits elsewhere; it opens Ready for you', async () => {
  const onOpen = vi.fn()
  const { rerender } = render(<Composer {...props} waits={{ count: 2, onOpen }} />)
  const waits = screen.getByRole('button', { name: 'Open Ready for you: 2 more wait elsewhere' })
  expect(waits.closest('.composer-below')).not.toBeNull()
  expect(waits).toHaveClass('link-btn')
  await userEvent.click(waits)
  expect(onOpen).toHaveBeenCalled()
  rerender(<Composer {...props} waits={{ count: 1, onOpen }} />)
  expect(screen.getByRole('button', { name: 'Open Ready for you: 1 more waits elsewhere' })).toBeInTheDocument()
  rerender(<Composer {...props} waits={{ count: 0, onOpen }} />)
  expect(screen.queryByRole('button', { name: /^Open Ready for you/ })).toBeNull()
})

test('the row under the box is in fewer words ("Settings", "2 wait") while, measured, it has no room for all of them; with room, in all', () => {
  let width = 400
  let resized = () => {}
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe = vi.fn()
      disconnect = vi.fn()
      constructor(fit: () => void) {
        resized = fit
      }
    },
  )
  // (jsdom lays nothing out: the row's words are 480 px long, 380 in fewer words.)
  const row = (el: HTMLElement) => el.classList.contains('composer-below')
  vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockImplementation(function (this: HTMLElement) {
    return row(this) ? width : 0
  })
  vi.spyOn(HTMLElement.prototype, 'scrollWidth', 'get').mockImplementation(function (this: HTMLElement) {
    return row(this) ? ('tight' in this.dataset ? 380 : 480) : 0
  })
  try {
    const { container } = render(<Composer {...props} sheet={<p>its rows</p>} waits={{ count: 2, onOpen: vi.fn() }} />)
    const below = container.querySelector<HTMLElement>('.composer-below')!
    expect(below).toHaveAttribute('data-tight')
    width = 500
    act(() => resized())
    expect(below).not.toHaveAttribute('data-tight')
    width = 420
    act(() => resized())
    expect(below).toHaveAttribute('data-tight')
  } finally {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  }
})

test('/model opens the model’s window while a turn runs too', async () => {
  const copilot = {
    id: 'p1',
    name: 'Copilot',
    kind: 'copilot_cli',
    default_model: 'gpt-6-luna',
    models: [],
  } as unknown as Provider
  const model = <ModelPicker providers={[copilot]} providerId={null} modelId={null} leadAuto onSave={vi.fn()} />
  useApp.setState({ conv: convState({ runs: [run('r')], agents: [agent('r')] }), projectId: 'p' })
  render(<Composer {...props} scope="c" running model={model} />)
  expect(document.querySelector('.composer-status-running')).not.toBeNull()
  await userEvent.type(screen.getByLabelText('Message'), '/model{Enter}')
  expect(screen.getByRole('form', { name: 'Model for this conversation' })).toBeInTheDocument()
})

test('the budget’s question takes the focus when it is asked, not each time its chat is shown again', async () => {
  const over = () => new ApiError(409, "this project is over this month's budget")
  const onSend = vi.fn().mockRejectedValueOnce(over())
  const { rerender } = render(<Composer {...props} onSend={onSend} scope="c1" />)
  await userEvent.type(screen.getByLabelText('Message'), 'more{Enter}')
  expect(screen.getByRole('button', { name: 'Go on anyway' })).toHaveFocus()
  // Away to another chat and back (the box is the same one): the focus stays where the user put it.
  rerender(<Composer {...props} onSend={onSend} scope="c2" />)
  expect(screen.queryByRole('button', { name: 'Go on anyway' })).toBeNull()
  screen.getByLabelText('Message').focus()
  rerender(<Composer {...props} onSend={onSend} scope="c1" />)
  expect(screen.getByRole('button', { name: 'Go on anyway' })).not.toHaveFocus()
  expect(screen.getByLabelText('Message')).toHaveFocus()
  // Asked again, it takes it again.
  await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))
  onSend.mockRejectedValueOnce(over())
  await userEvent.type(screen.getByLabelText('Message'), '{Enter}')
  expect(screen.getByRole('button', { name: 'Go on anyway' })).toHaveFocus()
})
