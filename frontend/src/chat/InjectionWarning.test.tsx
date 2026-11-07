import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import type { InjectionWarning } from '../api/types'
import { agent, assistantMessage, convState, run, userMessage } from '../test-fixtures'
import { applyEvent } from '../state/applyEvent'
import { useApp } from '../state/store'
import { SkillShown } from '../agents/SkillApproval'
import { MessageList } from './MessageList'

const handlers = { onRemoveQueued: vi.fn(), onOpenChange: vi.fn(), onDecide: vi.fn(), onDecideCommand: vi.fn() }

const warning = (over: Partial<InjectionWarning> = {}): InjectionWarning => ({
  id: 7,
  run_id: 'r',
  rule: 'ignore_previous',
  source: 'web',
  where: 'a web request',
  agent_id: 'r',
  call_id: null,
  false_alarm: false,
  false_alarms: 0,
  ...over,
})

const chat = (warnings: InjectionWarning[]) =>
  convState({
    runs: [run('r', 'completed')],
    messages: [userMessage('r', 'look it up'), assistantMessage('m', 'r', 'Done.')],
    agents: [agent('r', 'completed', { depth: 0 }), agent('sub', 'completed', { run_id: 'r', depth: 1, parent_agent_id: 'r', name: 'Coder' })],
    warnings,
  })

afterEach(() => {
  cleanup()
  useApp.setState({ conv: null })
  vi.unstubAllGlobals()
})

test('a warning is a card that only tells, under its turn: the rule and where, the Lead not named, a sub-agent named', () => {
  render(<MessageList {...handlers} state={chat([warning(), warning({ id: 8, agent_id: 'sub', where: 'the MCP tool fake__echo', rule: 'hide_from_user' })])} />)
  const [lead, sub] = screen.getAllByRole('note')
  expect(lead.textContent).toBe('Text tried to give ordersText from a web request looks like it tries to give the agent orders (rule: ignore previous).False alarm')
  expect(lead).toHaveClass('card-tell')
  expect(sub.textContent).toContain('Coder · Text from the MCP tool fake__echo')
  expect(sub.textContent).toContain('hide from user')
  // B-141: its name, as a screen reader reads it, has the rule.
  expect(screen.getByRole('note', { name: 'Coder · Text from the MCP tool fake__echo looks like it tries to give the agent orders (rule: hide from user).' })).toBe(sub)
})

test('False alarm is said once and the count of its rule is shown on every warning of it', async () => {
  const marked = warning({ false_alarm: true, false_alarms: 3 })
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(marked), { status: 200 })))
  useApp.setState({ conv: chat([warning(), warning({ id: 9, run_id: 'r' })]) })
  const Shown = () => <MessageList {...handlers} state={useApp(s => s.conv)!} />
  render(<Shown />)
  await userEvent.click(screen.getAllByRole('button', { name: 'False alarm' })[0])
  expect(vi.mocked(fetch).mock.calls[0][0]).toContain('/conversations/c/warnings/7/false-alarm')
  expect(screen.getByRole('button', { name: 'Marked false alarm' })).toBeDisabled()
  expect(screen.getAllByText('3 false alarms for this rule')).toHaveLength(2)
})

test('a False alarm that is not counted says so', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ detail: 'no such warning in this conversation' }), { status: 404 })))
  useApp.setState({ conv: chat([warning()]) })
  const Shown = () => <MessageList {...handlers} state={useApp(s => s.conv)!} />
  render(<Shown />)
  await userEvent.click(screen.getByRole('button', { name: 'False alarm' }))
  expect((await screen.findByRole('alert')).textContent).toContain('no such warning in this conversation')
  expect(screen.getByRole('button', { name: 'False alarm' })).toBeEnabled()
})

test('a warning that comes as an event is added once, with the id of its event', () => {
  const { id: _id, ...said } = warning()
  let state = applyEvent(chat([]), 12, 'injection.warned', said)
  state = applyEvent(state, 12, 'injection.warned', said)
  expect(state.warnings).toEqual([warning({ id: 12 })])
  // one a snapshot already had, read after the cursor it gave: not twice
  const read = { ...chat([warning({ id: 12 })]), lastEventId: 10 }
  expect(applyEvent(read, 12, 'injection.warned', said).warnings).toHaveLength(1)
})

test("a skill's card says when its text tries to steer an agent past you", () => {
  const skill = {
    name: 'tidy', description: '', license: 'MIT', text: '', files: ['SKILL.md'], size: 10, scripts: [], source: 'C:\\tidy',
    script_texts: {}, skipped: [], sha256: 's', injection_rules: ['hide_from_user', 'without_asking'],
    allowed_tools: [], programs: [], read_whole: true, runs_as_it_loads: [], shell_blocks: 0,
    seen: { read: 0, reaches: {}, programs: [], addresses: [], env: [], whole_env: false, hidden: [], unread: [] },
  }
  const { rerender } = render(<SkillShown skill={skill} />)
  expect(screen.getByRole('note').textContent).toContain('rules: hide from user, without asking')
  rerender(<SkillShown skill={{ ...skill, injection_rules: [] }} />)
  expect(screen.queryByRole('note')).toBeNull()
})
