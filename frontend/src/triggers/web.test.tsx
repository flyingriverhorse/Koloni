import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import type { Conversation, Trigger } from '../api/types'
import { conversation } from '../test-fixtures'
import { moreOf, newTrigger, trigger } from './fixtures'
import { blank, fromTrigger, leaveOf, toBody, toPatch, withConversation } from './triggerText'
import { TriggersPage } from './TriggersPage'

const second: Conversation = { ...conversation, id: 'c2', title: 'Nightly work' }
const leave = (more: object) => ({ write: false, commands: [], agents: 0, ...more })

function page(triggers: Trigger[], hosts: Record<string, string[]> = {}) {
  const h = {
    onCreate: vi.fn(async (values: object) => ({ ...trigger(values as Partial<Trigger>), id: 'new', key: null as string | null })),
    onSave: vi.fn().mockResolvedValue(undefined),
    onDelete: vi.fn(),
    onRun: vi.fn(),
    onShowTurn: vi.fn(),
    onDraftTaken: vi.fn(),
    onRules: vi.fn(async () => []),
    onAddRule: vi.fn(),
    onHosts: vi.fn(async (conversationId: string) => hosts[conversationId] ?? []),
  }
  render(<TriggersPage triggers={triggers} conversations={[conversation, second]} draft={null} origin="http://127.0.0.1:8790" {...h} />)
  return h
}
const form = () => within(screen.getByRole('form', { name: /trigger/i }))

test('what a trigger may do on the web is summed up with the rest', () => {
  const said = (permissions: object) => leaveOf(trigger({ permissions } as never))
  expect(said(leave({ web: true }))).toBe('may search the web')
  expect(said(leave({ hosts: ['api.example.com', 'example.org'] }))).toBe('may make GET and HEAD requests to: api.example.com, example.org')
  expect(said(leave({ write: true, web: true, hosts: ['example.org'], notify: true }))).toBe('may change files · may search the web · may make GET and HEAD requests to: example.org · may notify')
  // a trigger from before the web tools says nothing of them
  expect(said(leave({}))).toBe('reads only')
})

test('the form keeps what a trigger has on the web, and sends it; what is off is left out', () => {
  expect(blank('c')).toMatchObject({ web: false, hosts: [], notify: false })
  expect(toBody({ ...blank('c'), name: 'n', message: 'm' }).permissions).toEqual({ write: false, commands: [], agents: 0 })
  const values = fromTrigger(trigger({ permissions: leave({ web: true, hosts: ['example.org'], notify: true }) }))
  expect(values).toMatchObject({ web: true, hosts: ['example.org'], notify: true })
  expect(toPatch(values).permissions).toEqual({ write: false, commands: [], agents: 0, web: true, hosts: ['example.org'], notify: true })
  // the hosts are a conversation's, like the commands: another one chosen, none stays ticked
  expect(withConversation(values, 'c2')).toMatchObject({ hosts: [], web: true, notify: true })
})

test('a new trigger may be let search, ask the hosts its conversation allows, and notify - each said in a sentence', async () => {
  const h = page([], { c: ['api.example.com', 'example.org'], c2: ['other.example.net'] })
  await newTrigger()
  const f = form()
  expect(f.getByLabelText('May search the web')).not.toBeChecked()
  expect(f.getByLabelText('May send you notifications')).not.toBeChecked()
  expect(f.getByText('Its work searches the web without asking you. The query leaves this machine.')).toBeInTheDocument()
  const list = await f.findByRole('group', { name: 'May make requests to these hosts' })
  expect(h.onHosts).toHaveBeenCalledWith('c')
  expect(within(list).getAllByRole('checkbox').map(box => box.closest('label')?.textContent)).toEqual(['api.example.com', 'example.org'])
  // nothing is typed: a host is picked from the list, or it is not there
  expect(within(list).queryByRole('textbox')).not.toBeInTheDocument()
  await userEvent.click(within(list).getByLabelText('example.org'))
  await userEvent.click(f.getByLabelText('May search the web'))
  await userEvent.click(f.getByLabelText('May send you notifications'))
  await userEvent.type(f.getByLabelText('Name'), 'T')
  await userEvent.type(f.getByLabelText('Message'), 'm')
  await userEvent.click(f.getByRole('button', { name: 'Add trigger' }))
  expect(h.onCreate.mock.calls[0][0]).toMatchObject({ permissions: { web: true, hosts: ['example.org'], notify: true } })
})

test('another conversation chosen: its own hosts are shown and none stays ticked', async () => {
  page([], { c: ['example.org'], c2: ['other.example.net'] })
  await newTrigger()
  const f = form()
  await userEvent.click(await f.findByLabelText('example.org'))
  await userEvent.selectOptions(f.getByLabelText('Conversation'), 'c2')
  expect(await f.findByLabelText('other.example.net')).not.toBeChecked()
  expect(f.queryByLabelText('example.org')).not.toBeInTheDocument()
})

test('a conversation with no allowed host says how one gets on its list', async () => {
  page([])
  await newTrigger()
  expect(await form().findByText(/This conversation has no allowed hosts yet\. A host gets on its list when you answer a request in the chat with “Always allow GET to …”\./)).toBeInTheDocument()
  // what a ticked host is leave for: reading, there, and nothing wider
  expect(form().getByText(/a ticked host is asked with GET and HEAD only - over https on its usual port/)).toBeInTheDocument()
  expect(form().queryByText(/any method/)).not.toBeInTheDocument()
})

test('editing: a host the trigger has is ticked and can be unticked, also one its conversation no longer lists', async () => {
  const h = page([trigger({ permissions: leave({ hosts: ['gone.example.com', 'example.org'], web: true }) })], { c: ['example.org'] })
  await moreOf('Nightly look', 'Edit')
  const f = form()
  expect(f.getByLabelText('May search the web')).toBeChecked()
  expect(await f.findByLabelText('example.org')).toBeChecked()
  expect(f.getByLabelText('gone.example.com')).toBeChecked()
  await userEvent.click(f.getByLabelText('gone.example.com'))
  await userEvent.click(f.getByRole('button', { name: 'Save' }))
  expect(h.onSave.mock.calls[0][1]).toMatchObject({ permissions: { web: true, hosts: ['example.org'] } })
  expect(h.onSave.mock.calls[0][1].permissions).not.toHaveProperty('notify')
})
