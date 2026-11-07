import { render, screen } from '@testing-library/react'
import { expect, test } from 'vitest'
import { AGENT_STATUS } from '../agents/agentStatus'
import { ENDED_COLOR } from '../canvas/turns'
import { TOOL_STATUS } from '../chat/ToolRow'
import { StatusLabel } from './StatusLabel'

test('a state is said as its word, in its colour; the dot is drawn, not written', () => {
  render(<StatusLabel color="var(--ok)">done</StatusLabel>)
  const label = screen.getByText('done')
  expect(label).toHaveClass('status')
  expect(label.style.color).toBe('var(--ok)')
  // nothing but the word is there to be read out, or to be part of a button's name
  expect(label.textContent).toBe('done')
  expect(label.childElementCount).toBe(0)
})

test('the same state has the same word and the same colour whatever it is a state of', () => {
  // over: an agent, a tool call and a turn all say "done", in the colour of what went well
  expect(AGENT_STATUS.completed).toEqual(['done', 'var(--ok)'])
  expect(TOOL_STATUS.succeeded).toEqual(['done', 'var(--ok)'])
  expect(ENDED_COLOR.done).toBe('var(--ok)')
  // failed, stopped, interrupted, rejected
  expect(AGENT_STATUS.failed).toEqual(TOOL_STATUS.failed)
  expect(ENDED_COLOR.failed).toBe(AGENT_STATUS.failed[1])
  expect(AGENT_STATUS.cancelled).toEqual(['stopped', ENDED_COLOR.stopped])
  expect(AGENT_STATUS.interrupted).toEqual(TOOL_STATUS.interrupted)
  expect(ENDED_COLOR.interrupted).toBe(AGENT_STATUS.interrupted[1])
  expect(AGENT_STATUS.rejected).toEqual(TOOL_STATUS.denied)
  // what waits for the user is said in the colour of a warning, on the Board as in the chat
  expect(AGENT_STATUS.waiting_approval).toEqual(['waits for you', 'var(--warn)'])
  expect(AGENT_STATUS.proposed[1]).toBe('var(--warn)')
})
