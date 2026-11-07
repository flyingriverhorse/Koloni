import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, test, vi } from 'vitest'
import { ChatPanel } from '../chat/ChatPanel'
import { resetStoreForTests, useApp } from '../state/store'
import { agent, assistantMessage, convState, run, userMessage } from '../test-fixtures'
import { useVoice } from './voice'

// Each drawing of the chat's message list, counted.
const drawn = vi.hoisted(() => ({ times: 0 }))
vi.mock('../chat/MessageList', async original => {
  const real = await original<typeof import('../chat/MessageList')>()
  return { ...real, MessageList: (props: Parameters<typeof real.MessageList>[0]) => (drawn.times++, real.MessageList(props)) }
})

beforeEach(() => {
  localStorage.clear()
  resetStoreForTests()
})

test('a key typed in the message box does not draw the messages again, though it stops any reading', async () => {
  useApp.setState({
    conv: convState({ runs: [run('r0', 'completed')], messages: [userMessage('r0', 'hi'), assistantMessage('a0', 'r0', 'Hello.')], agents: [agent('r0', 'completed')] }),
    projectId: 'p',
  })
  render(<ChatPanel />)
  const before = drawn.times
  const stops = useVoice.getState().stops
  await userEvent.type(screen.getByLabelText('Message'), 'abc')
  expect(useVoice.getState().stops).toBe(stops + 3)
  expect(drawn.times).toBe(before)
})
