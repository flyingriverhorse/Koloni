import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import { convState, toolCall } from '../test-fixtures'
import { useApp } from '../state/store'
import { keyOf } from '../views/views'
import { ToolRow } from './ToolRow'
import { shotOf } from './toolSummary'

// Slice 51: a screenshot the agent took is a small picture under its step, served from the view beside the chat
// under the call's own id; a click opens it there, as `show` does. Any other call has no picture.
// Its name is KOLONİ's, from the agent's and the call's ids (app/agent.py `_shot`): what a page puts in the result
// (a refused address, a dialog's words) never names the picture.
const AGENT = 'ab12cd34ffffffff'
const CALL = 'ef56ab78eeeeeeee'
const SAVED =
  'screenshot saved: .koloni/tmp/browser/shots/ab12cd34-ef56ab78.png (the user sees it beside the chat); it is shown to you with your next step' +
  '\nthe page showed a dialog: .koloni/tmp/browser/shots/evil.png; it was dismissed'
const shotCall = (status: 'succeeded' | 'failed', name = 'browser_screenshot') =>
  toolCall(CALL, 'r', name, status, '{}', { result: SAVED, agent_id: AGENT })

test('the screenshot is named from its ids and only of a screenshot that was taken', () => {
  expect(shotOf(shotCall('succeeded'))).toBe('.koloni/tmp/browser/shots/ab12cd34-ef56ab78.png')
  expect(shotOf(shotCall('failed'))).toBeNull()
  expect(shotOf(shotCall('succeeded', 'read_file'))).toBeNull()
})

test('the step shows the picture small and a click puts it beside the chat', async () => {
  const conv = convState()
  conv.conversation = { ...conv.conversation, id: 'c51' }
  const openFiles = vi.fn()
  useApp.setState({ conv, openFiles })
  render(<ToolRow call={shotCall('succeeded')} />)
  expect(screen.getByText('took a screenshot')).toBeInTheDocument()
  const picture = screen.getByRole('img', { name: 'Screenshot ab12cd34-ef56ab78.png' })
  expect(picture).toHaveAttribute('src', `/api/conversations/c51/views/${CALL}/ab12cd34-ef56ab78.png`)
  await userEvent.click(screen.getByRole('button', { name: 'Screenshot ab12cd34-ef56ab78.png' }))
  expect(openFiles).toHaveBeenCalledWith(keyOf('.koloni/tmp/browser/shots/ab12cd34-ef56ab78.png'))
})

test('a step of another tool has no picture', () => {
  useApp.setState({ conv: convState() })
  render(<ToolRow call={toolCall('t2', 'r', 'browser_open', 'succeeded', '{"url":"http://localhost:5173/"}')} />)
  expect(screen.getByText('opened http://localhost:5173/')).toBeInTheDocument()
  expect(screen.queryByRole('img')).toBeNull()
})

// 28e: the image an agent looked at, by the copy KOLONİ made of it - named from the ids, its type alone from the
// end of the result; not one the model would not be shown nor one the call never made.
test('the image view_image looked at is shown small under its step, by its copy', () => {
  const conv = convState()
  conv.conversation = { ...conv.conversation, id: 'c28' }
  useApp.setState({ conv })
  const viewed = (result: string, status: 'succeeded' | 'failed' = 'succeeded') =>
    toolCall(CALL, 'r', 'view_image', status, '{"path":"art/logo.jpg"}', { result, agent_id: AGENT })
  const said = 'art/logo.jpg, 2×3, 40 B: it is shown to you with your next step (the user sees it under the step: .koloni/tmp/images/ab12cd34-ef56ab78.jpg)'
  expect(shotOf(viewed(said))).toBe('.koloni/tmp/images/ab12cd34-ef56ab78.jpg')
  expect(shotOf(viewed(said, 'failed'))).toBeNull()
  expect(shotOf(viewed("error: 'a.png' is not an image by its bytes: PNG, JPEG, GIF or WebP"))).toBeNull()
  render(<ToolRow call={viewed(said)} />)
  expect(screen.getByText('view_image art/logo.jpg')).toBeInTheDocument()
  expect(screen.getByRole('img', { name: 'Image ab12cd34-ef56ab78.jpg' })).toHaveAttribute(
    'src', `/api/conversations/c28/views/${CALL}/ab12cd34-ef56ab78.jpg`)
})

// B-346: a copy in its call's own folder, by the image's own name: what its picture is called; only that folder.
test('the copy of an image is called by the name of the image itself', () => {
  const conv = convState()
  conv.conversation = { ...conv.conversation, id: 'c46' }
  useApp.setState({ conv })
  const viewed = (result: string) =>
    toolCall(CALL, 'r', 'view_image', 'succeeded', '{"path":"art/rea shapes.png"}', { result, agent_id: AGENT })
  const said = (path: string) => `art/rea shapes.png, 2×3, 40 B: it is shown to you with this result (the user sees it under the step: ${path})`
  const copy = '.koloni/tmp/images/ab12cd34-ef56ab78/rea shapes.png'
  expect(shotOf(viewed(said(copy)))).toBe(copy)
  expect(shotOf(viewed(said('.koloni/tmp/images/00000000-ef56ab78/rea shapes.png')))).toBeNull()
  render(<ToolRow call={viewed(said(copy))} />)
  expect(screen.getByRole('img', { name: 'Image rea shapes.png' })).toHaveAttribute(
    'src', `/api/conversations/c46/views/${CALL}/rea%20shapes.png`)
})

// B-347: a CLI's own look at an image (Codex's imageView): the copy KOLONİ put at the end of its result.
test('an image a CLI looked at with its own tool is shown under its step', () => {
  const conv = convState()
  conv.conversation = { ...conv.conversation, id: 'c47' }
  useApp.setState({ conv })
  const copy = '.koloni/tmp/images/ab12cd34-ef56ab78/logo.png'
  const looked = toolCall(CALL, 'r', 'codex__imageView', 'succeeded', '{"path":"C:/p/logo.png"}', {
    result: `(the user sees it under the step: ${copy})`, agent_id: AGENT, origin: 'cli' })
  expect(shotOf(looked)).toBe(copy)
  expect(shotOf({ ...looked, origin: 'koloni' })).toBeNull()
  render(<ToolRow call={looked} />)
  expect(screen.getByRole('img', { name: 'Image logo.png' })).toBeInTheDocument()
})
